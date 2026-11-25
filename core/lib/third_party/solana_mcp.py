#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        solana_mcp
# role:        CONNECTOR · SOLANA_ON_CHAIN_RAIL · MUTATING_MEME_COIN
# tier:        L0
# substrate:   on-chain Token-2022 mint with embedded SVG metadata; the SVG
#              can be RE-WRITTEN via the Metaplex metadata-update tx (the
#              "mutating meme-coin" pattern). Complements sui_mcp.py on a
#              second chain — same Token-2022-style metadata shape, different
#              settlement substrate.
# storage:     ~/.cc/third_party_logs/solana_sends.jsonl + crystal chain
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.solana_mcp.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio/dapp/server.py /dapp/api/buy?payment_method=solana (future)
#   - core/cc.sh::cmd_solana_balance / cmd_solana_mint / cmd_solana_mutate
#   - studio_runtime (when card pass.engine='cloud' and provider='solana')
#   - studio passes mutating-meme-coin flow: passes pipeline can re-render an
#     SVG asset and chain update_token_svg(...) as the final on-chain anchor
# outbound:
#   - `solana` CLI subprocess (balance / confirm)
#   - `spl-token` CLI subprocess (create-token / create-account / mint / transfer / balance)
#   - `metaplex` CLI subprocess (token-metadata create / update — Token-2022)
#   - inference_logger.log (tier='monetization', model='solana_token_2022')
# substrate touch:
#   - reads:  SOLANA_KEYPAIR_PATH, SOLANA_RPC_URL, SOLANA_NETWORK,
#             SOLANA_MUTABLE_METADATA_PROGRAM via studio/auth/keys.load_env
#             (read directly from .env — KINDS is NOT widened; this is a
#             one-off connector deliberately scoped narrow)
#   - writes: send_log entries + crystal_chain monetization records
# ----------------------------------------------------------------------------
# TOOLS
# ----------------------------------------------------------------------------
#   query_balance(addr)
#   query_spl_balance(addr, mint)
#   mint_token_2022(name, symbol, decimals, initial_supply, svg_string)
#       — multi-step: create-token (Token-2022) → create-account → mint →
#         metaplex token-metadata create with data:image/svg+xml;base64,…
#   update_token_svg(mint, new_svg_string)
#       — THE mutating-meme-coin pattern: rewrites the on-chain SVG via
#         metaplex token-metadata update --uri data:image/svg+xml;base64,…
#       — crystal scope='svg_mutation' so the inference DAG can walk every
#         re-skin tx end-to-end
#   transfer(mint, to, amount)
#   tx_status(signature)
# ============================================================================
"""solana_mcp.py — Solana on-chain connector via subprocess to the `solana`,
`spl-token`, and `metaplex` CLIs.

Mirrors third_party/sui_mcp.py shape exactly. SERVICE = "solana". Stdlib only
— subprocess + json + base64. No `solana-py` or `solders` dep.

Every successful tool call crystal-anchors via inference_logger.log:
  - tier='monetization' for all tools
  - model='solana_token_2022'
  - scope=f'solana_{tool}'   (update_token_svg overrides → 'svg_mutation')

Mainnet gate: when SOLANA_NETWORK == 'mainnet-beta', all writes
(mint_token_2022, update_token_svg, transfer) require an explicit
`confirm=True` parameter — devnet/testnet treat the playground as
free-fire (matches sui_mcp pattern).

Graceful skip: if the `solana` CLI is not on PATH OR SOLANA_KEYPAIR_PATH is
absent, connect() returns False and send() emits
SendResult(success=False, error='solana_cli_not_configured').
"""
from __future__ import annotations

import base64
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
    "query_spl_balance",
    "mint_token_2022",
    "update_token_svg",
    "transfer",
    "tx_status",
)

# Canonical Solana Token-2022 program ID (constant across all clusters).
# TEXT-PLACEHOLDER: env override via SOLANA_TOKEN_2022_PROGRAM — keep this
# documented; production code should always source from env / on-chain
# registry. The literal below is the well-known Token-2022 SPL program id.
DEFAULT_TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# Default Metaplex Token Metadata program id (Mutable Metadata path used by
# the mutating-meme-coin pattern). Env override:
# SOLANA_MUTABLE_METADATA_PROGRAM.
DEFAULT_METADATA_PROGRAM = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"

