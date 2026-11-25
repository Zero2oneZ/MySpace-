#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        loom
# role:        SHELL · the data model + chat grounding + mint behind the Loom UI
# tier:        L0
# substrate:   a minted SCOPE = a label + glyph + archetype + profile + a saved
#              morph_chain id. The "+" chat grounds an intent against the closed
#              kernel_registry (RAG) and the morph_chain top-wheel taxonomy, then
#              proposes a buildable chain spec; CONFIRM bakes it into a scope row.
# storage:     ~/.cc/loom/scopes.jsonl  (append-only, dedup-by-id on read)
# reuse:       morph_chain (parse_spec/save/load/to_cards/top_wheel/neighbors),
#              kernel_registry (registry/resolve/norm_type), model_api (prose,
#              best-effort, degrades to deterministic — no network/key required).
# ----------------------------------------------------------------------------
"""loom — data model, chat grounding, and scope minting for the Loom shell.

Pure stdlib + sibling core/lib modules. Build-safe: every function returns a
useful result with no network and no keys. model_api prose is best-effort only.

CLI:
  loom ground "<intent>"
  loom mint   "<intent>" "<label>" "<chain_spec>"
  loom scopes
  loom scope  <scope_id>
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import morph_chain  # type: ignore
import kernel_registry  # type: ignore

# ── module constants ──────────────────────────────────────────────────────────

LOOM_DIR = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc"))) / "loom"

# ── TENANT HIERARCHY — clones inherit the ENGINE, not your STATE ──────────────
# Every tenant's state (scopes, connections, messages) lives in its own dir
# LOOM_DIR/<tenant>/. The kernel registry + morph_chain grammar + the governor
# are GLOBAL (the self-building node builder) — clones inherit them and, via the
# validation gate, can only *reference* vetted kernels, never reach your code.
# So a clone for your parents gets a clean self-building shelf; it never sees
# your scopes/connections/messages, and building in root can't corrupt it.
import threading as _threading
_CTX = _threading.local()
DEFAULT_TENANT = os.environ.get("MSPC_LOOM_TENANT", "root")


def _safe_tenant(t: str) -> str:
    t = (t or "").strip().lower() or DEFAULT_TENANT
    return "".join(c for c in t if c.isalnum() or c in "-_")[:48] or DEFAULT_TENANT


def set_tenant(t: str) -> None:
    """Set the current request's tenant (thread-local; the server calls this per
    request from the X-Loom-Tenant header). Isolates all state to that tenant."""
    _CTX.tenant = _safe_tenant(t)


def current_tenant() -> str:
    return getattr(_CTX, "tenant", None) or DEFAULT_TENANT


def _tdir() -> Path:
    return LOOM_DIR / current_tenant()


def _scopes() -> Path:
    return _tdir() / "scopes.jsonl"


def _conns() -> Path:
    return _tdir() / "connections.jsonl"


def _msgs() -> Path:
    return _tdir() / "messages.jsonl"

# ── archetype + glyph vocabulary (closed sets) ────────────────────────────────

ARCHETYPES = ("morph", "blend", "governor")   # the three mintable scope kinds
_ARCH_GLYPH = {"morph": "◆", "blend": "❖", "governor": "⛬"}
_GLYPH_POOL = ["◆", "❖", "⬡", "⬢", "◈", "✦", "▣", "◉", "⛬", "⊞", "✶", "❂"]

# registry archetype (UPPER) → mintable scope archetype (lower)
_ARCH_MAP = {"MORPH": "morph", "BLEND": "blend", "GOVERNOR": "governor"}

# intent keyword → modality token (lowercase, as morph_chain spec stages)
_KW_MOD = {
    "voice": "audio", "speak": "audio", "speech": "audio", "talk": "audio",
    "talking": "audio", "audio": "audio", "sound": "audio", "song": "audio",
    "music": "audio", "narrat": "audio", "podcast": "audio",
    "text": "text", "word": "text", "caption": "text", "transcript": "text",
    "prompt": "text", "describe": "text", "story": "text", "script": "text",
    "picture": "image", "photo": "image", "image": "image", "img": "image",
    "draw": "image", "art": "image", "frame": "image", "avatar": "image",
    "face": "image", "portrait": "image", "logo": "image", "render": "image",
    "clip": "video", "movie": "video", "video": "video", "animat": "video",
    "motion": "video", "film": "video", "reel": "video",
    "mesh": "3d", "model": "3d", "3d": "3d", "rig": "3d", "sculpt": "3d",
    "scene": "scene", "world": "scene", "level": "scene", "stage": "scene",
    "depth": "depth", "pose": "pose", "skeleton": "pose",
    "label": "label", "classif": "label", "tag": "label", "categor": "label",
    "embed": "embedding", "vector": "embedding", "similar": "embedding",
    "code": "code", "program": "code", "function": "code",
}

# intent keyword → morph stage {param} flag
_KW_PARAM = {
    "lipsync": "lipsync", "lip-sync": "lipsync", "lip sync": "lipsync",
    "mouth": "lipsync", "upscale": "upscale", "hi-res": "upscale",
    "hires": "upscale", "sharpen": "upscale", "denoise": "denoise",
}


# ── scope id + persistence ─────────────────────────────────────────────────────

def _scope_id(label: str, spec: str, ts: float) -> str:
    return "scope_" + hashlib.blake2b(
        f"{label}|{spec}|{ts}".encode(), digest_size=4).hexdigest()


def _append_scope(row: dict) -> None:
    _tdir().mkdir(parents=True, exist_ok=True)
    with _scopes().open("a") as f:
        f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")


# ── kernel resolution helpers ──────────────────────────────────────────────────

def _resolve_kernel(m) -> Optional[Dict[str, Any]]:
    """Resolve a morph node's kernel using the same precedence validate_ir uses."""
    if getattr(m, "control", "morph") != "morph":
        return None
    ref = (getattr(m, "model_ref", "") or getattr(m, "op", ""))
    if not ref:
        return None
    try:
        return kernel_registry.resolve(ref)
    except Exception:
        return None


