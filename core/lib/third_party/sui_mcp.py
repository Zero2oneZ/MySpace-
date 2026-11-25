#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        sui_mcp
# role:        CONNECTOR · SUI_ON_CHAIN_RAIL
# tier:        L0
# substrate:   on-chain settlement, NFT mint, DeFi lend/borrow for the dApp
# storage:     ~/.cc/third_party_logs/sui_sends.jsonl + crystal chain
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.sui_mcp.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio/dapp/server.py /dapp/api/buy?payment_method=sui
#   - core/cc.sh::cmd_sui_test  /  cmd_sui_nft_mint  /  cmd_sui_balance
#   - studio_runtime (when card pass.engine='cloud' and provider='sui')
#   - tensorchain_mcp escrow flows (A.7 of plan)
# outbound:
#   - `sui` CLI subprocess (client balance / client pay / client call / tx-block)
#   - inference_logger.log (tier='monetization' or 'defi_loop', model='sui')
# substrate touch:
#   - reads:  SUI_NETWORK, SUI_WALLET, SUI_KEYPAIR, TROLLN_PACKAGE_ID,
#             SYNTH_PACKAGE_ID, TROLLN_TREASURY_CAP_ID, SYNTH_TREASURY_CAP_ID,
#             AGENT_REGISTRY_ID, WALLET_ENCRYPTION_KEY, SUI_LENDING_PACKAGE_ID
#             via studio/auth/keys.upstream_key + load_env
#   - writes: send_log entries + crystal_chain monetization / defi_loop records
# ----------------------------------------------------------------------------
# TOOLS
# ----------------------------------------------------------------------------
#   query_balance(addr, coin_type='0x2::sui::SUI')
#   transfer_usdc(to, amount_micro)               -- gated: requires mainnet+confirm
#   nft_mint(attrs_json)                          -- TROLLN package, module=nft
#   lend_pool_deposit(pool_id, amount)            -- SUI_LENDING_PACKAGE_ID required
#   lend_pool_borrow(pool_id, collateral, borrow) -- SUI_LENDING_PACKAGE_ID required
#   tx_status(digest)
# ============================================================================
"""sui_mcp.py — Sui on-chain connector via subprocess to the `sui` CLI.

Mirrors third_party/stripe_mcp.py + deepseek_mcp.py shape exactly.
SERVICE = "sui". Stdlib only — no `pysui` dep.

Every successful tool call crystal-anchors via inference_logger.log:
  - tier='monetization' for query_balance, transfer_usdc, nft_mint, tx_status
  - tier='defi_loop'    for lend_pool_deposit, lend_pool_borrow

Mainnet gate: when SUI_NETWORK == 'mainnet', all writes (transfer_usdc,
nft_mint, lend_pool_deposit, lend_pool_borrow) require an explicit
`confirm=True` parameter (or message JSON arg) — devnet / testnet treat
the playground as free-fire.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402

EXPECTED_TOOLS = (
    "query_balance",
    "transfer_usdc",
    "nft_mint",
    "lend_pool_deposit",
    "lend_pool_borrow",
    "tx_status",
)

# Canonical Sui USDC coin type on mainnet (Wormhole-bridged).
# TEXT-PLACEHOLDER: env override via SUI_USDC_COIN_TYPE — keep this address
# documented; production code should always source from env / on-chain registry.
DEFAULT_USDC_COIN_TYPE = (
    "0x5d4b302506645c37ff133b98c4b50a5ae14841659738d6d733d59d0d217a93bf"
    "::coin::COIN"
)
DEFAULT_GAS_BUDGET = "10000000"
DEFAULT_TIMEOUT_S = 60

# Tools that *write* to chain → mainnet-gated by explicit confirm flag.
_WRITE_TOOLS = {
    "transfer_usdc",
    "nft_mint",
    "lend_pool_deposit",
    "lend_pool_borrow",
}
_DEFI_TOOLS = {"lend_pool_deposit", "lend_pool_borrow"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_env_dict() -> Dict[str, str]:
    """Pull the project .env via studio/auth/keys.load_env (fallback: {})."""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
        from auth.keys import load_env  # type: ignore
        return load_env() or {}
    except Exception:
        return {}


def _resolve_wallet() -> str:
    """Resolve SUI_WALLET via keys.upstream_key('sui'); env fallback."""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
        from auth.keys import upstream_key  # type: ignore
        k = upstream_key("sui")
        if k:
            return k
    except Exception:
        pass
    return os.environ.get("SUI_WALLET", "")


def _resolve_network() -> str:
    env = _load_env_dict()
    return (
        env.get("SUI_NETWORK")
        or os.environ.get("SUI_NETWORK", "")
        or "devnet"
    ).strip().lower()


def _run_sui(argv: List[str], timeout: int = DEFAULT_TIMEOUT_S) -> tuple[int, Dict[str, Any]]:
    """Invoke the `sui` CLI. Returns (returncode, parsed_json_or_error_dict).

    `--json` is preferred; we always try to parse stdout as JSON, falling
    back to a raw-string wrapper.
    """
    if shutil.which("sui") is None:
        return 127, {"_error": "sui_cli_not_on_path"}
    try:
        proc = subprocess.run(
            ["sui", *argv],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, {"_error": f"sui_timeout_{timeout}s"}
    except FileNotFoundError:
        return 127, {"_error": "sui_cli_not_found"}
    except Exception as e:
        return 1, {"_error": f"{type(e).__name__}: {e}"}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return proc.returncode, {
            "_error": stderr[:2048] or stdout[:2048] or f"rc={proc.returncode}",
        }
    if not stdout:
        return proc.returncode, {"_raw": "", "_stderr": stderr[:512]}
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return proc.returncode, {"_raw": stdout[:8192]}
    # `sui client balance --json` returns a list (`[[ [coin_type, [...],
    # totalBalance], ... ], false]`) rather than a dict; wrap so callers
    # consistently see a dict.
    if isinstance(parsed, list):
        return proc.returncode, {"_list": parsed}
    return proc.returncode, parsed


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_chain(tool: str, params: Dict[str, Any], result: Dict[str, Any],
               latency_ms: int, rc: int) -> str:
    """Append one InferenceRecord with model='sui' on success/failure.

    tier='defi_loop' for lend_pool_* tools; tier='monetization' otherwise.
    Scope=f'sui_{tool}'. Sensitive params (wallet, keypair) are redacted —
    only addresses, amounts, ids are persisted.
    """
    tier = "defi_loop" if tool in _DEFI_TOOLS else "monetization"
    # Redact: never persist the wallet keypair or master encryption material.
    safe_params = {
        k: v for k, v in params.items()
        if k not in ("keypair", "secret", "private_key", "encryption_key", "confirm")
    }
    safe_result = {}
    if isinstance(result, dict):
        for k in ("digest", "objectId", "object_id", "status",
                  "totalBalance", "totalGasCost", "transactionDigest",
                  "effects", "_error"):
            if k in result:
                v = result[k]
                if isinstance(v, (dict, list)):
                    safe_result[k] = json.dumps(v)[:256]
                else:
                    safe_result[k] = str(v)[:256]
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=f"sui.{tool}",
            enhanced_prompt=json.dumps(safe_params, separators=(",", ":"))[:512],
            output_text=json.dumps(safe_result, separators=(",", ":"))[:1024],
            tier=tier, model="sui",
            scope=f"sui_{tool}",
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_action=f"sui.{tool}",
            done_flag=(rc == 0),
            rc=rc,
        ) or ""
    except Exception as e:
        sys.stderr.write(f"warn: sui crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class SuiMCPConnector(ThirdPartyConnector):
    """Sui on-chain connector. Shells out to the `sui` CLI."""

    SERVICE = "sui"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name="sui_default",
                action="on_chain_rail",
            )
        super().__init__(config)
        self._wallet: str = ""
        self._network: str = ""
        self._env: Dict[str, str] = {}
        self._connected = False

    # ---- lifecycle -----------------------------------------------------

    def connect(self) -> bool:
        """Verify sui CLI is available, wallet is resolvable, network is set."""
        if shutil.which("sui") is None:
            self._connected = False
            return False
        self._env = _load_env_dict()
        self._wallet = _resolve_wallet()
        self._network = _resolve_network()
        if not self._wallet:
            self._connected = False
            return False
        # Smoke: `sui client active-env` — verifies CLI is initialized.
        rc, _ = _run_sui(["client", "active-env"], timeout=10)
        self._connected = (rc == 0)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    # ---- main dispatch -------------------------------------------------

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        """recipient = tool name; message = JSON args (preferred) or empty if kwargs."""
        if not self._connected and not self.connect():
            return SendResult(
                success=False, crystal_id="",
                service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.time(),
                error="sui_not_connected (missing sui CLI or SUI_WALLET?)",
                metadata={"network": self._network, "has_wallet": bool(self._wallet)},
            )

        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"message": message}
        params.update(kwargs)

        # Mainnet write-gate.
        if self._network == "mainnet" and recipient in _WRITE_TOOLS:
            if not bool(params.get("confirm", False)):
                return SendResult(
                    success=False, crystal_id="",
                    service=self.SERVICE, recipient=recipient,
                    message_preview="", timestamp=time.time(),
                    error="mainnet_write_requires_confirm",
                    metadata={
                        "network": self._network,
                        "hint": "pass confirm=true (or {\"confirm\":true} in message) to authorize",
                    },
                )

        t0 = time.time()
        if recipient == "query_balance":
            rc, body = self._query_balance(params)
        elif recipient == "transfer_usdc":
            rc, body = self._transfer_usdc(params)
        elif recipient == "nft_mint":
            rc, body = self._nft_mint(params)
        elif recipient == "lend_pool_deposit":
            rc, body = self._lend_pool_deposit(params)
        elif recipient == "lend_pool_borrow":
            rc, body = self._lend_pool_borrow(params)
        elif recipient == "tx_status":
            rc, body = self._tx_status(params)
        else:
            return SendResult(
                success=False, crystal_id="",
                service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.time(),
                error=f"unknown_tool:{recipient}",
                metadata={"expected_tools": list(EXPECTED_TOOLS)},
            )

        latency_ms = int((time.time() - t0) * 1000)
        crystal_id = _log_chain(recipient, params, body, latency_ms, rc)
        success = (rc == 0)

        # Build preview + structured metadata.
        if isinstance(body, dict):
            preview = (
                str(body.get("digest", ""))
                or str(body.get("objectId", ""))
                or str(body.get("totalBalance", ""))
                or body.get("_error", "")
                or str(body)[:200]
            )
            md = {
                "network": self._network,
                "latency_ms": latency_ms,
                "rc": rc,
                "digest": str(body.get("digest", "") or body.get("transactionDigest", "")),
                "object_id": str(body.get("objectId", "") or body.get("object_id", "")),
                "status": str(body.get("status", "")),
            }
            # For balance lookups surface the totalBalance value.
            if recipient == "query_balance" and success:
                tb = body.get("totalBalance")
                if tb is not None:
                    md["total_balance"] = str(tb)
                cc = body.get("coinObjectCount")
                if cc is not None:
                    md["coin_object_count"] = int(cc) if isinstance(cc, int) else cc
        else:
            preview = str(body)[:200]
            md = {"network": self._network, "latency_ms": latency_ms, "rc": rc}

        return SendResult(
            success=success, service=self.SERVICE, recipient=recipient,
            message_preview=preview[:200], timestamp=time.time(),
            crystal_id=crystal_id,
            error="" if success else (body.get("_error", "") if isinstance(body, dict) else f"rc_{rc}"),
            metadata=md,
        )

    def history(self, limit: int = 20) -> list:
        log_path = Path.home() / ".cc" / "third_party_logs" / "sui_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- Tool implementations -----------------------------------------

    def _query_balance(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        addr = (p.get("addr") or p.get("address") or self._wallet).strip()
        if not addr:
            return 1, {"_error": "missing addr (and no SUI_WALLET in env)"}
        coin_type = (p.get("coin_type") or "0x2::sui::SUI").strip()
        # Sui CLI takes ADDRESS as positional; --coin-type is optional flag.
        argv = [
            "client", "balance",
            addr,
            "--coin-type", coin_type,
            "--json",
        ]
        rc, body = _run_sui(argv, timeout=30)
        if rc != 0:
            return rc, body
        # Flatten the list shape: `[[ [coin_type, [coin_objs...], total], ... ], locked?]`
        # into a stable dict with totalBalance + coinObjectCount.
        out: Dict[str, Any] = {"address": addr, "coin_type": coin_type}
        try:
            lst = body.get("_list") if isinstance(body, dict) else None
            if isinstance(lst, list) and lst:
                rows = lst[0] if lst and isinstance(lst[0], list) else []
                if rows:
                    first = rows[0]
                    # first = [coin_type_str, [coin_objects...], total_balance_str]
                    if isinstance(first, list) and len(first) >= 3:
                        coin_objs = first[1] if isinstance(first[1], list) else []
                        out["totalBalance"] = str(first[2])
                        out["coinObjectCount"] = len(coin_objs)
                    else:
                        out["totalBalance"] = "0"
                        out["coinObjectCount"] = 0
                else:
                    out["totalBalance"] = "0"
                    out["coinObjectCount"] = 0
                out["_list"] = lst
        except Exception as e:
            out["_warn"] = f"balance parse: {type(e).__name__}: {e}"
            if isinstance(body, dict):
                out.update(body)
        return rc, out

    def _transfer_usdc(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        """USDC transfer via `sui client pay`.

        Note: `sui client pay` selects input coins by object-id, not coin-type,
        so the caller must supply `input_coins` (list of coin object IDs to
        spend) — typically discovered via `query_balance` with the USDC
        coin_type. The DEFAULT_USDC_COIN_TYPE is documented as a TEXT-PLACEHOLDER
        for the canonical bridged USDC address; production code should resolve
        SUI_USDC_COIN_TYPE from env / on-chain registry.
        """
        to = (p.get("to") or p.get("recipient") or "").strip()
        amount = p.get("amount_micro")
        if not to or amount is None:
            return 1, {"_error": "missing to / amount_micro"}
        try:
            amount_int = int(amount)
        except (TypeError, ValueError):
            return 1, {"_error": f"bad amount_micro: {amount!r}"}
        input_coins = p.get("input_coins") or p.get("coin_object_ids")
        if not input_coins:
            return 1, {
                "_error": (
                    "missing input_coins (list of USDC coin object IDs). "
                    "Discover via query_balance(coin_type=USDC); resolved USDC "
                    "coin_type for this network: "
                    + (
                        p.get("coin_type")
                        or os.environ.get("SUI_USDC_COIN_TYPE")
                        or self._env.get("SUI_USDC_COIN_TYPE")
                        or DEFAULT_USDC_COIN_TYPE
                    )
                ),
            }
        if isinstance(input_coins, str):
            input_coins = [input_coins]
        gas_budget = str(p.get("gas_budget", DEFAULT_GAS_BUDGET))
        argv = [
            "client", "pay",
            "--input-coins", *[str(c) for c in input_coins],
            "--recipients", to,
            "--amounts", str(amount_int),
            "--gas-budget", gas_budget,
            "--json",
        ]
        return _run_sui(argv, timeout=DEFAULT_TIMEOUT_S)

    def _nft_mint(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        pkg = (
            self._env.get("TROLLN_PACKAGE_ID")
            or os.environ.get("TROLLN_PACKAGE_ID", "")
        )
        if not pkg:
            return 1, {"_error": "TROLLN_PACKAGE_ID not set"}
        attrs = p.get("attrs_json") or p.get("attrs") or "{}"
        if isinstance(attrs, (dict, list)):
            attrs = json.dumps(attrs, separators=(",", ":"))
        gas_budget = str(p.get("gas_budget", DEFAULT_GAS_BUDGET))
        argv = [
            "client", "call",
            "--package", pkg,
            "--module", "nft",
            "--function", "mint",
            "--args", attrs,
            "--gas-budget", gas_budget,
            "--json",
        ]
        return _run_sui(argv, timeout=DEFAULT_TIMEOUT_S)

    def _lend_pool_deposit(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        pkg = (
            self._env.get("SUI_LENDING_PACKAGE_ID")
            or os.environ.get("SUI_LENDING_PACKAGE_ID", "")
        )
        if not pkg:
            return 1, {"_error": "SUI_LENDING_PACKAGE_ID not set"}
        pool_id = (p.get("pool_id") or "").strip()
        amount = p.get("amount")
        if not pool_id or amount is None:
            return 1, {"_error": "missing pool_id / amount"}
        try:
            amount_int = int(amount)
        except (TypeError, ValueError):
            return 1, {"_error": f"bad amount: {amount!r}"}
        gas_budget = str(p.get("gas_budget", DEFAULT_GAS_BUDGET))
        argv = [
            "client", "call",
            "--package", pkg,
            "--module", "lending_pool",
            "--function", "deposit",
            "--args", pool_id, str(amount_int),
            "--gas-budget", gas_budget,
            "--json",
        ]
        return _run_sui(argv, timeout=DEFAULT_TIMEOUT_S)

    def _lend_pool_borrow(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        pkg = (
            self._env.get("SUI_LENDING_PACKAGE_ID")
            or os.environ.get("SUI_LENDING_PACKAGE_ID", "")
        )
        if not pkg:
            return 1, {"_error": "SUI_LENDING_PACKAGE_ID not set"}
        pool_id = (p.get("pool_id") or "").strip()
        collateral = p.get("collateral")
        borrow = p.get("borrow")
        if not pool_id or collateral is None or borrow is None:
            return 1, {"_error": "missing pool_id / collateral / borrow"}
        try:
            collateral_int = int(collateral)
            borrow_int = int(borrow)
        except (TypeError, ValueError):
            return 1, {"_error": "bad collateral/borrow (must be integer micro-units)"}
        gas_budget = str(p.get("gas_budget", DEFAULT_GAS_BUDGET))
        argv = [
            "client", "call",
            "--package", pkg,
            "--module", "lending_pool",
            "--function", "borrow",
            "--args", pool_id, str(collateral_int), str(borrow_int),
            "--gas-budget", gas_budget,
            "--json",
        ]
        return _run_sui(argv, timeout=DEFAULT_TIMEOUT_S)

    def _tx_status(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        digest = (p.get("digest") or "").strip()
        if not digest:
            return 1, {"_error": "missing digest"}
        argv = ["client", "tx-block", digest, "--json"]
        return _run_sui(argv, timeout=30)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="sui_mcp — Sui on-chain connector smoke")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect")

    p_bal = sub.add_parser("balance", help="query balance for an address")
    p_bal.add_argument("--addr", default="", help="default: SUI_WALLET from env")
    p_bal.add_argument("--coin-type", default="0x2::sui::SUI")

    p_tx = sub.add_parser("tx", help="fetch transaction block by digest")
    p_tx.add_argument("digest")

    p_mint = sub.add_parser("mint", help="nft_mint via TROLLN_PACKAGE_ID")
    p_mint.add_argument("--attrs", default="{}", help="attrs JSON for mint args")
    p_mint.add_argument("--confirm", action="store_true",
                        help="required on mainnet")

    sub.add_parser("providers", help="list expected tools")

    args = ap.parse_args()
    c = SuiMCPConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({
            "connected": ok,
            "network": c._network,
            "has_wallet": bool(c._wallet),
            "wallet_len": len(c._wallet),
        }, indent=2))

    elif args.cmd == "balance":
        c.connect()
        body = {"addr": args.addr or c._wallet, "coin_type": args.coin_type}
        r = c.send("query_balance", json.dumps(body))
        print(json.dumps({
            "success": r.success,
            "preview": r.message_preview,
            "network": r.metadata.get("network", ""),
            "total_balance": r.metadata.get("total_balance", ""),
            "coin_object_count": r.metadata.get("coin_object_count", 0),
            "crystal": (r.crystal_id or "")[:24],
            "error": r.error,
        }, indent=2))

    elif args.cmd == "tx":
        c.connect()
        r = c.send("tx_status", json.dumps({"digest": args.digest}))
        print(json.dumps({
            "success": r.success,
            "digest": r.metadata.get("digest", ""),
            "status": r.metadata.get("status", ""),
            "crystal": (r.crystal_id or "")[:24],
            "error": r.error,
        }, indent=2))

    elif args.cmd == "mint":
        c.connect()
        msg = {"attrs_json": args.attrs}
        if args.confirm:
            msg["confirm"] = True
        r = c.send("nft_mint", json.dumps(msg))
        print(json.dumps({
            "success": r.success,
            "object_id": r.metadata.get("object_id", ""),
            "digest": r.metadata.get("digest", ""),
            "crystal": (r.crystal_id or "")[:24],
            "error": r.error,
        }, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({
            "expected_tools": list(EXPECTED_TOOLS),
            "default_usdc_coin_type": DEFAULT_USDC_COIN_TYPE,
            "default_gas_budget": DEFAULT_GAS_BUDGET,
            "write_tools": sorted(_WRITE_TOOLS),
            "defi_tools": sorted(_DEFI_TOOLS),
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
