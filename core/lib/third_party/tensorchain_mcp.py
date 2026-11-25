#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        tensorchain_mcp
# role:        CONNECTOR · TENSORCHAIN_DAPP_MINT_AND_ESCROW
# tier:        L0
# substrate:   Tom-owned L1 chain — NFT mint / escrow / royalty primitives
# storage:     ~/.cc/third_party_logs/tensorchain_sends.jsonl + crystal chain
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.tensorchain_mcp.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio/dapp/server.py /dapp/api/mint and /dapp/api/escrow_settle
#   - core/cc.sh::cmd_tensorchain_test  (future)
#   - studio_runtime._dispatch_cloud (when pass.provider_family='tensorchain')
#   - stripe_mcp webhook handler → escrow_settle on successful PI
# outbound:
#   - JSON-RPC POST to $TENSORCHAIN_RPC (if set)
#   - subprocess invocation of cargo run --bin tensorchain-service (fallback)
#   - inference_logger.log (tier='monetization', model='tensorchain'|'tensorchain_sui_fallback')
#   - sui_mcp (optional) for two-chain bridge fallback when SUI_FALLBACK=1
# substrate touch:
#   - reads:  TENSORCHAIN_RPC or SUI_WALLET via keys.upstream_key('tensorchain')
#   - reads:  /data/Projects/gently/crates/tensorchain-service/Cargo.toml (existence only)
#   - writes: send_log + crystal_chain monetization records
# ----------------------------------------------------------------------------
# BACKENDS (resolved in connect() in this priority order)
# ----------------------------------------------------------------------------
#   1. RPC      — env TENSORCHAIN_RPC set → urllib JSON-RPC 2.0
#   2. CARGO    — gently Rust crate present → subprocess cargo run (120s)
#   3. STUB     — neither available → SendResult(success=False) but still
#                 crystal-anchors the failure for audit
# ============================================================================
"""tensorchain_mcp.py — TensorChain (Tom-owned L1) connector w/ SUI bridge.

Mirrors third_party/stripe_mcp.py + deepseek_mcp.py shape. SERVICE = "tensorchain".
Stdlib only.

Tools (via send(recipient=tool_name, message=json_args, **kwargs)):
  - mint_nft(metadata_uri, royalty_bps, owner)              → "nft/mint"
  - deploy_contract(wasm_path, init_args)                   → "contract/deploy"
  - escrow_settle(escrow_id, beneficiary)                   → "escrow/settle"
  - royalty_split(asset_id, splits)                         → "royalty/split"
  - query_balance(addr)                                     → "balance/query"
  - tx_broadcast(payload)                                   → "tx/broadcast"

Two-chain bridge: if a tool returns JSON-RPC error -32601 ("method not found")
and env SUI_FALLBACK=1, attempt sui_mcp routing for mint_nft / query_balance.
Fallback calls crystal-anchor with model='tensorchain_sui_fallback'.

Every call crystal-anchors via inference_logger.log(tier='monetization').
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402

EXPECTED_TOOLS = (
    "mint_nft",
    "deploy_contract",
    "escrow_settle",
    "royalty_split",
    "query_balance",
    "tx_broadcast",
)

# RPC method names on the wire (whatever tensorchain-service exposes)
RPC_METHOD = {
    "mint_nft":         "nft/mint",
    "deploy_contract":  "contract/deploy",
    "escrow_settle":    "escrow/settle",
    "royalty_split":    "royalty/split",
    "query_balance":    "balance/query",
    "tx_broadcast":     "tx/broadcast",
}

# Tools that have a SUI equivalent for the two-chain bridge fallback
SUI_BRIDGEABLE = {
    "mint_nft":      "nft_mint",        # sui_mcp tool name
    "query_balance": "query_balance",
}

GENTLY_CRATE = Path("/data/Projects/gently/crates/tensorchain-service/Cargo.toml")
CARGO_BIN = "tensorchain-service"
CARGO_TIMEOUT_SEC = 120

BACKEND_RPC = "rpc"
BACKEND_CARGO = "cargo"
BACKEND_STUB = "stub"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_rpc_url() -> str:
    """Resolve TENSORCHAIN_RPC via keys.upstream_key('tensorchain') or env.
    Note: keys.upstream_key('tensorchain') falls back to SUI_WALLET per
    auth/keys.py, but a wallet address is NOT a valid RPC URL. We therefore
    look for an http(s):// scheme before accepting it as an RPC endpoint."""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
        from auth.keys import upstream_key  # type: ignore
        k = upstream_key("tensorchain")
        if k and (k.startswith("http://") or k.startswith("https://")):
            return k
    except Exception:
        pass
    raw = os.environ.get("TENSORCHAIN_RPC", "")
    if raw and (raw.startswith("http://") or raw.startswith("https://")):
        return raw
    return ""