def _profile_for(mc) -> dict:
    """kernels / hf_leaves / planes from the chain's transform nodes."""
    kernels: List[str] = []
    hf_leaves: List[str] = []
    planes: List[str] = []
    for m in getattr(mc, "morphs", []):
        k = _resolve_kernel(m)
        if not k:
            continue
        kid = k.get("id", "")
        if kid and kid not in kernels:
            kernels.append(kid)
        if k.get("archetype") == "LEAF" and kid and kid not in hf_leaves:
            hf_leaves.append(kid)
        pl = k.get("plane", "")
        if pl and pl not in planes:
            planes.append(pl)
    return {"kernels": kernels, "hf_leaves": hf_leaves, "planes": sorted(planes)}


def _archetype_for(mc, profile: dict) -> str:
    """Dominant kernel archetype → mintable archetype. LEAF/CONNECTOR/empty -> morph."""
    counts: Dict[str, int] = {}
    for m in getattr(mc, "morphs", []):
        k = _resolve_kernel(m)
        if not k:
            continue
        a = k.get("archetype", "")
        if a in _ARCH_MAP:
            counts[a] = counts.get(a, 0) + 1
    if not counts:
        return "morph"
    dominant = max(counts.items(), key=lambda kv: kv[1])[0]
    return _ARCH_MAP.get(dominant, "morph")


def _label_from_spec(spec: str) -> str:
    """'audio->...->video' -> 'Audio → Video'. Strips control tokens + {params}."""
    mods: List[str] = []
    for raw in spec.replace("→", "->").split("->"):
        s = raw.strip().lower()
        if not s:
            continue
        base = s.split(":", 1)[0].strip()
        if "{" in base:
            base = base.split("{", 1)[0].strip()
        if base in morph_chain._CTRL_KEYWORDS:
            continue
        if base in ("model.build", "rig.walk"):
            base = "3d"
        if base:
            mods.append(base)
    if not mods:
        return "Scope"
    ends = [mods[0], mods[-1]] if len(mods) > 1 else [mods[0]]
    pretty = [m.upper() if m in ("3d",) else m.title() for m in ends]
    return " → ".join(pretty)


