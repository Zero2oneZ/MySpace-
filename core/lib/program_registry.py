"""program_registry.py — curated catalog of OTHER web3 apps' program/package IDs.

These are PUBLIC on-chain addresses for popular Solana programs and Sui packages,
intentionally NOT ours. We monitor them as an oracle data source — what is
already happening on chain — so we can cross-reference DOM intent (Phantom wrapper)
with observed on-chain action and train classifiers / surface signals.

Storage: studio/assets/_program_registry/catalog.jsonl (append-only).
Verification: each entry has verified_at; entries with verified_at=null should be
re-confirmed with the chain RPC before driving real decisions (see `verify`).

Tom's own programs (TROLLN_PACKAGE_ID, SYNTH_PACKAGE_ID, etc.) live in .env and
are NOT seeded here — this file is exclusively for non-MySpace++ programs.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

REPO = Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO / "studio" / "assets" / "_program_registry"
CATALOG = CATALOG_DIR / "catalog.jsonl"

CHAINS = ("solana", "sui")

CATEGORIES = (
    "DEX",
    "DEX_AGGREGATOR",
    "DEX_CLMM",
    "DEX_ORDERBOOK",
    "PERPS",
    "LENDING",
    "LIQUID_STAKING",
    "NFT_MARKETPLACE",
    "NFT_AGGREGATOR",
    "MEMECOIN_LAUNCHPAD",
    "CASINO",
    "MEV",
    "TOKEN_PROGRAM",
    "SYSTEM",
    "BRIDGE",
    "ORACLE",
    "UNKNOWN",
)


@dataclass
class ProgramEntry:
    chain: str
    program_id: str
    name: str
    category: str = "UNKNOWN"
    source_url: str = ""
    verified_at: Optional[float] = None
    watch: bool = True
    notes: str = ""
    added_at: float = field(default_factory=time.time)

    def short(self) -> str:
        pid = self.program_id
        return pid[:6] + ".." + pid[-4:] if len(pid) > 14 else pid

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


# ── seed (well-known mainnet program IDs as of 2026 — verify before relying) ──

_SEED: List[ProgramEntry] = [
    # Solana — DEX
    ProgramEntry("solana", "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
                 "Jupiter Aggregator v6", "DEX_AGGREGATOR",
                 "https://station.jup.ag/docs/", notes="Confirmed public; major routing"),
    ProgramEntry("solana", "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
                 "Raydium AMM v4", "DEX",
                 "https://docs.raydium.io/", notes="Classic AMM"),
    ProgramEntry("solana", "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
                 "Raydium CLMM", "DEX_CLMM",
                 "https://docs.raydium.io/"),
    ProgramEntry("solana", "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
                 "Raydium CPMM", "DEX",
                 "https://docs.raydium.io/",
                 notes="Constant-product, gas-optimized standard swap layer"),
    ProgramEntry("solana", "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
                 "Orca Whirlpools", "DEX_CLMM",
                 "https://docs.orca.so/"),
    ProgramEntry("solana", "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
                 "Meteora DLMM", "DEX",
                 "https://docs.meteora.ag/"),
    # Solana — Pump.fun
    ProgramEntry("solana", "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
                 "Pump.fun bonding curve", "MEMECOIN_LAUNCHPAD",
                 "https://pump.fun/", notes="Already ingested by pump_stream_ingest"),
    ProgramEntry("solana", "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
                 "PumpSwap AMM", "DEX",
                 "https://pump.fun/"),
    # Solana — Orderbook / Perps
    ProgramEntry("solana", "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY",
                 "Phoenix orderbook", "DEX_ORDERBOOK",
                 "https://www.ellipsislabs.xyz/"),
    ProgramEntry("solana", "dRiftyHA39MWEi3m9aunc5MzRF1JYuBsbn6VPcn33UH",
                 "Drift v2 perps", "PERPS",
                 "https://docs.drift.trade/"),
    ProgramEntry("solana", "4MangoMjqJ2firMokCjjGgoK8d4MXcrgL7XJaL3w6fVg",
                 "Mango v4", "PERPS",
                 "https://docs.mango.markets/"),
    # Solana — Lending
    ProgramEntry("solana", "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD",
                 "Kamino Lend", "LENDING",
                 "https://docs.kamino.finance/"),
    ProgramEntry("solana", "So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo",
                 "Solend", "LENDING",
                 "https://docs.solend.fi/"),
    # Solana — Staking
    ProgramEntry("solana", "MarBmsSgKXdrN1egZf5sqe1TMThczhMLJhJP7ipBxzj",
                 "Marinade liquid staking", "LIQUID_STAKING",
                 "https://docs.marinade.finance/"),
    # Solana — NFT
    ProgramEntry("solana", "M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K",
                 "Magic Eden v2", "NFT_MARKETPLACE",
                 "https://docs.magiceden.io/"),
    ProgramEntry("solana", "TSWAPaqyCSx2KABk68Shruf4rp7CxcNi8hAsbdwmHbN",
                 "Tensor TSwap", "NFT_AGGREGATOR",
                 "https://docs.tensor.trade/"),
    # Solana — Casino / Gambling (Tom flagged this category)
    ProgramEntry("solana", "Gamba22222222222222222222222222222222222222",
                 "Gamba Core (provisional)", "CASINO",
                 "https://gamba.so/", verified_at=None,
                 notes="User-provided 2026-05-28; verify on-chain before relying"),
    # Solana — System
    ProgramEntry("solana", "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                 "SPL Token Program", "TOKEN_PROGRAM",
                 "https://spl.solana.com/token", watch=False,
                 notes="System program — too high volume, watch=False by default"),
    ProgramEntry("solana", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
                 "Token-2022 Program", "TOKEN_PROGRAM",
                 "https://spl.solana.com/token-2022", watch=False),

    # Sui packages (confidence varies — leave verified_at null for confirmation)
    ProgramEntry("sui", "0x000000000000000000000000000000000000000000000000000000000000dee9",
                 "DeepBook (system)", "DEX_ORDERBOOK",
                 "https://docs.sui.io/standards/deepbook",
                 notes="System singleton package"),
    ProgramEntry("sui", "0x1eabed72c53feb3805120a081dc15963c204dc8d091542592abaf7a35689b2fb",
                 "Cetus CLMM (provisional)", "DEX_CLMM",
                 "https://docs.cetus.zone/", verified_at=None,
                 notes="Package ID drifts on upgrade; reconfirm via cetus API"),
]


# ── persistence ──

def _ensure_dir() -> None:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)


def load() -> List[ProgramEntry]:
    _ensure_dir()
    if not CATALOG.exists():
        return []
    out: List[ProgramEntry] = []
    for line in CATALOG.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            out.append(ProgramEntry(**d))
        except Exception as exc:
            print(f"[registry] skip malformed line: {exc}", file=sys.stderr)
    return out


def save(entries: Iterable[ProgramEntry]) -> int:
    _ensure_dir()
    seen: Dict[str, ProgramEntry] = {}
    for e in entries:
        key = f"{e.chain}:{e.program_id}"
        seen[key] = e  # last write wins
    lines = [seen[k].to_jsonl() for k in sorted(seen)]
    CATALOG.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def add(entry: ProgramEntry) -> int:
    entries = load()
    by_key = {f"{e.chain}:{e.program_id}": e for e in entries}
    by_key[f"{entry.chain}:{entry.program_id}"] = entry
    return save(by_key.values())


def find(chain: str = "", program_id: str = "", category: str = "",
         watch_only: bool = False) -> List[ProgramEntry]:
    out = load()
    if chain:
        out = [e for e in out if e.chain == chain]
    if program_id:
        out = [e for e in out if e.program_id == program_id]
    if category:
        out = [e for e in out if e.category == category]
    if watch_only:
        out = [e for e in out if e.watch]
    return out


def watchset(chain: str = "") -> List[ProgramEntry]:
    return find(chain=chain, watch_only=True)


def seed(force: bool = False) -> int:
    existing = load()
    if existing and not force:
        return len(existing)
    return save(_SEED)


# ── verification (sanity-check format only; live RPC check is optional) ──

def _is_solana_addr(s: str) -> bool:
    if not 32 <= len(s) <= 44:
        return False
    alphabet = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
    return all(c in alphabet for c in s)


def _is_sui_id(s: str) -> bool:
    if not s.startswith("0x"):
        return False
    body = s[2:]
    if not (1 <= len(body) <= 64):
        return False
    return all(c in "0123456789abcdefABCDEF" for c in body)


def verify_format(entry: ProgramEntry) -> tuple[bool, str]:
    if entry.chain == "solana":
        return (True, "ok") if _is_solana_addr(entry.program_id) \
            else (False, "bad-base58-length")
    if entry.chain == "sui":
        return (True, "ok") if _is_sui_id(entry.program_id) \
            else (False, "bad-hex-id")
    return False, f"unknown-chain:{entry.chain}"


# ── live verification (Solana JSON-RPC getAccountInfo over stdlib urllib) ──

SOLANA_RPC_HTTP = "https://api.mainnet-beta.solana.com"


def verify_live_solana(program_id: str,
                        rpc_url: str = SOLANA_RPC_HTTP,
                        timeout: float = 10.0) -> tuple[bool, str]:
    """Return (executable_true, owner_program_id_or_error).

    Uses stdlib urllib only — no @solana/web3.js needed. We POST a
    getAccountInfo JSON-RPC call and check executable==true; the BPF loader
    that owns the account distinguishes deployed programs from regular
    accounts.
    """
    import json as _json
    import urllib.request
    import urllib.error
    req_body = _json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
        "params": [program_id, {"encoding": "base64"}],
    }).encode()
    req = urllib.request.Request(rpc_url, data=req_body,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = _json.loads(r.read().decode())
    except urllib.error.URLError as exc:
        return False, f"rpc-error:{exc}"
    except Exception as exc:
        return False, f"parse-error:{exc!r}"
    value = (resp.get("result") or {}).get("value")
    if value is None:
        return False, "account-not-found"
    if not value.get("executable"):
        return False, f"not-executable owner={value.get('owner', '?')}"
    return True, f"executable owner={value.get('owner', '?')}"


def verify_live_all(chain: str = "solana") -> Dict[str, Dict]:
    """Live-verify every catalog entry on the given chain. Updates
    verified_at in place on success. Returns a per-id status dict.
    """
    entries = load()
    results: Dict[str, Dict] = {}
    for e in entries:
        if e.chain != chain:
            continue
        if chain == "solana":
            ok, info = verify_live_solana(e.program_id)
        else:
            ok, info = (False, f"live-verify-not-implemented:{chain}")
        if ok:
            e.verified_at = time.time()
        results[e.program_id] = {
            "name": e.name, "ok": ok, "info": info,
            "verified_at": e.verified_at,
        }
    save(entries)
    return results


# ── CLI ──

def _print_row(e: ProgramEntry) -> None:
    flag = "👁 " if e.watch else "   "
    ver = "✓" if e.verified_at else "?"
    print(f"{flag}[{ver}] {e.chain:6s} {e.short():16s} {e.category:20s} {e.name}")


def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("program_registry — public web3 program catalog")
        print("Commands:")
        print("  seed [--force]                     # write seed catalog")
        print("  list [--chain solana|sui] [--cat C] [--watch]")
        print("  watchset [--chain X]               # entries with watch=true")
        print("  add <chain> <id> <name> [cat=UNKNOWN] [source=]")
        print("  set-watch <chain> <id> <on|off>")
        print("  verify [--chain X]                 # format check; counts ok/bad")
        print("  categories                          # list category vocab")
        print(f"  path                                # {CATALOG}")
        return 0

    cmd = argv[0]
    args = argv[1:]

    if cmd == "seed":
        force = "--force" in args
        n = seed(force=force)
        print(f"[registry] catalog has {n} entries (force={force})")
        return 0

    if cmd == "list":
        chain = ""
        cat = ""
        watch_only = False
        i = 0
        while i < len(args):
            a = args[i]
            if a == "--chain" and i + 1 < len(args):
                chain = args[i + 1]; i += 2; continue
            if a == "--cat" and i + 1 < len(args):
                cat = args[i + 1]; i += 2; continue
            if a == "--watch":
                watch_only = True; i += 1; continue
            i += 1
        entries = find(chain=chain, category=cat, watch_only=watch_only)
        for e in entries:
            _print_row(e)
        print(f"[registry] {len(entries)} entries")
        return 0

    if cmd == "watchset":
        chain = args[1] if len(args) >= 2 and args[0] == "--chain" else ""
        for e in watchset(chain=chain):
            _print_row(e)
        return 0

    if cmd == "add":
        if len(args) < 3:
            print("usage: add <chain> <id> <name> [category] [source_url]", file=sys.stderr)
            return 2
        chain, pid, name = args[0], args[1], args[2]
        cat = args[3] if len(args) > 3 else "UNKNOWN"
        url = args[4] if len(args) > 4 else ""
        entry = ProgramEntry(chain=chain, program_id=pid, name=name,
                              category=cat, source_url=url)
        ok, reason = verify_format(entry)
        if not ok:
            print(f"[registry] format check failed: {reason}", file=sys.stderr)
            return 3
        n = add(entry)
        print(f"[registry] added {entry.short()} ({name}); catalog={n}")
        return 0

    if cmd == "set-watch":
        if len(args) != 3:
            print("usage: set-watch <chain> <id> <on|off>", file=sys.stderr)
            return 2
        chain, pid, state = args[0], args[1], args[2].lower()
        entries = load()
        hit = False
        for e in entries:
            if e.chain == chain and e.program_id == pid:
                e.watch = state in ("on", "true", "1", "yes")
                hit = True
                break
        if not hit:
            print(f"[registry] not found: {chain}:{pid}", file=sys.stderr)
            return 4
        save(entries)
        print(f"[registry] {chain}:{pid[:8]}.. watch={state}")
        return 0

    if cmd == "verify":
        chain = args[1] if len(args) >= 2 and args[0] == "--chain" else ""
        entries = find(chain=chain) if chain else load()
        ok = bad = 0
        for e in entries:
            good, reason = verify_format(e)
            if good:
                ok += 1
            else:
                bad += 1
                print(f"  ✗ {e.chain} {e.program_id[:24]}.. — {reason}")
        print(f"[registry] format ok={ok} bad={bad}")
        return 0 if bad == 0 else 5

    if cmd == "verify-live":
        chain = args[1] if len(args) >= 2 and args[0] == "--chain" else "solana"
        if chain != "solana":
            print(f"[registry] live verify only implemented for solana (got {chain})",
                  file=sys.stderr)
            return 2
        print(f"[registry] live-verifying {chain} entries via {SOLANA_RPC_HTTP} ...")
        results = verify_live_all(chain=chain)
        ok = sum(1 for r in results.values() if r["ok"])
        bad = len(results) - ok
        for pid, r in results.items():
            tick = "✓" if r["ok"] else "✗"
            print(f"  {tick} {pid[:8]}.. {r['name']:30s} {r['info']}")
        print(f"[registry] live ok={ok} bad={bad}")
        return 0 if bad == 0 else 6

    if cmd == "categories":
        for c in CATEGORIES:
            print(c)
        return 0

    if cmd == "path":
        print(CATALOG)
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
