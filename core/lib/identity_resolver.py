#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        identity_resolver
# role:        SIGNAL_FUSION · AUDIENCE_PERSONA_VECTOR_EMITTER
# tier:        L0
# substrate:   the morphing-game runtime; takes a viewer's bearer token + any
#              available platform tokens and emits an AudiencePersonaVector
#              that morph_game_runtime uses to render the right scene variant.
# storage:     ~/.cc/persona_cache/<persona_id>.json (24h TTL) + crystal chain
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - morph_game_runtime (resolves the viewer once per session)
#   - any future surface that wants to know "who is looking at this"
# outbound:
#   - core/lib/freetier_gate.verify_token   (primary identity verification)
#   - core/lib/third_party/facebook_friends_graph.FacebookFriendsGraphConnector
#   - core/lib/social_graph_persistence.get_friends
#   - core/lib/third_party/sui_mcp.SuiMCPConnector::query_balance
#   - core/lib/third_party/solana_mcp.SolanaMCPConnector::query_balance
#   - core/lib/third_party/twitter.TwitterConnector::get_user
#   - core/lib/inference_logger.InferenceLogger.log (tier='identity_resolution')
# substrate touch:
#   - reads: every connector listed above (best-effort, never blocking >2s)
#   - writes: ~/.cc/persona_cache/<persona_id>.json + crystal chain
# ----------------------------------------------------------------------------
# THE 32-D PERSONA VECTOR — slot layout
# ----------------------------------------------------------------------------
#   [0..3]   tier one-hot              (freetier, trolln_tier, premium, unknown)
#   [4]      log10(friends_count + 1)
#   [5]      log10(sui_balance_usdc + 1)
#   [6]      friends_consent (0/1)
#   [7]      has_x (0/1)
#   [8]      has_snap (0/1)
#   [9]      has_fb (0/1)
#   [10]     log10(sui_nft_count + 1)
#   [11]     log10(solana_balance_sol + 1)
#   [12]     log10(solana_spl_count + 1)
#   [13]     log10(x_follower_count + 1)
#   [14]     has_sui_addr (0/1)
#   [15]     has_solana_addr (0/1)
#   [16..31] reserved (zero-padded)
# ----------------------------------------------------------------------------
# ROLE-INFERENCE TABLE (evaluated in order; first match wins)
# ----------------------------------------------------------------------------
#   sui_nft_count > 5 AND x_follower_count > 1000           -> 'gamer'
#   fb_player_id non-empty AND friends_count > 30           -> 'buyer'
#   x_handle in DEVELOPER_HANDLES OR claims.tier='premium'  -> 'developer'
#   claims.tier='trolln_tier' AND sui_balance_usdc > 100    -> 'realtor'
#   default                                                 -> 'unknown'
# ============================================================================
"""identity_resolver.py — the signal-fusion layer.

Resolves a viewer's bearer token + any platform tokens (Sui, Solana, X,
Snap, Facebook) into an AudiencePersonaVector that the morph_game_runtime
consumes to render the right scene variant per viewer.

Every connector call is lazy-imported and wrapped in try/except — if a key
or library is missing, that slot stays empty/zero and the rest of the
resolution proceeds. Never raises from resolve().

Persona is content-addressed by sha256(user_id + accepted_terms_hash +
first_seen_ts) so repeat resolutions for the same user collide on the
cache key. (stdlib has no blake3; sha256 is the contract.)

CLI:
    python3 core/lib/identity_resolver.py resolve <token>
    python3 core/lib/identity_resolver.py infer-role <signals_json>
    python3 core/lib/identity_resolver.py persona-stats
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "third_party"))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PERSONA_VECTOR_DIM = 32
PERSONA_CACHE_TTL_SECONDS = 24 * 3600

PERSONA_CACHE_DIR = Path(
    os.environ.get(
        "MYSPACE_PERSONA_CACHE",
        str(Path.home() / ".cc" / "persona_cache"),
    )
)

# Per-platform probe deadline. The CLAUDE.md contract says "never block
# longer than 2s on any platform probe."
PROBE_DEADLINE_SECONDS = 2.0

# Friendly developer/owner allowlist — promotes inferred_role='developer'.
DEVELOPER_HANDLES = frozenset({
    "zero2onez", "tomlee", "tomlee3d", "gentlyos",
})

# Tier one-hot index map (slots [0..3] of the persona vector).
_TIER_INDEX = {
    "freetier":    0,
    "trolln_tier": 1,
    "premium":     2,
    "unknown":     3,
}


# ---------------------------------------------------------------------------
# Dataclasses (the contract)
# ---------------------------------------------------------------------------

@dataclass
class AudiencePersonaVector:
    persona_id: str             # sha256 of (user_id + accepted_terms_hash + first_seen_ts)
    tier: str                   # freetier | trolln_tier | premium | unknown
    friends_count: int = 0
    friends_consent: bool = False
    sui_balance_usdc: float = 0.0
    sui_nft_count: int = 0
    solana_balance_sol: float = 0.0
    solana_spl_count: int = 0
    x_handle: str = ""
    x_follower_count: int = 0
    snap_external_id: str = ""
    fb_player_id: str = ""
    persona_vector: List[float] = field(default_factory=list)
    inferred_role: str = "unknown"
    crystal: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IdentitySignalBundle:
    raw_token: str
    claims: Any = None             # TokenClaims | None — typed Any so we don't hard-import
    sui_addr: str = ""
    solana_addr: str = ""
    x_user_id: str = ""
    snap_external_id: str = ""
    fb_player_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "raw_token_prefix": self.raw_token[:16],
            "sui_addr": self.sui_addr,
            "solana_addr": self.solana_addr,
            "x_user_id": self.x_user_id,
            "snap_external_id": self.snap_external_id,
            "fb_player_id": self.fb_player_id,
        }
        if self.claims is not None:
            try:
                d["claims"] = self.claims.to_dict() if hasattr(self.claims, "to_dict") else dict(vars(self.claims))
            except Exception:
                d["claims"] = None
        else:
            d["claims"] = None
        return d


# ---------------------------------------------------------------------------
# Probe-deadline guard (POSIX signal-based; soft fallback elsewhere)
# ---------------------------------------------------------------------------

class _ProbeTimeout(Exception):
    pass


@contextmanager
def _deadline(seconds: float = PROBE_DEADLINE_SECONDS):
    """Best-effort wall-clock guard. Works on POSIX main-thread only; on
    Windows or off-main-thread we simply skip the alarm and rely on the
    inner call's own timeouts. Raising _ProbeTimeout is caught upstream.
    """
    is_posix = hasattr(signal, "SIGALRM")
    is_main = False
    try:
        import threading
        is_main = threading.current_thread() is threading.main_thread()
    except Exception:
        is_main = True

    if not (is_posix and is_main):
        yield
        return

    def _handler(signum, frame):  # noqa: ARG001
        raise _ProbeTimeout(f"probe exceeded {seconds:.1f}s")

    prev = signal.signal(signal.SIGALRM, _handler)
    try:
        # setitimer takes float seconds; allow sub-second deadlines.
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        signal.signal(signal.SIGALRM, prev)


def _safe_probe(fn, default=None):
    """Run ``fn()`` under deadline + try/except. Returns ``default`` on
    any failure. This is the only way platform probes touch the network."""
    try:
        with _deadline(PROBE_DEADLINE_SECONDS):
            return fn()
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Token verification (the primary identity)
# ---------------------------------------------------------------------------

def _verify(token: str):
    """Lazy-import freetier_gate.verify_token. Returns TokenClaims | None."""
    try:
        from freetier_gate import verify_token  # type: ignore
        return verify_token(token, expected_domain=None)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Signal gathering — every connector wrapped, never raises
# ---------------------------------------------------------------------------

def _gather_friends(player_id: str) -> int:
    """Local friend cache lookup. Cheap, no network."""
    if not player_id:
        return 0

    def _go() -> int:
        from social_graph_persistence import get_friends  # type: ignore
        rows = get_friends(player_id) or []
        return len(rows)

    return _safe_probe(_go, default=0) or 0


def _gather_fb_consent(fb_player_id: str, raw_token_present: bool) -> bool:
    """Did the user grant user_friends on Facebook? Best-effort.

    We treat ``claims.friends_consent`` (already on the token) as authoritative
    when present; the FB connector is only probed if the token was actually
    issued with the consent flag, so we don't waste a probe on no-go cases.
    """
    if not (fb_player_id and raw_token_present):
        return False

    def _go() -> bool:
        from facebook_friends_graph import FacebookFriendsGraphConnector  # type: ignore
        c = FacebookFriendsGraphConnector()
        # The connector exposes a `_check_permissions` private helper; we
        # don't call private API from outside, so we just return True on
        # connect-success — the token already carried friends_consent.
        ok = False
        try:
            ok = bool(c.connect())
        except Exception:
            ok = False
        try:
            c.disconnect()
        except Exception:
            pass
        return ok

    return bool(_safe_probe(_go, default=False))


def _gather_sui(sui_addr: str) -> Dict[str, Any]:
    """Sui USDC balance + NFT count. Returns {'usdc': float, 'nft_count': int}."""
    out = {"usdc": 0.0, "nft_count": 0}
    if not sui_addr:
        return out

    def _go() -> Dict[str, Any]:
        from sui_mcp import SuiMCPConnector  # type: ignore
        c = SuiMCPConnector()
        r = {}
        try:
            res = c.send("query_balance", json.dumps({"addr": sui_addr}))
            if getattr(res, "success", False):
                meta = getattr(res, "metadata", None) or {}
                # metadata is the parsed body when success.
                total = 0.0
                try:
                    total = float(meta.get("totalBalance", "0") or "0")
                except Exception:
                    total = 0.0
                # USDC is 6-decimal on Sui; convert from MIST-style integer.
                r["usdc"] = total / 1_000_000.0 if total > 1_000 else total
                r["nft_count"] = int(meta.get("coinObjectCount", 0) or 0)
        finally:
            try:
                c.disconnect()
            except Exception:
                pass
        return r

    res = _safe_probe(_go, default=None)
    if isinstance(res, dict):
        out.update({k: v for k, v in res.items() if k in out})
    return out


def _gather_solana(solana_addr: str) -> Dict[str, Any]:
    """Solana SOL balance + Token-2022 holding count.
    Returns {'sol': float, 'spl_count': int}."""
    out = {"sol": 0.0, "spl_count": 0}
    if not solana_addr:
        return out

    def _go() -> Dict[str, Any]:
        # Agent D may not have landed yet; lazy + tolerant.
        from solana_mcp import SolanaMCPConnector  # type: ignore
        c = SolanaMCPConnector()
        r = {}
        try:
            res = c.send("query_balance", json.dumps({"addr": solana_addr}))
            if getattr(res, "success", False):
                meta = getattr(res, "metadata", None) or {}
                try:
                    lamports = float(meta.get("lamports", 0) or 0)
                    r["sol"] = lamports / 1_000_000_000.0
                except Exception:
                    r["sol"] = 0.0
                r["spl_count"] = int(meta.get("spl_count", 0) or 0)
        finally:
            try:
                c.disconnect()
            except Exception:
                pass
        return r

    res = _safe_probe(_go, default=None)
    if isinstance(res, dict):
        out.update({k: v for k, v in res.items() if k in out})
    return out


def _gather_x(x_user_id: str) -> Dict[str, Any]:
    """X handle + follower count via TwitterConnector.get_user.
    `x_user_id` may be a numeric id or a handle — connector takes a handle."""
    out = {"handle": "", "followers": 0}
    if not x_user_id:
        return out

    def _go() -> Dict[str, Any]:
        from twitter import TwitterConnector  # type: ignore
        c = TwitterConnector()
        r = {}
        try:
            user = c.get_user(x_user_id) or {}
            if user.get("success"):
                r["handle"] = str(user.get("username", "") or "")
                pm = user.get("public_metrics") or {}
                r["followers"] = int(pm.get("followers_count", 0) or 0)
        finally:
            try:
                c.disconnect()
            except Exception:
                pass
        return r

    res = _safe_probe(_go, default=None)
    if isinstance(res, dict):
        out.update({k: v for k, v in res.items() if k in out})
    return out


# ---------------------------------------------------------------------------
# Role inference (cheap classifier, evaluated in order)
# ---------------------------------------------------------------------------

def infer_role(signals: IdentitySignalBundle, friends_count: int,
                 wallet_balances: Dict[str, Any]) -> str:
    """Cheap classifier based on signal patterns. First match wins.

    ``wallet_balances`` schema:
        {
          'sui_balance_usdc': float, 'sui_nft_count': int,
          'solana_balance_sol': float, 'solana_spl_count': int,
          'x_handle': str, 'x_follower_count': int,
        }
    """
    sui_nft = int(wallet_balances.get("sui_nft_count", 0) or 0)
    sui_usdc = float(wallet_balances.get("sui_balance_usdc", 0.0) or 0.0)
    x_followers = int(wallet_balances.get("x_follower_count", 0) or 0)
    x_handle = (wallet_balances.get("x_handle") or "").lower().lstrip("@")

    tier = ""
    try:
        if signals.claims is not None:
            tier = getattr(signals.claims, "tier", "") or ""
    except Exception:
        tier = ""

    # Rule 1: high-NFT + high-following → gamer
    if sui_nft > 5 and x_followers > 1000:
        return "gamer"
    # Rule 2: FB-anchored + decent social graph → buyer
    if signals.fb_player_id and friends_count > 30:
        return "buyer"
    # Rule 3: known developer handle OR premium tier → developer
    if (x_handle and x_handle in DEVELOPER_HANDLES) or tier == "premium":
        return "developer"
    # Rule 4: TROLLN tier + USDC liquidity → realtor
    if tier == "trolln_tier" and sui_usdc > 100.0:
        return "realtor"
    return "unknown"


# ---------------------------------------------------------------------------
# Persona vector (deterministic 32-d float)
# ---------------------------------------------------------------------------

def compute_persona_vector(signals: IdentitySignalBundle,
                              extras: Optional[Dict[str, Any]] = None) -> List[float]:
    """Build the 32-d persona vector. Slot layout documented at module head.

    ``extras`` carries gathered numeric features so we don't re-probe:
        friends_count, sui_balance_usdc, sui_nft_count,
        solana_balance_sol, solana_spl_count,
        x_handle, x_follower_count, snap_external_id
    """
    extras = extras or {}
    v = [0.0] * PERSONA_VECTOR_DIM

    # Slots [0..3]: tier one-hot
    tier = "unknown"
    try:
        if signals.claims is not None:
            tier = getattr(signals.claims, "tier", "") or "unknown"
    except Exception:
        tier = "unknown"
    idx = _TIER_INDEX.get(tier, _TIER_INDEX["unknown"])
    v[idx] = 1.0

    # Numerics
    friends_count = int(extras.get("friends_count", 0) or 0)
    sui_usdc = float(extras.get("sui_balance_usdc", 0.0) or 0.0)
    sui_nft = int(extras.get("sui_nft_count", 0) or 0)
    solana_sol = float(extras.get("solana_balance_sol", 0.0) or 0.0)
    solana_spl = int(extras.get("solana_spl_count", 0) or 0)
    x_followers = int(extras.get("x_follower_count", 0) or 0)
    x_handle = extras.get("x_handle") or ""

    friends_consent = False
    try:
        if signals.claims is not None:
            friends_consent = bool(getattr(signals.claims, "friends_consent", False))
    except Exception:
        friends_consent = False

    def _log1p10(x: float) -> float:
        try:
            return math.log10(max(float(x), 0.0) + 1.0)
        except Exception:
            return 0.0

    v[4]  = _log1p10(friends_count)
    v[5]  = _log1p10(sui_usdc)
    v[6]  = 1.0 if friends_consent else 0.0
    v[7]  = 1.0 if x_handle else 0.0
    v[8]  = 1.0 if signals.snap_external_id else 0.0
    v[9]  = 1.0 if signals.fb_player_id else 0.0
    v[10] = _log1p10(sui_nft)
    v[11] = _log1p10(solana_sol)
    v[12] = _log1p10(solana_spl)
    v[13] = _log1p10(x_followers)
    v[14] = 1.0 if signals.sui_addr else 0.0
    v[15] = 1.0 if signals.solana_addr else 0.0
    # Slots [16..31] reserved/zero-padded.
    return v


# ---------------------------------------------------------------------------
# Persona cache (sqlite-less — flat JSON, 24h TTL)
# ---------------------------------------------------------------------------

def _cache_path(persona_id: str) -> Path:
    return PERSONA_CACHE_DIR / f"{persona_id}.json"


def _cache_read(persona_id: str) -> Optional[Dict[str, Any]]:
    p = _cache_path(persona_id)
    try:
        if not p.exists():
            return None
        if (time.time() - p.stat().st_mtime) > PERSONA_CACHE_TTL_SECONDS:
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_write(persona: AudiencePersonaVector) -> None:
    try:
        PERSONA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _cache_path(persona.persona_id)
        p.write_text(json.dumps(persona.to_dict(), separators=(",", ":")),
                       encoding="utf-8")
    except Exception:
        pass


def _persona_id(user_id: str, accepted_terms_hash: str, first_seen_ts: int) -> str:
    """Deterministic content-addressed persona id. stdlib has no blake3,
    so sha256 is the contract — same string in, same id out."""
    payload = f"{user_id}|{accepted_terms_hash}|{first_seen_ts}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Crystal anchor
# ---------------------------------------------------------------------------

def _crystal_anchor(token: str, persona_id: str) -> str:
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=(token or "")[:16],
            enhanced_prompt=f"persona_id={persona_id[:16]}",
            output_text=persona_id,
            tier="identity_resolution",
            model="identity_resolver",
            scope="persona_computed",
            tokens_in=0, tokens_out=0, latency_ms=0,
            source_action="resolve",
            done_flag=True, rc=0,
        ) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Public API — resolve()
# ---------------------------------------------------------------------------

def resolve(token: str, extra_signals: Optional[Dict[str, Any]] = None) -> AudiencePersonaVector:
    """Verify token, gather all platform signals (best-effort, never blocking
    longer than 2s/probe), compute persona vector + inferred_role, crystal-anchor,
    return AudiencePersonaVector.

    ``extra_signals`` (optional) supplies platform addresses/handles that the
    bearer token does not carry directly:
        sui_addr, solana_addr, x_user_id, snap_external_id, fb_player_id

    NEVER RAISES.
    """
    extra_signals = extra_signals or {}
    claims = _verify(token or "")

    # Build the signal bundle. The token's user_id IS the canonical
    # fb_player_id in the freetier scheme, so we default to it unless
    # caller overrode explicitly.
    bundle = IdentitySignalBundle(
        raw_token=token or "",
        claims=claims,
        sui_addr=str(extra_signals.get("sui_addr", "") or ""),
        solana_addr=str(extra_signals.get("solana_addr", "") or ""),
        x_user_id=str(extra_signals.get("x_user_id", "") or ""),
        snap_external_id=str(extra_signals.get("snap_external_id", "") or ""),
        fb_player_id=str(extra_signals.get("fb_player_id", "") or
                          (claims.user_id if claims else "")),
    )

    # Best-effort gather. Each call is independently safe.
    friends_count = _gather_friends(bundle.fb_player_id)
    sui = _gather_sui(bundle.sui_addr)
    sol = _gather_solana(bundle.solana_addr)
    x = _gather_x(bundle.x_user_id)
    friends_consent_from_fb = _gather_fb_consent(
        bundle.fb_player_id,
        bool(claims and getattr(claims, "friends_consent", False)),
    )

    # The token's `friends_consent` is authoritative when set; the FB probe
    # is corroboration only. Either-true wins.
    friends_consent = bool(
        (claims and getattr(claims, "friends_consent", False))
        or friends_consent_from_fb
    )

    extras = {
        "friends_count": friends_count,
        "sui_balance_usdc": sui.get("usdc", 0.0),
        "sui_nft_count": sui.get("nft_count", 0),
        "solana_balance_sol": sol.get("sol", 0.0),
        "solana_spl_count": sol.get("spl_count", 0),
        "x_handle": x.get("handle", ""),
        "x_follower_count": x.get("followers", 0),
        "snap_external_id": bundle.snap_external_id,
    }

    vector = compute_persona_vector(bundle, extras=extras)
    role = infer_role(bundle, friends_count, extras)

    # Persona id: deterministic on (user_id, accepted_terms_hash, first_seen_ts).
    user_id = claims.user_id if claims else (token[:16] if token else "anon")
    terms_hash = (claims.accepted_terms_hash if claims else "") or ""
    # first_seen_ts: prefer the token's `iat`, falling back to now() — this
    # makes the persona_id stable across the token's lifetime.
    first_seen = int(getattr(claims, "iat", 0) or 0) or int(time.time())
    pid = _persona_id(user_id, terms_hash, first_seen)

    tier_str = (getattr(claims, "tier", "") if claims else "") or "unknown"

    persona = AudiencePersonaVector(
        persona_id=pid,
        tier=tier_str,
        friends_count=friends_count,
        friends_consent=friends_consent,
        sui_balance_usdc=float(extras["sui_balance_usdc"]),
        sui_nft_count=int(extras["sui_nft_count"]),
        solana_balance_sol=float(extras["solana_balance_sol"]),
        solana_spl_count=int(extras["solana_spl_count"]),
        x_handle=str(extras["x_handle"]),
        x_follower_count=int(extras["x_follower_count"]),
        snap_external_id=bundle.snap_external_id,
        fb_player_id=bundle.fb_player_id,
        persona_vector=vector,
        inferred_role=role,
        crystal="",
    )

    # Crystal anchor + cache write are both best-effort.
    persona.crystal = _crystal_anchor(token or "", pid)
    _cache_write(persona)
    return persona


# ---------------------------------------------------------------------------
# Persona stats — count cached personas by inferred_role
# ---------------------------------------------------------------------------

def persona_stats() -> Dict[str, Any]:
    """Walk the persona cache and bucket by inferred_role."""
    out: Dict[str, Any] = {"total": 0, "by_role": {}, "by_tier": {}, "stale": 0}
    try:
        PERSONA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        return out
    now = time.time()
    for p in PERSONA_CACHE_DIR.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out["total"] += 1
        role = str(doc.get("inferred_role", "unknown"))
        tier = str(doc.get("tier", "unknown"))
        out["by_role"][role] = out["by_role"].get(role, 0) + 1
        out["by_tier"][tier] = out["by_tier"].get(tier, 0) + 1
        try:
            if (now - p.stat().st_mtime) > PERSONA_CACHE_TTL_SECONDS:
                out["stale"] += 1
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_resolve(token: str) -> int:
    persona = resolve(token)
    print(json.dumps(persona.to_dict(), indent=2, default=str))
    return 0


def _cli_infer_role(signals_json: str) -> int:
    try:
        doc = json.loads(signals_json)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"bad json: {e}"}, indent=2))
        return 2

    # Build a synthetic bundle from the json. Claims subset accepted as dict.
    claims_doc = doc.get("claims") or {}

    class _ShimClaims:
        def __init__(self, d: Dict[str, Any]):
            self.user_id = str(d.get("user_id", ""))
            self.domain = str(d.get("domain", ""))
            self.tier = str(d.get("tier", ""))
            self.accepted_terms_hash = str(d.get("accepted_terms_hash", ""))
            self.iat = int(d.get("iat", 0) or 0)
            self.exp = int(d.get("exp", 0) or 0)
            self.friends_consent = bool(d.get("friends_consent", False))

        def to_dict(self) -> Dict[str, Any]:
            return dict(vars(self))

    bundle = IdentitySignalBundle(
        raw_token=str(doc.get("raw_token", "")),
        claims=_ShimClaims(claims_doc) if claims_doc else None,
        sui_addr=str(doc.get("sui_addr", "")),
        solana_addr=str(doc.get("solana_addr", "")),
        x_user_id=str(doc.get("x_user_id", "")),
        snap_external_id=str(doc.get("snap_external_id", "")),
        fb_player_id=str(doc.get("fb_player_id", "")),
    )
    friends_count = int(doc.get("friends_count", 0) or 0)
    balances = {
        "sui_balance_usdc": float(doc.get("sui_balance_usdc", 0.0) or 0.0),
        "sui_nft_count": int(doc.get("sui_nft_count", 0) or 0),
        "solana_balance_sol": float(doc.get("solana_balance_sol", 0.0) or 0.0),
        "solana_spl_count": int(doc.get("solana_spl_count", 0) or 0),
        "x_handle": str(doc.get("x_handle", "")),
        "x_follower_count": int(doc.get("x_follower_count", 0) or 0),
    }
    role = infer_role(bundle, friends_count, balances)
    print(json.dumps({"inferred_role": role}, indent=2))
    return 0


def _cli_persona_stats() -> int:
    print(json.dumps(persona_stats(), indent=2))
    return 0


def _main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: identity_resolver.py <resolve|infer-role|persona-stats> [arg]",
                file=sys.stderr)
        return 64
    cmd = argv[1]
    if cmd == "resolve":
        if len(argv) < 3:
            print("usage: identity_resolver.py resolve <token>", file=sys.stderr)
            return 64
        return _cli_resolve(argv[2])
    if cmd in ("infer-role", "infer_role"):
        if len(argv) < 3:
            print("usage: identity_resolver.py infer-role <signals_json>", file=sys.stderr)
            return 64
        return _cli_infer_role(argv[2])
    if cmd in ("persona-stats", "persona_stats", "stats"):
        return _cli_persona_stats()
    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