DEFAULT_RPC_URL = "https://api.devnet.solana.com"
DEFAULT_TIMEOUT_S = 60

# Tools that *write* to chain → mainnet-gated by explicit confirm flag.
_WRITE_TOOLS = {
    "mint_token_2022",
    "update_token_svg",
    "transfer",
}


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


def _resolve_keypair_path(env: Dict[str, str]) -> str:
    """Resolve SOLANA_KEYPAIR_PATH from .env / environment.

    KINDS in studio/auth/keys.py is NOT widened to add 'solana' — this is a
    one-off connector and the path is read directly via load_env(). Documented
    in the agent card under 'env_vars'.
    """
    path = (
        env.get("SOLANA_KEYPAIR_PATH")
        or os.environ.get("SOLANA_KEYPAIR_PATH", "")
    ).strip()
    if path:
        return os.path.expanduser(path)
    # Default install path for `solana-keygen new`.
    default = os.path.expanduser("~/.config/solana/id.json")
    return default if os.path.exists(default) else ""


def _resolve_rpc_url(env: Dict[str, str]) -> str:
    return (
        env.get("SOLANA_RPC_URL")
        or os.environ.get("SOLANA_RPC_URL", "")
        or DEFAULT_RPC_URL
    ).strip()


def _resolve_network(env: Dict[str, str]) -> str:
    return (
        env.get("SOLANA_NETWORK")
        or os.environ.get("SOLANA_NETWORK", "")
        or "devnet"
    ).strip().lower()


def _resolve_metadata_program(env: Dict[str, str]) -> str:
    return (
        env.get("SOLANA_MUTABLE_METADATA_PROGRAM")
        or os.environ.get("SOLANA_MUTABLE_METADATA_PROGRAM", "")
        or DEFAULT_METADATA_PROGRAM
    ).strip()


def _resolve_token_2022_program(env: Dict[str, str]) -> str:
    return (
        env.get("SOLANA_TOKEN_2022_PROGRAM")
        or os.environ.get("SOLANA_TOKEN_2022_PROGRAM", "")
        or DEFAULT_TOKEN_2022_PROGRAM
    ).strip()


