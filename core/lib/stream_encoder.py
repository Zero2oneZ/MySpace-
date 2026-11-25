"""stream_encoder.py — warm CLIP daemon that embeds every event in real-time.

The substrate inversion Tom asked for: instead of firing FLUX on every event
(wasteful and slow), keep a small encoder permanently warm in VRAM and embed
EVERY event that arrives in any of the existing JSONL sinks. Output is a
single continuous embedding stream that the NN trains against.

  inputs (tailed):
    ~/.cc/program_events/<chain>/<short>/<date>.jsonl   (program_monitor)
    ~/.cc/correlations/<date>.jsonl                       (program_correlator)
    ~/.cc/meta_xr_mocap.jsonl                             (Meta XR body track)
    ~/.cc/snap_lens_mocap.jsonl                           (Snap Lens body track)
    ~/.cc/phantom_dom_events.jsonl                        (DOM intent — optional)
    ~/.cc/chain_renders/_video_queue.completed.jsonl      (render output events)

  output:
    ~/.cc/embeddings/YYYY-MM-DD.jsonl   (one line per encoded event)
    {ts, source, kind, crystal_anchor, vec_hex, vec_norm,
     model_id, device, source_event_hash}

  vec_hex is the L2-normalized embedding packed as hex bytes (float32 → 4
  bytes × N dims = 2048 hex chars for CLIP-B's 512-d). Same input always
  produces same hex (deterministic, cached) so the NN training corpus is
  reproducible.

Model: CLIP-ViT-B/32 by default (~600 MB fp32, 200 MB fp16). Fits in 1-2 GB
VRAM. Encodes text AND images into the same 512-d space — chain events and
rendered images share coordinates. Override via MSPC_STREAM_ENCODER_MODEL.

Single-instance daemon via lockfile at ~/.cc/embeddings/_encoder.lock. Probes
CUDA, falls back to CPU. Graceful shutdown on SIGINT.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "lib"))

EMB_ROOT = Path(os.path.expanduser("~/.cc/embeddings"))
LOCK = EMB_ROOT / "_encoder.lock"
OFFSETS = EMB_ROOT / "_encoder_offsets.json"
LATEST = EMB_ROOT / "_latest.jsonl"  # rolling 1000-entry tail for quick lookups

DEFAULT_MODEL = os.environ.get("MSPC_STREAM_ENCODER_MODEL",
                                 "openai/clip-vit-base-patch32")
DEFAULT_DEVICE = os.environ.get("MSPC_STREAM_ENCODER_DEVICE", "auto")

# Sinks to tail. Each is (path_pattern, source_label, kind_extractor_fn_name).
SINKS: Tuple[Tuple[str, str, str], ...] = (
    ("~/.cc/program_events/*/*/*.jsonl", "program_monitor", "_kind_program"),
    ("~/.cc/correlations/*.jsonl",          "program_correlator", "_kind_correlation"),
    ("~/.cc/meta_xr_mocap.jsonl",           "meta_xr_mocap",   "_kind_mocap"),
    ("~/.cc/snap_lens_mocap.jsonl",         "snap_lens_mocap", "_kind_mocap"),
    ("~/.cc/phantom_dom_events.jsonl",      "phantom_dom",     "_kind_dom"),
    ("~/.cc/chain_renders/_video_queue.completed.jsonl", "video_render",
     "_kind_render"),
)


# ── kind extractors ─────────────────────────────────────────────────────────

def _kind_program(event: Dict) -> str:
    return f"chain:{event.get('chain','?')}:{event.get('category','?')}:{event.get('action','other')}"


def _kind_correlation(event: Dict) -> str:
    return f"correlation:{event.get('top_category','?')}:{event.get('dom_kind','?')}"


def _kind_mocap(event: Dict) -> str:
    n_joints = len(event.get("joints", {}))
    return f"mocap:{event.get('source_id','?')}:{n_joints}j"


def _kind_dom(event: Dict) -> str:
    return f"dom:{event.get('kind','unknown')}"


def _kind_render(event: Dict) -> str:
    return f"render:{event.get('status','?')}"


KIND_FNS = {
    "_kind_program": _kind_program,
    "_kind_correlation": _kind_correlation,
    "_kind_mocap": _kind_mocap,
    "_kind_dom": _kind_dom,
    "_kind_render": _kind_render,
}


# ── canonical-sentence flattening for text encoding ─────────────────────────

def event_to_sentence(event: Dict, source: str, kind: str) -> str:
    """Convert any event dict to a short canonical English sentence that
    captures its semantics. CLIP's text encoder sees this. Same event always
    produces the same sentence (deterministic ordering, no timestamps in the
    body since CLIP doesn't benefit from those)."""
    if source == "program_monitor":
        return (f"{event.get('action','event')} on "
                f"{event.get('program_name', event.get('program_short','?'))} "
                f"{event.get('category','').lower()} chain {event.get('chain','solana')}")
    if source == "program_correlator":
        actions = list((event.get("chain_actions") or {}).keys())
        return (f"intent {event.get('dom_kind','signal')} correlated to "
                f"{event.get('n_chain_events',0)} chain events on "
                f"{event.get('top_category','unknown')} with actions {','.join(actions[:3])}")
    if source in ("meta_xr_mocap", "snap_lens_mocap"):
        joints = list(event.get("joints") or {})
        if joints:
            return (f"motion capture frame with {len(joints)} joints including "
                    f"{','.join(sorted(joints)[:5])}")
        return f"motion capture frame from {event.get('source_id','?')}"
    if source == "phantom_dom":
        return f"wallet intent {event.get('kind','event')} on {event.get('source_url','dom')[:60]}"
    if source == "video_render":
        return (f"video render {event.get('status','?')} "
                f"{event.get('crystal_short','')[:8]} model "
                f"{event.get('model','?')}")
    # Fallback: a compact key:value string
    summary = " ".join(f"{k}={str(v)[:24]}" for k, v in sorted(event.items())
                        if k not in ("ts", "dim") and not k.startswith("_"))[:240]
    return f"{kind} {summary}"


# ── image candidate extraction ──────────────────────────────────────────────

def event_image_path(event: Dict, source: str) -> Optional[Path]:
    """Some events reference an image file (rendered tile, etc.). Return the
    absolute Path if it exists, else None — caller falls back to text-encode."""
    candidates = []
    for key in ("image_path", "path", "out_path"):
        v = event.get(key)
        if isinstance(v, str) and v.endswith(".png"):
            candidates.append(v)
    for c in candidates:
        p = Path(c).expanduser()
        if p.exists():
            return p
    # video_render rows reference a render dir
    if source == "video_render":
        out_dir = event.get("out_dir")
        if out_dir:
            p = Path(out_dir).expanduser() / "image.png"
            if p.exists():
                return p
    return None


# ── encoder ─────────────────────────────────────────────────────────────────

@dataclass
class EncodedEvent:
    ts: float
    source: str
    kind: str
    crystal_anchor: str
    vec_hex: str
    vec_norm: float
    dim: int
    model_id: str
    device: str
    source_event_hash: str
    sentence: str = ""
    encoded_image: str = ""

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


class StreamEncoder:
    """Warm CLIP daemon. Lazy-loads torch + transformers on first use so the
    module imports cheaply even when torch isn't installed (the daemon mode
    requires torch, the CLI inspect mode does not)."""

    def __init__(self, model_id: str = DEFAULT_MODEL,
                 device_pref: str = DEFAULT_DEVICE):
        self.model_id = model_id
        self.device_pref = device_pref
        self.device = ""
        self._model = None
        self._processor = None
        self._dim = 0
        self.encode_count_text = 0
        self.encode_count_image = 0

    def warm(self) -> None:
        """Load model + processor + move to device. May raise."""
        try:
            import torch  # type: ignore
            from transformers import CLIPModel, CLIPProcessor  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                f"stream_encoder requires torch + transformers in PYTHONPATH "
                f"({exc!r}). Run under MediaLab's venv: "
                f"/data/Projects/ComfyUI/.venv/bin/python") from exc
        if self.device_pref == "auto":
            if torch.cuda.is_available():
                # try GPU 0 first; if OOM, fall back to CPU
                self.device = "cuda:0"
            else:
                self.device = "cpu"
        else:
            self.device = self.device_pref
        sys.stderr.write(f"[encoder] loading {self.model_id} on {self.device}...\n")
        self._model = CLIPModel.from_pretrained(self.model_id)
        self._processor = CLIPProcessor.from_pretrained(self.model_id)
        try:
            self._model = self._model.to(self.device).eval()
        except RuntimeError as exc:
            if "out of memory" in str(exc).lower() and self.device.startswith("cuda"):
                sys.stderr.write(f"[encoder] CUDA OOM on {self.device}; falling back to CPU\n")
                self.device = "cpu"
                self._model = self._model.to(self.device).eval()
            else:
                raise
        # Projection dim
        self._dim = int(self._model.config.projection_dim)
        sys.stderr.write(f"[encoder] ready: dim={self._dim} device={self.device}\n")

    def encode_text(self, text: str) -> Tuple[List[float], float]:
        import torch  # type: ignore
        if not self._model or not self._processor:
            self.warm()
        with torch.no_grad():
            # Use the tokenizer directly (CLIPProcessor.tokenizer); transformers
            # v5's CLIPModel.get_text_features returns a BaseModelOutputWithPooling
            # on some paths, so we go through text_model + text_projection
            # which is guaranteed to return a Tensor.
            inputs = self._processor.tokenizer(
                [text[:1024]], return_tensors="pt", padding=True, truncation=True)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            text_outputs = self._model.text_model(**inputs)
            # pooled_output across transformers versions: [1] index or .pooler_output
            pooled = text_outputs[1] if isinstance(text_outputs, tuple) \
                else getattr(text_outputs, "pooler_output",
                              text_outputs[1] if hasattr(text_outputs, "__getitem__") else None)
            if pooled is None:
                pooled = text_outputs.last_hidden_state[:, 0, :]  # CLS-pool fallback
            features = self._model.text_projection(pooled)
            features = features / features.norm(dim=-1, keepdim=True)
            vec = features[0].cpu().tolist()
        self.encode_count_text += 1
        return vec, 1.0

    def encode_image(self, image_path: Path) -> Tuple[List[float], float]:
        import torch  # type: ignore
        from PIL import Image  # type: ignore
        if not self._model or not self._processor:
            self.warm()
        img = Image.open(image_path).convert("RGB")
        with torch.no_grad():
            ip = (getattr(self._processor, "image_processor", None)
                   or getattr(self._processor, "feature_extractor", None)
                   or self._processor)
            inputs = ip(images=[img], return_tensors="pt")
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            vision_outputs = self._model.vision_model(**inputs)
            pooled = vision_outputs[1] if isinstance(vision_outputs, tuple) \
                else getattr(vision_outputs, "pooler_output",
                              vision_outputs[1] if hasattr(vision_outputs, "__getitem__") else None)
            if pooled is None:
                pooled = vision_outputs.last_hidden_state[:, 0, :]
            features = self._model.visual_projection(pooled)
            features = features / features.norm(dim=-1, keepdim=True)
            vec = features[0].cpu().tolist()
        self.encode_count_image += 1
        return vec, 1.0


