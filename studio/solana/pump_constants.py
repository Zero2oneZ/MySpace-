"""pump_constants.py — Verified Pump.fun program IDs + Solana defaults.

All addresses are base58-encoded Solana public keys.
These are the canonical addresses as of 2026-05-28.
"""
from __future__ import annotations

# ── Solana defaults ──────────────────────────────────────────────────────────
SOLANA_DEFAULT_RPC = "https://api.mainnet-beta.solana.com"
SOLANA_DEVNET_RPC = "https://api.devnet.solana.com"
SOLANA_WS_MAINNET = "wss://api.mainnet-beta.solana.com"
SOLANA_WS_DEVNET = "wss://api.devnet.solana.com"

# ── Pump.fun canonical program IDs ───────────────────────────────────────────
PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_GLOBAL_ACCOUNT = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"
PUMP_FEE_RECIPIENT = "CebN5WGQ4dEizB5mNosWNZVtHc6daP9ExV7QjE61zytW"
PUMP_EVENT_AUTHORITY = "Ce6TQqeHC9p8KetsX6Ks..."

# Pump.fun instruction discriminators (first 8 bytes of sighash)
PUMP_CREATE = "24b69665dd1c1c83"  # create instruction
PUMP_BUY = "66063d1201daebea"     # buy instruction
PUMP_SELL = "33e685a401b0edab"    # sell instruction

# ── Raydium AMM (tokens graduate here) ───────────────────────────────────────
RAYDIUM_AMM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
RAYDIUM_OPENBOOK = "srmqPvymJeFKQ4zGQed1GFppYrR8aC2bR8F9J1L4N"

# ── System programs ────────────────────────────────────────────────────────
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
SYSTEM_PROGRAM = "11111111111111111111111111111111"

# ── Known Pump.fun bonding curve / pool accounts ─────────────────────────────
# These are discovered at runtime via getProgramAccounts
# but we seed a few known high-volume ones for faster bootstrap.
KNOWN_POOLS = [
    # Format: "base58_pubkey"
]

# ── Feature vector schema (what the GPU model sees) ─────────────────────────
FEATURE_DIM = 32
FEATURE_NAMES = [
    "price_sol",           # 0  — current price in SOL
    "market_cap_sol",      # 1  — market cap estimate
    "virtual_sol_reserves",# 2  — bonding curve virtual SOL
    "virtual_token_reserves",# 3 — bonding curve virtual tokens
    "real_sol_reserves",   # 4  — real SOL in curve
    "real_token_reserves", # 5  — real tokens in curve
    "total_supply",        # 6  — mint total supply
    "holder_count",        # 7  — unique token accounts
    "tx_count_1m",         # 8  — transactions in last 60s
    "buy_count_1m",        # 9  — buy tx count 60s
    "sell_count_1m",       # 10 — sell tx count 60s
    "volume_sol_1m",       # 11 — SOL volume 60s
    "volume_sol_5m",       # 12 — SOL volume 5min
    "volume_sol_15m",      # 13 — SOL volume 15min
    "buy_sell_ratio",      # 14 — buys / (buys + sells)
    "price_velocity",      # 15 — d(price)/dt
    "price_acceleration",  # 16 — d²(price)/dt²
    "entropy_tx",          # 17 — Shannon entropy of tx sizes
    "entropy_holders",     # 18 — Gini / concentration of holders
    "first_buy_delay_ms",  # 19 — ms from create to first buy
    "bot_score",           # 20 — heuristic bot detection score
    "creator_sol_balance", # 21 — creator wallet SOL balance
    "creator_tx_count",    # 22 — creator historical tx count
    "graduated",           # 23 — 1.0 if migrated to Raydium
    "twitter_mentions",    # 24 — social signal (placeholder)
    "dev_burnt_lp",        # 25 — did dev burn LP tokens
    "top10_pct",           # 26 — % supply in top 10 wallets
    "snipe_count",         # 27 — tx within first 3 blocks
    "rug_pull_score",      # 28 — heuristic rug score
    "time_since_create_s", # 29 — seconds since token creation
    "is_mutable",          # 30 — mint authority still exists
    "slot",                # 31 — current Solana slot
]