# ── MINT ────────────────────────────────────────────────────────────────────────

def mint(intent_text: str, confirmed_spec: str,
         label: str = "", archetype: str = "", glyph: str = "") -> dict:
    """Mint a scope from a confirmed chain spec. Build-safe: never raises on a
    parseable spec; mints even when the chain yields zero morphs."""
    spec = (confirmed_spec or "").strip()
    if not spec:
        spec = (ground(intent_text or "").get("proposed_chain_spec") or "text->image").strip()

    mc = morph_chain.parse_spec(spec)
    try:
        morph_chain.save(mc)
    except Exception:
        pass

    profile = _profile_for(mc)
    archetype = (archetype or "").strip().lower()
    if archetype not in ARCHETYPES:
        archetype = _archetype_for(mc, profile)
    label = (label or _label_from_spec(spec)).strip()[:120]
    created_ts = time.time()
    scope_id = _scope_id(label, spec, created_ts)
    if not glyph:
        glyph = _ARCH_GLYPH.get(archetype, "◆")
    glyph = (glyph or "◆")[:2]

    row = {
        "scope_id": scope_id,
        "label": label,
        "glyph": glyph,
        "archetype": archetype,
        "profile": profile,
        "morph_chain_id": mc.chain_id,
        "chain_spec": spec,
        "intent": (intent_text or "")[:512],
        "created_ts": created_ts,
    }
    _append_scope(row)
    return row


# ── READ ──────────────────────────────────────────────────────────────────────

def list_scopes() -> list:
    """All scope rows, oldest-first (file order). Missing file -> []. Malformed
    lines skipped. Dedup by scope_id (last write wins) preserving first-seen order."""
    if not _scopes().exists():
        return []
    order: List[str] = []
    by_id: Dict[str, dict] = {}
    try:
        text = _scopes().read_text()
    except Exception:
        return []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            row = json.loads(ln)
        except Exception:
            continue
        sid = row.get("scope_id")
        if not sid:
            continue
        if sid not in by_id:
            order.append(sid)
        by_id[sid] = row
    return [by_id[sid] for sid in order]


def get_scope(scope_id: str) -> Optional[dict]:
    """Return the scope row with matching scope_id, or None. Last write wins."""
    if not scope_id:
        return None
    match: Optional[dict] = None
    for row in list_scopes():
        if row.get("scope_id") == scope_id:
            match = row
    return match


# ── THE GOVERNOR (engine.morpher) — auto-bind scopes from observed activity ───
# The user doesn't press "+". As they connect things — a login, a session, an
# email account — the governor observes the connection and AUTO-MINTS the
# matching scope onto the left shelf. "Login collects and binds the workflow as
# they go." Email is MCP by default (an inbox connection mints a triage scope).
# All local: these are the user's own captured connections on their own box.


# observed service (substring match) → (scope label, intent the governor grounds)
_GOVERNOR_MAP = [
    (("gmail", "outlook", "imap", "email", "inbox", "mail"),
     ("Email Triage", "ingest incoming email and pdf attachments, classify and summarize each item")),
    (("geico", "progressive", "statefarm", "allstate", "nationwide", "carrier", "insurance", "ezlynx", "pl rating"),
     ("Insurance Quotes", "process an insurance case document, fetch carrier quotes and compare to find the cheapest")),
    (("youtube", "tiktok", "vimeo", "video"),
     ("Video Studio", "generate video from a text idea through images")),
    (("blender", "avatar", "mocap", "character", "3d"),
     ("Avatar Builder", "build a rigged controllable 3d character from a reference")),
    (("shopify", "stripe", "invoice", "quickbooks", "docs", "drive"),
     ("Doc Processing", "extract, classify and organize incoming documents")),
]
_DEFAULT_GOV = ("Workspace", "organize and process incoming items")


