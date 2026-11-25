"""animation_registry.py — substrate for declaring + recording animation flow.

Two registries living in one module:

(a) AnimationSource — declarations of WHERE mocap comes from. One JSON file
    per source under studio/assets/_animation_sources/<source_id>.json. Mirrors
    the program_registry verified_at / watch / notes shape.

(b) AnimationFrame — verified frames that landed in the substrate. Append-only
    JSONL at ~/.cc/animation_frames.jsonl. One row per recorded MocapFrame.

Both registries are stdlib-only and consume the canonical `MocapFrame`
dataclass from `core/lib/mocap_frame.py`. We do NOT redefine MocapFrame —
this module imports it and records its `frame_hash()` along with metadata.

The `anchor_uuids` on a source are the XR_FB_spatial_entity UUIDs from
`spatial_anchor` — the "particles we placed long ago" that mocap frames are
aligned against.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Allow `python3 core/lib/animation_registry.py` to import sibling module.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from mocap_frame import MocapFrame, is_valid_xr_anchor_uuid  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SOURCES_DIR = REPO / "studio" / "assets" / "_animation_sources"
FRAMES_LOG = Path(os.path.expanduser("~/.cc/animation_frames.jsonl"))

CHAINS = ("meta_xr", "snap_lens", "mediapipe", "mixamo_clip")


# ============================================================================
# Dataclasses
# ============================================================================

@dataclass
class AnimationSource:
    """Declaration of a mocap source. One per file under _animation_sources/."""
    chain: str  # one of CHAINS
    source_id: str
    capture_method: str
    rig_target_glb: str  # path or URI to the rig the source drives
    anchor_uuids: List[str] = field(default_factory=list)
    verified_at: Optional[float] = None
    watch: bool = True
    notes: str = ""
    added_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return asdict(self)


# ============================================================================
# Persistence — sources
# ============================================================================

def _ensure_dirs() -> None:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    FRAMES_LOG.parent.mkdir(parents=True, exist_ok=True)


def _source_path(source_id: str) -> Path:
    return SOURCES_DIR / f"{source_id}.json"


def register_source(entry: AnimationSource) -> Path:
    """Write/overwrite the source file. Last write wins. Returns the path."""
    if entry.chain not in CHAINS:
        raise ValueError(f"unknown chain: {entry.chain}; expected one of {CHAINS}")
    # Filter anchor_uuids through the XR validator — drop anything malformed.
    entry.anchor_uuids = [
        u.strip().lower() for u in entry.anchor_uuids
        if is_valid_xr_anchor_uuid(u)
    ]
    _ensure_dirs()
    p = _source_path(entry.source_id)
    p.write_text(json.dumps(entry.to_dict(), indent=2, sort_keys=True) + "\n")
    return p


def load_sources() -> List[AnimationSource]:
    _ensure_dirs()
    out: List[AnimationSource] = []
    for p in sorted(SOURCES_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text())
            out.append(AnimationSource(**d))
        except Exception as exc:
            print(f"[anim] skip malformed {p.name}: {exc}", file=sys.stderr)
    return out


def find_source(source_id: str) -> Optional[AnimationSource]:
    p = _source_path(source_id)
    if not p.exists():
        return None
    try:
        return AnimationSource(**json.loads(p.read_text()))
    except Exception as exc:
        print(f"[anim] load failed {source_id}: {exc}", file=sys.stderr)
        return None


def mark_source_verified(source_id: str) -> bool:
    src = find_source(source_id)
    if src is None:
        return False
    src.verified_at = time.time()
    register_source(src)
    return True


# ============================================================================
# Persistence — frames (append-only JSONL)
# ============================================================================

def record_frame(frame: MocapFrame, alignment_crystal: str) -> Dict:
    """Append a frame entry to ~/.cc/animation_frames.jsonl. Returns the
    recorded dict (with frame_hash, source_id, ts, joint_count, etc.)."""
    _ensure_dirs()
    entry = {
        "frame_hash": frame.frame_hash(),
        "source_id": frame.source_id,
        "ts": float(frame.ts),
        "joint_count": len(frame.joints),
        "face_blendshape_count": len(frame.face_blendshapes),
        "anchor_uuids": list(frame.anchor_uuids),
        "alignment_crystal": alignment_crystal,
        "verified_at": time.time(),
    }
    with FRAMES_LOG.open("a") as fh:
        fh.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
    return entry


def recent_frames(source_id: str = "", limit: int = 100) -> List[Dict]:
    if not FRAMES_LOG.exists():
        return []
    out: List[Dict] = []
    # Read entire file then slice — JSONL is small for typical session counts.
    for line in FRAMES_LOG.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if source_id and d.get("source_id") != source_id:
            continue
        out.append(d)
    return out[-limit:]


# ============================================================================
# Stats
# ============================================================================

def stats() -> Dict:
    sources = load_sources()
    frames = recent_frames(limit=10**9)  # all
    per_source: Dict[str, int] = {}
    for f in frames:
        sid = f.get("source_id", "")
        per_source[sid] = per_source.get(sid, 0) + 1
    return {
        "source_count": len(sources),
        "verified_source_count": sum(1 for s in sources if s.verified_at),
        "frame_count": len(frames),
        "frames_per_source": per_source,
    }


# ============================================================================
# Seed
# ============================================================================

_SEED: List[AnimationSource] = [
    AnimationSource(
        chain="meta_xr",
        source_id="meta_xr_quest3",
        capture_method="meta_xr_body",
        rig_target_glb="studio/assets/_models/avatars/meta_body_default.glb",
        anchor_uuids=[],
        watch=True,
        notes="Quest 3 / Quest Pro full-body XR_FB_body_tracking. "
              "22 joints + ARKit face. Aligns to whatever XR_FB anchors "
              "the spatial_anchor agent has placed.",
    ),
    AnimationSource(
        chain="snap_lens",
        source_id="snap_lens_default",
        capture_method="snap_lens_bodytrack",
        rig_target_glb="studio/assets/_models/avatars/snap_upper_body.glb",
        anchor_uuids=[],
        watch=True,
        notes="Snap Camera Kit BodyTrack — upper-body only on most lenses. "
              "Mapped through SNAP_BODYTRACK_TO_META_BODY remap.",
    ),
    AnimationSource(
        chain="mediapipe",
        source_id="mediapipe_holistic_browser",
        capture_method="mediapipe_holistic",
        rig_target_glb="studio/assets/_models/avatars/mediapipe_pose.glb",
        anchor_uuids=[],
        watch=True,
        notes="MediaPipe Holistic in-browser via WASM. 33 pose landmarks + "
              "face mesh. Remapped via MEDIAPIPE_POSE_TO_META_BODY.",
    ),
]


def seed(force: bool = False) -> int:
    existing = load_sources()
    if existing and not force:
        return len(existing)
    n = 0
    for s in _SEED:
        register_source(s)
        n += 1
    return n


# ============================================================================
# CLI
# ============================================================================

def _print_source(s: AnimationSource) -> None:
    watch = "watch " if s.watch else "      "
    ver = "verified" if s.verified_at else "unverif "
    anchors = f"{len(s.anchor_uuids)} anchors" if s.anchor_uuids else "no anchors"
    print(f"  {watch} {ver}  {s.chain:12s} {s.source_id:32s} "
          f"-> {s.rig_target_glb}  [{anchors}]")


def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("animation_registry — declare + record mocap sources and frames")
        print("Commands:")
        print("  seed [--force]")
        print("  list-sources [--watch]")
        print("  add-source <chain> <source_id> <capture_method> <rig_target_glb> "
              "[--anchors uuid1,uuid2]")
        print("  mark-verified <source_id>")
        print("  record-frame <frame.json>")
        print("  recent-frames [--source X] [--limit N]")
        print("  stats")
        print(f"  paths -> {SOURCES_DIR}  |  {FRAMES_LOG}")
        return 0

    cmd = argv[0]
    args = argv[1:]

    if cmd == "seed":
        force = "--force" in args
        n = seed(force=force)
        existing = len(load_sources())
        print(f"[anim] {n} new sources written; total now {existing}")
        return 0

    if cmd == "list-sources":
        watch_only = "--watch" in args
        srcs = load_sources()
        if watch_only:
            srcs = [s for s in srcs if s.watch]
        for s in srcs:
            _print_source(s)
        print(f"[anim] {len(srcs)} sources")
        return 0

    if cmd == "add-source":
        if len(args) < 4:
            print("usage: add-source <chain> <source_id> <capture_method> "
                  "<rig_target_glb> [--anchors uuid1,uuid2]", file=sys.stderr)
            return 2
        chain, source_id, capture_method, rig_target_glb = args[:4]
        anchors: List[str] = []
        i = 4
        while i < len(args):
            if args[i] == "--anchors" and i + 1 < len(args):
                anchors = [u.strip() for u in args[i + 1].split(",") if u.strip()]
                i += 2
                continue
            i += 1
        entry = AnimationSource(
            chain=chain, source_id=source_id,
            capture_method=capture_method, rig_target_glb=rig_target_glb,
            anchor_uuids=anchors,
        )
        try:
            p = register_source(entry)
        except ValueError as exc:
            print(f"[anim] {exc}", file=sys.stderr)
            return 3
        print(f"[anim] wrote {p}")
        return 0

    if cmd == "mark-verified":
        if len(args) != 1:
            print("usage: mark-verified <source_id>", file=sys.stderr)
            return 2
        ok = mark_source_verified(args[0])
        if not ok:
            print(f"[anim] not found: {args[0]}", file=sys.stderr)
            return 4
        print(f"[anim] {args[0]} verified_at={time.time():.0f}")
        return 0

    if cmd == "record-frame":
        if len(args) < 1:
            print("usage: record-frame <frame.json> [--crystal HASH]",
                  file=sys.stderr)
            return 2
        frame_path = Path(args[0])
        if not frame_path.exists():
            print(f"[anim] missing: {frame_path}", file=sys.stderr)
            return 4
        crystal = ""
        if "--crystal" in args:
            idx = args.index("--crystal")
            if idx + 1 < len(args):
                crystal = args[idx + 1]
        try:
            d = json.loads(frame_path.read_text())
            # Allow either a plain MocapFrame dict (asdict form) or a wrapper.
            if "joints" in d or "source_id" in d:
                frame = MocapFrame(**d)
            else:
                raise ValueError("not a MocapFrame dict")
        except Exception as exc:
            print(f"[anim] could not parse {frame_path}: {exc}", file=sys.stderr)
            return 5
        entry = record_frame(frame, alignment_crystal=crystal)
        print(f"[anim] recorded {entry['frame_hash'][:16]}.. "
              f"source={entry['source_id']} joints={entry['joint_count']}")
        return 0

    if cmd == "recent-frames":
        source = ""
        limit = 20
        i = 0
        while i < len(args):
            if args[i] == "--source" and i + 1 < len(args):
                source = args[i + 1]
                i += 2
                continue
            if args[i] == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
                i += 2
                continue
            i += 1
        rows = recent_frames(source_id=source, limit=limit)
        for r in rows:
            print(f"  {r['ts']:.2f}  {r['source_id']:28s} "
                  f"{r['frame_hash'][:16]}..  j={r['joint_count']} "
                  f"f={r['face_blendshape_count']} "
                  f"anchors={len(r['anchor_uuids'])}")
        print(f"[anim] {len(rows)} frames")
        return 0

    if cmd == "stats":
        s = stats()
        print(json.dumps(s, indent=2, sort_keys=True))
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