def _svg_to_data_uri(svg: str) -> str:
    """Encode an SVG string as a data: URI suitable for the metadata --uri arg.

    Used by both mint_token_2022 (initial SVG) and update_token_svg (the
    mutation). The on-chain URI itself carries the full SVG payload; that's
    what makes the coin's art mutable via a single metadata update tx.
    """
    payload = svg.encode("utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(payload).decode("ascii")


def _run_cli(binary: str, argv: List[str],
             timeout: int = DEFAULT_TIMEOUT_S) -> tuple[int, Dict[str, Any]]:
    """Invoke a CLI (`solana`, `spl-token`, `metaplex`). Returns
    (returncode, parsed_json_or_error_dict).
    """
    if shutil.which(binary) is None:
        return 127, {"_error": f"{binary}_not_on_path"}
    try:
        proc = subprocess.run(
            [binary, *argv],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, {"_error": f"{binary}_timeout_{timeout}s"}
    except FileNotFoundError:
        return 127, {"_error": f"{binary}_not_found"}
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
        # Many spl-token / metaplex stdouts are line-oriented, not JSON. Pull
        # well-known fields (Signature: …, Address: …, Token: …) heuristically
        # so callers can still get a useful metadata bag.
        out: Dict[str, Any] = {"_raw": stdout[:8192]}
        for line in stdout.splitlines():
            line = line.strip()
            for tag, key in (
                ("Signature:", "signature"),
                ("Address:", "address"),
                ("Token:", "mint"),
                ("Creating token", "mint"),
                ("Account:", "account"),
                ("Minting", "minted"),
            ):
                if line.startswith(tag):
                    val = line[len(tag):].strip()
                    out.setdefault(key, val)
        return proc.returncode, out
    if isinstance(parsed, list):
        return proc.returncode, {"_list": parsed}
    return proc.returncode, parsed


def _run_solana(argv: List[str], rpc_url: str,
                timeout: int = DEFAULT_TIMEOUT_S) -> tuple[int, Dict[str, Any]]:
    return _run_cli("solana", argv + ["--url", rpc_url], timeout=timeout)


def _run_spl(argv: List[str], rpc_url: str, keypair: str,
             timeout: int = DEFAULT_TIMEOUT_S) -> tuple[int, Dict[str, Any]]:
    base = ["--url", rpc_url]
    if keypair:
        base += ["--fee-payer", keypair, "--owner", keypair]
    return _run_cli("spl-token", argv + base, timeout=timeout)


def _run_metaplex(argv: List[str], rpc_url: str, keypair: str,
                  timeout: int = DEFAULT_TIMEOUT_S) -> tuple[int, Dict[str, Any]]:
    base = ["--rpc", rpc_url]
    if keypair:
        base += ["--keypair", keypair]
    return _run_cli("metaplex", argv + base, timeout=timeout)


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_chain(tool: str, params: Dict[str, Any], result: Dict[str, Any],
               latency_ms: int, rc: int) -> str:
    """Append one InferenceRecord with model='solana_token_2022' on every call.

    tier='monetization' for all tools (Solana side has no DeFi loop yet).
    scope=f'solana_{tool}'; update_token_svg uses scope='svg_mutation' so
    the inference DAG can walk every re-skin tx end-to-end.

    Sensitive params (keypair_path, svg_string contents) and the keypair
    itself are redacted before persistence — we keep mint address, signature,
    amounts, and an svg_byte_len hash.
    """
    tier = "monetization"
    scope = "svg_mutation" if tool == "update_token_svg" else f"solana_{tool}"

    # Redact: never persist keypair material or raw SVG bytes (keep length +
    # hash for traceability).
    safe_params: Dict[str, Any] = {}
    for k, v in params.items():
        if k in ("keypair", "secret", "private_key", "keypair_path", "confirm"):
            continue
        if k in ("svg_string", "new_svg_string"):
            # Persist length + a short content hash; never the bytes.
            try:
                blen = len(v.encode("utf-8")) if isinstance(v, str) else len(v or "")
            except Exception:
                blen = -1
            import hashlib as _hashlib
            try:
                h = _hashlib.sha256(
                    v.encode("utf-8") if isinstance(v, str) else (v or b"")
                ).hexdigest()[:16]
            except Exception:
                h = ""
            safe_params[f"{k}_len"] = blen
            safe_params[f"{k}_sha256_16"] = h
        else:
            safe_params[k] = v

    safe_result: Dict[str, Any] = {}
    if isinstance(result, dict):
        for k in ("signature", "transactionSignature", "mint", "address",
                  "account", "decimals", "amount", "value", "balance",
                  "uiAmount", "uiAmountString", "owner", "status",
                  "blockTime", "slot", "_error"):
            if k in result:
                val = result[k]
                if isinstance(val, (dict, list)):
                    safe_result[k] = json.dumps(val)[:256]
                else:
                    safe_result[k] = str(val)[:256]

    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=f"solana.{tool}",
            enhanced_prompt=json.dumps(safe_params, separators=(",", ":"))[:512],
            output_text=json.dumps(safe_result, separators=(",", ":"))[:1024],
            tier=tier, model="solana_token_2022",
            scope=scope,
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_action=f"solana.{tool}",
            done_flag=(rc == 0),
            rc=rc,
        ) or ""
    except Exception as e:
        sys.stderr.write(
            f"warn: solana crystal log failed: {type(e).__name__}: {e}\n"
        )
        return ""


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class SolanaMCPConnector(ThirdPartyConnector):
    """Solana on-chain connector. Shells out to `solana`, `spl-token`,
    and `metaplex` CLIs. Implements the mutating-meme-coin pattern via
    Token-2022 + on-chain SVG metadata.
    """

    SERVICE = "solana"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name="solana_default",
                action="on_chain_rail",
            )
        super().__init__(config)
        self._keypair_path: str = ""
        self._rpc_url: str = ""
        self._network: str = ""
        self._env: Dict[str, str] = {}
        self._metadata_program: str = ""
        self._token_2022_program: str = ""
        self._connected = False

    # ---- lifecycle -----------------------------------------------------

    def connect(self) -> bool:
        """Verify solana CLI is available + keypair path resolves.

        Returns False (graceful) if the CLI is absent or
        SOLANA_KEYPAIR_PATH is unset. send() then emits
        SendResult(success=False, error='solana_cli_not_configured').
        """
        self._env = _load_env_dict()
        self._rpc_url = _resolve_rpc_url(self._env)
        self._network = _resolve_network(self._env)
        self._metadata_program = _resolve_metadata_program(self._env)
        self._token_2022_program = _resolve_token_2022_program(self._env)
        self._keypair_path = _resolve_keypair_path(self._env)

        if shutil.which("solana") is None:
            self._connected = False
            return False
        if not self._keypair_path:
            self._connected = False
            return False
        # Smoke: `solana config get` works without --url; cheap + offline.
        rc, _ = _run_cli("solana", ["config", "get"], timeout=10)
        self._connected = (rc == 0)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    # ---- main dispatch -------------------------------------------------

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        """recipient = tool name; message = JSON args (preferred) or empty."""
        if not self._connected and not self.connect():
            return SendResult(
                success=False, crystal_id="",
                service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.time(),
                error="solana_cli_not_configured",
                metadata={
                    "network": self._network,
                    "rpc_url": self._rpc_url,
                    "has_keypair": bool(self._keypair_path),
                    "has_cli": shutil.which("solana") is not None,
                },
            )

        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"message": message}
        params.update(kwargs)

        # Mainnet write-gate. Solana mainnet cluster moniker = 'mainnet-beta'.
        if self._network == "mainnet-beta" and recipient in _WRITE_TOOLS:
            if not bool(params.get("confirm", False)):
                return SendResult(
                    success=False, crystal_id="",
                    service=self.SERVICE, recipient=recipient,
                    message_preview="", timestamp=time.time(),
                    error="mainnet_write_requires_confirm",
                    metadata={
                        "network": self._network,
                        "hint": (
                            "pass confirm=true (or {\"confirm\":true} in "
                            "message) to authorize"
                        ),
                    },
                )

        t0 = time.time()
        if recipient == "query_balance":
            rc, body = self._query_balance(params)
        elif recipient == "query_spl_balance":
            rc, body = self._query_spl_balance(params)
        elif recipient == "mint_token_2022":
            rc, body = self._mint_token_2022(params)
        elif recipient == "update_token_svg":
            rc, body = self._update_token_svg(params)
        elif recipient == "transfer":
            rc, body = self._transfer(params)
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
                str(body.get("signature", ""))
                or str(body.get("mint", ""))
                or str(body.get("address", ""))
                or str(body.get("uiAmountString", ""))
                or str(body.get("value", ""))
                or body.get("_error", "")
                or str(body)[:200]
            )
            md = {
                "network": self._network,
                "rpc_url": self._rpc_url,
                "latency_ms": latency_ms,
                "rc": rc,
                "signature": str(
                    body.get("signature", "")
                    or body.get("transactionSignature", "")
                ),
                "mint": str(body.get("mint", "")),
                "address": str(body.get("address", "")),
                "status": str(body.get("status", "")),
            }
            # Balance lookups surface ui amount / lamports value.
            if recipient == "query_balance" and success:
                v = body.get("value")
                if v is not None:
                    md["lamports"] = str(v)
            if recipient == "query_spl_balance" and success:
                v = (
                    body.get("uiAmountString")
                    or body.get("uiAmount")
                    or body.get("amount")
                    or body.get("balance")
                )
                if v is not None:
                    md["spl_balance"] = str(v)
        else:
            preview = str(body)[:200]
            md = {
                "network": self._network,
                "rpc_url": self._rpc_url,
                "latency_ms": latency_ms,
                "rc": rc,
            }

        return SendResult(
            success=success, service=self.SERVICE, recipient=recipient,
            message_preview=preview[:200], timestamp=time.time(),
            crystal_id=crystal_id,
            error="" if success else (
                body.get("_error", "") if isinstance(body, dict) else f"rc_{rc}"
            ),
            metadata=md,
        )

    def history(self, limit: int = 20) -> list:
        log_path = Path.home() / ".cc" / "third_party_logs" / "solana_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- Tool implementations -----------------------------------------

    def _query_balance(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        addr = (p.get("addr") or p.get("address") or "").strip()
        if not addr:
            return 1, {"_error": "missing addr"}
        argv = ["balance", addr, "--output", "json"]
        rc, body = _run_solana(argv, self._rpc_url, timeout=30)
        if rc != 0:
            return rc, body
        # `solana balance --output json` shape: {"value": <lamports>} on newer
        # CLIs; older CLIs emit "0.000123 SOL" as plain text → _raw fallback.
        if isinstance(body, dict):
            body.setdefault("address", addr)
        return rc, body

    def _query_spl_balance(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        addr = (p.get("addr") or p.get("address") or p.get("owner") or "").strip()
        mint = (p.get("mint") or "").strip()
        if not mint:
            return 1, {"_error": "missing mint"}
        argv: List[str] = ["balance", mint, "--output", "json"]
        if addr:
            argv += ["--owner", addr]
        rc, body = _run_spl(argv, self._rpc_url, self._keypair_path, timeout=30)
        if rc != 0:
            return rc, body
        if isinstance(body, dict):
            body.setdefault("mint", mint)
            if addr:
                body.setdefault("owner", addr)
        return rc, body

    def _mint_token_2022(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        """Multi-step Token-2022 mint with on-chain SVG metadata.

        Steps:
          1. spl-token create-token --program-id <Token-2022> --decimals <n>
          2. spl-token create-account <mint>
          3. spl-token mint <mint> <initial_supply>
          4. metaplex token-metadata create --mint <mint> --name <name>
                 --symbol <symbol> --uri data:image/svg+xml;base64,<svg>

        Returns combined dict: {mint, account, mint_signature,
        metadata_signature, name, symbol, decimals, initial_supply,
        svg_byte_len}.
        """
        name = (p.get("name") or "").strip()
        symbol = (p.get("symbol") or "").strip()
        decimals_raw = p.get("decimals")
        supply_raw = p.get("initial_supply")
        svg = p.get("svg_string") or ""
        if not name or not symbol:
            return 1, {"_error": "missing name / symbol"}
        if decimals_raw is None or supply_raw is None:
            return 1, {"_error": "missing decimals / initial_supply"}
        try:
            decimals = int(decimals_raw)
            initial_supply = int(supply_raw)
        except (TypeError, ValueError):
            return 1, {"_error": f"bad decimals/initial_supply: {decimals_raw!r}/{supply_raw!r}"}
        if not isinstance(svg, str) or not svg.strip():
            return 1, {"_error": "missing svg_string (the mutating coin pattern requires an initial SVG)"}

        out: Dict[str, Any] = {
            "name": name, "symbol": symbol,
            "decimals": decimals, "initial_supply": initial_supply,
            "svg_byte_len": len(svg.encode("utf-8")),
        }

        # Step 1: create Token-2022 mint.
        rc, body = _run_spl(
            ["create-token",
             "--program-id", self._token_2022_program,
             "--decimals", str(decimals),
             "--output", "json"],
            self._rpc_url, self._keypair_path,
            timeout=DEFAULT_TIMEOUT_S,
        )
        if rc != 0:
            return rc, {"_error": f"create-token: {body.get('_error', body)}", **out}
        mint = (
            body.get("commandOutput", {}).get("address")
            if isinstance(body.get("commandOutput"), dict) else None
        ) or body.get("address") or body.get("mint") or ""
        if not mint:
            return 1, {"_error": "could not parse mint address from create-token output",
                       "_raw": body, **out}
        out["mint"] = str(mint)
        out["mint_creation"] = body

        # Step 2: create associated token account for fee-payer / owner.
        rc, body = _run_spl(
            ["create-account", str(mint), "--output", "json"],
            self._rpc_url, self._keypair_path,
            timeout=DEFAULT_TIMEOUT_S,
        )
        if rc != 0:
            return rc, {"_error": f"create-account: {body.get('_error', body)}", **out}
        account = (
            body.get("commandOutput", {}).get("address")
            if isinstance(body.get("commandOutput"), dict) else None
        ) or body.get("address") or body.get("account") or ""
        out["account"] = str(account)

        # Step 3: mint initial supply.
        rc, body = _run_spl(
            ["mint", str(mint), str(initial_supply), "--output", "json"],
            self._rpc_url, self._keypair_path,
            timeout=DEFAULT_TIMEOUT_S,
        )
        if rc != 0:
            return rc, {"_error": f"mint: {body.get('_error', body)}", **out}
        out["mint_signature"] = str(
            body.get("signature", "") or body.get("transactionSignature", "")
        )

        # Step 4: write Metaplex token metadata pointing at inline SVG.
        data_uri = _svg_to_data_uri(svg)
        rc, body = _run_metaplex(
            ["token-metadata", "create",
             "--mint", str(mint),
             "--name", name,
             "--symbol", symbol,
             "--uri", data_uri,
             "--program", self._metadata_program],
            self._rpc_url, self._keypair_path,
            timeout=DEFAULT_TIMEOUT_S,
        )
        if rc != 0:
            return rc, {"_error": f"metadata create: {body.get('_error', body)}", **out}
        out["metadata_signature"] = str(
            body.get("signature", "") or body.get("transactionSignature", "")
        )
        return 0, out

    def _update_token_svg(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        """THE mutating meme-coin pattern.

        Rewrites the on-chain SVG art for an existing Token-2022 mint by
        updating its Metaplex token-metadata --uri to a fresh
        data:image/svg+xml;base64,… payload. Crystal-anchored under
        scope='svg_mutation' so every re-skin tx is walkable from the
        InferenceRecord chain.
        """
        mint = (p.get("mint") or "").strip()
        svg = p.get("new_svg_string") or p.get("svg_string") or ""
        if not mint:
            return 1, {"_error": "missing mint"}
        if not isinstance(svg, str) or not svg.strip():
            return 1, {"_error": "missing new_svg_string"}
        data_uri = _svg_to_data_uri(svg)
        argv = [
            "token-metadata", "update",
            "--mint", mint,
            "--uri", data_uri,
            "--program", self._metadata_program,
        ]
        rc, body = _run_metaplex(
            argv, self._rpc_url, self._keypair_path,
            timeout=DEFAULT_TIMEOUT_S,
        )
        if isinstance(body, dict):
            body.setdefault("mint", mint)
            body["svg_byte_len"] = len(svg.encode("utf-8"))
        return rc, body

    def _transfer(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        mint = (p.get("mint") or "").strip()
        to = (p.get("to") or p.get("recipient") or "").strip()
        amount = p.get("amount")
        if not mint or not to or amount is None:
            return 1, {"_error": "missing mint / to / amount"}
        try:
            amount_str = str(amount)
            # Accept int or decimal-string; spl-token transfer takes ui-amount.
        except Exception:
            return 1, {"_error": f"bad amount: {amount!r}"}
        argv = [
            "transfer", mint, amount_str, to,
            "--allow-unfunded-recipient",
            "--fund-recipient",
            "--output", "json",
        ]
        rc, body = _run_spl(
            argv, self._rpc_url, self._keypair_path,
            timeout=DEFAULT_TIMEOUT_S,
        )
        if isinstance(body, dict):
            body.setdefault("mint", mint)
        return rc, body

    def _tx_status(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        sig = (p.get("signature") or p.get("sig") or p.get("digest") or "").strip()
        if not sig:
            return 1, {"_error": "missing signature"}
        argv = ["confirm", sig, "--output", "json"]
        return _run_solana(argv, self._rpc_url, timeout=30)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="solana_mcp — Solana on-chain connector smoke"
    )
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect")

    p_bal = sub.add_parser("balance", help="query SOL balance for an address")
    p_bal.add_argument("addr")

    p_spl = sub.add_parser(
        "spl-balance", help="query SPL/Token-2022 balance for an owner+mint",
    )
    p_spl.add_argument("addr")
    p_spl.add_argument("mint")

    p_tx = sub.add_parser("tx", help="fetch transaction status by signature")
    p_tx.add_argument("signature")

    p_mint = sub.add_parser(
        "mint", help="mint_token_2022 with inline SVG metadata",
    )
    p_mint.add_argument("--name", required=True)
    p_mint.add_argument("--symbol", required=True)
    p_mint.add_argument("--decimals", type=int, default=0)
    p_mint.add_argument("--supply", type=int, default=1)
    p_mint.add_argument(
        "--svg", default='<svg xmlns="http://www.w3.org/2000/svg"/>',
    )
    p_mint.add_argument(
        "--confirm", action="store_true", help="required on mainnet-beta",
    )

    p_mut = sub.add_parser(
        "mutate", help="update_token_svg — the mutating meme-coin pattern",
    )
    p_mut.add_argument("mint")
    p_mut.add_argument("svg_path", help="path to new SVG file on disk")
    p_mut.add_argument(
        "--confirm", action="store_true", help="required on mainnet-beta",
    )

    sub.add_parser("providers", help="list expected tools")

    args = ap.parse_args()
    c = SolanaMCPConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({
            "connected": ok,
            "network": c._network,
            "rpc_url": c._rpc_url,
            "has_keypair": bool(c._keypair_path),
            "metadata_program": c._metadata_program,
            "token_2022_program": c._token_2022_program,
        }, indent=2))

    elif args.cmd == "balance":
        c.connect()
        r = c.send("query_balance", json.dumps({"addr": args.addr}))
        print(json.dumps({
            "success": r.success,
            "preview": r.message_preview,
            "network": r.metadata.get("network", ""),
            "lamports": r.metadata.get("lamports", ""),
            "crystal": (r.crystal_id or "")[:24],
            "error": r.error,
        }, indent=2))

    elif args.cmd == "spl-balance":
        c.connect()
        r = c.send(
            "query_spl_balance",
            json.dumps({"addr": args.addr, "mint": args.mint}),
        )
        print(json.dumps({
            "success": r.success,
            "spl_balance": r.metadata.get("spl_balance", ""),
            "mint": r.metadata.get("mint", ""),
            "crystal": (r.crystal_id or "")[:24],
            "error": r.error,
        }, indent=2))

    elif args.cmd == "tx":
        c.connect()
        r = c.send("tx_status", json.dumps({"signature": args.signature}))
        print(json.dumps({
            "success": r.success,
            "signature": r.metadata.get("signature", ""),
            "status": r.metadata.get("status", ""),
            "crystal": (r.crystal_id or "")[:24],
            "error": r.error,
        }, indent=2))

    elif args.cmd == "mint":
        c.connect()
        msg: Dict[str, Any] = {
            "name": args.name,
            "symbol": args.symbol,
            "decimals": args.decimals,
            "initial_supply": args.supply,
            "svg_string": args.svg,
        }
        if args.confirm:
            msg["confirm"] = True
        r = c.send("mint_token_2022", json.dumps(msg))
        print(json.dumps({
            "success": r.success,
            "mint": r.metadata.get("mint", ""),
            "signature": r.metadata.get("signature", ""),
            "crystal": (r.crystal_id or "")[:24],
            "error": r.error,
        }, indent=2))

    elif args.cmd == "mutate":
        c.connect()
        try:
            svg = Path(args.svg_path).read_text(encoding="utf-8")
        except Exception as e:
            print(json.dumps({"error": f"read_svg_failed: {type(e).__name__}: {e}"}))
            return
        msg = {"mint": args.mint, "new_svg_string": svg}
        if args.confirm:
            msg["confirm"] = True
        r = c.send("update_token_svg", json.dumps(msg))
        print(json.dumps({
            "success": r.success,
            "mint": r.metadata.get("mint", ""),
            "signature": r.metadata.get("signature", ""),
            "crystal": (r.crystal_id or "")[:24],
            "error": r.error,
        }, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({
            "expected_tools": list(EXPECTED_TOOLS),
            "default_token_2022_program": DEFAULT_TOKEN_2022_PROGRAM,
            "default_metadata_program": DEFAULT_METADATA_PROGRAM,
            "default_rpc_url": DEFAULT_RPC_URL,
            "write_tools": sorted(_WRITE_TOOLS),
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
