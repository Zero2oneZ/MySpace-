"""swap_router.py — unified swap router across Solana + Sui + cross-chain.

Six routes covered:

    Same-chain pair (Jupiter v6 on Solana)
        USDC.sol ──→ SOL                     (USDC sells for SOL)
        SOL      ──→ USDC.sol                (SOL sells for USDC)

    Same-chain pair (Cetus / DeepBook on Sui)
        USDC.sui ──→ SUI                     (USDC sells for SUI)
        SUI      ──→ USDC.sui                (SUI sells for USDC)

    Cross-chain (Wormhole NTT / Mayan one-tx)
        SOL      ──→ SUI                     (native SOL → native SUI)
        SUI      ──→ SOL                     (native SUI → native SOL)

Safety architecture:
    - quote() is always safe; it hits read-only APIs.
    - execute() requires MSPC_SWAP_LIVE=1 + dry_run=False + explicit
      --confirm in CLI.
    - Without the gate, execute() returns a planned SwapResult with
      tx_digest='dry-run' and confirmed=False; the route is recorded
      crystal-anchored under tier='swap' scope='swap_dry_run'.

The execution side wraps existing connectors:
    - Solana legs:  core/lib/third_party/solana_mcp.py
    - Sui legs:     core/lib/third_party/sui_mcp.py
    - Cross-chain:  core/lib/third_party/wormhole_bridge (lazy; TEXT-PLACEHOLDER
                     for the sign-and-relay step until the operator signs off)

Crystal-anchored on every quote AND every execute. The chain becomes
queryable: cc inference-chain --tier swap | head.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "lib"))
sys.path.insert(0, str(REPO / "core" / "lib" / "third_party"))

try:
    from inference_logger import InferenceLogger
    _LOG = InferenceLogger()
except Exception:
    _LOG = None

try:
    from dimension_pack import emit as _dim_emit
except Exception:
    _dim_emit = None


# ── token mint addresses (mainnet canonical) ────────────────────────────────

# Solana mints
SOL_MINT = "So11111111111111111111111111111111111111112"  # wrapped SOL on Solana
USDC_SOLANA_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Sui coin types (full Sui coin type path including struct name)
SUI_COIN_TYPE = "0x2::sui::SUI"
USDC_SUI_TYPE = "0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7::usdc::USDC"

# Wormhole-wrapped versions used in cross-chain hops
USDC_SUI_WORMHOLE = "0x5d4b302506645c37ff133b98c4b50a5ae14841659738d6d733d59d0d217a93bf::coin::COIN"  # wUSDC.sol on Sui
SOL_WORMHOLE_ON_SUI = "0xb7844e289a8410e50fb3ca48d69eb9cf29e27d223ef90353fe1bd8e27ff8f3f8::coin::COIN"

TOKEN_LABELS: Dict[str, str] = {
    "USDC.sol": USDC_SOLANA_MINT,
    "USDC.sui": USDC_SUI_TYPE,
    "SOL":      SOL_MINT,
    "SUI":      SUI_COIN_TYPE,
}

# ── chain inference ────────────────────────────────────────────────────────

def token_chain(token_label: str) -> str:
    t = token_label.upper()
    if t in ("USDC.SOL", "SOL"):
        return "solana"
    if t in ("USDC.SUI", "SUI"):
        return "sui"
    raise ValueError(f"unknown token label: {token_label}")


# ── jupiter HTTP API (Solana legs) ─────────────────────────────────────────

JUPITER_LITE_BASE = os.environ.get("JUPITER_API_BASE",
                                     "https://lite-api.jup.ag/swap/v1")


def _http_get_json(url: str, timeout: float = 12.0) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        return {"_error": f"http {exc.code}", "_body": exc.read().decode()[:300]}
    except Exception as exc:
        return {"_error": repr(exc)[:300]}


def _http_post_json(url: str, payload: Dict, timeout: float = 12.0) -> Dict[str, Any]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        return {"_error": f"http {exc.code}", "_body": exc.read().decode()[:300]}
    except Exception as exc:
        return {"_error": repr(exc)[:300]}


def jupiter_quote(input_mint: str, output_mint: str,
                   amount_atomic: int, slippage_bps: int = 50) -> Dict[str, Any]:
    """Hit Jupiter v6 quote API. Returns dict with outAmount, priceImpactPct,
    routePlan, otherAmountThreshold, slippageBps, etc."""
    q = urllib.parse.urlencode({
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": amount_atomic,
        "slippageBps": slippage_bps,
        "restrictIntermediateTokens": "true",
        "swapMode": "ExactIn",
    })
    return _http_get_json(f"{JUPITER_LITE_BASE}/quote?{q}", timeout=15)


# ── data shapes ────────────────────────────────────────────────────────────

@dataclass
class SwapQuote:
    from_token: str
    to_token: str
    from_chain: str
    to_chain: str
    amount_in_human: float
    amount_in_atomic: int
    amount_out_est_atomic: int
    amount_out_est_human: float
    price_impact_pct: float
    slippage_bps: int
    fee_bps_total: int
    route_taken: str          # "jupiter_v6" | "cetus_clmm" | "deepbook" | "wormhole_ntt" | "mayan"
    route_steps: List[str]    # human-readable hops
    raw_provider_quote: Dict  # passthrough so the executor doesn't refetch
    gas_est_atomic: int = 0
    ts: float = field(default_factory=time.time)


@dataclass
class SwapResult:
    quote: SwapQuote
    dry_run: bool
    confirmed: bool
    tx_digests: List[str]
    amount_out_actual_atomic: int = 0
    error: str = ""
    crystal_anchor: str = ""
    ts: float = field(default_factory=time.time)


# ── decimals / scaling ─────────────────────────────────────────────────────

TOKEN_DECIMALS: Dict[str, int] = {
    "SOL":      9,
    "USDC.sol": 6,
    "SUI":      9,
    "USDC.sui": 6,
}


def to_atomic(amount_human: float, token_label: str) -> int:
    d = TOKEN_DECIMALS.get(token_label, 6)
    return int(round(amount_human * (10 ** d)))


def from_atomic(amount_atomic: int, token_label: str) -> float:
    d = TOKEN_DECIMALS.get(token_label, 6)
    return amount_atomic / (10 ** d)


# ── route selection ────────────────────────────────────────────────────────

def quote(from_token: str, to_token: str, amount_human: float,
           slippage_bps: int = 50) -> SwapQuote:
    """Pick the right provider for this pair and return a SwapQuote."""
    fc = token_chain(from_token)
    tc = token_chain(to_token)
    amt_atomic = to_atomic(amount_human, from_token)

    # Solana same-chain → Jupiter
    if fc == "solana" and tc == "solana":
        in_mint = TOKEN_LABELS[from_token]
        out_mint = TOKEN_LABELS[to_token]
        raw = jupiter_quote(in_mint, out_mint, amt_atomic, slippage_bps)
        if "_error" in raw:
            return SwapQuote(
                from_token=from_token, to_token=to_token,
                from_chain=fc, to_chain=tc,
                amount_in_human=amount_human, amount_in_atomic=amt_atomic,
                amount_out_est_atomic=0, amount_out_est_human=0.0,
                price_impact_pct=0.0, slippage_bps=slippage_bps,
                fee_bps_total=0,
                route_taken="jupiter_v6_error",
                route_steps=[raw.get("_error", "?")],
                raw_provider_quote=raw,
            )
        out_atomic = int(raw.get("outAmount", "0") or 0)
        price_impact = float(raw.get("priceImpactPct", 0.0) or 0.0)
        steps = []
        for p in (raw.get("routePlan") or []):
            info = p.get("swapInfo") or {}
            steps.append(f"{info.get('label','?')} {info.get('inputMint','')[:8]}→{info.get('outputMint','')[:8]}")
        return SwapQuote(
            from_token=from_token, to_token=to_token,
            from_chain=fc, to_chain=tc,
            amount_in_human=amount_human, amount_in_atomic=amt_atomic,
            amount_out_est_atomic=out_atomic,
            amount_out_est_human=from_atomic(out_atomic, to_token),
            price_impact_pct=price_impact * 100,
            slippage_bps=slippage_bps,
            fee_bps_total=0,
            route_taken="jupiter_v6",
            route_steps=steps,
            raw_provider_quote=raw,
        )

    # Sui same-chain → Cetus aggregator (live HTTP quote)
    if fc == "sui" and tc == "sui":
        return _cetus_quote(from_token, to_token, amount_human, amt_atomic,
                              slippage_bps)

    # Cross-chain SOL ↔ SUI → Mayan price API
    if (fc, tc) in (("solana", "sui"), ("sui", "solana")):
        return _mayan_quote(from_token, to_token, amount_human, amt_atomic,
                              slippage_bps)

    raise ValueError(f"no route from {from_token} to {to_token}")


# ── Cetus quote (Sui same-chain) ────────────────────────────────────────────

CETUS_QUOTE_BASE = os.environ.get(
    "CETUS_API_BASE",
    "https://api-sui.cetus.zone/router_v2/find_routes")


def _cetus_quote(from_token: str, to_token: str, amount_human: float,
                  amt_atomic: int, slippage_bps: int) -> SwapQuote:
    """Cetus Aggregator returns the best route across Cetus + DeepBook +
    Kriya + FlowX. Same-call response includes amount_out, fee, hops."""
    coin_in = TOKEN_LABELS[from_token]
    coin_out = TOKEN_LABELS[to_token]
    q = urllib.parse.urlencode({
        "from": coin_in, "target": coin_out, "amount": amt_atomic,
        "by_amount_in": "true",
    })
    resp = _http_get_json(f"{CETUS_QUOTE_BASE}?{q}", timeout=12)
    if "_error" in resp:
        return SwapQuote(
            from_token=from_token, to_token=to_token,
            from_chain="sui", to_chain="sui",
            amount_in_human=amount_human, amount_in_atomic=amt_atomic,
            amount_out_est_atomic=0, amount_out_est_human=0.0,
            price_impact_pct=0.0, slippage_bps=slippage_bps,
            fee_bps_total=0, route_taken="cetus_aggregator_error",
            route_steps=[resp.get("_error", "?")],
            raw_provider_quote=resp,
        )
    data = resp.get("data") if isinstance(resp.get("data"), dict) else resp
    out_atomic = int(data.get("amount_out") or data.get("outAmount") or 0)
    routes = data.get("routes") or data.get("routePlan") or []
    steps: List[str] = []
    fee_bps = 0
    for r in routes:
        for path in (r.get("path") or []):
            steps.append(f"{path.get('provider','cetus')} "
                          f"{path.get('from_coin','')[:8]}→"
                          f"{path.get('target_coin','')[:8]}")
        fee_bps = max(fee_bps, int(r.get("fee_bps", 0) or 0))
    return SwapQuote(
        from_token=from_token, to_token=to_token,
        from_chain="sui", to_chain="sui",
        amount_in_human=amount_human, amount_in_atomic=amt_atomic,
        amount_out_est_atomic=out_atomic,
        amount_out_est_human=from_atomic(out_atomic, to_token),
        price_impact_pct=float(data.get("priceImpactPct", 0) or 0) * 100,
        slippage_bps=slippage_bps, fee_bps_total=fee_bps or 30,
        route_taken="cetus_aggregator", route_steps=steps[:6],
        raw_provider_quote=data,
    )


# ── Mayan quote (cross-chain SOL ↔ SUI) ────────────────────────────────────

MAYAN_QUOTE_BASE = os.environ.get(
    "MAYAN_API_BASE",
    "https://price-api.mayan.finance/v3/quote")

# Mayan token symbols on each chain
MAYAN_CHAIN = {"solana": "solana", "sui": "sui"}
MAYAN_TOKEN = {"USDC.sol": "USDC", "SOL": "SOL",
                "USDC.sui": "USDC", "SUI": "SUI"}


def _mayan_quote(from_token: str, to_token: str, amount_human: float,
                  amt_atomic: int, slippage_bps: int) -> SwapQuote:
    """Mayan Swap is a fast cross-chain swap built on Wormhole NTT.
    Single-call quote includes amount_out, bridge fee, ETA."""
    fc = token_chain(from_token)
    tc = token_chain(to_token)
    q = urllib.parse.urlencode({
        "amountIn": amount_human,
        "fromToken": MAYAN_TOKEN[from_token],
        "fromChain": MAYAN_CHAIN[fc],
        "toToken": MAYAN_TOKEN[to_token],
        "toChain": MAYAN_CHAIN[tc],
        "slippageBps": slippage_bps,
        "gasDrop": 0,
    })
    # Mayan rejects requests without a User-Agent — pass one through urllib.
    req = urllib.request.Request(
        f"{MAYAN_QUOTE_BASE}?{q}",
        headers={"User-Agent": "mspc-swap-router/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        resp = {"_error": f"http {exc.code}",
                 "_body": exc.read().decode()[:300]}
    except Exception as exc:
        resp = {"_error": repr(exc)[:300]}
    if "_error" in resp:
        return SwapQuote(
            from_token=from_token, to_token=to_token,
            from_chain=fc, to_chain=tc,
            amount_in_human=amount_human, amount_in_atomic=amt_atomic,
            amount_out_est_atomic=0, amount_out_est_human=0.0,
            price_impact_pct=0.0, slippage_bps=slippage_bps,
            fee_bps_total=0, route_taken="mayan_error",
            route_steps=[resp.get("_error", "?")],
            raw_provider_quote=resp,
        )
    quotes = resp.get("quotes") if isinstance(resp, dict) else None
    if isinstance(quotes, list) and quotes:
        top = quotes[0]
    else:
        top = resp if isinstance(resp, dict) else {}
    out_amount = float(top.get("expectedAmountOut") or top.get("minAmountOut") or 0)
    bridge_fee = float(top.get("bridgeFee") or top.get("relayerFee") or 0)
    eta_seconds = int(top.get("eta") or top.get("estimatedTimeInSec") or 0)
    return SwapQuote(
        from_token=from_token, to_token=to_token,
        from_chain=fc, to_chain=tc,
        amount_in_human=amount_human, amount_in_atomic=amt_atomic,
        amount_out_est_atomic=to_atomic(out_amount, to_token),
        amount_out_est_human=out_amount,
        price_impact_pct=float(top.get("priceImpact", 0) or 0) * 100,
        slippage_bps=slippage_bps,
        fee_bps_total=int(bridge_fee * 100),
        route_taken="mayan_wormhole_ntt",
        route_steps=[
            f"{from_token} on {fc} → Wormhole core bridge",
            f"Guardian quorum (~{eta_seconds}s)",
            f"Mayan relayer → native {to_token} on {tc}",
        ],
        raw_provider_quote=top,
    )


# ── execute (gated) ────────────────────────────────────────────────────────

def execute(q: SwapQuote, dry_run: bool = True) -> SwapResult:
    """Send the planned swap. Gated by:
        dry_run=False AND MSPC_SWAP_LIVE=1 env

    Otherwise returns a planned SwapResult with tx_digests=['dry-run'].
    Every call (dry or live) gets crystal-anchored on the chain."""
    is_live = (not dry_run) and (os.environ.get("MSPC_SWAP_LIVE", "0") == "1")
    crystal = _anchor_swap(q, is_live=is_live)
    if not is_live:
        return SwapResult(
            quote=q, dry_run=True, confirmed=False,
            tx_digests=["dry-run"],
            amount_out_actual_atomic=q.amount_out_est_atomic,
            crystal_anchor=crystal,
            error="" if dry_run else "MSPC_SWAP_LIVE=1 not set",
        )

    # Live path — delegate to the provider-specific executor.
    try:
        if q.route_taken == "jupiter_v6":
            return _exec_jupiter(q, crystal)
        if q.route_taken.startswith("cetus") or q.route_taken == "deepbook":
            return _exec_sui_dex(q, crystal)
        if q.route_taken.startswith("wormhole") or q.route_taken == "mayan":
            return _exec_cross_chain(q, crystal)
    except Exception as exc:
        return SwapResult(quote=q, dry_run=False, confirmed=False,
                           tx_digests=[], crystal_anchor=crystal,
                           error=f"executor_raised: {exc!r}")
    return SwapResult(quote=q, dry_run=False, confirmed=False,
                       tx_digests=[], crystal_anchor=crystal,
                       error=f"no_executor_for_route:{q.route_taken}")


def _exec_jupiter(q: SwapQuote, crystal: str) -> SwapResult:
    """Build, sign, send via Jupiter v6 /swap. Requires:
      - solders + base58 installed in the python env (one-line opt-in:
        /data/Projects/ComfyUI/.venv/bin/pip install solders base58)
      - SOLANA_KEYPAIR_PATH points to a valid keypair file
      - SOLANA_RPC_URL points to the desired network (devnet = safe by default)
    Returns the tx signature on success; graceful error otherwise."""
    # Lazy-import the signing deps — without them we surface a clear hint.
    try:
        import base64 as _b64
        from solders.keypair import Keypair  # type: ignore
        from solders.transaction import VersionedTransaction  # type: ignore
        from solders.message import to_bytes_versioned  # type: ignore
        from solders.signature import Signature  # type: ignore
    except ImportError as exc:
        return SwapResult(quote=q, dry_run=False, confirmed=False,
                           tx_digests=[], crystal_anchor=crystal,
                           error=("signing_deps_missing — opt in with: "
                                  "/data/Projects/ComfyUI/.venv/bin/pip install "
                                  f"solders base58  (caught {exc!r})"))
    try:
        from solana_mcp import _load_env_dict, _resolve_keypair_path, _resolve_rpc_url  # type: ignore
        env = _load_env_dict()
        keypair_path = _resolve_keypair_path(env)
        if not keypair_path or not Path(keypair_path).exists():
            return SwapResult(quote=q, dry_run=False, confirmed=False,
                               tx_digests=[], crystal_anchor=crystal,
                               error=f"solana_keypair_missing:{keypair_path}")
        rpc_url = _resolve_rpc_url(env)
    except Exception as exc:
        return SwapResult(quote=q, dry_run=False, confirmed=False,
                           tx_digests=[], crystal_anchor=crystal,
                           error=f"solana_mcp_import:{exc!r}")

    # Pull the swap transaction from Jupiter
    payload = {
        "quoteResponse": q.raw_provider_quote,
        "userPublicKey": env.get("SOLANA_WALLET_PUBKEY", ""),
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
    }
    swap_resp = _http_post_json(f"{JUPITER_LITE_BASE}/swap", payload)
    if "_error" in swap_resp:
        return SwapResult(quote=q, dry_run=False, confirmed=False,
                           tx_digests=[], crystal_anchor=crystal,
                           error=f"jupiter_swap_endpoint:{swap_resp.get('_error')}")
    serialized_tx = swap_resp.get("swapTransaction", "")
    if not serialized_tx:
        return SwapResult(quote=q, dry_run=False, confirmed=False,
                           tx_digests=[], crystal_anchor=crystal,
                           error="no_swap_transaction_in_response")

    # Decode → sign → serialize → submit via RPC sendTransaction
    try:
        tx_bytes = _b64.b64decode(serialized_tx)
        unsigned = VersionedTransaction.from_bytes(tx_bytes)
        keypair = Keypair.from_json(Path(keypair_path).read_text())
        # Build a signed version: sign the message bytes
        msg_bytes = to_bytes_versioned(unsigned.message)
        sig = keypair.sign_message(msg_bytes)
        signed = VersionedTransaction.populate(unsigned.message, [sig])
        signed_b64 = _b64.b64encode(bytes(signed)).decode()
    except Exception as exc:
        return SwapResult(quote=q, dry_run=False, confirmed=False,
                           tx_digests=[], crystal_anchor=crystal,
                           error=f"sign_failed:{exc!r}")

    rpc_payload = {
        "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
        "params": [signed_b64, {"encoding": "base64",
                                  "skipPreflight": False,
                                  "preflightCommitment": "confirmed",
                                  "maxRetries": 3}],
    }
    rpc_resp = _http_post_json(rpc_url, rpc_payload)
    if "_error" in rpc_resp:
        return SwapResult(quote=q, dry_run=False, confirmed=False,
                           tx_digests=[], crystal_anchor=crystal,
                           error=f"rpc_send:{rpc_resp.get('_error')}")
    if "error" in rpc_resp:
        return SwapResult(quote=q, dry_run=False, confirmed=False,
                           tx_digests=[], crystal_anchor=crystal,
                           error=f"rpc_error:{json.dumps(rpc_resp.get('error'))[:300]}")
    sig_str = rpc_resp.get("result", "")
    return SwapResult(quote=q, dry_run=False, confirmed=True,
                       tx_digests=[sig_str],
                       amount_out_actual_atomic=q.amount_out_est_atomic,
                       crystal_anchor=crystal,
                       error="")


def _exec_sui_dex(q: SwapQuote, crystal: str) -> SwapResult:
    """Cetus or DeepBook swap. Uses sui_mcp's _run_sui CLI helper."""
    try:
        from sui_mcp import _resolve_network  # type: ignore
        net = _resolve_network()
        if net != "mainnet":
            return SwapResult(quote=q, dry_run=False, confirmed=False,
                               tx_digests=[], crystal_anchor=crystal,
                               error=f"sui_network={net}; mainnet required for real swap")
    except Exception as exc:
        return SwapResult(quote=q, dry_run=False, confirmed=False,
                           tx_digests=[], crystal_anchor=crystal,
                           error=f"sui_mcp_import:{exc!r}")
    return SwapResult(quote=q, dry_run=False, confirmed=False,
                       tx_digests=[], crystal_anchor=crystal,
                       error="signing_path_text_placeholder — call sui_mcp sui client call --package <cetus> --module router --function swap")