# ── vec packing ─────────────────────────────────────────────────────────────

def vec_to_hex(vec: List[float]) -> str:
    """Pack a list of float32 into hex. Same vector → same hex.
    For a 512-d CLIP embedding this is 2048 hex chars (1 KB)."""
    import struct
    buf = b"".join(struct.pack("<f", float(v)) for v in vec)
    return buf.hex()


def hex_to_vec(hex_str: str) -> List[float]:
    import struct
    data = bytes.fromhex(hex_str)
    return list(struct.unpack(f"<{len(data)//4}f", data))


# ── persistence ─────────────────────────────────────────────────────────────

def _today_jsonl() -> Path:
    EMB_ROOT.mkdir(parents=True, exist_ok=True)
    return EMB_ROOT / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"


def _read_offsets() -> Dict[str, int]:
    if not OFFSETS.exists():
        return {}
    try:
        return json.loads(OFFSETS.read_text())
    except Exception:
        return {}


def _write_offsets(d: Dict[str, int]) -> None:
    OFFSETS.parent.mkdir(parents=True, exist_ok=True)
    OFFSETS.write_text(json.dumps(d, sort_keys=True))


def _event_hash(event: Dict) -> str:
    """Stable hash of an event so we can dedup across re-tails."""
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"),
                            default=str, ensure_ascii=True)
    return hashlib.blake2b(canonical.encode(), digest_size=12).hexdigest()


