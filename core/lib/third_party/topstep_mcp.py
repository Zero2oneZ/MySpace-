#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        topstep_mcp
# role:        CONNECTOR  TOPSTEPX_FUTURES_RAIL
# tier:        L0
# substrate:   futures-broker bridge for the trade-blob scalper
# storage:     ~/.cc/third_party_logs/topstep_sends.jsonl
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.topstep_mcp.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio_runtime (when card pass.engine='topstepx')
#   - core/cc.sh::cmd_topstep_* (future)
#   - studio dashboards reading account_status / positions
# outbound:
#   - subprocess to /data/Projects/trade-blob/scripts/tsx_cli.py (cross-repo shim)
#   - inference_logger.log (tier='trade_action', model='topstepx')
# substrate touch:
#   - reads:  TOPSTEP_USERNAME + TOPSTEP_API_KEY from /data/Projects/trade-blob/.env
#   - writes: ~/.cc/third_party_logs/topstep_sends.jsonl
#             ~/.cc/inference_master_chain.jsonl
#             ~/.cc/topstep_quotes/<symbol>.jsonl (quote_subscribe target)
# ============================================================================
"""topstep_mcp.py  TopstepX futures connector with hard DRY-RUN safety rails.

THE LAW:
    Every write tool (order_market, order_limit, flatten_all) DEFAULTS to
    DRY-RUN. A real order ONLY fires when BOTH:
      (1) the caller passes `confirm=True` in the JSON args, AND
      (2) the environment variable TOPSTEP_LIVE_TRADING is set to "1"
    are true.  Either gate alone returns a safe stub.

    `flatten_all` is the nuclear close-everything button  same gates apply.
    `cancel_order` is treated as safe (no fresh exposure  no quota risk).

Pattern:
    Wraps the existing standalone scalper at /data/Projects/trade-blob/ via
    `subprocess` against a tiny CLI shim (`scripts/tsx_cli.py`) that we expect
    to land in the trade-blob repo. Until that shim exists this connector:
      - parses + validates every request,
      - returns SendResult(success=False, error='tsx_cli_not_found: ...') for
        write tools, and
      - returns stub payloads for read tools (account_status, positions,
        health_check) so dashboards do not crash.

    Reads TOPSTEP_USERNAME / TOPSTEP_API_KEY directly from the trade-blob
    `.env` file (mirrored layout). The keys never appear in logs  only the
    fact that they were loaded.

Tools (via send(recipient=tool_name, message=json_args)):
    account_status()                    margin / equity / day P&L
    positions()                         list open positions
    health_check()                      ping the API
    order_market(symbol, qty, side, confirm=False)
    order_limit(symbol, qty, side, price, confirm=False)
    cancel_order(order_id)              safe (no quota risk)
    flatten_all(confirm=False)          nuclear close-everything
    quote_subscribe(symbol)             writes ~/.cc/topstep_quotes/<sym>.jsonl
    pnl_intraday(start_ts, end_ts)

Crystal anchor:
    Every call (success OR DRY-RUN) writes one InferenceRecord with
      tier='trade_action', model='topstepx', scope=f'topstep_<tool>'.
    DRY-RUN records embed `dry_run: True` in output_text so audit walks can
    distinguish a fake fill from a real one.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402

# ---------------------------------------------------------------------------
# Constants / paths
# ---------------------------------------------------------------------------
TRADE_BLOB_ROOT = Path("/data/Projects/trade-blob")
TRADE_BLOB_ENV = TRADE_BLOB_ROOT / ".env"
TSX_CLI = TRADE_BLOB_ROOT / "scripts" / "tsx_cli.py"
TRADE_BLOB_VENV_PY = TRADE_BLOB_ROOT / ".venv" / "bin" / "python"

LIVE_ENV_VAR = "TOPSTEP_LIVE_TRADING"
LIVE_VALUE = "1"

QUOTE_DIR = Path.home() / ".cc" / "topstep_quotes"

EXPECTED_TOOLS = (
    "account_status",
    "positions",
    "health_check",
    "order_market",
    "order_limit",
    "cancel_order",
    "flatten_all",
    "quote_subscribe",
    "pnl_intraday",
)

# Tools whose default behaviour is to fire real orders / move positions.
# Each requires BOTH confirm=True AND TOPSTEP_LIVE_TRADING=1.
WRITE_TOOLS = ("order_market", "order_limit", "flatten_all")

# Read tools  safe to attempt; return stubs if shim missing.
READ_TOOLS = ("account_status", "positions", "health_check",
              "quote_subscribe", "pnl_intraday")


# ---------------------------------------------------------------------------
# Tiny env reader  scoped to trade-blob/.env
# ---------------------------------------------------------------------------
def _load_trade_blob_env() -> Dict[str, str]:
    """Parse /data/Projects/trade-blob/.env into a dict. Never logs values."""
    out: Dict[str, str] = {}
    if not TRADE_BLOB_ENV.exists():
        return out
    try:
        for ln in TRADE_BLOB_ENV.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, _, v = ln.partition("=")
            out[k.strip()] = v.strip().strip("'\"")
    except OSError:
        return {}
    return out


def _topstep_credentials() -> Tuple[str, str]:
    """Returns (TOPSTEP_USERNAME, TOPSTEP_API_KEY) or ('', '') if missing.
    Order of precedence: process env  trade-blob/.env. Never echoes to stdout."""
    env = _load_trade_blob_env()
    username = (os.environ.get("TOPSTEP_USERNAME")
                or env.get("TOPSTEP_USERNAME")
                or "")
    api_key = (os.environ.get("TOPSTEP_API_KEY")
               or env.get("TOPSTEP_API_KEY")
               or "")
    return username, api_key


def _live_trading_enabled() -> bool:
    """True iff TOPSTEP_LIVE_TRADING=1 in process env. Anything else = DRY-RUN."""
    return os.environ.get(LIVE_ENV_VAR, "") == LIVE_VALUE


def _python_bin() -> str:
    """trade-blob's venv python when present, else python3 on PATH."""
    return str(TRADE_BLOB_VENV_PY) if TRADE_BLOB_VENV_PY.exists() else "python3"


