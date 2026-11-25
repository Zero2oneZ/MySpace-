"""gpu_trainer.py — Dual-GPU Sui DEX model trainer.

Architecture:
- GPU 0: inference worker (loads latest checkpoint, scores incoming DEX txs)
- GPU 1: training worker (continuously trains on accumulated JSONL data)

Usage:
    # GPU 1 only (training)
    CUDA_VISIBLE_DEVICES=1 python3 gpu_trainer.py --mode train --data ./feed/live_features.jsonl

    # GPU 0 only (inference)
    CUDA_VISIBLE_DEVICES=0 python3 gpu_trainer.py --mode infer --checkpoint ./models/latest.pt

    # Both (default — spawns two processes internally)
    python3 gpu_trainer.py
"""
from __future__ import annotations

import argparse
import json
import os
import time
import warnings
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    warnings.warn("PyTorch not installed. Run: pip install torch --index-url https://download.pytorch.org/whl/cu121")

from sui_constants import FEATURE_DIM

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "feed" / "live_features.jsonl"
DEFAULT_CHECKPOINT = HERE / "models" / "latest.pt"
DEFAULT_LOG = HERE / "models" / "training.log"


class SuiTransformer(nn.Module):
    """Small sequence model for Sui DEX tabular features."""
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
        h = self.input_proj(x)
        h = self.transformer(h)
        h = h.mean(dim=1)
        return self.mlp(h)


@dataclass
class SuiSample:
    features: list[float]
    label: float
    ts: float
    digest: str


class SuiJsonlDataset:
    """Streaming dataset that reads from a growing JSONL file."""
    def __init__(self, path: Path, seq_len: int = 16, stride: int = 1):
        self.path = path
        self.seq_len = seq_len
        self.stride = stride
        self.samples: list[SuiSample] = []
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
                    label = self._auto_label(feats)
                    self.samples.append(SuiSample(
                        features=feats,
                        label=label,
                        ts=obj.get("ts", 0),
                        digest=obj.get("digest", ""),
                    ))
                except Exception:
                    continue
        self._last_size = size

    def _auto_label(self, feats: list[float]) -> float:
        price_vel = feats[15] if len(feats) > 15 else 0
        buy_ratio = feats[13] if len(feats) > 13 else 0.5
        rug_score = feats[27] if len(feats) > 27 else 0
        if rug_score > 0.5:
            return 0.0
        if price_vel > 0.01 and buy_ratio > 0.7:
            return 1.0
        return 0.0

    def __len__(self) -> int:
        self._refresh()
        return max(0, len(self.samples) - self.seq_len)

    def get_sequence(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        seq = self.samples[idx:idx + self.seq_len]
        x = torch.tensor([s.features for s in seq], dtype=torch.float32)
        y = torch.tensor([seq[-1].label], dtype=torch.float32)
        return x, y


def train_step(model: nn.Module, dataset: SuiJsonlDataset, device: torch.device,
               batch_size: int = 32, optimizer: Optional[torch.optim.Optimizer] = None) -> dict:
    if optimizer is None:
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    model.train()
    n = len(dataset)
    if n < batch_size * 2:
        return {"loss": float("nan"), "samples": n}
    indices = list(range(n))
    import random
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
                x = torch.nan_to_num(x, nan=0.0, posinf=1e4, neginf=-1e4).clamp(-1e4, 1e4)
                batch_x.append(x)
                batch_y.append(y)
            except Exception:
                continue
        if not batch_x:
            continue
        x = torch.stack(batch_x).to(device)
        y = torch.stack(batch_y).to(device)
        pred = model(x)
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
    if not HAS_TORCH:
        print("[train] PyTorch not installed. Aborting.")
        return
    device = torch.device(f"cuda:{device_id}" if torch.cuda.is_available() else "cpu")
    print(f"[train] Using device: {device}")
    model = SuiTransformer().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=100, T_mult=2)
    if checkpoint_path.exists():
        try:
            state = torch.load(checkpoint_path, map_location=device)
            model.load_state_dict(state["model"])
            optimizer.load_state_dict(state["optimizer"])
            print(f"[train] Resumed from {checkpoint_path}")
        except Exception as e:
            print(f"[train] Failed to resume: {e}")
    dataset = SuiJsonlDataset(data_path, seq_len=16)
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
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n[train] Stopped")
            break
        except Exception as e:
            print(f"[train] ERROR: {e}")
            time.sleep(10)


def infer_worker(checkpoint_path: Path, device_id: int = 0,
                 alert_threshold: float = 0.85, ring_buffer: Optional[deque] = None):
    if not HAS_TORCH:
        print("[infer] PyTorch not installed. Aborting.")
        return
    device = torch.device(f"cuda:{device_id}" if torch.cuda.is_available() else "cpu")
    print(f"[infer] Using device: {device}")
    model = SuiTransformer().to(device)
    model.eval()
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
    if ring_buffer is None:
        try:
            import sui_feed
            ring_buffer = sui_feed.RING_BUFFER
        except Exception:
            ring_buffer = deque(maxlen=10000)
    print(f"[infer] Scoring incoming DEX txs (threshold={alert_threshold})")
    processed: set[str] = set()
    while True:
        try:
            new_items = []
            for _ in range(min(100, len(ring_buffer))):
                try:
                    item = ring_buffer.popleft()
                    dig = item.get("digest", "")
                    if dig not in processed:
                        processed.add(dig)
                        new_items.append(item)
                except IndexError:
                    break
            if not new_items:
                time.sleep(1)
                continue
            batch_x = []
            batch_meta = []
            for item in new_items:
                feats = item.get("features", [])
                if len(feats) != FEATURE_DIM:
                    continue
                seq = torch.tensor([feats] * 16, dtype=torch.float32)
                batch_x.append(seq)
                batch_meta.append(item)
            if not batch_x:
                continue
            x = torch.stack(batch_x).to(device)
            with torch.no_grad():
                probs = model(x).cpu().numpy().flatten()
            for prob, meta in zip(probs, batch_meta):
                prob = float(max(0.0, min(1.0, prob)))
                if prob > alert_threshold:
                    dig = meta.get("digest", "")[:16]
                    print(f"🚨 SUI ALERT: pump_prob={prob:.3f} dig={dig}... ckpt={meta.get('checkpoint')}")
        except KeyboardInterrupt:
            print("\n[infer] Stopped")
            break
        except Exception as e:
            print(f"[infer] ERROR: {e}")
            time.sleep(5)


def main():
    ap = argparse.ArgumentParser(description="Sui DEX dual-GPU trainer")
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