def _gov_match(service: str) -> tuple:
    s = (service or "").lower()
    for keys, plan in _GOVERNOR_MAP:
        if any(k in s for k in keys):
            return plan
    return _DEFAULT_GOV


def connect(service: str, kind: str = "session", label: str = "",
            auto_mint: bool = True) -> dict:
    """Record an observed connection (oauth | cookie | session | email | login)
    and, by default, let the governor auto-mint the matching scope. This is the
    engine.morpher creating the user's tool-shelf for them, from what they do.

    kind ∈ {oauth, cookie, session, email, login}. Local-only: the user's own
    captured auth on their own host. Returns {connection, minted}.
    """
    _tdir().mkdir(parents=True, exist_ok=True)
    ts = time.time()
    conn = {"conn_id": "conn_" + hashlib.blake2b(f"{service}|{kind}|{ts}".encode(),
                                                 digest_size=4).hexdigest(),
            "service": service, "kind": kind,
            "label": (label or service)[:120], "captured_ts": ts}
    with _conns().open("a") as f:
        f.write(json.dumps(conn, separators=(",", ":"), default=str) + "\n")

    minted = None
    if auto_mint:
        gov_label, intent = _gov_match(service)
        # don't double-mint a scope of the same governed label
        if not any(s.get("label") == gov_label for s in list_scopes()):
            g = ground(intent)
            try:
                minted = mint(intent, g.get("proposed_chain_spec", ""),
                              label=gov_label)
            except Exception:
                minted = None
    # the governor narrates into #activity (the hub shows its own self-assembly)
    try:
        if minted:
            announce(f"🔗 {conn['label']} connected → bound new scope “{minted['label']}”",
                     scope_id=minted.get("scope_id"))
        else:
            announce(f"🔗 {conn['label']} connected ({kind})")
    except Exception:
        pass
    return {"connection": conn, "minted": minted,
            "governed_label": _gov_match(service)[0]}


# ── THE HUB (Slack-clone) — channels + messages + the bot ─────────────────────
# The Loom shell IS a local chat hub: #general (people), #activity (the governor
# announces auto-mints + connections here), and the bot DM "loom" (talk → ground
# → Confirm mints a scope). A channel is a morph.engine; the hub is a blend.engine;
# the bot is the engine.morpher governor. Self-hosted, local, no Slack SaaS.

DEFAULT_CHANNELS = ["loom", "general", "activity"]   # loom = the bot DM


def channels() -> list:
    """Channels in use (defaults + any that have messages)."""
    seen = list(DEFAULT_CHANNELS)
    for m in messages_all():
        ch = m.get("channel")
        if ch and ch not in seen:
            seen.append(ch)
    return seen


def messages_all() -> list:
    if not _msgs().exists():
        return []
    out = []
    for ln in _msgs().read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def messages(channel: str = "general", limit: int = 100) -> list:
    msgs = [m for m in messages_all() if m.get("channel") == channel]
    return msgs[-limit:] if limit else msgs


def _post_raw(channel: str, author: str, text: str, **extra) -> dict:
    _tdir().mkdir(parents=True, exist_ok=True)
    ts = time.time()
    msg = {"msg_id": "m_" + hashlib.blake2b(f"{channel}|{author}|{ts}".encode(),
                                            digest_size=5).hexdigest(),
           "channel": channel, "author": author, "text": text, "ts": ts, **extra}
    with _msgs().open("a") as f:
        f.write(json.dumps(msg, separators=(",", ":"), default=str) + "\n")
    return msg