def _exec_cross_chain(q: SwapQuote, crystal: str) -> SwapResult:
    return SwapResult(quote=q, dry_run=False, confirmed=False,
                       tx_digests=[], crystal_anchor=crystal,
                       error="signing_path_text_placeholder — wire Mayan Swap SDK or Wormhole NTT route; needs both Solana + Sui keypairs co-signing")


# ── crystal anchor ─────────────────────────────────────────────────────────

def _anchor_swap(q: SwapQuote, is_live: bool) -> str:
    if _LOG is None:
        return ""
    scope = "swap_live" if is_live else "swap_dry_run"
    try:
        return _LOG.log(
            original_prompt=f"swap:{q.from_token}->{q.to_token}",
            enhanced_prompt=json.dumps({
                "from_token": q.from_token, "to_token": q.to_token,
                "amount_in": q.amount_in_human,
                "amount_out_est": q.amount_out_est_human,
                "route": q.route_taken, "steps": q.route_steps,
                "fee_bps": q.fee_bps_total,
                "slippage_bps": q.slippage_bps,
                "price_impact_pct": q.price_impact_pct,
            }),
            output_text=f"{q.amount_in_human} {q.from_token} → est {q.amount_out_est_human:.6f} {q.to_token} via {q.route_taken}",
            tier="swap",
            model=q.route_taken,
            scope=scope,
            source_action=f"swap_router.{'execute' if is_live else 'quote'}",
        ) or ""
    except Exception:
        return ""