# ── lock ────────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _lockfile():
    EMB_ROOT.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip() or "-1")
            os.kill(pid, 0)
            raise SystemExit(f"[encoder] daemon already running (pid={pid})")
        except (ProcessLookupError, ValueError):
            LOCK.unlink(missing_ok=True)
    LOCK.write_text(str(os.getpid()))
    try:
        yield
    finally:
        LOCK.unlink(missing_ok=True)


# ── tail + encode loop ──────────────────────────────────────────────────────

def _iter_sink_paths(sink_pattern: str) -> List[Path]:
    """Expand a glob like ~/.cc/program_events/*/*/*.jsonl into Paths."""
    p = Path(os.path.expanduser(sink_pattern))
    if "*" in str(p):
        return sorted(Path(os.path.expanduser("~")).glob(
            str(p.relative_to(Path(os.path.expanduser("~"))))))
    return [p] if p.exists() else []


def encode_loop(model_id: str = DEFAULT_MODEL,
                device_pref: str = DEFAULT_DEVICE,
                poll_s: float = 1.0,
                max_events: int = 0,
                verbose: bool = True) -> int:
    """Main daemon loop: tail every sink, encode every NEW event, append
    to today's embeddings JSONL. Returns total encoded count on exit."""
    enc = StreamEncoder(model_id=model_id, device_pref=device_pref)
    enc.warm()
    offsets = _read_offsets()
    encoded = 0
    stop = False

    def _on_sigint(_s, _f):
        nonlocal stop
        stop = True
        if verbose:
            sys.stderr.write("\n[encoder] SIGINT received; finishing current poll\n")

    signal.signal(signal.SIGINT, _on_sigint)

    with _lockfile():
        while not stop:
            new_events_this_poll = 0
            for pattern, source, kind_fn_name in SINKS:
                for sink_path in _iter_sink_paths(pattern):
                    spath = str(sink_path)
                    start = offsets.get(spath, 0)
                    try:
                        size = sink_path.stat().st_size
                    except Exception:
                        continue
                    if size <= start:
                        continue
                    with sink_path.open() as f:
                        f.seek(start)
                        new_text = f.read()
                    offsets[spath] = size
                    for ln in new_text.splitlines():
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            event = json.loads(ln)
                        except Exception:
                            continue
                        rec = _encode_one(enc, event, source, kind_fn_name)
                        if rec is None:
                            continue
                        with _today_jsonl().open("a") as out:
                            out.write(rec.to_jsonl() + "\n")
                        # rolling tail
                        with LATEST.open("a") as tail:
                            tail.write(rec.to_jsonl() + "\n")
                        encoded += 1
                        new_events_this_poll += 1
                        if verbose and (encoded % 25 == 0):
                            sys.stderr.write(
                                f"[encoder] +{encoded} (text={enc.encode_count_text} "
                                f"image={enc.encode_count_image})\n")
                        if max_events and encoded >= max_events:
                            stop = True
                            break
                    if stop:
                        break
                if stop:
                    break
            _write_offsets(offsets)
            # Trim _latest.jsonl to 1000 lines
            try:
                with LATEST.open() as f:
                    lines = f.readlines()
                if len(lines) > 1200:
                    with LATEST.open("w") as f:
                        f.writelines(lines[-1000:])
            except FileNotFoundError:
                pass
            if not stop and new_events_this_poll == 0:
                time.sleep(poll_s)
        return encoded


