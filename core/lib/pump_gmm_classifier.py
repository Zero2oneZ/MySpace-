#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        pump_gmm_classifier                                            =
# role:        ML · UNSUPERVISED_BOT_VS_HUMAN_CLUSTERING                      =
# tier:        L0                                                             =
# substrate:   per-train + per-inference crystal anchors via inference_logger =
# engine:      2-component full-cov GMM (sklearn) OR stdlib EM fallback       =
# storage:     studio/assets/_models/pump_gmm.pkl                             =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.pump_gmm_classifier.active.json  =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - pump_feature_extractor (parallel agent B) -> features CSV / row dict    =
#   - surf executor (downstream) -> bot_cluster_signature() for live scoring  =
#   - CLI: python3 core/lib/pump_gmm_classifier.py {train,classify-wallet,    =
#          inspect}                                                           =
# outbound:                                                                   =
#   - pickle.dump/load of trained model bundle                                =
#   - inference_logger.InferenceLogger.log (crystal anchor per call)          =
# substrate touch:                                                            =
#   - reads:  features CSV (pump_feature_extractor output)                    =
#   - writes: studio/assets/_models/pump_gmm.pkl + inference_master_chain     =
# ============================================================================
"""pump_gmm_classifier.py — unsupervised 2-cluster GMM (bot vs human).

Trains on the 10 behavioral features produced by pump_feature_extractor:
  tx_per_block, tx_per_block_var, value_entropy, benford_distance,
  funding_proximity, gas_distortion, jito_bundle_ratio, buy_sell_balance,
  unique_mints_touched, session_length_seconds.

Cluster IDs are arbitrary. Post-training, we assign 'bot_cluster' to whichever
of the two clusters has the LOWER value_entropy mean (bots emit more uniform
trade values -> less entropy). The mapping is persisted alongside the model.

sklearn is OPTIONAL. If `from sklearn.mixture import GaussianMixture` works we
use it. Otherwise we run a tiny stdlib EM loop:
  - k-means++ stub for initial means
  - 50 iterations of E-step (responsibilities) + M-step (means, vars, weights)
  - diagonal covariance (one variance per feature per component)
  - log-likelihood tracked across iterations

Persistence: stdlib `pickle`. The bundle records sklearn-vs-fallback shape so
inspect/classify_wallet can reload either. Bundle also includes the bot
cluster id + bot_mean_features so downstream consumers don't re-derive.

Crystal anchor:
  - training -> tier='ml_train', model='pump_gmm', scope='gmm_trained'
  - per-wallet inference -> tier='ml_inference', model='pump_gmm',
                            scope='wallet_classified', source_file=<wallet>

CLI:
  python3 core/lib/pump_gmm_classifier.py train <features.csv> [--out PATH]
  python3 core/lib/pump_gmm_classifier.py classify-wallet <wallet> \
      --features '<json>'
  python3 core/lib/pump_gmm_classifier.py inspect <model_path>
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
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
FEATURE_NAMES: Tuple[str, ...] = (
    "tx_per_block",
    "tx_per_block_var",
    "value_entropy",
    "benford_distance",
    "funding_proximity",
    "gas_distortion",
    "jito_bundle_ratio",
    "buy_sell_balance",
    "unique_mints_touched",
    "session_length_seconds",
)
NUM_FEATURES = len(FEATURE_NAMES)
N_COMPONENTS = 2

# Project layout — resolve via paths.py if present, else fall back to walking up
def _default_model_path() -> Path:
    try:
        from paths import STUDIO_DIR  # type: ignore
        return Path(STUDIO_DIR) / "assets" / "_models" / "pump_gmm.pkl"
    except Exception:
        pass
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "studio"))
        from paths import STUDIO_DIR  # type: ignore
        return Path(STUDIO_DIR) / "assets" / "_models" / "pump_gmm.pkl"
    except Exception:
        pass
    # Fallback: walk up looking for studio/
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        cand = parent / "studio" / "assets" / "_models" / "pump_gmm.pkl"
        if (parent / "studio").is_dir():
            return cand
    return Path.cwd() / "studio" / "assets" / "_models" / "pump_gmm.pkl"

DEFAULT_MODEL_PATH = _default_model_path()

# ----------------------------------------------------------------------------
# Optional sklearn detection
# ----------------------------------------------------------------------------
try:
    from sklearn.mixture import GaussianMixture  # type: ignore
    _HAS_SKLEARN = True
except Exception:
    GaussianMixture = None  # type: ignore
    _HAS_SKLEARN = False


# ----------------------------------------------------------------------------
# Public dataclass
# ----------------------------------------------------------------------------
@dataclass
class ClusterAssignment:
    wallet: str
    cluster_id: int            # 0 or 1
    cluster_label: str         # 'bot' | 'human'
    bot_probability: float     # GMM responsibility for the bot cluster
    crystal: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------------
# Feature row utilities
# ----------------------------------------------------------------------------
def _row_to_vector(row: Dict[str, Any]) -> List[float]:
    out: List[float] = []
    for k in FEATURE_NAMES:
        try:
            out.append(float(row[k]))
        except (KeyError, TypeError, ValueError):
            out.append(0.0)
    return out


def _load_features_csv(path: Path) -> Tuple[List[str], List[List[float]]]:
    wallets: List[str] = []
    vectors: List[List[float]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            wallets.append(row.get("wallet", f"row_{len(wallets)}"))
            vectors.append(_row_to_vector(row))
    return wallets, vectors


def _features_df_to_rows(features_df: Any) -> Tuple[List[str], List[List[float]]]:
    """Accept either a list[dict], a path-like CSV, or a pandas DataFrame."""
    # path-like
    if isinstance(features_df, (str, Path)):
        return _load_features_csv(Path(features_df))
    # pandas-ish: has iterrows or to_dict
    if hasattr(features_df, "iterrows"):
        wallets, vectors = [], []
        for _, r in features_df.iterrows():
            d = dict(r)
            wallets.append(str(d.get("wallet", f"row_{len(wallets)}")))
            vectors.append(_row_to_vector(d))
        return wallets, vectors
    # list of dicts
    if isinstance(features_df, list):
        wallets, vectors = [], []
        for i, r in enumerate(features_df):
            wallets.append(str(r.get("wallet", f"row_{i}")))
            vectors.append(_row_to_vector(r))
        return wallets, vectors
    raise TypeError(f"unsupported features_df type: {type(features_df)!r}")


# ----------------------------------------------------------------------------
# Stdlib EM fallback (2-component, diagonal covariance)
# ----------------------------------------------------------------------------
def _vec_sub(a: List[float], b: List[float]) -> List[float]:
    return [a[i] - b[i] for i in range(len(a))]


def _vec_sq_dist(a: List[float], b: List[float]) -> float:
    s = 0.0
    for i in range(len(a)):
        d = a[i] - b[i]
        s += d * d
    return s


def _kmeanspp_init(data: List[List[float]], k: int, rng: random.Random) -> List[List[float]]:
    """k-means++ seed: pick first uniformly, then weight remaining by sq distance."""
    n = len(data)
    if n == 0:
        return [[0.0] * NUM_FEATURES for _ in range(k)]
    first = rng.randrange(n)
    centers: List[List[float]] = [list(data[first])]
    while len(centers) < k:
        d2 = []
        total = 0.0
        for p in data:
            best = min(_vec_sq_dist(p, c) for c in centers)
            d2.append(best)
            total += best
        if total <= 0.0:
            # all points coincide with existing centers; just pick another random
            centers.append(list(data[rng.randrange(n)]))
            continue
        r = rng.random() * total
        acc = 0.0
        chosen = n - 1
        for i, v in enumerate(d2):
            acc += v
            if acc >= r:
                chosen = i
                break
        centers.append(list(data[chosen]))
    return centers


class _StdlibGMM:
    """Tiny 2-component diagonal-cov GMM via EM (stdlib only).

    State:
      means    : list[list[float]]   shape (k, d)
      variances: list[list[float]]   shape (k, d)  diagonal
      weights  : list[float]         shape (k,)    mixture weights
      log_likelihood: float          final
    """

    EPS = 1e-6

    def __init__(self, n_components: int = N_COMPONENTS, max_iter: int = 50,
                 tol: float = 1e-4, random_state: int = 42):
        self.n_components = n_components
        self.max_iter = max_iter
        self.tol = tol
        self.random_state = random_state
        self.means: List[List[float]] = []
        self.variances: List[List[float]] = []
        self.weights: List[float] = []
        self.log_likelihood: float = float("-inf")

    @staticmethod
    def _log_normal_diag(x: List[float], mean: List[float],
                         var: List[float]) -> float:
        """log N(x | mean, diag(var))."""
        d = len(x)
        s = 0.0
        for i in range(d):
            v = max(var[i], _StdlibGMM.EPS)
            s += math.log(2.0 * math.pi * v) + ((x[i] - mean[i]) ** 2) / v
        return -0.5 * s

    @staticmethod
    def _logsumexp(values: List[float]) -> float:
        m = max(values)
        if m == float("-inf"):
            return m
        s = 0.0
        for v in values:
            s += math.exp(v - m)
        return m + math.log(s)

    def fit(self, data: List[List[float]]) -> "_StdlibGMM":
        n = len(data)
        if n == 0:
            raise ValueError("cannot fit GMM on empty data")
        d = len(data[0])
        rng = random.Random(self.random_state)

        # Init means via k-means++ stub
        self.means = _kmeanspp_init(data, self.n_components, rng)

        # Init variances: feature-wise variance across the whole dataset
        global_mean = [sum(p[i] for p in data) / n for i in range(d)]
        global_var = [
            max(sum((p[i] - global_mean[i]) ** 2 for p in data) / n, self.EPS)
            for i in range(d)
        ]
        self.variances = [list(global_var) for _ in range(self.n_components)]

        # Uniform initial weights
        self.weights = [1.0 / self.n_components] * self.n_components

        prev_ll = float("-inf")
        for _ in range(self.max_iter):
            # E-step: compute responsibilities + log-likelihood
            resps: List[List[float]] = []
            ll = 0.0
            for x in data:
                logp = [
                    math.log(max(self.weights[k], self.EPS))
                    + self._log_normal_diag(x, self.means[k], self.variances[k])
                    for k in range(self.n_components)
                ]
                lse = self._logsumexp(logp)
                ll += lse
                resps.append([math.exp(lp - lse) for lp in logp])

            # M-step
            for k in range(self.n_components):
                nk = sum(r[k] for r in resps)
                nk_safe = max(nk, self.EPS)
                # mean
                self.means[k] = [
                    sum(resps[i][k] * data[i][j] for i in range(n)) / nk_safe
                    for j in range(d)
                ]
                # diagonal variance
                self.variances[k] = [
                    max(
                        sum(resps[i][k] * (data[i][j] - self.means[k][j]) ** 2
                            for i in range(n)) / nk_safe,
                        self.EPS,
                    )
                    for j in range(d)
                ]
                # weight
                self.weights[k] = nk_safe / n

            self.log_likelihood = ll
            if abs(ll - prev_ll) < self.tol:
                break
            prev_ll = ll
        return self

    def predict_proba_one(self, x: List[float]) -> List[float]:
        logp = [
            math.log(max(self.weights[k], self.EPS))
            + self._log_normal_diag(x, self.means[k], self.variances[k])
            for k in range(self.n_components)
        ]
        lse = self._logsumexp(logp)
        return [math.exp(lp - lse) for lp in logp]

    def predict_proba(self, data: List[List[float]]) -> List[List[float]]:
        return [self.predict_proba_one(x) for x in data]

    def predict(self, data: List[List[float]]) -> List[int]:
        out = []
        for probs in self.predict_proba(data):
            out.append(0 if probs[0] >= probs[1] else 1)
        return out


# ----------------------------------------------------------------------------
# Crystal anchor (graceful)
# ----------------------------------------------------------------------------
def _try_crystal_anchor(*, tier: str, scope: str, output_text: str,
                        source_file: str = "",
                        source_action: str = "") -> str:
    """Log via inference_logger if available. Always returns a string id."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from inference_logger import InferenceLogger  # type: ignore
        logger = InferenceLogger()
        cid = logger.log(
            original_prompt="pump_gmm_classifier",
            enhanced_prompt=scope,
            output_text=output_text,
            tier=tier,
            model="pump_gmm",
            scope=scope,
            source_file=source_file,
            source_action=source_action,
        )
        return cid or ""
    except Exception:
        # Stable local fallback hash so we still emit a crystal id
        import hashlib
        payload = f"{tier}|{scope}|{output_text}|{source_file}|{source_action}"
        return hashlib.blake2b(payload.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------
# Bot-cluster identification
# ----------------------------------------------------------------------------
def _identify_bot_cluster(vectors: List[List[float]], labels: List[int]
                          ) -> Tuple[int, float, float, Dict[int, List[float]]]:
    """Bot cluster = the one with LOWER value_entropy mean.

    Returns: (bot_cluster_id, bot_mean_entropy, human_mean_entropy,
              mean_features_per_cluster).
    """
    ve_idx = FEATURE_NAMES.index("value_entropy")
    sums: Dict[int, List[float]] = {k: [0.0] * NUM_FEATURES
                                    for k in range(N_COMPONENTS)}
    counts: Dict[int, int] = {k: 0 for k in range(N_COMPONENTS)}
    for v, c in zip(vectors, labels):
        if c not in sums:
            continue
        counts[c] += 1
        for j in range(NUM_FEATURES):
            sums[c][j] += v[j]
    means: Dict[int, List[float]] = {}
    for c in range(N_COMPONENTS):
        n = max(counts.get(c, 0), 1)
        means[c] = [sums[c][j] / n for j in range(NUM_FEATURES)]
    ve_0 = means[0][ve_idx] if counts.get(0, 0) > 0 else float("inf")
    ve_1 = means[1][ve_idx] if counts.get(1, 0) > 0 else float("inf")
    bot_id = 0 if ve_0 <= ve_1 else 1
    human_id = 1 - bot_id
    return bot_id, means[bot_id][ve_idx], means[human_id][ve_idx], means


# ----------------------------------------------------------------------------
# Public API: train_gmm
# ----------------------------------------------------------------------------
def train_gmm(features_df: Any,
              model_out_path: Optional[Path] = None,
              random_state: int = 42) -> Dict[str, Any]:
    """Train a 2-component GMM on the 10 behavioral features.

    `features_df` may be: a CSV path, a list[dict], or a pandas DataFrame.
    Returns: dict with model_path, n_samples, bot_cluster_id, bot_mean_entropy,
             human_mean_entropy, log_likelihood, sklearn_used.
    """
    wallets, vectors = _features_df_to_rows(features_df)
    n_samples = len(vectors)
    if n_samples < 2:
        raise ValueError(f"need >= 2 samples to train a 2-component GMM, got {n_samples}")

    out_path = Path(model_out_path) if model_out_path else DEFAULT_MODEL_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bundle: Dict[str, Any] = {
        "schema_version": 1,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "feature_names": list(FEATURE_NAMES),
        "n_components": N_COMPONENTS,
        "random_state": random_state,
        "n_samples": n_samples,
        "sklearn_used": _HAS_SKLEARN,
    }

    if _HAS_SKLEARN:
        # Use a small list-of-lists -> we pass through GaussianMixture directly
        gm = GaussianMixture(  # type: ignore
            n_components=N_COMPONENTS,
            covariance_type="full",
            random_state=random_state,
            max_iter=200,
        )
        gm.fit(vectors)
        labels = list(gm.predict(vectors))
        log_likelihood = float(gm.score(vectors) * n_samples)
        bundle["sklearn_model_bytes"] = pickle.dumps(gm)
    else:
        gm = _StdlibGMM(n_components=N_COMPONENTS, max_iter=50,
                       random_state=random_state)
        gm.fit(vectors)
        labels = gm.predict(vectors)
        log_likelihood = float(gm.log_likelihood)
        bundle["fallback_gmm"] = {
            "means": gm.means,
            "variances": gm.variances,
            "weights": gm.weights,
        }

    bot_id, bot_ve, human_ve, mean_feats = _identify_bot_cluster(vectors, labels)
    bundle["bot_cluster_id"] = bot_id
    bundle["bot_mean_entropy"] = bot_ve
    bundle["human_mean_entropy"] = human_ve
    bundle["log_likelihood"] = log_likelihood
    bundle["bot_mean_features"] = dict(zip(FEATURE_NAMES, mean_feats[bot_id]))
    bundle["human_mean_features"] = dict(zip(FEATURE_NAMES,
                                             mean_feats[1 - bot_id]))

    with out_path.open("wb") as f:
        pickle.dump(bundle, f, protocol=pickle.HIGHEST_PROTOCOL)

    summary_text = json.dumps({
        "model_path": str(out_path),
        "n_samples": n_samples,
        "bot_cluster_id": bot_id,
        "bot_mean_entropy": bot_ve,
        "human_mean_entropy": human_ve,
        "log_likelihood": log_likelihood,
        "sklearn_used": _HAS_SKLEARN,
    }, separators=(",", ":"))
    crystal = _try_crystal_anchor(
        tier="ml_train", scope="gmm_trained",
        output_text=summary_text,
        source_action=f"train n={n_samples} sklearn={_HAS_SKLEARN}",
    )

    return {
        "model_path": str(out_path),
        "n_samples": n_samples,
        "bot_cluster_id": bot_id,
        "bot_mean_entropy": bot_ve,
        "human_mean_entropy": human_ve,
        "log_likelihood": log_likelihood,
        "sklearn_used": _HAS_SKLEARN,
        "crystal": crystal,
    }


# ----------------------------------------------------------------------------
# Load helper
# ----------------------------------------------------------------------------
def _load_bundle(model_path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
    if not path.exists():
        raise FileNotFoundError(f"model not found: {path} — run `train` first")
    with path.open("rb") as f:
        return pickle.load(f)


def _bundle_predict_proba(bundle: Dict[str, Any],
                          vectors: List[List[float]]) -> List[List[float]]:
    if bundle.get("sklearn_used") and "sklearn_model_bytes" in bundle:
        try:
            gm = pickle.loads(bundle["sklearn_model_bytes"])
            return [list(row) for row in gm.predict_proba(vectors)]
        except Exception:
            # sklearn was used to train but missing at inference; fall through
            pass
    # Use fallback or rebuild equivalent
    fb = bundle.get("fallback_gmm")
    if fb is None:
        # sklearn-trained but sklearn now missing AND no fallback stored: emit
        # uniform probs so callers degrade rather than crash
        return [[0.5, 0.5] for _ in vectors]
    g = _StdlibGMM(n_components=N_COMPONENTS)
    g.means = fb["means"]
    g.variances = fb["variances"]
    g.weights = fb["weights"]
    return g.predict_proba(vectors)


# ----------------------------------------------------------------------------
# Public API: classify_wallet / classify_dataframe
# ----------------------------------------------------------------------------
def classify_wallet(features_row: Dict[str, Any],
                    model_path: Optional[Path] = None) -> ClusterAssignment:
    """Predict cluster + label + bot_probability for a single wallet row."""
    bundle = _load_bundle(model_path)
    wallet = str(features_row.get("wallet", "unknown"))
    vec = _row_to_vector(features_row)
    probs = _bundle_predict_proba(bundle, [vec])[0]
    cluster_id = 0 if probs[0] >= probs[1] else 1
    bot_id = int(bundle.get("bot_cluster_id", 0))
    cluster_label = "bot" if cluster_id == bot_id else "human"
    bot_probability = float(probs[bot_id])

    summary = json.dumps({
        "wallet": wallet,
        "cluster_id": cluster_id,
        "cluster_label": cluster_label,
        "bot_probability": bot_probability,
    }, separators=(",", ":"))
    crystal = _try_crystal_anchor(
        tier="ml_inference", scope="wallet_classified",
        output_text=summary,
        source_file=wallet,
        source_action=f"classify cluster={cluster_label}",
    )
    return ClusterAssignment(
        wallet=wallet,
        cluster_id=cluster_id,
        cluster_label=cluster_label,
        bot_probability=bot_probability,
        crystal=crystal,
    )


def classify_dataframe(features_df: Any,
                       model_path: Optional[Path] = None
                       ) -> List[ClusterAssignment]:
    bundle = _load_bundle(model_path)
    wallets, vectors = _features_df_to_rows(features_df)
    probs_list = _bundle_predict_proba(bundle, vectors)
    bot_id = int(bundle.get("bot_cluster_id", 0))
    out: List[ClusterAssignment] = []
    for w, probs in zip(wallets, probs_list):
        cluster_id = 0 if probs[0] >= probs[1] else 1
        cluster_label = "bot" if cluster_id == bot_id else "human"
        bot_probability = float(probs[bot_id])
        summary = json.dumps({
            "wallet": w,
            "cluster_id": cluster_id,
            "cluster_label": cluster_label,
            "bot_probability": bot_probability,
        }, separators=(",", ":"))
        crystal = _try_crystal_anchor(
            tier="ml_inference", scope="wallet_classified",
            output_text=summary,
            source_file=w,
            source_action=f"classify cluster={cluster_label}",
        )
        out.append(ClusterAssignment(
            wallet=w,
            cluster_id=cluster_id,
            cluster_label=cluster_label,
            bot_probability=bot_probability,
            crystal=crystal,
        ))
    return out


# ----------------------------------------------------------------------------
# Public API: bot_cluster_signature
# ----------------------------------------------------------------------------
def bot_cluster_signature(model_path: Optional[Path] = None) -> Dict[str, Any]:
    """Return the mean feature vector of the bot cluster + bookkeeping."""
    bundle = _load_bundle(model_path)
    return {
        "bot_cluster_id": int(bundle.get("bot_cluster_id", 0)),
        "bot_mean_features": dict(bundle.get("bot_mean_features", {})),
        "human_mean_features": dict(bundle.get("human_mean_features", {})),
        "bot_mean_entropy": float(bundle.get("bot_mean_entropy", 0.0)),
        "human_mean_entropy": float(bundle.get("human_mean_entropy", 0.0)),
        "n_samples": int(bundle.get("n_samples", 0)),
        "trained_at": bundle.get("trained_at", ""),
        "sklearn_used": bool(bundle.get("sklearn_used", False)),
    }


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def _parse_features_json(s: str) -> Dict[str, Any]:
    """Accept either strict JSON or a loose `{k:v,k:v}` Python-ish form."""
    s = s.strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # Loose parse: turn bare keys into quoted ones
    import re
    fixed = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'\1"\2"\3', s)
    return json.loads(fixed)


def _cmd_train(args: argparse.Namespace) -> int:
    out_path = Path(args.out) if args.out else DEFAULT_MODEL_PATH
    result = train_gmm(Path(args.features_csv), model_out_path=out_path)
    print(json.dumps(result, indent=2))
    return 0


def _cmd_classify_wallet(args: argparse.Namespace) -> int:
    feats = _parse_features_json(args.features)
    feats["wallet"] = args.wallet
    model_path = Path(args.model) if args.model else DEFAULT_MODEL_PATH
    assign = classify_wallet(feats, model_path=model_path)
    print(json.dumps(assign.to_dict(), indent=2))
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    model_path = Path(args.model_path)
    sig = bot_cluster_signature(model_path=model_path)
    print(json.dumps(sig, indent=2))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pump_gmm_classifier",
        description="2-component GMM bot-vs-human classifier (sklearn-or-fallback)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_tr = sub.add_parser("train", help="train GMM on features CSV")
    p_tr.add_argument("features_csv", help="path to features CSV from pump_feature_extractor")
    p_tr.add_argument("--out", default=None, help=f"model output path (default: {DEFAULT_MODEL_PATH})")
    p_tr.set_defaults(func=_cmd_train)

    p_cw = sub.add_parser("classify-wallet", help="classify one wallet")
    p_cw.add_argument("wallet", help="wallet id")
    p_cw.add_argument("--features", required=True, help="features as JSON dict")
    p_cw.add_argument("--model", default=None, help="model path")
    p_cw.set_defaults(func=_cmd_classify_wallet)

    p_in = sub.add_parser("inspect", help="dump bot cluster signature")
    p_in.add_argument("model_path", help="path to pump_gmm.pkl")
    p_in.set_defaults(func=_cmd_inspect)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