def post(channel: str, text: str, author: str = "you") -> dict:
    """Post a human message. If it's the bot DM ('loom'), the governor replies:
    it GROUNDS the text and offers a Confirm that mints a scope — the +→chat→mint
    flow, as a chat. Returns {message, bot_reply}."""
    msg = _post_raw(channel, author, text)
    bot = None
    if channel == "loom" and author != "bot":
        g = ground(text)
        bot = _post_raw("loom", "bot",
                        g.get("reply", "Here's what I can wire for that."),
                        proposed_label=g.get("proposed_label", ""),
                        proposed_chain_spec=g.get("proposed_chain_spec", ""),
                        action="confirm_mint")
    return {"message": msg, "bot_reply": bot}


def announce(text: str, **extra) -> dict:
    """The governor posts to #activity (auto-mints, new connections, ships)."""
    return _post_raw("activity", "governor", text, **extra)


def connections() -> list:
    """All observed connections (the inbox), oldest-first."""
    if not _conns().exists():
        return []
    out = []
    for ln in _conns().read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


# ── GROUND (chat) ────────────────────────────────────────────────────────────

def _tokens(text: str) -> List[str]:
    out: List[str] = []
    cur = ""
    for ch in (text or "").lower():
        if ch.isalnum():
            cur += ch
        else:
            if cur:
                out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def _matched_modalities(intent: str) -> List[str]:
    """Ordered (first-mention) modality list. Synonyms via _KW_MOD + raw _MOD keys."""
    low = (intent or "").lower()
    hits: List[tuple] = []   # (position, modality)
    seen: set = set()
    # keyword/synonym scan (substring — catches 'narrate', 'classif' stems)
    for kw, mod in _KW_MOD.items():
        idx = low.find(kw)
        if idx >= 0 and mod not in seen:
            hits.append((idx, mod))
            seen.add(mod)
    # also catch bare morph_chain._MOD keys not covered above
    for kw, tok in morph_chain._MOD.items():
        mod = kw  # _MOD keys are lowercase modality words
        if mod in seen:
            continue
        idx = low.find(kw)
        if idx >= 0:
            hits.append((idx, mod))
            seen.add(mod)
    # Order by PIPELINE DIRECTION (source→sink), not text position, so
    # "video studio from text" → text->video (not video->text). Explicit
    # "from X" forces X to source; "to/into X" forces X to sink.
    _MOD_RANK = {"text": 0, "audio": 1, "speech": 1, "document": 1,
                 "label": 2, "code": 2, "embedding": 2, "vector": 2,
                 "image": 3, "depth": 3, "pose": 3,
                 "video": 4, "3d": 4, "mesh": 4, "scene": 5}

    def _dir_rank(item):
        idx, mod = item
        r = _MOD_RANK.get(mod, 3)
        if f"from {mod}" in low or f"given {mod}" in low:
            r = -1                      # explicit source
        elif f"to {mod}" in low or f"into {mod}" in low:
            r = 99                      # explicit sink (e.g. 'audio to text' → audio->text)
        return (r, idx)
    hits.sort(key=_dir_rank)
    mods = [m for _, m in hits]
    if len(mods) < 2:
        # seed sensible defaults preserving any single match
        base = ["text", "image"]
        for m in mods:
            if m not in base:
                base = [m] + [b for b in base if b != m]
        # keep at least 2
        mods = base[:2] if len(base) >= 2 else (base + ["image"])[:2]
    return mods


def _matched_params(intent: str) -> List[str]:
    low = (intent or "").lower()
    out: List[str] = []
    for kw, param in _KW_PARAM.items():
        if kw in low and param not in out:
            out.append(param)
    return out


def _mod_type(mod: str) -> str:
    try:
        return kernel_registry.norm_type(mod)
    except Exception:
        return (mod or "").upper()