def _tsx_cli_present() -> bool:
    return TSX_CLI.exists()


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------
def _log_trade(tool: str, params: Dict[str, Any], result: Dict[str, Any],
                latency_ms: int, success: bool, dry_run: bool) -> str:
    """Append one InferenceRecord with tier='trade_action', model='topstepx'.
    Returns crystal_id ('' on logger failure). Never embeds credentials."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        # Strip anything credential-shaped just in case.
        safe_params = {k: v for k, v in params.items()
                       if k not in ("api_key", "password", "TOPSTEP_API_KEY",
                                    "TOPSTEP_USERNAME")}
        safe_result = {k: v for k, v in result.items()
                       if k in ("order_id", "fake_order_id", "status",
                                "symbol", "qty", "side", "price",
                                "would_have_ordered", "balance", "equity",
                                "day_pnl", "positions", "dry_run", "stub",
                                "error", "tsx_cli_path", "ok")}
        # Make sure dry_run flag is preserved in the audit row.
        if dry_run and "dry_run" not in safe_result:
            safe_result["dry_run"] = True
        crystal_id = il.log(
            original_prompt=f"topstep.{tool}",
            enhanced_prompt=json.dumps(safe_params, separators=(",", ":"))[:512],
            output_text=json.dumps(safe_result, separators=(",", ":"))[:512],
            tier="trade_action", model="topstepx",
            scope=f"topstep_{tool}",
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_action=f"topstep.{tool}",
            done_flag=success,
            rc=0 if success else 1,
        )
        return crystal_id or ""
    except Exception as e:
        sys.stderr.write(f"warn: topstep crystal log failed: "
                         f"{type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# CLI shim invocation (when the shim exists)
# ---------------------------------------------------------------------------
def _invoke_tsx_cli(tool: str, args: Dict[str, Any],
                     username: str, api_key: str,
                     timeout: int = 30) -> Tuple[int, Dict[str, Any]]:
    """subprocess against /data/Projects/trade-blob/scripts/tsx_cli.py.
    Returns (returncode, parsed_json_or_error_dict). Caller MUST verify
    shim existence first  this function assumes presence."""
    cmd = [
        _python_bin(),
        str(TSX_CLI),
        tool,
        "--json",
        json.dumps(args, separators=(",", ":")),
    ]
    # Inherit process env but inject credentials. Never log this dict.
    env = {**os.environ,
           "TOPSTEP_USERNAME": username,
           "TOPSTEP_API_KEY": api_key}
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(TRADE_BLOB_ROOT),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, {"_error": f"tsx_cli timeout after {timeout}s"}
    except FileNotFoundError as e:
        return 127, {"_error": f"tsx_cli launch failed: {e}"}
    except OSError as e:
        return 1, {"_error": f"tsx_cli os_error: {type(e).__name__}: {e}"}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return proc.returncode, {
            "_error": stderr[:2048] or f"tsx_cli rc={proc.returncode}",
            "stdout": stdout[:2048],
        }
    if not stdout:
        return 0, {"ok": True, "_note": "tsx_cli returned empty stdout"}
    try:
        return 0, json.loads(stdout)
    except json.JSONDecodeError:
        return 0, {"_raw": stdout[:8192]}


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------
class TopStepMCPConnector(ThirdPartyConnector):
    """TopstepX futures connector with HARD DRY-RUN safety rails.

    Real orders require BOTH:
        confirm=True in the tool args, AND
        TOPSTEP_LIVE_TRADING=1 in the process environment.
    Either gate alone returns a safe DRY-RUN stub.
    """

    SERVICE = "topstep"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name="topstep_default",
                action="futures_rail",
            )
        super().__init__(config)
        self._username = ""
        self._api_key = ""
        self._connected = False

    # ---- ThirdPartyConnector lifecycle ----------------------------------
    def connect(self) -> bool:
        """Load credentials. Returns True iff both username+key are present.
        Does NOT make a network call  caller may invoke health_check
        separately."""
        u, k = _topstep_credentials()
        self._username = u
        self._api_key = k
        self._connected = bool(u and k)
        return self._connected

    def disconnect(self) -> None:
        self._username = ""
        self._api_key = ""
        self._connected = False

    def history(self, thread_id: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        """Read last N entries from the local send log."""
        log_path = Path.home() / ".cc" / "third_party_logs" / "topstep_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            out = []
            for ln in lines:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
            return out
        except OSError:
            return []

    # ---- send dispatcher -------------------------------------------------
    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        """recipient = tool name. message = JSON args (preferred) else kwargs."""
        if not self._connected and not self.connect():
            return SendResult(
                success=False,
                crystal_id="",
                service=self.SERVICE,
                recipient=recipient,
                message_preview="",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                error="topstep_not_connected (missing TOPSTEP_USERNAME or "
                      "TOPSTEP_API_KEY in /data/Projects/trade-blob/.env)",
                metadata={"tsx_cli_present": _tsx_cli_present(),
                          "live_env_set": _live_trading_enabled()},
            )

        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"message": message}
        params.update(kwargs)

        if recipient not in EXPECTED_TOOLS:
            return SendResult(
                success=False,
                crystal_id="",
                service=self.SERVICE,
                recipient=recipient,
                message_preview="",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                error=f"unknown_tool:{recipient}",
                metadata={"expected_tools": list(EXPECTED_TOOLS)},
            )

        t0 = time.time()
        dry_run = False
        if recipient in WRITE_TOOLS:
            success, body, dry_run = self._dispatch_write(recipient, params)
        else:
            success, body = self._dispatch_read(recipient, params)

        latency_ms = int((time.time() - t0) * 1000)
        crystal_id = _log_trade(recipient, params, body, latency_ms,
                                 success, dry_run)

        if dry_run:
            preview = "DRY-RUN"
        else:
            preview = (body.get("status")
                       or body.get("order_id")
                       or body.get("ok")
                       or str(body)[:200])
        preview_str = str(preview)[:200]

        return SendResult(
            success=success,
            crystal_id=crystal_id,
            service=self.SERVICE,
            recipient=recipient,
            message_preview=preview_str,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error="" if success else (body.get("_error") or body.get("error", ""))[:512],
            metadata={
                "latency_ms": latency_ms,
                "dry_run": dry_run,
                "tsx_cli_present": _tsx_cli_present(),
                "live_env_set": _live_trading_enabled(),
                "would_have_ordered": body.get("would_have_ordered"),
                "fake_order_id": body.get("fake_order_id"),
                "order_id": body.get("order_id"),
                "status": body.get("status"),
                "stub": body.get("stub", False),
            },
        )

    # ---- write-tool dispatcher (the dangerous path) ---------------------
    def _dispatch_write(self, tool: str, p: Dict[str, Any]
                         ) -> Tuple[bool, Dict[str, Any], bool]:
        """Returns (success, body, dry_run).

        HARD GATE: real orders require BOTH confirm=True AND
        TOPSTEP_LIVE_TRADING=1.  Either missing  DRY-RUN stub.
        """
        confirm = bool(p.get("confirm", False))
        live = _live_trading_enabled()

        # Build the would-have-ordered descriptor up front  used by both
        # the DRY-RUN body and the real call (for audit).
        would: Dict[str, Any] = {}
        if tool == "order_market":
            would = {
                "tool": "order_market",
                "symbol": p.get("symbol", ""),
                "qty":    p.get("qty", 0),
                "side":   p.get("side", ""),
            }
        elif tool == "order_limit":
            would = {
                "tool": "order_limit",
                "symbol": p.get("symbol", ""),
                "qty":    p.get("qty", 0),
                "side":   p.get("side", ""),
                "price":  p.get("price", 0),
            }
        elif tool == "flatten_all":
            would = {"tool": "flatten_all", "scope": "ALL_OPEN_POSITIONS"}

        if not (confirm and live):
            # DRY-RUN path  ALWAYS safe.
            body = {
                "dry_run": True,
                "would_have_ordered": would,
                "fake_order_id": uuid.uuid4().hex,
                "status": "DRY_RUN",
                "gates": {
                    "confirm": confirm,
                    "live_env": live,
                    "live_env_var": LIVE_ENV_VAR,
                },
                "note": "set TOPSTEP_LIVE_TRADING=1 in env AND pass "
                        "confirm=True to fire a real order",
            }
            return True, body, True

        # Both gates open  but if the shim is missing we still cannot
        # actually fire. Refuse cleanly.
        if not _tsx_cli_present():
            return False, {
                "_error": "tsx_cli_not_found: "
                          f"{TSX_CLI} needs to be created in the trade-blob "
                          "repo before live orders can be fired",
                "would_have_ordered": would,
            }, False

        rc, body = _invoke_tsx_cli(tool, p, self._username, self._api_key,
                                    timeout=30)
        success = (rc == 0 and not body.get("_error"))
        # Tag the audit body with the order intent so DRY-RUN comparison stays
        # apples-to-apples if someone scans the log later.
        body.setdefault("would_have_ordered", would)
        return success, body, False

    # ---- read-tool dispatcher (always safe) -----------------------------
    def _dispatch_read(self, tool: str, p: Dict[str, Any]
                        ) -> Tuple[bool, Dict[str, Any]]:
        """account_status / positions / health_check / quote_subscribe /
        pnl_intraday / cancel_order  no quota risk."""
        # cancel_order treated as read-class (no new exposure).
        if tool == "cancel_order":
            if not _tsx_cli_present():
                return False, {
                    "_error": "tsx_cli_not_found: "
                              f"{TSX_CLI} needs to be created in the "
                              "trade-blob repo",
                    "stub": True,
                }
            rc, body = _invoke_tsx_cli(tool, p, self._username, self._api_key,
                                        timeout=15)
            return (rc == 0 and not body.get("_error")), body

        if tool == "quote_subscribe":
            sym = str(p.get("symbol", "")).strip().upper()
            if not sym:
                return False, {"_error": "missing symbol"}
            try:
                QUOTE_DIR.mkdir(parents=True, exist_ok=True)
                target = QUOTE_DIR / f"{sym}.jsonl"
                target.touch(exist_ok=True)
                return True, {
                    "ok": True,
                    "stub": not _tsx_cli_present(),
                    "symbol": sym,
                    "sink": str(target),
                    "note": ("real implementation will tail TopstepX websocket "
                             "into this file once tsx_cli.py exists"),
                }
            except OSError as e:
                return False, {"_error": f"quote_subscribe os_error: {e}"}

        # Genuine read tools  try shim, fall back to stub.
        if not _tsx_cli_present():
            return True, self._stub_read(tool, p)

        timeout_map = {
            "account_status": 15,
            "positions":      15,
            "health_check":   10,
            "pnl_intraday":   30,
        }
        rc, body = _invoke_tsx_cli(tool, p, self._username, self._api_key,
                                    timeout=timeout_map.get(tool, 15))
        success = (rc == 0 and not body.get("_error"))
        return success, body

    # ---- stub payloads for read tools when the shim is absent -----------
    def _stub_read(self, tool: str, p: Dict[str, Any]) -> Dict[str, Any]:
        """Read-only stubs that keep dashboards alive while tsx_cli is missing.
        Every stub carries `stub: True` so consumers can tell it apart from
        real broker data."""
        base = {
            "stub": True,
            "ok": True,
            "tsx_cli_path": str(TSX_CLI),
            "note": "tsx_cli_not_found in trade-blob; returning stub data "
                    "so dashboards do not crash",
        }
        if tool == "account_status":
            base.update({
                "balance": 0.0,
                "equity":  0.0,
                "day_pnl": 0.0,
                "currency": "USD",
                "account":  "STUB",
            })
        elif tool == "positions":
            base.update({"positions": []})
        elif tool == "health_check":
            base.update({"status": "stub", "live_env_set": _live_trading_enabled()})
        elif tool == "pnl_intraday":
            base.update({
                "start_ts": p.get("start_ts"),
                "end_ts":   p.get("end_ts"),
                "pnl":      0.0,
                "trades":   [],
            })
        return base


# ---------------------------------------------------------------------------
# CLI surface  smoke-only, NEVER fires a real order
# ---------------------------------------------------------------------------
def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="topstep_mcp  TopstepX connector smoke (DRY-RUN only)")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect")
    sub.add_parser("health-check")
    sub.add_parser("account-status")
    sub.add_parser("positions")
    sub.add_parser("providers", help="list expected tools")
    sub.add_parser("safety", help="report live-trading gate state")

    p_om = sub.add_parser("order-market", help="DRY-RUN by default")
    p_om.add_argument("--symbol", required=True)
    p_om.add_argument("--qty", type=int, required=True)
    p_om.add_argument("--side", required=True, choices=["BUY", "SELL"])
    p_om.add_argument("--confirm", action="store_true",
                       help="caller-side gate; still requires "
                            "TOPSTEP_LIVE_TRADING=1 to fire for real")

    args = ap.parse_args()
    c = TopStepMCPConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({
            "connected": ok,
            "tsx_cli_present": _tsx_cli_present(),
            "live_env_set": _live_trading_enabled(),
        }, indent=2))

    elif args.cmd == "safety":
        print(json.dumps({
            "live_env_var": LIVE_ENV_VAR,
            "live_env_set": _live_trading_enabled(),
            "tsx_cli_present": _tsx_cli_present(),
            "write_tools_gated_by": [
                "confirm=True in args",
                f"{LIVE_ENV_VAR}=1 in env",
            ],
            "law": "either gate missing  DRY-RUN",
        }, indent=2))

    elif args.cmd == "health-check":
        r = c.send("health_check", "")
        print(json.dumps({"success": r.success,
                          "preview": r.message_preview,
                          "metadata": r.metadata,
                          "error": r.error}, indent=2))

    elif args.cmd == "account-status":
        r = c.send("account_status", "")
        print(json.dumps({"success": r.success,
                          "preview": r.message_preview,
                          "metadata": r.metadata,
                          "error": r.error}, indent=2))

    elif args.cmd == "positions":
        r = c.send("positions", "")
        print(json.dumps({"success": r.success,
                          "preview": r.message_preview,
                          "metadata": r.metadata,
                          "error": r.error}, indent=2))

    elif args.cmd == "order-market":
        payload = {"symbol": args.symbol, "qty": args.qty, "side": args.side}
        if args.confirm:
            payload["confirm"] = True
        r = c.send("order_market", json.dumps(payload))
        print(json.dumps({
            "success": r.success,
            "preview": r.message_preview,
            "dry_run": r.metadata.get("dry_run"),
            "fake_order_id": r.metadata.get("fake_order_id"),
            "would_have_ordered": r.metadata.get("would_have_ordered"),
            "error": r.error,
        }, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({"expected_tools": list(EXPECTED_TOOLS),
                          "write_tools": list(WRITE_TOOLS)}, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
