#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        pump_stream_ingest
# role:        SOURCE · SOLANA_LIVE_LOGS · PUMP_FUN_INGEST
# tier:        L0
# substrate:   ~/.cc/pump_stream/<YYYY-MM-DD>.jsonl  (one file per local day,
#              append-only — every pump.fun program invocation captured from
#              the Solana RPC log feed becomes one JSON line keyed by signature)
# storage:     ~/.cc/pump_stream/*.jsonl + crystal-anchored session bookends
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.pump_stream_ingest.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound (future):
#   - core/cc.sh::cmd_pump_stream_start / cmd_pump_stream_status (future)
#   - studio_runtime live-trade pass (when card pass.engine='pump_stream')
#   - watchdog cron: keep one ingest_loop running per box
# outbound:
#   - subprocess: `solana logs --url <RPC>` (default v1 — stdlib, zero dep)
#   - HTTP getTransaction fetch via urllib.request (opt-in; v1 SKIPS this by
#     default — feature extractor will hydrate on demand via solana_mcp)
#   - inference_logger.log (session bookends only; tier='pump_stream_session')
# substrate touch:
#   - reads:  PUMP_RPC_WSS / PUMP_RPC_HTTPS / SOLANA_NETWORK / PUMP_SOLANA_BIN
#             via os.environ (and falls back to default mainnet/devnet)
#   - writes: ~/.cc/pump_stream/<date>.jsonl (one line per event) +
#             two InferenceRecord rows per session (session_start/session_end)
# ----------------------------------------------------------------------------
# TOOLS / API
# ----------------------------------------------------------------------------
#   ingest_loop(duration_seconds=0, max_events=0, rpc_wss="", out_dir=None)
#       → int (events_written)
#   replay_jsonl(jsonl_path)  → Iterator[PumpEvent]
#   PumpEvent dataclass (12 canonical fields — see schema docstring)
# ============================================================================
"""pump_stream_ingest.py — Solana live-logs ingest for pump.fun.

Subscribes to the Solana RPC log feed filtered on the pump.fun program ID,
parses each emitted log block into a `PumpEvent`, and appends one JSON line
per event to `~/.cc/pump_stream/<YYYY-MM-DD>.jsonl`. The downstream feature
extractor (agent B) consumes these jsonl files for opcode-router training
data and live signal generation.

# v1 limitation (documented)
`websockets` is NOT installed; instead of opening a raw WebSocket to
`logsSubscribe` from stdlib (possible but verbose), v1 uses the
`solana logs --url <RPC>` CLI subprocess as the streaming transport. This:
  - is zero-dep (just subprocess + json),
  - filters to a single program ID via the positional ADDRESS arg (the CLI
    forwards that as the `mentions` filter to logsSubscribe under the hood),
  - emits human-readable blocks we parse line-by-line.

The trade-off: `solana logs` lines carry signature + slot + raw program logs,
but NOT the structured instruction args (sol_amount, token_amount, jito tip).
The feature extractor side hydrates those by calling solana_mcp.tx_status or
a direct getTransaction RPC on demand — done lazily so this hot path stays
cheap.

# Crystal anchoring
Per-event crystallization would be too noisy (a busy pump.fun slot emits
thousands of log blocks per second). Instead this module crystal-anchors only
two records per session:
  - tier='pump_stream_session', scope='session_start'  at ingest_loop entry
  - tier='pump_stream_session', scope='session_end'    at ingest_loop exit
    with output_text='{"events_captured": N, "duration_s": T, ...}'

# Stdlib only
subprocess + json + pathlib + dataclasses + os + sys + time + re + argparse.
NO websockets, NO solana-py, NO solders, NO requests.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pump.fun mainnet program — invoked on every pump.fun bonded-curve buy/sell
# and on every create_pool. Constant across all clusters where the program is
# deployed (currently mainnet only; devnet is dry-fire).
PUMP_FUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

# PumpSwap — the AMM router that handles post-graduation liquidity after a
# pump.fun coin migrates to a Raydium-style pool. Same shape, different
# program ID. Override via PUMP_SWAP_PROGRAM_ID if upstream renames.
PUMPSWAP_PROGRAM_ID_DEFAULT = "PSwApMUFqDsBvVBkU2DJYWuJokSjUMyJ4dxxnFnDxxh"

# Default RPC endpoints — public, rate-limited. Tom will override
# PUMP_RPC_WSS / PUMP_RPC_HTTPS to a Helius/Triton URL for production runs.
DEFAULT_MAINNET_RPC_HTTPS = "https://api.mainnet-beta.solana.com"
DEFAULT_DEVNET_RPC_HTTPS = "https://api.devnet.solana.com"

# Where to write events. One file per local date.
DEFAULT_OUT_DIR = Path.home() / ".cc" / "pump_stream"

# Bring in the project lib path for inference_logger (graceful if absent).
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_HERE))


# ---------------------------------------------------------------------------
# Canonical event schema
# ---------------------------------------------------------------------------


@dataclass
class PumpEvent:
    """One captured pump.fun (or pumpswap) program invocation.

    v1 capture is light: `solana logs` only carries signature + slot + raw
    log lines. Amount / fee fields are populated when the feature extractor
    side hydrates the transaction details via getTransaction. Fields stay on
    the schema (zero/empty defaults) so the JSONL schema is stable.
    """
    ts: float                       # wall-clock epoch seconds at capture
    signature: str                  # tx signature (base58)
    slot: int                       # slot number
    program: str                    # 'pump.fun' | 'pumpswap' | 'unknown'
    kind: str                       # 'buy' | 'sell' | 'create_pool' |
                                    # 'remove_liquidity' | 'unknown'
    payer: str                      # wallet pubkey (filled by hydrator; "" in v1)
    mint: str                       # token mint addr (filled by hydrator; "" in v1)
    sol_amount: float               # lamports / 1e9   (0.0 until hydrated)
    token_amount: float             # raw token amount (0.0 until hydrated)
    priority_fee_lamports: int      # compute-budget priority fee (0 until hydrated)
    jito_tip_lamports: int          # Jito bundle tip (0 if not a Jito tx)
    raw_logs: List[str] = field(default_factory=list)
    # Convenience metadata — survives JSONL round-trip.
    status: str = "ok"              # 'ok' | 'error_<code>' | 'unknown'
    err_code: str = ""              # e.g. '0x4' (parsed from "Status: Error ...")


# ---------------------------------------------------------------------------
# RPC resolution
# ---------------------------------------------------------------------------


def _resolve_network() -> str:
    return (os.environ.get("SOLANA_NETWORK", "") or "mainnet-beta").strip().lower()


def _resolve_rpc_https(network: str) -> str:
    explicit = (os.environ.get("PUMP_RPC_HTTPS", "") or "").strip()
    if explicit:
        return explicit
    if network in ("devnet",):
        return DEFAULT_DEVNET_RPC_HTTPS
    return DEFAULT_MAINNET_RPC_HTTPS


def _resolve_rpc_wss(network: str) -> str:
    explicit = (os.environ.get("PUMP_RPC_WSS", "") or "").strip()
    if explicit:
        return explicit
    # Public WSS — same hostname, different scheme. Solana CLI does the right
    # thing if we pass the HTTPS URL; it derives the websocket automatically.
    return _resolve_rpc_https(network)


def _resolve_pumpswap_program() -> str:
    return (
        (os.environ.get("PUMP_SWAP_PROGRAM_ID", "") or "").strip()
        or PUMPSWAP_PROGRAM_ID_DEFAULT
    )


def _resolve_solana_bin() -> str:
    """Resolve the `solana` binary.

    Order:
      1. $PUMP_SOLANA_BIN (explicit override)
      2. `which solana`
      3. ~/.local/share/solana/install/active_release/bin/solana (Agave default)
      4. "" if none found → ingest_loop returns 0 with a friendly stderr.
    """
    explicit = (os.environ.get("PUMP_SOLANA_BIN", "") or "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("solana")
    if found:
        return found
    agave = Path.home() / ".local/share/solana/install/active_release/bin/solana"
    if agave.exists():
        return str(agave)
    return ""


# ---------------------------------------------------------------------------
# Parser — `solana logs` block extractor
# ---------------------------------------------------------------------------

# `solana logs` emits human-readable blocks. Example:
#
#   Transaction executed in slot 365603903:
#     Signature: omfPo5ECjPwkXz...884
#     Status: Confirmed
#     Log Messages:
#       Program ComputeBudget111... invoke [1]
#       Program ComputeBudget111... success
#       Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [1]
#       Program log: Instruction: Buy
#       Program 6EF8rrecthR5... success
#
# We track block boundaries by the "Transaction executed in slot N:" line and
# flush on the next such header (or on stream end).

_RE_SLOT_HEADER = re.compile(r"^Transaction executed in slot\s+(\d+)\s*:\s*$")
_RE_SIGNATURE = re.compile(r"^\s*Signature:\s*(\S+)\s*$")
_RE_STATUS = re.compile(r"^\s*Status:\s*(.+?)\s*$")
_RE_ERROR_CODE = re.compile(r"custom program error:\s*(0x[0-9a-fA-F]+)")
_RE_LOG_LINE = re.compile(r"^\s+(Program\s+.*)\s*$")
_RE_INSTRUCTION = re.compile(r"^\s+Program log:\s+Instruction:\s+(\w+)\s*$")


def _classify_kind(raw_logs: List[str]) -> str:
    """Heuristic kind classifier — scan log lines for the well-known pump.fun
    instruction marker (`Program log: Instruction: <Kind>`).
    """
    for line in raw_logs:
        m = _RE_INSTRUCTION.match(line) if not line.lstrip().startswith("Program log:") else None
        # Fallback: case-insensitive match against the full line text.
        stripped = line.strip()
        for token, label in (
            ("Instruction: Buy", "buy"),
            ("Instruction: Sell", "sell"),
            ("Instruction: Create", "create_pool"),
            ("Instruction: InitializePool", "create_pool"),
            ("Instruction: CreateBondingCurve", "create_pool"),
            ("Instruction: RemoveLiquidity", "remove_liquidity"),
            ("Instruction: Withdraw", "remove_liquidity"),
        ):
            if token in stripped:
                return label
        if m:
            label = m.group(1).lower()
            if label in ("buy", "sell"):
                return label
            if label.startswith("create"):
                return "create_pool"
            if label.startswith("remove") or label.startswith("withdraw"):
                return "remove_liquidity"
    return "unknown"


def _classify_program(raw_logs: List[str], pumpswap_program: str) -> str:
    """pump.fun or pumpswap. Look at which program ID appears in `invoke [1]`."""
    for line in raw_logs:
        if PUMP_FUN_PROGRAM_ID in line:
            return "pump.fun"
        if pumpswap_program and pumpswap_program in line:
            return "pumpswap"
    return "unknown"


def _parse_status(status_line: str) -> tuple[str, str]:
    """Returns (status, err_code).

    'Confirmed' → ('ok', '')
    'Error processing Instruction 2: custom program error: 0x4' →
        ('error_0x4', '0x4')
    """
    if not status_line:
        return "unknown", ""
    if status_line.lower().startswith("confirmed") or status_line.lower().startswith("ok"):
        return "ok", ""
    m = _RE_ERROR_CODE.search(status_line)
    if m:
        code = m.group(1)
        return f"error_{code}", code
    return "error_unknown", ""


def _emit_event_from_block(
    slot: int,
    signature: str,
    status_line: str,
    raw_logs: List[str],
    pumpswap_program: str,
) -> Optional[PumpEvent]:
    """Build a PumpEvent from a parsed block.

    Returns None if the block doesn't actually mention our target program
    (defensive — `solana logs <ADDRESS>` should already filter, but we double
    check so a misconfigured stream doesn't pollute the JSONL).
    """
    if not signature:
        return None
    mentions_target = any(
        (PUMP_FUN_PROGRAM_ID in line) or (pumpswap_program and pumpswap_program in line)
        for line in raw_logs
    )
    if not mentions_target:
        return None
    status, err_code = _parse_status(status_line)
    return PumpEvent(
        ts=time.time(),
        signature=signature,
        slot=slot,
        program=_classify_program(raw_logs, pumpswap_program),
        kind=_classify_kind(raw_logs),
        payer="",
        mint="",
        sol_amount=0.0,
        token_amount=0.0,
        priority_fee_lamports=0,
        jito_tip_lamports=0,
        raw_logs=raw_logs[:128],   # cap — busy txs can emit hundreds of lines
        status=status,
        err_code=err_code,
    )


# ---------------------------------------------------------------------------
# JSONL writer (one file per local day, append-only)
# ---------------------------------------------------------------------------


def _jsonl_path_for_today(out_dir: Path) -> Path:
    today = time.strftime("%Y-%m-%d", time.localtime())
    return out_dir / f"{today}.jsonl"


def _append_event(out_dir: Path, evt: PumpEvent) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = _jsonl_path_for_today(out_dir)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(evt), separators=(",", ":")) + "\n")


# ---------------------------------------------------------------------------
# Crystal anchor (session bookends only — NOT per event)
# ---------------------------------------------------------------------------


def _crystal_anchor(scope: str, payload: dict) -> str:
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=f"pump_stream.{scope}",
            enhanced_prompt=json.dumps({k: payload[k] for k in payload if k != "events_captured"}, separators=(",", ":"))[:512],
            output_text=json.dumps(payload, separators=(",", ":"))[:1024],
            tier="pump_stream_session",
            model="solana_pump_stream",
            scope=scope,
            tokens_in=0,
            tokens_out=0,
            latency_ms=int(payload.get("duration_s", 0.0) * 1000),
            source_action=f"pump_stream.{scope}",
            done_flag=(scope == "session_end"),
            rc=0,
        ) or ""
    except Exception as e:
        sys.stderr.write(
            f"warn: pump_stream crystal anchor failed ({scope}): "
            f"{type(e).__name__}: {e}\n"
        )
        return ""


# ---------------------------------------------------------------------------
# Public API — ingest_loop
# ---------------------------------------------------------------------------


def ingest_loop(
    duration_seconds: int = 0,
    max_events: int = 0,
    rpc_wss: str = "",
    out_dir: Optional[Path] = None,
    program_id: str = PUMP_FUN_PROGRAM_ID,
) -> int:
    """Stream pump.fun program logs and write one JSONL line per event.

    duration_seconds=0 → run forever (until SIGINT / killed externally).
    max_events=0       → no cap.
    Returns the number of events successfully written.

    Crystal-anchors:
      - session_start on entry  (scope='session_start', tier='pump_stream_session')
      - session_end on exit     (scope='session_end',   tier='pump_stream_session')
        with output_text payload {events_captured, duration_s, rpc, program_id}.
    """
    out_dir = out_dir or DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    network = _resolve_network()
    rpc_url = (rpc_wss or "").strip() or _resolve_rpc_wss(network)
    if rpc_url.startswith("wss://") or rpc_url.startswith("ws://"):
        # `solana logs --url` accepts http(s) — convert if a websocket URL was
        # passed. The CLI will derive the WSS internally.
        rpc_url = "https://" + rpc_url.split("://", 1)[1]
    # Friendly rate-limit warning when the public mainnet RPC is in play.
    if "api.mainnet-beta.solana.com" in rpc_url:
        sys.stderr.write(
            "[pump_stream] WARN: streaming via public RPC "
            "(api.mainnet-beta.solana.com) — rate-limited; set PUMP_RPC_HTTPS "
            "or PUMP_RPC_WSS to a Helius/Triton URL for production runs.\n"
        )

    solana_bin = _resolve_solana_bin()
    if not solana_bin:
        sys.stderr.write(
            "[pump_stream] ERROR: `solana` binary not found. "
            "Set PUMP_SOLANA_BIN or install Agave CLI 4.x. "
            "Expected at ~/.local/share/solana/install/active_release/bin/solana.\n"
        )
        return 0

    pumpswap_program = _resolve_pumpswap_program()
    start_ts = time.time()

    session_start_payload = {
        "rpc": rpc_url,
        "network": network,
        "program_id": program_id,
        "pumpswap_program": pumpswap_program,
        "duration_seconds": duration_seconds,
        "max_events": max_events,
        "solana_bin": solana_bin,
        "out_dir": str(out_dir),
    }
    session_start_crystal = _crystal_anchor("session_start", session_start_payload)

    cmd = [
        solana_bin, "logs",
        "--url", rpc_url,
        "--commitment", "confirmed",
        program_id,
    ]

    events_written = 0
    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        sys.stderr.write(
            f"[pump_stream] ERROR: could not exec {solana_bin}\n"
        )
        _crystal_anchor("session_end", {
            **session_start_payload,
            "events_captured": 0,
            "duration_s": 0.0,
            "session_start_crystal": session_start_crystal,
            "exit_reason": "exec_failed",
        })
        return 0

    # Block-accumulator state.
    cur_slot = 0
    cur_sig = ""
    cur_status = ""
    cur_logs: List[str] = []
    in_logs_section = False

    def flush_block() -> int:
        nonlocal events_written
        if cur_sig:
            evt = _emit_event_from_block(
                cur_slot, cur_sig, cur_status, cur_logs, pumpswap_program,
            )
            if evt is not None:
                _append_event(out_dir, evt)
                events_written += 1
        return events_written

    exit_reason = "duration_elapsed"
    try:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            now = time.time()
            if duration_seconds and (now - start_ts) >= duration_seconds:
                exit_reason = "duration_elapsed"
                break
            if max_events and events_written >= max_events:
                exit_reason = "max_events_reached"
                break

            # New transaction block — flush prior one first.
            m = _RE_SLOT_HEADER.match(line)
            if m:
                if cur_sig:
                    flush_block()
                cur_slot = int(m.group(1))
                cur_sig = ""
                cur_status = ""
                cur_logs = []
                in_logs_section = False
                continue

            ms = _RE_SIGNATURE.match(line)
            if ms:
                cur_sig = ms.group(1)
                continue

            mst = _RE_STATUS.match(line)
            if mst:
                cur_status = mst.group(1)
                continue

            if line.strip().startswith("Log Messages"):
                in_logs_section = True
                continue

            if in_logs_section:
                ml = _RE_LOG_LINE.match(line)
                if ml:
                    cur_logs.append(ml.group(1))
                    continue
                # Lines like '    Program log: Instruction: Buy'
                stripped = line.rstrip("\n")
                if stripped.strip().startswith(("Program ", "Program log:")):
                    cur_logs.append(stripped.strip())
                    continue
    except KeyboardInterrupt:
        exit_reason = "keyboard_interrupt"
    except BrokenPipeError:
        exit_reason = "broken_pipe"
    except Exception as e:
        exit_reason = f"exception:{type(e).__name__}:{e}"
        sys.stderr.write(
            f"[pump_stream] unexpected error in ingest_loop: "
            f"{type(e).__name__}: {e}\n"
        )
    finally:
        # Flush a final pending block.
        if cur_sig:
            flush_block()
        # Tear down the subprocess.
        if proc is not None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
            except Exception:
                pass
        duration_s = time.time() - start_ts
        _crystal_anchor("session_end", {
            **session_start_payload,
            "events_captured": events_written,
            "duration_s": round(duration_s, 3),
            "session_start_crystal": session_start_crystal,
            "exit_reason": exit_reason,
        })

    return events_written


# ---------------------------------------------------------------------------
# Public API — replay_jsonl
# ---------------------------------------------------------------------------


def replay_jsonl(jsonl_path: Path) -> Iterator[PumpEvent]:
    """Yield PumpEvent rows from a captured JSONL.

    Missing fields fall back to dataclass defaults so older capture schemas
    can be replayed against newer code.
    """
    p = Path(jsonl_path)
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                yield PumpEvent(
                    ts=float(d.get("ts", 0.0)),
                    signature=str(d.get("signature", "")),
                    slot=int(d.get("slot", 0)),
                    program=str(d.get("program", "unknown")),
                    kind=str(d.get("kind", "unknown")),
                    payer=str(d.get("payer", "")),
                    mint=str(d.get("mint", "")),
                    sol_amount=float(d.get("sol_amount", 0.0)),
                    token_amount=float(d.get("token_amount", 0.0)),
                    priority_fee_lamports=int(d.get("priority_fee_lamports", 0)),
                    jito_tip_lamports=int(d.get("jito_tip_lamports", 0)),
                    raw_logs=list(d.get("raw_logs", []) or []),
                    status=str(d.get("status", "unknown")),
                    err_code=str(d.get("err_code", "")),
                )
            except Exception:
                # Skip malformed rows; the JSONL is append-only so partial
                # writes on crash are tolerated by skipping the offending line.
                continue


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="pump_stream_ingest — Solana RPC live-logs → JSONL",
    )
    sub = ap.add_subparsers(dest="cmd")

    p_ing = sub.add_parser("ingest", help="stream pump.fun logs to ~/.cc/pump_stream/")
    p_ing.add_argument("--duration", type=int, default=0,
                       help="seconds to run (0 = forever)")
    p_ing.add_argument("--max-events", type=int, default=0,
                       help="stop after N events (0 = no cap)")
    p_ing.add_argument("--rpc", default="",
                       help="RPC URL (overrides PUMP_RPC_HTTPS / PUMP_RPC_WSS)")
    p_ing.add_argument("--out-dir", default="",
                       help="output dir (default ~/.cc/pump_stream)")
    p_ing.add_argument("--program-id", default=PUMP_FUN_PROGRAM_ID,
                       help="program ID to subscribe to (default pump.fun)")

    p_rep = sub.add_parser("replay", help="dump a captured JSONL as pretty rows")
    p_rep.add_argument("path")
    p_rep.add_argument("--limit", type=int, default=20)

    p_inf = sub.add_parser("info", help="print resolved env + constants")

    args = ap.parse_args()

    if args.cmd == "ingest":
        out_dir = Path(args.out_dir) if args.out_dir else None
        n = ingest_loop(
            duration_seconds=args.duration,
            max_events=args.max_events,
            rpc_wss=args.rpc,
            out_dir=out_dir,
            program_id=args.program_id,
        )
        print(json.dumps({"events_written": n}, indent=2))

    elif args.cmd == "replay":
        printed = 0
        for evt in replay_jsonl(Path(args.path)):
            if printed >= args.limit:
                break
            print(json.dumps(asdict(evt), separators=(",", ":")))
            printed += 1
        print(json.dumps({"_replayed": printed}, indent=2))

    elif args.cmd == "info":
        network = _resolve_network()
        print(json.dumps({
            "pump_fun_program_id": PUMP_FUN_PROGRAM_ID,
            "pumpswap_program_id": _resolve_pumpswap_program(),
            "network": network,
            "rpc_https": _resolve_rpc_https(network),
            "rpc_wss": _resolve_rpc_wss(network),
            "solana_bin": _resolve_solana_bin() or "(not found)",
            "default_out_dir": str(DEFAULT_OUT_DIR),
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