def _candidate_kernels(intent: str, mods: List[str], tokens: List[str]) -> List[dict]:
    """Score registry kernels by modality type-overlap + keyword-in-id. Top 8."""
    try:
        reg = kernel_registry.registry()
    except Exception:
        return []
    mod_types = {_mod_type(m) for m in mods}
    tokset = set(tokens)
    scored: List[tuple] = []
    for kid, k in reg.items():
        ins = set(k.get("in_type", []))
        outs = set(k.get("out_type", []))
        overlap = len((ins | outs) & mod_types)
        kid_low = kid.lower().replace("-", " ")
        kw_in_id = any(tok in kid_low for tok in tokset if len(tok) >= 3)
        score = overlap * 2 + (1 if kw_in_id else 0)
        if score <= 0:
            continue
        why = ""
        if overlap:
            why = f"matched {overlap} modalit{'y' if overlap == 1 else 'ies'} in intent"
        elif kw_in_id:
            why = "id matched a keyword in intent"
        scored.append((score, kid, {
            "id": kid, "archetype": k.get("archetype"), "plane": k.get("plane"),
            "in_type": k.get("in_type", []), "out_type": k.get("out_type", []),
            "why": why,
        }))
    # stable: highest score first, then alpha
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [c for _, _, c in scored[:8]]


def _build_spec(mods: List[str], params: List[str], candidates: List[dict]) -> str:
    """Join modality list with '->'; append a {param} to the most apt stage.
    Validate it parses + resolves; fall back to a 2-stage best-kernel spec."""
    stages = list(dict.fromkeys(mods))  # dedupe preserve order
    if len(stages) < 2:
        stages = (stages + ["text", "image"])[:2]
    # attach params to a sensible stage: lipsync/denoise → image, upscale → last
    stage_params: Dict[int, List[str]] = {}
    for p in params:
        if p in ("lipsync", "denoise") and "image" in stages:
            stage_params.setdefault(stages.index("image"), []).append(p)
        else:
            stage_params.setdefault(len(stages) - 1, []).append(p)
    spec_parts: List[str] = []
    for i, s in enumerate(stages):
        if i in stage_params and stage_params[i]:
            spec_parts.append(f"{s}{{{','.join(stage_params[i])}}}")
        else:
            spec_parts.append(s)
    spec = "->".join(spec_parts)

    # validate it resolves cleanly; else fall back
    try:
        mc = morph_chain.parse_spec(spec)
        v = morph_chain.validate_ir(mc)
        if v.get("ok"):
            return spec
    except Exception:
        pass

    # fallback: two best-scored kernels' modalities (LEAF kernels carry in/out)
    leaf = [c for c in candidates if c.get("archetype") == "LEAF"]
    if len(leaf) >= 1:
        k0 = leaf[0]
        frm = (k0.get("in_type") or ["TEXT"])[0]
        to = (k0.get("out_type") or ["IMAGE"])[0]
        fb = f"{_type_to_mod(frm)}->{_type_to_mod(to)}"
        try:
            if morph_chain.validate_ir(morph_chain.parse_spec(fb)).get("ok"):
                return fb
        except Exception:
            pass
    # last resort: a guaranteed-clean spec
    return spec


_TYPE_TO_MOD = {"TEXT": "text", "IMAGE": "image", "VIDEO": "video", "AUDIO": "audio",
                "3D": "3d", "SCENE": "scene", "DEPTH": "depth", "POSE": "pose",
                "LABEL": "label", "EMB": "embedding", "CODE": "code"}


def _type_to_mod(t: str) -> str:
    return _TYPE_TO_MOD.get((t or "").upper(), "text")


def _enrich_neighbors(candidates: List[dict]) -> List[dict]:
    """Add chainable/accent neighbors of the top LEAF kernel (an HF task = a wheel
    node) as extra candidates — the 'only propose buildable work' guarantee."""
    out = list(candidates)
    have = {c["id"] for c in out}
    top_leaf = next((c for c in candidates if c.get("archetype") == "LEAF"), None)
    if not top_leaf:
        return out
    try:
        nbrs = morph_chain.neighbors(top_leaf["id"])
        reg = kernel_registry.registry()
    except Exception:
        return out
    for nxt in nbrs.get("chainable_into", []):
        if len(out) >= 8:
            break
        if nxt in have or nxt not in reg:
            continue
        k = reg[nxt]
        out.append({"id": nxt, "archetype": k.get("archetype"), "plane": k.get("plane"),
                    "in_type": k.get("in_type", []), "out_type": k.get("out_type", []),
                    "why": "chainable next — this output feeds it"})
        have.add(nxt)
    for acc in nbrs.get("accent", []):
        if len(out) >= 8:
            break
        if acc in have or acc not in reg:
            continue
        k = reg[acc]
        out.append({"id": acc, "archetype": k.get("archetype"), "plane": k.get("plane"),
                    "in_type": k.get("in_type", []), "out_type": k.get("out_type", []),
                    "why": "accent sibling — complements this step"})
        have.add(acc)
    return out[:8]