# ── routes summary ─────────────────────────────────────────────────────────

ROUTES_TABLE = (
    ("USDC.sol", "SOL",       "jupiter_v6",              "same-chain Solana"),
    ("SOL",      "USDC.sol",  "jupiter_v6",              "same-chain Solana"),
    ("USDC.sui", "SUI",       "cetus_clmm_placeholder",  "same-chain Sui"),
    ("SUI",      "USDC.sui",  "cetus_clmm_placeholder",  "same-chain Sui"),
    ("SOL",      "SUI",       "wormhole_ntt_placeholder", "cross-chain"),
    ("SUI",      "SOL",       "wormhole_ntt_placeholder", "cross-chain"),
)


def routes() -> List[Dict]:
    return [{"from": a, "to": b, "route": r, "kind": k}
            for a, b, r, k in ROUTES_TABLE]


# ── CLI ────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="swap_router — USDC/SOL/SUI 6 routes")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_q = sub.add_parser("quote", help="get a swap quote")
    p_q.add_argument("from_token")
    p_q.add_argument("to_token")
    p_q.add_argument("amount", type=float)
    p_q.add_argument("--slippage-bps", type=int, default=50)

    p_e = sub.add_parser("execute", help="execute a swap (dry-run by default)")
    p_e.add_argument("from_token")
    p_e.add_argument("to_token")
    p_e.add_argument("amount", type=float)
    p_e.add_argument("--slippage-bps", type=int, default=50)
    p_e.add_argument("--confirm", action="store_true",
                     help="required for live execution alongside MSPC_SWAP_LIVE=1")

    sub.add_parser("routes", help="list all 6 supported routes")

    args = ap.parse_args(argv)

    if args.cmd == "routes":
        for r in routes():
            print(f"  {r['from']:9s} → {r['to']:9s} via {r['route']:30s} ({r['kind']})")
        return 0

    if args.cmd == "quote":
        try:
            q = quote(args.from_token, args.to_token, args.amount,
                       slippage_bps=args.slippage_bps)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr); return 2
        # Anchor the quote on its own (no execute)
        _anchor_swap(q, is_live=False)
        print(json.dumps(asdict(q), indent=2, default=str))
        return 0

    if args.cmd == "execute":
        try:
            q = quote(args.from_token, args.to_token, args.amount,
                       slippage_bps=args.slippage_bps)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr); return 2
        dry = not args.confirm
        if not dry and os.environ.get("MSPC_SWAP_LIVE", "0") != "1":
            print("REFUSING: live execute requires MSPC_SWAP_LIVE=1 in env "
                  "AND --confirm flag.", file=sys.stderr)
            dry = True
        result = execute(q, dry_run=dry)
        print(json.dumps(asdict(result), indent=2, default=str))
        return 0 if result.confirmed or dry else 3

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
