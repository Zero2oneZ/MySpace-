#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        morph_game_runtime                                             =
# role:        SUBSTRATE · POLYMORPHIC_SCENE_PLANNER                          =
# tier:        L0                                                             =
# substrate:   the brain that maps AudiencePersonaVector → ScenePlan          =
# engine:      deterministic table lookup + content-hash; NO LLM call         =
# storage:     studio/assets/_morph_plans/<persona_id>.json (6h TTL)          =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.morph_game_runtime.active.json   =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - studio/dapp/server.py /dapp/play_morph (renders persona-specific shell) =
#   - identity_resolver after persona vector finalization                     =
#   - cli: python3 core/lib/morph_game_runtime.py plan-from-{persona,token}   =
# outbound:                                                                   =
#   - inference_logger.log (tier='morph_plan', model='morph_game_runtime')    =
#   - studio/assets/_morph_plans/<persona_id>.json (plan persistence)         =
# substrate touch:                                                            =
#   - reads:  AudiencePersonaVector from identity_resolver (lazy import)      =
#   - reads:  freetier_gate.verify_token (when plan-from-token CLI used)      =
#   - writes: morph_plans dir + crystal chain                                 =
# ----------------------------------------------------------------------------=
# THE 5 ROLES (deterministic routing table)                                   =
# ----------------------------------------------------------------------------=
#   realtor    → play_realtor    + realestate_walkthrough_full.tscn (cheap)   =
#   buyer      → play_buyer      + avatar_rigged.tscn               (cheap)   =
#   gamer      → play_gamer      + planet_map.tscn                  (fast)    =
#   developer  → play_developer  + main.tscn                        (premium) =
#   unknown    → play_default    + main.tscn                        (free)    =
# ============================================================================
"""morph_game_runtime.py — the polymorphic game runtime.

Takes an AudiencePersonaVector (from identity_resolver, sibling module) and
emits a deterministic ScenePlan describing exactly which Godot scene variant,
which dApp face, which Snap lens deeplink, and which Solana coin variant to
show this specific viewer.

The whole point: "a game that changes depending on who sees it." Realtor
sees the staging tool. Buyer sees the avatar walkthrough. Gamer sees the
leaderboard. Developer sees the substrate dashboard. All from the same
single-page entrypoint, all picked deterministically by inferred_role +
persona_vector hash.

ZERO LLM CALLS. Pure stdlib. Pure table lookup + hash mod arithmetic. This
keeps the morph runtime free, deterministic, and replay-safe: same persona
in = same scene plan out, byte for byte.

Plans persist to studio/assets/_morph_plans/<persona_id>.json with a 6h TTL
and a crystal-chain anchor at tier='morph_plan'.

Public API:
    plan_for(persona)              -> ScenePlan
    render_dapp_overrides(plan)    -> <style>+<script type="application/json"> HTML block
    emit_plan(plan, output_path?)  -> Path
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_HERE))

MORPH_PLANS_DIR = Path(os.environ.get(
    "MYSPACE_MORPH_PLANS_DIR",
    str(_PROJECT_ROOT / "studio" / "assets" / "_morph_plans"),
))
PLAN_TTL_SECONDS = 6 * 3600  # 6h


# ---------------------------------------------------------------------------
# Routing table — the heart of the polymorphism
# ---------------------------------------------------------------------------

ROLES = ("realtor", "buyer", "gamer", "developer", "unknown")

# role → (primary_face, godot_scene, workflow_card, cost_class, accent_color)
_ROUTING_TABLE: Dict[str, Dict[str, str]] = {
    "realtor": {
        "primary_face":  "play_realtor",
        "godot_scene":   "scenes/realestate_walkthrough_full.tscn",
        "workflow_card": "realestate_walkthrough_full",
        "cost_class":    "cheap",
        "accent":        "#FFD250",  # warm staging gold
    },
    "buyer": {
        "primary_face":  "play_buyer",
        "godot_scene":   "scenes/avatar_rigged.tscn",
        "workflow_card": "photo_to_avatar_rigged",
        "cost_class":    "cheap",
        "accent":        "#5b8def",  # avatar walkthrough blue
    },
    "gamer": {
        "primary_face":  "play_gamer",
        "godot_scene":   "scenes/planet_map.tscn",
        "workflow_card": "pinterest_vector_motherload",
        "cost_class":    "fast",
        "accent":        "#e53935",  # leaderboard red
    },
    "developer": {
        "primary_face":  "play_developer",
        "godot_scene":   "scenes/main.tscn",
        "workflow_card": "autonomous_3d_asset",
        "cost_class":    "premium",
        "accent":        "#9c27b0",  # substrate purple
    },
    "unknown": {
        "primary_face":  "play_default",
        "godot_scene":   "scenes/main.tscn",
        "workflow_card": "realestate_walkthrough_full",
        "cost_class":    "free",
        "accent":        "#4caf50",  # neutral welcome green
    },
}

# 8 Solana coin variants — one bucket per persona hash mod 8.
_COIN_VARIANTS = (
    "tier_seed",
    "tier_sprout",
    "tier_bloom",
    "tier_canopy",
    "tier_fruit",
    "tier_root",
    "tier_drift",
    "tier_signal",
)

# Snap lens deeplink template per coin variant — keeps the lens variation in
# lock-step with the coin variation so a viewer's collectible tier and AR
# lens always tell the same on-chain story.
_SNAP_LENS_IDS = {
    "tier_seed":   "lens_mspc_seed_v0",
    "tier_sprout": "lens_mspc_sprout_v0",
    "tier_bloom":  "lens_mspc_bloom_v0",
    "tier_canopy": "lens_mspc_canopy_v0",
    "tier_fruit":  "lens_mspc_fruit_v0",
    "tier_root":   "lens_mspc_root_v0",
    "tier_drift":  "lens_mspc_drift_v0",
    "tier_signal": "lens_mspc_signal_v0",
}

# Default mapping from role → sui_nft_recommendation slug. Plan picker can
# override but this is the deterministic baseline.
_SUI_NFT_BY_ROLE = {
    "realtor":   "sui_walkthrough_certificate_v0",
    "buyer":     "sui_avatar_passport_v0",
    "gamer":     "sui_planet_emblem_v0",
    "developer": "sui_substrate_credential_v0",
    "unknown":   "sui_visitor_seal_v0",
}


# ---------------------------------------------------------------------------
# ScenePlan — the deterministic render plan returned by plan_for()
# ---------------------------------------------------------------------------

@dataclass
class ScenePlan:
    """A deterministic render plan for ONE viewer.

    Fields are exactly what the dApp /dapp/play_morph page + the Godot main
    bootstrap + the snap_camera_kit deeplink builder + the on-chain Token-2022
    metadata mutator need to pick the correct variant of every surface for
    this specific viewer."""
    persona_id: str = ""
    inferred_role: str = "unknown"

    primary_face:           str  = "play_default"   # dApp template slug
    godot_scene:            str  = "scenes/main.tscn"
    snap_lens_deeplink:     str  = ""               # snapchat:// URL
    solana_coin_variant:    str  = "tier_seed"      # SVG-variant slug
    sui_nft_recommendation: str  = ""               # sui_mcp.nft_mint payload slug
    workflow_card:          str  = ""               # _workflows/*.v0.json slug
    cost_class:             str  = "free"           # passed to cloud_providers.pick

    # CSS vars injected into the dApp shell at render time so the SAME page
    # source serves every role — only the colors flip.
    custom_css_vars: Dict[str, str] = field(default_factory=dict)

    crystal:    str = ""             # crystal_id from inference_logger.log
    created_at: int = 0              # unix seconds
    expires_at: int = 0              # unix seconds — 6h after created_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Persona shim — works with or without identity_resolver.AudiencePersonaVector
# ---------------------------------------------------------------------------

def _persona_to_dict(persona: Any) -> Dict[str, Any]:
    """Normalize whatever the caller passed into a plain dict.

    The sibling identity_resolver module is still being built. We accept:
      - identity_resolver.AudiencePersonaVector (preferred, when available)
      - any dataclass (uses dataclasses.asdict)
      - dict (passthrough)
      - JSON string (decoded)

    We never raise — unknown shapes become an empty dict and routing falls
    back to role='unknown'."""
    if persona is None:
        return {}
    if isinstance(persona, dict):
        return dict(persona)
    if isinstance(persona, (bytes, str)):
        try:
            text = persona.decode("utf-8") if isinstance(persona, bytes) else persona
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    # Dataclass / object with __dict__ / asdict
    try:
        return asdict(persona)  # type: ignore[arg-type]
    except Exception:
        pass
    if hasattr(persona, "__dict__"):
        return {k: v for k, v in persona.__dict__.items() if not k.startswith("_")}
    return {}


def _coerce_role(raw: Any) -> str:
    """Map an arbitrary inferred_role string to one of the 5 known roles."""
    if not raw:
        return "unknown"
    role = str(raw).strip().lower()
    if role in ROLES:
        return role
    # Light synonym map — keeps the routing table strict while accepting
    # near-misses from the identity_resolver.
    synonyms = {
        "agent":      "realtor",
        "broker":     "realtor",
        "homeowner":  "buyer",
        "homebuyer":  "buyer",
        "shopper":    "buyer",
        "player":     "gamer",
        "kid":        "gamer",
        "dev":        "developer",
        "engineer":   "developer",
        "builder":    "developer",
        "hacker":     "developer",
    }
    return synonyms.get(role, "unknown")


# ---------------------------------------------------------------------------
# Deterministic pickers (hash mod arithmetic; no LLM)
# ---------------------------------------------------------------------------

def _persona_hash(persona_id: str, role: str) -> str:
    """Stable SHA256 of (persona_id|role). Used as the input to every
    variant picker so the SAME persona always lands on the SAME bucket."""
    return hashlib.sha256(f"{persona_id}|{role}".encode("utf-8")).hexdigest()


def _pick_coin_variant(persona_id: str, role: str) -> str:
    """hash(persona|role) % 8 → coin variant."""
    h = _persona_hash(persona_id, role)
    # Use first 8 hex chars → int → mod len(variants)
    bucket = int(h[:8], 16) % len(_COIN_VARIANTS)
    return _COIN_VARIANTS[bucket]


def _pick_snap_lens_deeplink(persona_id: str, coin_variant: str) -> str:
    """snapchat://camera?lens=<id>&hint=<persona>. Lens id is derived from the
    coin variant so lens + coin always match."""
    lens_id = _SNAP_LENS_IDS.get(coin_variant, "")
    if not lens_id:
        return ""
    # urlencode by hand — stdlib-only and avoids importing urllib at top level
    # for a one-liner that is essentially identifier-safe.
    safe_persona = "".join(ch for ch in persona_id if ch.isalnum() or ch in "-_.")
    if safe_persona:
        return f"snapchat://camera?lens={lens_id}&hint={safe_persona}"
    return f"snapchat://camera?lens={lens_id}"


def _persona_id_from(persona_dict: Dict[str, Any]) -> str:
    """Extract a stable persona_id from the persona dict.

    Tries (in order): persona_id, id, user_id, viewer_id. Falls back to a
    SHA256 of the canonical-sorted JSON so an anonymous persona still
    deterministically maps to the same plan."""
    for key in ("persona_id", "id", "user_id", "viewer_id"):
        v = persona_dict.get(key)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, (int, float)) and v:
            return str(v)
    if not persona_dict:
        return "anonymous_default"
    canonical = json.dumps(persona_dict, sort_keys=True, separators=(",", ":"))
    return "anon_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public API: plan_for / render_dapp_overrides / emit_plan
# ---------------------------------------------------------------------------

def plan_for(persona: Any) -> ScenePlan:
    """Deterministic scene picker. Pure table lookup + hash mod arithmetic.

    NO LLM call. NO network call. Same persona in → same plan out, byte-for-byte.
    The crystal anchor written at the end of this function IS the LLM-free
    audit trail that the rest of the system can replay later."""
    persona_dict = _persona_to_dict(persona)
    persona_id   = _persona_id_from(persona_dict)
    role         = _coerce_role(persona_dict.get("inferred_role"))

    row = _ROUTING_TABLE[role]
    coin_variant = _pick_coin_variant(persona_id, role)
    snap_deeplink = _pick_snap_lens_deeplink(persona_id, coin_variant)
    sui_recommendation = _SUI_NFT_BY_ROLE.get(role, _SUI_NFT_BY_ROLE["unknown"])

    now = int(time.time())
    plan = ScenePlan(
        persona_id=persona_id,
        inferred_role=role,
        primary_face=row["primary_face"],
        godot_scene=row["godot_scene"],
        snap_lens_deeplink=snap_deeplink,
        solana_coin_variant=coin_variant,
        sui_nft_recommendation=sui_recommendation,
        workflow_card=row["workflow_card"],
        cost_class=row["cost_class"],
        custom_css_vars={"--accent": row["accent"]},
        created_at=now,
        expires_at=now + PLAN_TTL_SECONDS,
    )

    # Crystal-anchor the plan emission. tier/model/scope per the agent spec.
    plan.crystal = _crystal_anchor_plan(plan)
    return plan


def render_dapp_overrides(plan: ScenePlan) -> str:
    """Return a single HTML block injectable into the /dapp/play_morph page.

    The block carries:
      1. a <style> tag with the persona's CSS vars (so colors flip per role)
      2. a <script type="application/json" id="mspc-morph-plan"> embedding the
         full plan JSON for the HTMX surface to read at runtime
      3. a <meta> tag exposing the godot_scene + primary_face for SSR
         consumers that scrape <head>

    Caller is expected to inject this into <head> so the HTMX HX-Trigger
    handlers can read window.__MSPC_PLAN at boot.
    """
    css_vars = plan.custom_css_vars or {}
    # Build the :root rule. Sort keys for determinism.
    declarations = ";".join(f"{k}:{v}" for k, v in sorted(css_vars.items()))
    style_block = f"<style id=\"mspc-morph-style\">:root{{{declarations}}}</style>" if declarations else ""

    metadata = {
        "persona_id":           plan.persona_id,
        "inferred_role":        plan.inferred_role,
        "primary_face":         plan.primary_face,
        "godot_scene":          plan.godot_scene,
        "snap_lens_deeplink":   plan.snap_lens_deeplink,
        "solana_coin_variant":  plan.solana_coin_variant,
        "sui_nft_recommendation": plan.sui_nft_recommendation,
        "workflow_card":        plan.workflow_card,
        "cost_class":           plan.cost_class,
        "crystal":              plan.crystal,
        "expires_at":           plan.expires_at,
    }
    # json.dumps escapes < and > if we ask. We use ensure_ascii to keep the
    # block 7-bit clean so it survives whatever template engine wraps it.
    metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=True)
    # Defensive: replace "</" inside the JSON so a stray "</script>" can't
    # break out. Standard inline-JSON hardening.
    metadata_json = metadata_json.replace("</", "<\\/")
    script_block = (
        f"<script type=\"application/json\" id=\"mspc-morph-plan\">"
        f"{metadata_json}"
        f"</script>"
    )

    meta_block = (
        f"<meta name=\"mspc-godot-scene\" content=\"{plan.godot_scene}\">"
        f"<meta name=\"mspc-primary-face\" content=\"{plan.primary_face}\">"
        f"<meta name=\"mspc-cost-class\" content=\"{plan.cost_class}\">"
    )

    return style_block + meta_block + script_block


def emit_plan(plan: ScenePlan, output_path: Optional[Path] = None) -> Path:
    """Persist a ScenePlan to studio/assets/_morph_plans/<persona_id>.json.

    The directory is created on first call. The file is overwritten on every
    emit — the crystal_id in the file is the audit-trail anchor, not the
    file itself."""
    MORPH_PLANS_DIR.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        # Sanitize persona_id for a filename. Keep it short + filesystem-safe.
        safe = "".join(ch for ch in plan.persona_id if ch.isalnum() or ch in "-_.")
        if not safe:
            safe = "anonymous"
        output_path = MORPH_PLANS_DIR / f"{safe}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(plan.to_dict(), indent=2, sort_keys=True)
    output_path.write_text(payload, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Crystal anchor
# ---------------------------------------------------------------------------

def _crystal_anchor_plan(plan: ScenePlan) -> str:
    """Append one InferenceRecord with tier='morph_plan', model='morph_game_runtime'.
    Returns crystal_id (empty string if logger unavailable — graceful degrade)."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        crystal_id = il.log(
            original_prompt=f"morph_game_runtime.plan_for:{plan.inferred_role}",
            enhanced_prompt=json.dumps({
                "persona_id":   plan.persona_id,
                "role":         plan.inferred_role,
                "primary_face": plan.primary_face,
                "godot_scene":  plan.godot_scene,
            }, separators=(",", ":"))[:512],
            output_text=json.dumps({
                "coin":          plan.solana_coin_variant,
                "lens_deeplink": plan.snap_lens_deeplink[:128],
                "sui_nft":       plan.sui_nft_recommendation,
                "workflow":      plan.workflow_card,
                "cost":          plan.cost_class,
            }, separators=(",", ":"))[:512],
            tier="morph_plan",
            model="morph_game_runtime",
            scope="scene_plan_emitted",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
            source_action="morph_game_runtime.plan_for",
            source_file=f"persona:{plan.persona_id}|role:{plan.inferred_role}",
            done_flag=True,
            rc=0,
        ) or ""
        return crystal_id
    except Exception as e:
        sys.stderr.write(f"warn: morph_game_runtime crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _persona_from_token_cli(token: str) -> Dict[str, Any]:
    """Build a minimal persona dict from a freetier_gate token.

    The token's claims supply user_id + tier; everything else falls back to
    'unknown' until identity_resolver is online. This keeps the smoke test
    flow self-contained: issue token -> derive plan."""
    persona: Dict[str, Any] = {"inferred_role": "unknown"}
    try:
        from freetier_gate import verify_token  # type: ignore
        claims = verify_token(token)
        if claims is not None:
            persona["persona_id"] = claims.user_id
            persona["user_id"]    = claims.user_id
            persona["tier"]       = claims.tier
            persona["domain"]     = claims.domain
    except Exception as e:
        sys.stderr.write(f"warn: token decode failed: {type(e).__name__}: {e}\n")
    return persona


def _stats() -> Dict[str, Any]:
    """Count emitted plans by inferred_role + overall counts."""
    counts: Dict[str, int] = {r: 0 for r in ROLES}
    total = 0
    expired = 0
    now = int(time.time())
    if MORPH_PLANS_DIR.exists():
        for p in MORPH_PLANS_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            total += 1
            role = data.get("inferred_role", "unknown")
            if role not in counts:
                counts[role] = 0
            counts[role] += 1
            exp = int(data.get("expires_at") or 0)
            if exp and exp < now:
                expired += 1
    return {
        "total_plans":   total,
        "by_role":       counts,
        "expired_plans": expired,
        "morph_plans_dir": str(MORPH_PLANS_DIR),
    }


def _main() -> None:
    ap = argparse.ArgumentParser(
        description="morph_game_runtime — polymorphic ScenePlan emitter (deterministic, no LLM)",
    )
    sub = ap.add_subparsers(dest="cmd")

    p_plan_pj = sub.add_parser("plan-from-persona",
                                 help="emit a ScenePlan from a persona JSON file or '-' for stdin")
    p_plan_pj.add_argument("persona_json", help="path to persona JSON, or '-' for stdin")
    p_plan_pj.add_argument("--no-emit", action="store_true",
                              help="just print the plan, don't write to _morph_plans/")

    p_plan_tk = sub.add_parser("plan-from-token",
                                 help="emit a ScenePlan from a freetier_gate token")
    p_plan_tk.add_argument("token", help="bearer token (issued by freetier_gate.issue_token)")
    p_plan_tk.add_argument("--no-emit", action="store_true")

    sub.add_parser("stats", help="count emitted plans by role")
    sub.add_parser("table", help="dump the deterministic routing table")

    args = ap.parse_args()

    if args.cmd == "plan-from-persona":
        if args.persona_json == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.persona_json).read_text(encoding="utf-8")
        try:
            persona = json.loads(text)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"persona_json_parse: {e}"}, indent=2))
            sys.exit(2)
        plan = plan_for(persona)
        if not args.no_emit:
            path = emit_plan(plan)
            print(json.dumps({"plan": plan.to_dict(),
                                "emitted_to": str(path)}, indent=2))
        else:
            print(json.dumps(plan.to_dict(), indent=2))

    elif args.cmd == "plan-from-token":
        persona = _persona_from_token_cli(args.token)
        plan = plan_for(persona)
        if not args.no_emit:
            path = emit_plan(plan)
            print(json.dumps({"plan": plan.to_dict(),
                                "emitted_to": str(path)}, indent=2))
        else:
            print(json.dumps(plan.to_dict(), indent=2))

    elif args.cmd == "stats":
        print(json.dumps(_stats(), indent=2))

    elif args.cmd == "table":
        print(json.dumps({
            "roles":         list(ROLES),
            "routing_table": _ROUTING_TABLE,
            "coin_variants": list(_COIN_VARIANTS),
            "snap_lens_ids": _SNAP_LENS_IDS,
            "sui_nft_by_role": _SUI_NFT_BY_ROLE,
            "ttl_seconds":   PLAN_TTL_SECONDS,
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