def _model_prose(intent_text: str, spec: str, candidates: List[dict]) -> tuple:
    """Best-effort richer prose via model_api. Returns (reply_or_None, source).
    Tries ModelAPI().text(...) first, then _api().connector_call('generate','text',...).
    Any failure → (None, 'deterministic')."""
    # SNAPPY DEFAULT: the deterministic reply is instant + good. The model call
    # is a real network request (DeepSeek) — calling it inline froze the chat.
    # Opt in with MSPC_LOOM_PROSE=1, and even then cap it at a hard timeout so a
    # slow/hung model can never freeze the UI.
    if os.environ.get("MSPC_LOOM_PROSE", "") != "1":
        return None, "deterministic"
    sys_prompt = ("You are the Loom build assistant. ONLY describe work achievable "
                  "with the provided kernels. 1-3 sentences. No code, no markdown.")
    payload = json.dumps({"intent": intent_text, "chain_spec": spec,
                          "kernels": [k["id"] for k in candidates]})

    def _call():
        try:
            from model_api import ModelAPI  # type: ignore
            r = ModelAPI().text(payload, max_tokens=160, temperature=0.2, system=sys_prompt)
            if getattr(r, "ok", False) and (r.output or "").strip():
                return r.output.strip()
        except Exception:
            return None
        return None

    try:
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=1) as ex:
            out = ex.submit(_call).result(timeout=6)   # hard ceiling — never hang
        if out:
            return out, "model_api"
    except Exception:
        pass
    return None, "deterministic"


def ground(intent_text: str) -> dict:
    """Ground an intent against the closed kernel set + the morph_chain taxonomy.
    Build-safe: always returns 200-shaped dict with no network/keys required."""
    intent_text = intent_text or ""
    tokens = _tokens(intent_text)

    # registry-empty short circuit
    try:
        reg_empty = not kernel_registry.registry()
    except Exception:
        reg_empty = True

    mods = _matched_modalities(intent_text)
    params = _matched_params(intent_text)
    candidates = _candidate_kernels(intent_text, mods, tokens) if not reg_empty else []
    candidates = _enrich_neighbors(candidates) if candidates else candidates

    if reg_empty or not candidates:
        spec = "text->image"
        grounded = False
    else:
        spec = _build_spec(mods, params, candidates)
        grounded = True

    # proposed metadata from the chain itself
    try:
        mc = morph_chain.parse_spec(spec)
        profile = _profile_for(mc)
        proposed_archetype = _archetype_for(mc, profile)
        v = morph_chain.validate_ir(mc)
        validation = {"ok": bool(v.get("ok")),
                      "kernels_bound": int(v.get("kernels_bound", 0)),
                      "errors": (v.get("errors") or [])[:5]}
    except Exception as e:
        proposed_archetype = "morph"
        validation = {"ok": False, "kernels_bound": 0, "errors": [f"{type(e).__name__}: {e}"]}

    proposed_label = _label_from_spec(spec)
    proposed_glyph = _ARCH_GLYPH.get(proposed_archetype, "◆")

    top3 = ", ".join(c["id"] for c in candidates[:3]) if candidates else "the default pipeline"
    n = len(candidates)
    reply = (f"I can build a {proposed_label} pipeline using {n} vetted kernel"
             f"{'' if n == 1 else 's'}: {top3}. "
             f"It runs {spec.replace('->', ' → ')}. Confirm to bake it into a scope.")
    source = "deterministic"

    prose, src = _model_prose(intent_text, spec, candidates)
    if prose:
        reply, source = prose, src

    return {
        "reply": reply,
        "proposed_label": proposed_label,
        "proposed_glyph": proposed_glyph,
        "proposed_archetype": proposed_archetype,
        "proposed_chain_spec": spec,
        "candidate_kernels": candidates,
        "validation": validation,
        "grounded": bool(grounded and candidates),
        "source": source,
    }


