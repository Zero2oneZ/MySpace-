"""gpu_trainer.py — Dual-GPU Pump.fun model trainer.

Architecture:
- GPU 0: inference worker (loads latest checkpoint, scores incoming tokens)
- GPU 1: training worker (continuously trains on accumulated JSONL data)

The model is a small Transformer + MLP hybrid designed for tabular
sequence data (32-dim feature vectors).

Usage:
    # GPU 1 only (training)
    CUDA_VISIBLE_DEVICES=1 python3 gpu_trainer.py --mode train --data ./feed/live_features.jsonl

    # GPU 0 only (inference)
    CUDA_VISIBLE_DEVICES=0 python3 gpu_trainer.py --mode infer --checkpoint ./models/latest.pt

    # Both (default — spawns two processes internally)
    python3 gpu_trainer.py

Install deps first:
    pip install torch --index-url https://download.pytorch.org/whl/cu121
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
import warnings
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ── Lazy torch import (graceful fallback if not installed) ─────────────────
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    warnings.warn("PyTorch not installed. Run: pip install torch --index-url https://download.pytorch.org/whl/cu121")

from pump_constants import FEATURE_DIM

try:
    from bot_forensics import BotForensics
    HAS_FORENSICS = True
except ImportError:
    HAS_FORENSICS = False

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "feed" / "live_features.jsonl"
DEFAULT_CHECKPOINT = HERE / "models" / "latest.pt"
DEFAULT_LOG = HERE / "models" / "training.log"


# ── Model ─────────────────────────────────────────────────────────────────────

class PumpTransformer(nn.Module):
    """Small sequence model for Pump.fun tabular features.

    Input:  (B, T, F)  batch x time x features
    Output: (B, 1)     probability of pump / rug
    """
    def __init__(self, feat_dim: int = FEATURE_DIM, d_model: int = 64, nhead: int = 4,
                 num_layers: int = 2, dropout: float = 0.1):
        super().__init__()
        self.input_proj = nn.Linear(feat_dim, d_model)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=d_model * 4,
            dropout=dropout, batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.mlp = nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, d_model // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, T, F)
        h = self.input_proj(x)           # (B, T, D)
        h = self.transformer(h)          # (B, T, D)
        h = h.mean(dim=1)                  # (B, D) — global average pooling
        return self.mlp(h)                 # (B, 1)


# ── Dataset ──────────────────────────────────────────────────────────────────

@dataclass
class PumpSample:
    features: list[float]
    label: float  # 1.0 = pump, 0.0 = rug/neutral
    ts: float
    signature: str


class PumpJsonlDataset:
    """Streaming dataset that reads from a growing JSONL file."""
    def __init__(self, path: Path, seq_len: int = 16, stride: int = 1):
        self.path = path
        self.seq_len = seq_len
        self.stride = stride
        self.samples: list[PumpSample] = []
        self._last_size = 0
        self._refresh()

    def _refresh(self):
        if not self.path.exists():
            return
        size = self.path.stat().st_size
        if size <= self._last_size:
            return
        with open(self.path, "r") as f:
            f.seek(self._last_size)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    feats = obj.get("features", [])
                    if len(feats) != FEATURE_DIM:
                        continue
                    # Auto-label: positive if price_velocity > threshold and buy ratio high
                    label = self._auto_label(feats)
                    self.samples.append(PumpSample(
                        features=feats,
                        label=label,
                        ts=obj.get("ts", 0),
                        signature=obj.get("signature", ""),
                    ))
                except Exception:
                    continue
        self._last_size = size

    def _auto_label(self, feats: list[float]) -> float:
        """Heuristic auto-label based on feature vector.
        Returns 1.0 if looks like a pump, 0.0 if rug/neutral."""
        price_vel = feats[15] if len(feats) > 15 else 0
        buy_ratio = feats[14] if len(feats) > 14 else 0.5
        rug_score = feats[28] if len(feats) > 28 else 0
        if rug_score > 0.5:
            return 0.0
        if price_vel > 0.01 and buy_ratio > 0.7:
            return 1.0
        return 0.0

    def __len__(self) -> int:
        self._refresh()
        return max(0, len(self.samples) - self.seq_len)

    def get_sequence(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        """Return (seq_features, label) tensors."""
        seq = self.samples[idx:idx + self.seq_len]
        x = torch.tensor([s.features for s in seq], dtype=torch.float32)
        y = torch.tensor([seq[-1].label], dtype=torch.float32)
        return x, y


# ── Training ─────────────────────────────────────────────────────────────────

def train_step(model: nn.Module, dataset: PumpJsonlDataset, device: torch.device,
               batch_size: int = 32, optimizer: Optional[torch.optim.Optimizer] = None) -> dict:
    """Run one training epoch."""
    if optimizer is None:
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)

    model.train()
    n = len(dataset)
    if n < batch_size * 2:
        return {"loss": float("nan"), "samples": n}

    indices = list(range(n))
    random.shuffle(indices)
    total_loss = 0.0
    count = 0

    criterion = nn.BCELoss()

    for i in range(0, n, batch_size):
        batch_indices = indices[i:i + batch_size]
        batch_x = []
        batch_y = []
        for idx in batch_indices:
            try:
                x, y = dataset.get_sequence(idx)
                # Sanitize: clamp features to prevent NaN/Inf in model
                x = torch.nan_to_num(x, nan=0.0, posinf=1e4, neginf=-1e4).clamp(-1e4, 1e4)
                batch_x.append(x)
                batch_y.append(y)
            except Exception:
                continue
        if not batch_x:
            continue
        x = torch.stack(batch_x).to(device)    # (B, T, F)
        y = torch.stack(batch_y).to(device)    # (B, 1)
        pred = model(x)
        # Clamp sigmoid output to valid BCE range to prevent CUDA assert
        pred = torch.clamp(pred, min=1e-7, max=1.0 - 1e-7)
        loss = criterion(pred, y)
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        total_loss += loss.item()
        count += 1

    return {"loss": total_loss / max(count, 1), "samples": n}


def train_worker(data_path: Path, checkpoint_path: Path, device_id: int = 1,
                 log_path: Optional[Path] = None, save_interval: int = 60):
    """Continuous training loop on GPU 1."""
    if not HAS_TORCH:
        print("[train] PyTorch not installed. Aborting.")
        return

    device = torch.device(f"cuda:{device_id}" if torch.cuda.is_available() else "cpu")
    print(f"[train] Using device: {device}")

    model = PumpTransformer().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=100, T_mult=2)

    # Resume if checkpoint exists
    if checkpoint_path.exists():
        try:
            state = torch.load(checkpoint_path, map_location=device)
            model.load_state_dict(state["model"])
            optimizer.load_state_dict(state["optimizer"])
            print(f"[train] Resumed from {checkpoint_path}")
        except Exception as e:
            print(f"[train] Failed to resume: {e}")

    dataset = PumpJsonlDataset(data_path, seq_len=16)
    step = 0
    last_save = time.time()

    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    print("[train] Starting continuous training loop...")
    while True:
        try:
            metrics = train_step(model, dataset, device, batch_size=32, optimizer=optimizer)
            step += 1
            scheduler.step()

            if step % 10 == 0:
                msg = f"[train] step={step} loss={metrics['loss']:.4f} samples={metrics['samples']}"
                print(msg)
                if log_path:
                    with open(log_path, "a") as f:
                        f.write(f"{time.time():.0f},{step},{metrics['loss']:.6f},{metrics['samples']}\n")

            if time.time() - last_save > save_interval:
                checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                torch.save({
                    "model": model.state_dict(),
                    "optimizer": optimizer.state_dict(),
                    "step": step,
                    "ts": time.time(),
                }, checkpoint_path)
                print(f"[train] Checkpoint saved to {checkpoint_path}")
                last_save = time.time()

            time.sleep(5)  # brief pause between epochs
        except KeyboardInterrupt:
            print("\n[train] Stopped")
            break
        except Exception as e:
            print(f"[train] ERROR: {e}")
            time.sleep(10)


# ── Inference ─────────────────────────────────────────────────────────────────

def infer_worker(checkpoint_path: Path, device_id: int = 0,
                 alert_threshold: float = 0.85, ring_buffer: Optional[deque] = None):
    """Continuous inference loop on GPU 0.

    Reads from the shared ring buffer (pump_feed.py RING_BUFFER) and
    emits alerts when pump probability > threshold.
    """
    if not HAS_TORCH:
        print("[infer] PyTorch not installed. Aborting.")
        return

    device = torch.device(f"cuda:{device_id}" if torch.cuda.is_available() else "cpu")
    print(f"[infer] Using device: {device}")

    model = PumpTransformer().to(device)
    model.eval()

    # Wait for checkpoint
    while not checkpoint_path.exists():
        print(f"[infer] Waiting for checkpoint at {checkpoint_path}...")
        time.sleep(30)

    try:
        state = torch.load(checkpoint_path, map_location=device)
        model.load_state_dict(state["model"])
        print(f"[infer] Loaded checkpoint step={state.get('step', '?')}")
    except Exception as e:
        print(f"[infer] Failed to load checkpoint: {e}")
        return

    # Import ring buffer from pump_feed if available
    if ring_buffer is None:
        try:
            import pump_feed
            ring_buffer = pump_feed.RING_BUFFER
        except Exception:
            ring_buffer = deque(maxlen=10000)

    print(f"[infer] Scoring incoming tokens (threshold={alert_threshold})")
    processed: set[str] = set()

    # Bot forensics integration
    forensics = BotForensics() if HAS_FORENSICS else None
    if forensics:
        print("[infer] Bot forensics enabled")

    # Social alert dispatchers
    social_dispatchers: list[tuple[str, callable]] = []
    try:
        from social import telegram as _tg
        social_dispatchers.append(("telegram", _tg.send_message))
    except Exception as e:
        print(f"[infer] Telegram alert disabled: {e}")
    try:
        from social import facebook as _fb
        social_dispatchers.append(("facebook", _fb.send_message))
    except Exception as e:
        print(f"[infer] Facebook alert disabled: {e}")
    try:
        from social import snapchat as _sc
        social_dispatchers.append(("snapchat", _sc.send_message))
    except Exception as e:
        print(f"[infer] Snapchat alert disabled: {e}")

    if social_dispatchers:
        print(f"[infer] Social alerts wired: {', '.join(n for n, _ in social_dispatchers)}")

    def _dispatch_alert(text: str) -> None:
        for name, fn in social_dispatchers:
            try:
                res = fn(text)
                if getattr(res, "success", False):
                    print(f"[alert] Sent to {name}")
                else:
                    err = getattr(res, "error", "unknown")
                    print(f"[alert] {name} failed: {err}")
            except Exception as e:
                print(f"[alert] {name} exception: {e}")

    while True:
        try:
            # Grab new items from ring buffer
            new_items = []
            for _ in range(min(100, len(ring_buffer))):
                try:
                    item = ring_buffer.popleft()
                    sig = item.get("signature", "")
                    if sig not in processed:
                        processed.add(sig)
                        new_items.append(item)
                except IndexError:
                    break

            if not new_items:
                time.sleep(1)
                continue

            # Run bot forensics on each new item (side-effect: builds wallet profiles)
            bot_tags_by_sig: dict[str, list[str]] = {}
            if forensics:
                for item in new_items:
                    rec = forensics.ingest(item)
                    if rec:
                        bot_tags_by_sig[item.get("signature", "")] = rec["tags"]

            # Batch inference
            batch_x = []
            batch_meta = []
            for item in new_items:
                feats = item.get("features", [])
                if len(feats) != FEATURE_DIM:
                    continue
                # Build a pseudo-sequence: repeat the single vector to seq_len
                seq = torch.tensor([feats] * 16, dtype=torch.float32)
                batch_x.append(seq)
                batch_meta.append(item)

            if not batch_x:
                continue

            x = torch.stack(batch_x).to(device)
            with torch.no_grad():
                probs = model(x).cpu().numpy().flatten()

            for prob, meta in zip(probs, batch_meta):
                # Clamp to valid probability range
                prob = float(max(0.0, min(1.0, prob)))
                sig = meta.get("signature", "")[:16]
                tags = bot_tags_by_sig.get(meta.get("signature", ""), [])
                if prob > alert_threshold:
                    bot_str = f" bots={tags}" if tags else ""
                    msg = f"🚨 Pump.fun ALERT\npump_prob={prob:.3f}{bot_str}\nsig={sig}...\nslot={meta.get('slot')}"
                    print(msg)
                    _dispatch_alert(msg)

        except KeyboardInterrupt:
            print("\n[infer] Stopped")
            break
        except Exception as e:
            print(f"[infer] ERROR: {e}")
            time.sleep(5)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Pump.fun dual-GPU trainer")
    ap.add_argument("--mode", choices=["train", "infer", "both"], default="both",
                    help="train=GPU1, infer=GPU0, both=spawn both")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--gpu-train", type=int, default=1, help="GPU for training")
    ap.add_argument("--gpu-infer", type=int, default=0, help="GPU for inference")
    ap.add_argument("--threshold", type=float, default=0.85, help="Alert threshold")
    args = ap.parse_args()

    if not HAS_TORCH:
        print("! PyTorch not installed.")
        print("! Run: pip install torch --index-url https://download.pytorch.org/whl/cu121")
        return 1

    if args.mode == "train":
        train_worker(args.data, args.checkpoint, args.gpu_train, args.log)
    elif args.mode == "infer":
        infer_worker(args.checkpoint, args.gpu_infer, args.threshold)
    else:
        import multiprocessing
        p_train = multiprocessing.Process(
            target=train_worker,
            args=(args.data, args.checkpoint, args.gpu_train, args.log)
        )
        p_infer = multiprocessing.Process(
            target=infer_worker,
            args=(args.checkpoint, args.gpu_infer, args.threshold)
        )
        p_train.start()
        p_infer.start()
        try:
            p_train.join()
            p_infer.join()
        except KeyboardInterrupt:
            p_train.terminate()
            p_infer.terminate()
            print("\nBoth workers stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
