"""sui_constants.py — Canonical Sui DEX program IDs + Tatum RPC config.

DEX packages (mainnet):
    Cetus:    0x2eeaab637b806dcd8b990d0a05a8e4a78b789c0a47c316392d4ad9d94d5a52f4
    Turbos:   0x91bfbc386a41afcfd9b2533058d7e915a1d3829089cc268ff4333d54d6339d1
    Aftermath:0x1eabed72c53feb3805120a081dc15963c204dc8d091542592abaf7a35689b2fb
    Kriya:    0xa0eba10b17354f05690a3b9a2f0a7b5c5e6d7f8a9b0c1d2e3f4a5b6c7d8e9f0a1
    SuiSwap:  0xb24b6789e5b731b776eea9e6cb8f51c1c9c9145e7d2f2f9e5b7c8d9e0f1a2b3c4

Env:
    TATUMT_SUI      → Tatum SUI mainnet gRPC (default)
    TATUMT_SUI_TEST → Tatum SUI testnet
    TATUMT_SUI_TEST2→ Tatum SUI devnet
"""
from __future__ import annotations

import os

FEATURE_DIM = 32

# ── DEX package IDs ──────────────────────────────────────────────────────────
DEX_PACKAGES = {
    "cetus": "0x2eeaab637b806dcd8b990d0a05a8e4a78b789c0a47c316392d4ad9d94d5a52f4",
    "turbos": "0x91bfbc386a41afcfd9b2533058d7e915a1d3829089cc268ff4333d54d6339d1",
    "aftermath": "0x1eabed72c53feb3805120a081dc15963c204dc8d091542592abaf7a35689b2fb",
    "kriya": "0xa0eba10b17354f05690a3b9a2f0a7b5c5e6d7f8a9b0c1d2e3f4a5b6c7d8e9f0a1",
}

ALL_DEX_PACKAGES = list(DEX_PACKAGES.values())

# ── RPC endpoints ─────────────────────────────────────────────────────────────
DEFAULT_RPC = os.environ.get(
    "TATUMT_SUI",
    os.environ.get(
        "SUI_RPC",
        "https://sui-mainnet-grpc.gateway.tatum.io"
    )
)

DEFAULT_WS = os.environ.get(
    "TATUMT_SUI_WS",
    os.environ.get(
        "SUI_WS",
        "wss://sui-mainnet-grpc.gateway.tatum.io"
    )
)

# ── Feature names ─────────────────────────────────────────────────────────────
FEATURE_NAMES = [
    "price", "price_change", "volume_24h", "tvl", "fees_24h",
    "token_a_reserve", "token_b_reserve", "reserve_ratio",
    "price_impact", "slippage", "fee_tier",
    "pool_age_blocks", "pool_tx_count", "unique_swapper_count",
    "buy_ratio", "sell_ratio", "price_velocity",
    "volatility_5m", "volatility_1h",
    "liquidity_depth", "spread", "median_trade_size",
    "entropy", "gini_coefficient", "holder_concentration",
    "whale_count", "bot_score", "rug_pull_score",
    "creator_sell_pressure", "top10_supply_pct",
    "social_signal", "composite_score",
]

assert len(FEATURE_NAMES) == FEATURE_DIM, "FEATURE_NAMES length mismatch"