# ── CLONES — launch an isolated tenant (the self-building node builder) ───────

def create_clone(tenant_id: str, label: str = "") -> dict:
    """Provision an isolated clone tenant. It inherits the engine (kernels +
    grammar + governor) but starts with EMPTY state — it self-builds its own
    shelf from its own connections. It can never see root's scopes/connections/
    messages, and (via the validation gate) can only reference vetted kernels."""
    t = _safe_tenant(tenant_id)
    prev = current_tenant()
    set_tenant(t)
    try:
        _tdir().mkdir(parents=True, exist_ok=True)
        if not _msgs().exists():
            _post_raw("loom", "bot",
                      f"Welcome to your Loom{(' — ' + label) if label else ''}. "
                      f"Describe a tool, or connect an account — I'll build your "
                      f"shelf as you go.", action="")
        info = {"tenant": t, "label": label or t, "url": f"/dapp/loom?tenant={t}",
                "scopes": len(list_scopes()), "connections": len(connections()),
                "inherits": "engine (kernels+grammar+governor); state is isolated"}
    finally:
        set_tenant(prev)
    return info


def tenants() -> list:
    """List all tenants (root + clones) with their isolated state counts.
    Root-only operation in practice — a clone only ever sees its own tenant."""
    if not LOOM_DIR.exists():
        return []
    out = []
    prev = current_tenant()
    try:
        for d in sorted(LOOM_DIR.iterdir()):
            if not d.is_dir():
                continue
            set_tenant(d.name)
            out.append({"tenant": d.name, "is_root": d.name == DEFAULT_TENANT,
                        "scopes": len(list_scopes()), "connections": len(connections())})
    finally:
        set_tenant(prev)
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    # --tenant <t> isolates the whole command to a clone's state
    if "--tenant" in args:
        i = args.index("--tenant")
        if i + 1 < len(args):
            set_tenant(args[i + 1])
            args = args[:i] + args[i + 2:]
    if cmd == "clone":
        if not args:
            print('usage: clone <tenant_id> ["label"] ', file=sys.stderr)
            return 2
        print(json.dumps(create_clone(args[0], args[1] if len(args) > 1 else ""),
                         indent=2, ensure_ascii=False))
        return 0
    if cmd == "tenants":
        print(json.dumps(tenants(), indent=2, ensure_ascii=False))
        return 0
    if cmd == "ground":
        if not args:
            print('usage: ground "<intent>"', file=sys.stderr)
            return 2
        print(json.dumps(ground(" ".join(args)), indent=2, ensure_ascii=False))
        return 0
    if cmd == "mint":
        if len(args) < 1:
            print('usage: mint "<intent>" "<label>" "<chain_spec>"', file=sys.stderr)
            return 2
        intent = args[0]
        label = args[1] if len(args) > 1 else ""
        spec = args[2] if len(args) > 2 else ""
        print(json.dumps(mint(intent, spec, label=label), indent=2, ensure_ascii=False))
        return 0
    if cmd == "scopes":
        print(json.dumps(list_scopes(), indent=2, ensure_ascii=False))
        return 0
    if cmd == "scope":
        if not args:
            print("usage: scope <scope_id>", file=sys.stderr)
            return 2
        s = get_scope(args[0])
        if s is None:
            print(json.dumps({"error": "no such scope"}))
            return 1
        print(json.dumps(s, indent=2, ensure_ascii=False))
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
