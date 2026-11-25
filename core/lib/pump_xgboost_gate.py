#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        pump_xgboost_gate                                              =
# role:        DEFI · PUMP_FUN_HYPER_FAST_INFERENCE_GATE                      =
# tier:        L0                                                             =
# substrate:   xgboost binary classifier (student of GMM teacher) + decision  =
#              gate combining bot_probability with companion human_inflow     =
# engine:      xgboost (canonical) OR stdlib decision-stump ensemble (fallback=
#              ~120 LOC, 20 stumps max_depth=3). Both readable by predict.    =
# storage:     studio/assets/_models/pump_xgb.json    (xgb native dump)       =
#              studio/assets/_models/pump_xgb.fb.json (stub fallback dump)    =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.pump_xgboost_gate.active.json    =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - surf_executor (agent E) — calls gate() per incoming pump.fun event      =
#   - core/lib/defi_loop.py   — bulk inference batch path                     =
#   - CLI: python3 core/lib/pump_xgboost_gate.py {train|gate|predict|...}     =
# outbound:                                                                   =
#   - pump_gmm_classifier (agent C) — TEACHER labels training set             =
#   - inference_logger.log  (tier='ml_train' / 'ml_inference')                =
# substrate touch:                                                            =
#   - reads:  features CSV + GMM labels CSV (training)                        =
#             pump_xgb.json (inference)                                       =
#   - writes: pump_xgb.json + crystal chain entries                           =
# ============================================================================
"""pump_xgboost_gate.py — hyper-fast bot/human classifier + BUY/HOLD/ABORT gate.

GMM (parallel agent C) is the unsupervised teacher: it discovers cluster
structure in wallet features. XGBoost is the production-fast student: trained
on GMM cluster labels (bot=1, human=0), it scores incoming wallets at sub-ms
latency for the surf_executor.

The gate then combines bot_probability with a companion human_inflow_score
(0.0-1.0, supplied by the caller — typically derived from how active the
human-cluster wallets are around the same token) and emits:

  abort          — pure bot cluster, guaranteed rug
  surf_candidate — bot volume + human inflow = surfable pump
  hold           — mixed / organic / no momentum

Deterministic-first: training writes a JSON model that predict_wallet() reads.
xgboost is optional — if absent, a stdlib decision-stump ensemble (~20 stumps,
max_depth=3) provides a graceful fallback. Both produce the same shape of
output and the same JSON file format (different `model_kind`).

Crystal anchoring is fire-and-forget — never blocks a gate decision.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import pickle
import random
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = PROJECT_ROOT / "studio" / "assets" / "_models"
DEFAULT_MODEL_PATH = DEFAULT_MODEL_DIR / "pump_xgb.json"

# Canonical feature order — MUST match pump_feature_extractor (agent B).
# If extractor changes, update this list and retrain.
FEATURE_ORDER: List[str] = [
    "tx_per_block",
    "value_entropy",
    "jito_bundle_ratio",
    "buy_sell_balance",
    "unique_mints_touched",
    "benford_distance",
    "funding_proximity",
    "gas_distortion",
    "tx_per_block_var",
    "session_length_seconds",
]

# Decision thresholds (the gate)
BOT_HIGH_THRESHOLD = 0.85       # ≥ → almost certainly bot
BOT_LOW_THRESHOLD = 0.30        # < → likely human
HUMAN_INFLOW_LOW = 0.20         # < → no human interest
HUMAN_INFLOW_HIGH = 0.40        # ≥ → humans flooding in

# ---------------------------------------------------------------------------
# Optional xgboost import (graceful fallback)
# ---------------------------------------------------------------------------

try:
    import xgboost as xgb  # type: ignore
    _HAS_XGB = True
    _XGB_VERSION = getattr(xgb, "__version__", "unknown")
except Exception:
    _HAS_XGB = False
    _XGB_VERSION = "absent"


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class GateDecision:
    """Result of one gate() call — what surf_executor consumes."""
    wallet: str
    decision: str               # 'abort' | 'surf_candidate' | 'hold'
    bot_probability: float
    human_inflow_score: float
    reason: str
    crystal: str = ""           # crystal_id if logging succeeded, else ""


# ---------------------------------------------------------------------------
# Stub gradient-boosting fallback (used when xgboost is unavailable)
# ---------------------------------------------------------------------------
# Tiny ensemble of decision stumps with depth 3, fit by gradient descent over
# the log-loss residual (Newton-Raphson per node, like sklearn / xgboost).
# ~120 LOC. Deterministic via a fixed seed.

@dataclass
class _StubNode:
    feature: int = -1
    threshold: float = 0.0
    left: Optional["_StubNode"] = None
    right: Optional["_StubNode"] = None
    value: float = 0.0          # leaf log-odds contribution


def _stub_build_tree(X: List[List[float]], grad: List[float], hess: List[float],
                      depth: int, max_depth: int, min_samples: int = 2,
                      lam: float = 1.0, rng: Optional[random.Random] = None) -> _StubNode:
    """Build one regression tree on (gradient, hessian) targets — XGB-style."""
    n = len(X)
    if n == 0:
        return _StubNode(value=0.0)
    G = sum(grad)
    H = sum(hess) + lam
    if depth >= max_depth or n < min_samples:
        return _StubNode(value=-G / H)

    nf = len(X[0]) if X else 0
    best_gain = 0.0
    best_feat = -1
    best_thr = 0.0
    best_split: Optional[Tuple[List[int], List[int]]] = None

    # Try a handful of candidate splits per feature (quantile-ish)
    for f in range(nf):
        vals = sorted({row[f] for row in X})
        if len(vals) < 2:
            continue
        # sample ~8 candidate thresholds for speed
        step = max(1, len(vals) // 8)
        candidates = vals[step::step] if len(vals) > 8 else vals[1:]
        for thr in candidates:
            li = [i for i, row in enumerate(X) if row[f] < thr]
            ri = [i for i, row in enumerate(X) if row[f] >= thr]
            if not li or not ri:
                continue
            GL = sum(grad[i] for i in li); HL = sum(hess[i] for i in li) + lam
            GR = sum(grad[i] for i in ri); HR = sum(hess[i] for i in ri) + lam
            gain = 0.5 * ((GL * GL) / HL + (GR * GR) / HR - (G * G) / H)
            if gain > best_gain:
                best_gain = gain
                best_feat = f
                best_thr = thr
                best_split = (li, ri)

    if best_feat < 0 or best_split is None:
        return _StubNode(value=-G / H)

    li, ri = best_split
    XL = [X[i] for i in li]; gL = [grad[i] for i in li]; hL = [hess[i] for i in li]
    XR = [X[i] for i in ri]; gR = [grad[i] for i in ri]; hR = [hess[i] for i in ri]
    return _StubNode(
        feature=best_feat, threshold=best_thr,
        left=_stub_build_tree(XL, gL, hL, depth + 1, max_depth, min_samples, lam, rng),
        right=_stub_build_tree(XR, gR, hR, depth + 1, max_depth, min_samples, lam, rng),
    )


def _stub_predict_tree(node: _StubNode, row: List[float]) -> float:
    while node.feature >= 0:
        node = node.left if row[node.feature] < node.threshold else node.right  # type: ignore
        if node is None:
            return 0.0
    return node.value


def _sigmoid(z: float) -> float:
    if z >= 0:
        e = math.exp(-z)
        return 1.0 / (1.0 + e)
    e = math.exp(z)
    return e / (1.0 + e)


def _stub_train(X: List[List[float]], y: List[int],
                 n_estimators: int = 20, max_depth: int = 3,
                 lr: float = 0.3, seed: int = 1337) -> Dict[str, Any]:
    """Train a tiny gradient-boosted ensemble. Returns serializable dict."""
    rng = random.Random(seed)
    n = len(X)
    base = 0.0
    if n > 0:
        pos = sum(y); pos = max(min(pos, n - 1), 1)  # clamp to avoid log(0)
        base = math.log(pos / (n - pos))
    pred = [base] * n
    trees: List[_StubNode] = []
    for _ in range(n_estimators):
        # binary log-loss gradients
        p = [_sigmoid(z) for z in pred]
        grad = [p[i] - y[i] for i in range(n)]
        hess = [p[i] * (1.0 - p[i]) + 1e-6 for i in range(n)]
        tree = _stub_build_tree(X, grad, hess, depth=0, max_depth=max_depth, rng=rng)
        trees.append(tree)
        for i, row in enumerate(X):
            pred[i] += lr * _stub_predict_tree(tree, row)
    return {
        "model_kind": "stub_gbm_v1",
        "base_score": base,
        "lr": lr,
        "feature_order": list(FEATURE_ORDER),
        "trees": [_stub_tree_to_dict(t) for t in trees],
    }


def _stub_tree_to_dict(node: _StubNode) -> Dict[str, Any]:
    if node.feature < 0:
        return {"v": node.value}
    return {
        "f": node.feature, "t": node.threshold,
        "l": _stub_tree_to_dict(node.left) if node.left else {"v": 0.0},
        "r": _stub_tree_to_dict(node.right) if node.right else {"v": 0.0},
    }


def _stub_tree_from_dict(d: Dict[str, Any]) -> _StubNode:
    if "v" in d:
        return _StubNode(value=float(d["v"]))
    return _StubNode(
        feature=int(d["f"]), threshold=float(d["t"]),
        left=_stub_tree_from_dict(d["l"]),
        right=_stub_tree_from_dict(d["r"]),
    )


def _stub_predict_proba(model: Dict[str, Any], row: List[float]) -> float:
    z = float(model.get("base_score", 0.0))
    lr = float(model.get("lr", 0.3))
    for t in model["trees"]:
        node = _stub_tree_from_dict(t)
        z += lr * _stub_predict_tree(node, row)
    return _sigmoid(z)


def _stub_feature_importance(model: Dict[str, Any]) -> Dict[str, float]:
    """Count how often each feature is used as a split."""
    counts: Dict[int, int] = {}
    for t in model["trees"]:
        _stub_walk_count(t, counts)
    feats = model.get("feature_order", FEATURE_ORDER)
    total = sum(counts.values()) or 1
    return {feats[i]: counts.get(i, 0) / total for i in range(len(feats))}


def _stub_walk_count(d: Dict[str, Any], counts: Dict[int, int]) -> None:
    if "v" in d:
        return
    counts[int(d["f"])] = counts.get(int(d["f"]), 0) + 1
    _stub_walk_count(d["l"], counts)
    _stub_walk_count(d["r"], counts)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _row_to_vector(row: Dict[str, Any]) -> List[float]:
    """Project a feature dict onto FEATURE_ORDER as a float vector."""
    vec: List[float] = []
    for k in FEATURE_ORDER:
        v = row.get(k, 0.0)
        try:
            vec.append(float(v))
        except (TypeError, ValueError):
            vec.append(0.0)
    return vec


def _load_features(features_csv: Path) -> Tuple[List[str], List[List[float]]]:
    """Load wallets + feature vectors from CSV."""
    wallets: List[str] = []
    X: List[List[float]] = []
    with open(features_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            w = row.get("wallet") or row.get("address") or ""
            if not w:
                continue
            wallets.append(w)
            X.append(_row_to_vector(row))
    return wallets, X


def _load_labels(gmm_labels_csv: Path) -> Dict[str, int]:
    """Load wallet → binary label (bot=1, human=0) from GMM labels CSV.

    Accepts either:
      - cluster_label column with values like 'bot'/'human'/'mixed', OR
      - bot_probability column (>=0.5 → 1, else 0)
    """
    labels: Dict[str, int] = {}
    with open(gmm_labels_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            w = row.get("wallet") or row.get("address") or ""
            if not w:
                continue
            cl = (row.get("cluster_label") or "").strip().lower()
            if cl == "bot":
                labels[w] = 1
                continue
            if cl == "human":
                labels[w] = 0
                continue
            bp = row.get("bot_probability")
            if bp is not None and bp != "":
                try:
                    labels[w] = 1 if float(bp) >= 0.5 else 0
                    continue
                except ValueError:
                    pass
            # default: skip ambiguous rows
    return labels


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

def train_xgb(features_csv: Path,
              gmm_labels_csv: Path,
              model_out_path: Optional[Path] = None,
              use_gpu: bool = True) -> dict:
    """Train binary classifier on GMM-labeled features. Returns metrics dict.

    Persists to `studio/assets/_models/pump_xgb.json` by default.
    If xgboost is available, uses xgb.train; otherwise falls back to the
    stdlib stub gradient-boosting ensemble.
    """
    features_csv = Path(features_csv)
    gmm_labels_csv = Path(gmm_labels_csv)
    out_path = Path(model_out_path) if model_out_path else DEFAULT_MODEL_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wallets, X = _load_features(features_csv)
    label_map = _load_labels(gmm_labels_csv)

    paired_X: List[List[float]] = []
    paired_y: List[int] = []
    paired_w: List[str] = []
    for w, x in zip(wallets, X):
        if w in label_map:
            paired_X.append(x)
            paired_y.append(label_map[w])
            paired_w.append(w)

    n = len(paired_X)
    if n < 2:
        raise ValueError(f"need ≥2 labeled rows for training, got {n}")

    # 80/20 deterministic split
    rng = random.Random(42)
    indices = list(range(n))
    rng.shuffle(indices)
    cut = max(1, int(n * 0.8))
    train_idx = indices[:cut]
    test_idx = indices[cut:] or indices[-1:]  # ensure non-empty holdout
    Xtr = [paired_X[i] for i in train_idx]
    ytr = [paired_y[i] for i in train_idx]
    Xte = [paired_X[i] for i in test_idx]
    yte = [paired_y[i] for i in test_idx]

    t0 = time.time()
    model_kind = ""
    importances: Dict[str, float] = {}
    backend = "stub"

    if _HAS_XGB:
        backend = "xgboost"
        model_kind = "xgb_v1"
        try:
            dtrain = xgb.DMatrix(Xtr, label=ytr, feature_names=FEATURE_ORDER)
            dtest = xgb.DMatrix(Xte, label=yte, feature_names=FEATURE_ORDER)
            params: Dict[str, Any] = {
                "objective": "binary:logistic",
                "eval_metric": "logloss",
                "max_depth": 4,
                "eta": 0.2,
                "subsample": 0.9,
                "tree_method": "hist",
                "verbosity": 0,
                "seed": 42,
            }
            if use_gpu:
                # xgboost 2.x style; harmless on CPU build (will error → caught)
                try:
                    params["device"] = "cuda"
                    booster = xgb.train(params, dtrain, num_boost_round=80,
                                         evals=[(dtest, "test")], verbose_eval=False)
                except Exception:
                    params.pop("device", None)
                    booster = xgb.train(params, dtrain, num_boost_round=80,
                                         evals=[(dtest, "test")], verbose_eval=False)
            else:
                booster = xgb.train(params, dtrain, num_boost_round=80,
                                     evals=[(dtest, "test")], verbose_eval=False)

            booster.save_model(str(out_path))
            # Importance map (gain-based)
            try:
                raw = booster.get_score(importance_type="gain")
                tot = sum(raw.values()) or 1.0
                importances = {k: v / tot for k, v in raw.items()}
            except Exception:
                importances = {}
            preds_te = booster.predict(dtest).tolist()
            preds_tr = booster.predict(dtrain).tolist()
        except Exception as e:
            sys.stderr.write(f"xgboost path failed ({type(e).__name__}: {e}), "
                             f"falling back to stub\n")
            backend = "stub"

    if backend == "stub":
        model_kind = "stub_gbm_v1"
        stub = _stub_train(Xtr, ytr, n_estimators=20, max_depth=3, lr=0.3, seed=42)
        # write as plain JSON (xgb model_kind=stub_gbm_v1)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(stub, f, separators=(",", ":"))
        importances = _stub_feature_importance(stub)
        preds_te = [_stub_predict_proba(stub, row) for row in Xte]
        preds_tr = [_stub_predict_proba(stub, row) for row in Xtr]

    train_time_ms = int((time.time() - t0) * 1000)

    # Holdout accuracy + simple AUC-ish
    def _acc(preds: List[float], truth: List[int]) -> float:
        if not truth:
            return 0.0
        hits = sum(1 for p, y in zip(preds, truth) if (p >= 0.5) == bool(y))
        return hits / len(truth)
    train_acc = _acc(preds_tr, ytr)
    test_acc = _acc(preds_te, yte)

    metrics = {
        "backend": backend,
        "xgboost_available": _HAS_XGB,
        "xgboost_version": _XGB_VERSION,
        "model_kind": model_kind,
        "model_path": str(out_path),
        "n_train": len(Xtr),
        "n_test": len(Xte),
        "n_pos": sum(ytr),
        "n_neg": len(ytr) - sum(ytr),
        "train_acc": round(train_acc, 4),
        "holdout_acc": round(test_acc, 4),
        "train_time_ms": train_time_ms,
        "feature_importance": {k: round(v, 4) for k, v in importances.items()},
        "feature_order": FEATURE_ORDER,
    }

    _emit_crystal(
        tier="ml_train",
        model="pump_xgboost",
        scope="xgb_trained",
        source_file=str(features_csv),
        output_text=json.dumps({"backend": backend,
                                  "holdout_acc": metrics["holdout_acc"],
                                  "n_train": metrics["n_train"],
                                  "feature_importance": metrics["feature_importance"]},
                                separators=(",", ":")),
    )

    return metrics


# ---------------------------------------------------------------------------
# Predict
# ---------------------------------------------------------------------------

def _load_model(model_path: Optional[Path] = None) -> Tuple[str, Any]:
    """Returns (model_kind, model_object).
    model_object is xgb.Booster for xgb_v1, dict for stub_gbm_v1.
    """
    p = Path(model_path) if model_path else DEFAULT_MODEL_PATH
    if not p.exists():
        raise FileNotFoundError(f"model not found at {p}; run `train` first")

    # Try to identify by content — xgboost saves a JSON with "version" and
    # "learner" keys; stub uses "model_kind" key.
    try:
        with open(p, "r", encoding="utf-8") as f:
            blob = json.load(f)
    except Exception as e:
        raise ValueError(f"cannot parse model file: {e}")

    if isinstance(blob, dict) and blob.get("model_kind") == "stub_gbm_v1":
        return "stub_gbm_v1", blob

    if _HAS_XGB:
        booster = xgb.Booster()
        booster.load_model(str(p))
        return "xgb_v1", booster

    raise RuntimeError("model is an xgboost dump but xgboost is not installed")


def predict_wallet(features_row: Dict[str, Any],
                    model_path: Optional[Path] = None) -> dict:
    """Returns {bot_probability, prediction_latency_ms, backend}."""
    kind, mdl = _load_model(model_path)
    vec = _row_to_vector(features_row)

    t0 = time.perf_counter()
    if kind == "stub_gbm_v1":
        prob = _stub_predict_proba(mdl, vec)
        backend = "stub"
    else:
        dmat = xgb.DMatrix([vec], feature_names=FEATURE_ORDER)
        prob = float(mdl.predict(dmat)[0])
        backend = "xgboost"
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "bot_probability": round(float(prob), 6),
        "prediction_latency_ms": round(elapsed_ms, 4),
        "backend": backend,
    }


# ---------------------------------------------------------------------------
# Gate (the public decision)
# ---------------------------------------------------------------------------

def gate(wallet_feature_row: Dict[str, Any],
         human_cluster_inflow_score: float,
         model_path: Optional[Path] = None) -> GateDecision:
    """Decision gate. Combines XGB bot_probability + human_inflow.

    Logic (matches card):
      bot ≥ 0.85 AND inflow < 0.20 → 'abort'          (pure bot cluster → rug)
      bot ≥ 0.85 AND inflow ≥ 0.40 → 'surf_candidate' (bot vol + humans flooding)
      bot ≥ 0.85 AND 0.20 ≤ inflow < 0.40 → 'hold'    (uncertain — wait)
      bot < 0.30                  → 'hold'             (organic, no momentum)
      else                        → 'hold' (mixed signal)
    """
    wallet = str(wallet_feature_row.get("wallet")
                  or wallet_feature_row.get("address")
                  or "unknown")
    inflow = max(0.0, min(1.0, float(human_cluster_inflow_score)))

    try:
        pred = predict_wallet(wallet_feature_row, model_path)
        bot_prob = float(pred["bot_probability"])
    except Exception as e:
        # Catastrophic: model missing → fail safely with 'hold' + reason
        return GateDecision(
            wallet=wallet, decision="hold",
            bot_probability=0.0, human_inflow_score=inflow,
            reason=f"model_unavailable:{type(e).__name__}",
            crystal="",
        )

    if bot_prob >= BOT_HIGH_THRESHOLD and inflow < HUMAN_INFLOW_LOW:
        decision = "abort"
        reason = "pure_bot_cluster_no_human_interest"
    elif bot_prob >= BOT_HIGH_THRESHOLD and inflow >= HUMAN_INFLOW_HIGH:
        decision = "surf_candidate"
        reason = "bot_volume_plus_human_inflow"
    elif bot_prob >= BOT_HIGH_THRESHOLD:
        decision = "hold"
        reason = "bot_volume_uncertain_human_signal"
    elif bot_prob < BOT_LOW_THRESHOLD:
        decision = "hold"
        reason = "organic_no_bot_momentum"
    else:
        decision = "hold"
        reason = "mixed_signal"

    crystal = _emit_crystal(
        tier="ml_inference",
        model="pump_xgboost_gate",
        scope="gate_decision",
        source_file=wallet,
        output_text=json.dumps({"decision": decision,
                                  "bot_probability": round(bot_prob, 6),
                                  "human_inflow": round(inflow, 4),
                                  "reason": reason},
                                separators=(",", ":")),
    )

    return GateDecision(
        wallet=wallet, decision=decision,
        bot_probability=round(bot_prob, 6),
        human_inflow_score=round(inflow, 4),
        reason=reason, crystal=crystal,
    )


# ---------------------------------------------------------------------------
# Crystal anchor (fire-and-forget; never blocks)
# ---------------------------------------------------------------------------

def _emit_crystal(tier: str, model: str, scope: str,
                   source_file: str, output_text: str) -> str:
    try:
        # add core/lib to path for direct script invocation
        _here = str(Path(__file__).parent)
        if _here not in sys.path:
            sys.path.insert(0, _here)
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=f"{model}:{scope}",
            enhanced_prompt=source_file[:128],
            output_text=output_text,
            tier=tier, model=model, scope=scope,
            tokens_in=0, tokens_out=0, latency_ms=0,
            source_file=source_file,
            source_action="pump_xgb_gate",
            done_flag=True, rc=0,
        ) or ""
    except Exception as e:
        # NEVER block gate. Log to stderr and move on.
        sys.stderr.write(f"warn: pump_xgb crystal log failed: "
                         f"{type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Feature importance CLI helper
# ---------------------------------------------------------------------------

def feature_importance(model_path: Optional[Path] = None) -> Dict[str, float]:
    """Return normalized feature importance dict."""
    kind, mdl = _load_model(model_path)
    if kind == "stub_gbm_v1":
        return _stub_feature_importance(mdl)
    try:
        raw = mdl.get_score(importance_type="gain")
        tot = sum(raw.values()) or 1.0
        return {k: v / tot for k, v in raw.items()}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_features_json(s: str) -> Dict[str, Any]:
    """Tolerate Python-dict-ish JSON missing quotes around keys."""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # try a light fix: quote bare keys
        import re
        fixed = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', s)
        return json.loads(fixed)


def _main() -> int:
    ap = argparse.ArgumentParser(description="pump_xgboost_gate CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_train = sub.add_parser("train", help="Train XGB on GMM labels")
    p_train.add_argument("features_csv")
    p_train.add_argument("gmm_labels_csv")
    p_train.add_argument("--out", default=None, help="model output path")
    p_train.add_argument("--cpu", action="store_true", help="force CPU")

    p_gate = sub.add_parser("gate", help="Run gate decision for one wallet")
    p_gate.add_argument("wallet")
    p_gate.add_argument("--features", required=True, help="JSON feature dict")
    p_gate.add_argument("--human-inflow", type=float, required=True)
    p_gate.add_argument("--model", default=None)

    p_pred = sub.add_parser("predict", help="Raw bot-probability for one wallet")
    p_pred.add_argument("wallet")
    p_pred.add_argument("--features", required=True)
    p_pred.add_argument("--model", default=None)

    p_imp = sub.add_parser("importance", help="Show feature importance")
    p_imp.add_argument("model_path", nargs="?", default=None)

    args = ap.parse_args()

    if args.cmd == "train":
        out = Path(args.out) if args.out else None
        metrics = train_xgb(
            Path(args.features_csv), Path(args.gmm_labels_csv),
            model_out_path=out, use_gpu=not args.cpu,
        )
        print(json.dumps(metrics, indent=2, sort_keys=True))
        return 0

    if args.cmd == "gate":
        feats = _parse_features_json(args.features)
        feats.setdefault("wallet", args.wallet)
        mdl = Path(args.model) if args.model else None
        d = gate(feats, args.human_inflow, model_path=mdl)
        print(json.dumps(asdict(d), indent=2))
        return 0

    if args.cmd == "predict":
        feats = _parse_features_json(args.features)
        feats.setdefault("wallet", args.wallet)
        mdl = Path(args.model) if args.model else None
        out = predict_wallet(feats, mdl)
        out["wallet"] = args.wallet
        print(json.dumps(out, indent=2))
        return 0

    if args.cmd == "importance":
        mdl = Path(args.model_path) if args.model_path else None
        imp = feature_importance(mdl)
        print(json.dumps(imp, indent=2, sort_keys=True))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(_main())