def _encode_one(enc: StreamEncoder, event: Dict, source: str,
                 kind_fn_name: str) -> Optional[EncodedEvent]:
    kind = KIND_FNS[kind_fn_name](event)
    img = event_image_path(event, source)
    try:
        if img is not None:
            vec, norm = enc.encode_image(img)
            sentence = ""
            encoded_image = str(img)
        else:
            sentence = event_to_sentence(event, source, kind)
            vec, norm = enc.encode_text(sentence)
            encoded_image = ""
    except Exception as exc:
        sys.stderr.write(f"[encoder] encode fail for {source}/{kind}: {exc!r}\n")
        return None
    return EncodedEvent(
        ts=float(event.get("ts") or time.time()),
        source=source,
        kind=kind,
        crystal_anchor=str(event.get("crystal_id") or event.get("crystal_anchor") or ""),
        vec_hex=vec_to_hex(vec),
        vec_norm=norm,
        dim=len(vec),
        model_id=enc.model_id,
        device=enc.device,
        source_event_hash=_event_hash(event),
        sentence=sentence,
        encoded_image=encoded_image,
    )


# ── inspect ─────────────────────────────────────────────────────────────────

def stats() -> Dict:
    today = _today_jsonl()
    encoded = 0
    sources: Dict[str, int] = {}
    if today.exists():
        with today.open() as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                encoded += 1
                sources[d.get("source", "?")] = sources.get(d.get("source", "?"), 0) + 1
    return {
        "today_jsonl": str(today),
        "today_encoded": encoded,
        "sources": sources,
        "lock_present": LOCK.exists(),
        "lock_pid": LOCK.read_text().strip() if LOCK.exists() else "",
        "default_model": DEFAULT_MODEL,
        "offsets_path": str(OFFSETS),
    }


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="stream_encoder — warm CLIP daemon")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="long-running daemon")
    p_run.add_argument("--model", default=DEFAULT_MODEL)
    p_run.add_argument("--device", default=DEFAULT_DEVICE)
    p_run.add_argument("--poll", type=float, default=1.0)
    p_run.add_argument("--max-events", type=int, default=0)
    p_run.add_argument("--quiet", action="store_true")

    p_one = sub.add_parser("one", help="encode a single event JSON from stdin")
    p_one.add_argument("--source", default="manual")
    p_one.add_argument("--kind", default="manual:event")
    p_one.add_argument("--model", default=DEFAULT_MODEL)
    p_one.add_argument("--device", default=DEFAULT_DEVICE)

    sub.add_parser("stats")
    sub.add_parser("reset-lock")

    args = ap.parse_args(argv)

    if args.cmd == "stats":
        print(json.dumps(stats(), indent=2))
        return 0
    if args.cmd == "reset-lock":
        if LOCK.exists():
            LOCK.unlink()
            print("[encoder] lock removed")
        else:
            print("[encoder] no lock present")
        return 0
    if args.cmd == "one":
        event = json.loads(sys.stdin.read())
        enc = StreamEncoder(model_id=args.model, device_pref=args.device)
        enc.warm()
        sentence = event_to_sentence(event, args.source, args.kind)
        vec, norm = enc.encode_text(sentence)
        rec = EncodedEvent(
            ts=float(event.get("ts") or time.time()),
            source=args.source, kind=args.kind,
            crystal_anchor="", vec_hex=vec_to_hex(vec), vec_norm=norm,
            dim=len(vec), model_id=enc.model_id, device=enc.device,
            source_event_hash=_event_hash(event), sentence=sentence,
        )
        print(rec.to_jsonl())
        return 0
    if args.cmd == "run":
        try:
            n = encode_loop(model_id=args.model, device_pref=args.device,
                             poll_s=args.poll, max_events=args.max_events,
                             verbose=not args.quiet)
        except SystemExit as exc:
            print(str(exc), file=sys.stderr); return 1
        print(f"[encoder] encoded {n} events; exiting cleanly")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