def _http_post_json(url: str, payload: Dict[str, Any],
                     headers: Optional[Dict[str, str]] = None,
                     timeout: int = 30) -> Tuple[int, Dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(txt)
            except json.JSONDecodeError:
                return resp.status, {"_raw": txt[:8192]}
    except urllib.error.HTTPError as e:
        try:
            body_txt = e.read().decode("utf-8", errors="replace")
            if body_txt.strip().startswith("{"):
                return e.code, json.loads(body_txt)
            return e.code, {"_error": body_txt[:2048]}
        except Exception:
            return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_monetization(tool: str, params: Dict[str, Any], result: Dict[str, Any],
                       latency_ms: int, status_code: int, backend: str,
                       model: str = "tensorchain") -> str:
    """Append one InferenceRecord with tier='monetization'. Returns crystal_id."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=f"tensorchain.{tool}",
            enhanced_prompt=json.dumps(
                {k: v for k, v in params.items() if k not in ("wasm_path",)},
                separators=(",", ":"), default=str,
            )[:512],
            output_text=json.dumps(
                {k: v for k, v in result.items()
                 if k in ("tx_hash", "asset_id", "balance", "status",
                          "escrow_id", "owner", "package_id", "object_id",
                          "_error", "_backend")},
                separators=(",", ":"), default=str,
            )[:512],
            tier="monetization", model=model,
            scope=f"tensorchain_{tool}",
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_action=f"tensorchain.{tool}[{backend}]",
            done_flag=(status_code == 200),
            rc=0 if status_code == 200 else 1,
        ) or ""
    except Exception as e:
        sys.stderr.write(f"warn: tensorchain crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class TensorChainMCPConnector(ThirdPartyConnector):
    """TensorChain L1 connector — RPC | cargo | stub backend resolution.

    Two-chain bridge: on JSON-RPC -32601 (method not found) and SUI_FALLBACK=1,
    routes mint_nft / query_balance through sui_mcp (TROLLN package) for
    graceful degradation while tensorchain-service grows its method set."""

    SERVICE = "tensorchain"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE, name="tensorchain_default",
                action="dapp_mint_escrow",
            )
        super().__init__(config)
        self._rpc_url = ""
        self._backend = BACKEND_STUB
        self._cargo_manifest: Optional[Path] = None
        self._connected = False

    # ---- ThirdPartyConnector lifecycle ----------------------------------

    def connect(self) -> str:
        """Resolve a backend. Returns backend name (rpc|cargo|stub).
        Note: base.py annotates this as `str`; stripe_mcp returns bool. We
        return the backend identifier so callers can branch on it; truthy
        equivalence (non-empty string) preserves the bool-style contract."""
        # 1) RPC
        rpc = _load_rpc_url()
        if rpc:
            self._rpc_url = rpc.rstrip("/")
            self._backend = BACKEND_RPC
            self._connected = True
            return BACKEND_RPC
        # 2) Cargo
        if GENTLY_CRATE.exists():
            self._cargo_manifest = GENTLY_CRATE
            self._backend = BACKEND_CARGO
            self._connected = True
            return BACKEND_CARGO
        # 3) Stub
        self._backend = BACKEND_STUB
        self._connected = True  # still "connected" — stub mode logs failures
        return BACKEND_STUB

    def disconnect(self) -> str:
        prev = self._backend
        self._connected = False
        self._backend = BACKEND_STUB
        return prev

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        if not self._connected:
            self.connect()

        if recipient not in EXPECTED_TOOLS:
            return SendResult(
                success=False, service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.time(),
                crystal_id="",
                error=f"unknown_tool:{recipient}",
                metadata={"expected_tools": list(EXPECTED_TOOLS)},
            )

        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"message": message}
        params.update(kwargs)

        t0 = time.time()
        model_label = "tensorchain"

        if self._backend == BACKEND_RPC:
            status, body = self._call_rpc(recipient, params)
        elif self._backend == BACKEND_CARGO:
            status, body = self._call_cargo(recipient, params)
        else:
            status, body = 0, {
                "_error": "tensorchain unreachable: no RPC, no cargo crate, no stub backend",
                "_backend": "stub",
            }

        # ---- Two-chain bridge: JSON-RPC -32601 → SUI fallback ------------
        method_not_found = self._is_method_not_found(body)
        if (method_not_found and os.environ.get("SUI_FALLBACK", "") == "1"
                and recipient in SUI_BRIDGEABLE):
            sui_status, sui_body = self._sui_fallback(recipient, params)
            if sui_status:
                status, body = sui_status, sui_body
                model_label = "tensorchain_sui_fallback"
                body.setdefault("_backend", "sui_fallback")

        latency_ms = int((time.time() - t0) * 1000)
        crystal_id = _log_monetization(
            recipient, params, body, latency_ms, status,
            backend=self._backend, model=model_label,
        )
        success = 200 <= status < 300

        preview = (body.get("tx_hash") or body.get("asset_id")
                   or body.get("balance") or body.get("status")
                   or body.get("_error") or str(body))[:200] if isinstance(
            (body.get("tx_hash") or body.get("asset_id") or body.get("balance")
             or body.get("status") or body.get("_error") or str(body)),
            str,
        ) else str(body)[:200]

        return SendResult(
            success=success, service=self.SERVICE, recipient=recipient,
            message_preview=preview, timestamp=time.time(),
            crystal_id=crystal_id,
            error="" if success else (body.get("_error", "") or f"backend_{self._backend}_status_{status}"),
            metadata={
                "status_code": status,
                "latency_ms": latency_ms,
                "backend": self._backend,
                "model": model_label,
                "rpc_method": RPC_METHOD.get(recipient, ""),
                "tx_hash": body.get("tx_hash", ""),
                "asset_id": body.get("asset_id", ""),
                "escrow_id": body.get("escrow_id", ""),
                "owner": body.get("owner", ""),
                "balance": body.get("balance", ""),
                "sui_fallback_used": (model_label == "tensorchain_sui_fallback"),
            },
        )

    def history(self, thread_id: str = "", limit: int = 20) -> list:
        log_path = Path.home() / ".cc" / "third_party_logs" / "tensorchain_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- Backend implementations ----------------------------------------

    def _call_rpc(self, tool: str, params: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        method = RPC_METHOD[tool]
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": [params],
            "id": 1,
        }
        status, body = _http_post_json(self._rpc_url, payload, timeout=30)
        body = dict(body) if isinstance(body, dict) else {"_raw": str(body)}
        body["_backend"] = "rpc"
        # JSON-RPC envelope: extract result/error
        if isinstance(body.get("result"), dict):
            inner = dict(body["result"])
            inner["_backend"] = "rpc"
            # carry forward the envelope's "error" key if any (for -32601 detection)
            if body.get("error"):
                inner["error"] = body["error"]
            return status, inner
        if body.get("error"):
            err = body["error"]
            code = err.get("code") if isinstance(err, dict) else None
            msg = err.get("message") if isinstance(err, dict) else str(err)
            out = {
                "_error": f"jsonrpc[{code}]: {msg}",
                "_backend": "rpc",
                "error": err,
            }
            # surface as non-2xx so success calc is correct
            return (status if status >= 400 else 500), out
        return status, body

    def _call_cargo(self, tool: str, params: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if self._cargo_manifest is None:
            return 0, {"_error": "no cargo manifest set", "_backend": "cargo"}
        method = RPC_METHOD[tool]
        cmd = [
            "cargo", "run",
            "--manifest-path", str(self._cargo_manifest),
            "--bin", CARGO_BIN, "--",
            method,
            json.dumps(params, default=str),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=CARGO_TIMEOUT_SEC, check=False,
            )
        except subprocess.TimeoutExpired:
            return 0, {
                "_error": f"cargo timeout after {CARGO_TIMEOUT_SEC}s",
                "_backend": "cargo",
            }
        except FileNotFoundError:
            return 0, {
                "_error": "cargo binary not found on PATH",
                "_backend": "cargo",
            }
        except Exception as e:
            return 0, {
                "_error": f"cargo failed: {type(e).__name__}: {e}",
                "_backend": "cargo",
            }
        if proc.returncode != 0:
            return 500, {
                "_error": f"cargo rc={proc.returncode}: "
                          f"{(proc.stderr or '').strip()[:1024]}",
                "_backend": "cargo",
            }
        out = (proc.stdout or "").strip()
        try:
            parsed = json.loads(out)
            if isinstance(parsed, dict):
                parsed["_backend"] = "cargo"
                return 200, parsed
            return 200, {"_raw": parsed, "_backend": "cargo"}
        except json.JSONDecodeError:
            return 200, {"_raw": out[:8192], "_backend": "cargo"}

    @staticmethod
    def _is_method_not_found(body: Dict[str, Any]) -> bool:
        """Detect JSON-RPC -32601 method-not-found in any nested shape."""
        if not isinstance(body, dict):
            return False
        err = body.get("error")
        if isinstance(err, dict) and err.get("code") == -32601:
            return True
        # Also flag cargo / stub textual signals
        msg = body.get("_error", "") or ""
        if "method not found" in str(msg).lower() or "-32601" in str(msg):
            return True
        return False

    def _sui_fallback(self, tool: str, params: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Route via sui_mcp. May raise ImportError handled here."""
        try:
            from third_party import sui_mcp  # type: ignore  # noqa: F401
        except Exception as e:
            return 0, {
                "_error": f"sui_fallback unavailable: {type(e).__name__}: {e}",
                "_backend": "sui_fallback_missing",
            }
        try:
            sui_tool = SUI_BRIDGEABLE[tool]
            connector_cls = getattr(sui_mcp, "SuiMCPConnector", None) \
                or getattr(sui_mcp, "SUIMCPConnector", None)
            if connector_cls is None:
                return 0, {
                    "_error": "sui_mcp exports no SuiMCPConnector",
                    "_backend": "sui_fallback_missing",
                }
            c = connector_cls()
            try:
                c.connect()
            except Exception:
                pass
            r = c.send(sui_tool, json.dumps(params, default=str))
            ok = bool(getattr(r, "success", False))
            md = getattr(r, "metadata", {}) or {}
            return (200 if ok else 500), {
                "status": "ok" if ok else "err",
                "tx_hash": md.get("tx_hash", ""),
                "object_id": md.get("object_id", ""),
                "package_id": md.get("package_id", ""),
                "balance": md.get("balance", ""),
                "_error": "" if ok else getattr(r, "error", "sui_fallback_failed"),
                "_backend": "sui_fallback",
                "_sui_preview": getattr(r, "message_preview", "")[:200],
            }
        except Exception as e:
            return 0, {
                "_error": f"sui_fallback runtime: {type(e).__name__}: {e}",
                "_backend": "sui_fallback",
            }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="tensorchain_mcp — TensorChain L1 connector")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect", help="resolve backend (rpc|cargo|stub)")

    p_mint = sub.add_parser("mint", help="mint_nft tool")
    p_mint.add_argument("--metadata-uri", default="ipfs://QmTest")
    p_mint.add_argument("--royalty-bps", type=int, default=500)
    p_mint.add_argument("--owner", default="0x0")

    p_bal = sub.add_parser("balance", help="query_balance tool")
    p_bal.add_argument("addr")

    p_esc = sub.add_parser("escrow-settle", help="escrow_settle tool")
    p_esc.add_argument("escrow_id")
    p_esc.add_argument("--beneficiary", default="0x0")

    sub.add_parser("providers", help="list expected tools + backends")

    args = ap.parse_args()
    c = TensorChainMCPConnector()

    if args.cmd == "connect":
        backend = c.connect()
        print(json.dumps({
            "backend": backend,
            "rpc_url": c._rpc_url,
            "cargo_crate_present": bool(c._cargo_manifest),
            "sui_fallback_armed": os.environ.get("SUI_FALLBACK") == "1",
        }, indent=2))

    elif args.cmd == "mint":
        r = c.send("mint_nft", json.dumps({
            "metadata_uri": args.metadata_uri,
            "royalty_bps": args.royalty_bps,
            "owner": args.owner,
        }))
        print(json.dumps({
            "success": r.success,
            "backend": r.metadata.get("backend", ""),
            "tx_hash": r.metadata.get("tx_hash", ""),
            "asset_id": r.metadata.get("asset_id", ""),
            "sui_fallback_used": r.metadata.get("sui_fallback_used", False),
            "crystal": r.crystal_id[:24] if r.crystal_id else "",
            "preview": r.message_preview,
            "error": r.error,
        }, indent=2))

    elif args.cmd == "balance":
        r = c.send("query_balance", json.dumps({"addr": args.addr}))
        print(json.dumps({
            "success": r.success,
            "backend": r.metadata.get("backend", ""),
            "balance": r.metadata.get("balance", ""),
            "sui_fallback_used": r.metadata.get("sui_fallback_used", False),
            "error": r.error,
        }, indent=2))

    elif args.cmd == "escrow-settle":
        r = c.send("escrow_settle", json.dumps({
            "escrow_id": args.escrow_id,
            "beneficiary": args.beneficiary,
        }))
        print(json.dumps({
            "success": r.success,
            "backend": r.metadata.get("backend", ""),
            "tx_hash": r.metadata.get("tx_hash", ""),
            "crystal": r.crystal_id[:24] if r.crystal_id else "",
            "error": r.error,
        }, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({
            "expected_tools": list(EXPECTED_TOOLS),
            "rpc_methods": RPC_METHOD,
            "sui_bridgeable": SUI_BRIDGEABLE,
            "backends": [BACKEND_RPC, BACKEND_CARGO, BACKEND_STUB],
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
