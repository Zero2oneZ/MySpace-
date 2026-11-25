#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        dapp_server
# role:        HTTP · SINGLE_TENANT_DAPP_SURFACE
# tier:        L0
# substrate:   the user-facing dApp — services browse + photo→NFT mint +
#              wallet view. Single-tenant (no Host routing); Caddy on the
#              droplet handles TLS + domain mapping.
# storage:     templates rendered fresh per request; tokens via freetier_gate
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.dapp_server.active.json
# ----------------------------------------------------------------------------
# ROUTES
# ----------------------------------------------------------------------------
# GET  /dapp/                       → 302 to /dapp/services
# GET  /dapp/services               → product cards + buy buttons
# GET  /dapp/mint                   → photo upload → mint
# GET  /dapp/wallet                 → Sui wallet-connect + balance polling
# GET  /dapp/api/products           → JSON list (PUBLIC, no auth)
# GET  /dapp/api/balance?addr=X     → fanout: {sui, tensorchain}
# GET  /dapp/healthz                → JSON {ok}
# POST /dapp/api/buy   (bearer)     → stripe.create_payment_intent | sui.transfer_usdc
# POST /dapp/api/mint  (bearer)     → tensorchain.mint_nft (SUI_FALLBACK if needed)
# GET  /dapp/play_morph             → public · morph-driven Godot embed page
# GET  /dapp/api/morph_plan (bearer) → ScenePlan JSON via identity_resolver + morph_game_runtime
# GET  /dapp/pump_surf              → public · pump.fun bot-vs-human radar embed
# GET  /dapp/api/pump_wave (bearer) → WaveFrame JSON via pump_visualizer_3d.build_wave_frame
# ----------------------------------------------------------------------------
# All write endpoints crystal-anchor via inference_logger.
# All HTML rendered server-side via string.Template style (stdlib only).
# Photo upload capped at 8 MB; MIME-sniffed for image/*.
# HTMX-aware: returns inner panel HTML if HX-Request: true.
# ============================================================================
"""dapp_server.py — flat-HTML + HTMX-only dApp HTTP surface (port 8520).

Stdlib only (http.server.ThreadingHTTPServer). Mirrors freetier_callback
server pattern. Bind to 127.0.0.1 by default — Caddy on the droplet handles
TLS + domain mapping in production.

Run locally:
    MSPC_DAPP_PORT=8520 python3 studio/dapp/server.py

Smoke:
    curl http://localhost:8520/dapp/healthz
    curl http://localhost:8520/dapp/api/products
    curl http://localhost:8520/dapp/services
    curl -X POST http://localhost:8520/dapp/api/buy -d '{}'  # expect 401
"""
from __future__ import annotations

import base64
import html
import json
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
# loom_ui lives in studio/dapp (next to this file) — make `import loom_ui` resolve.
sys.path.insert(0, str(_HERE))

# freetier_gate — bearer-gate for the write APIs.
from freetier_gate import (  # type: ignore  # noqa: E402
    DOMAINS,
    require_token,
    TokenClaims,
)

# Wallet-map store — DOM ingest + on-chain graph (read-only render here).
import token_wallet_mapper as wmap  # type: ignore  # noqa: E402
# Audio → rgb/hex sound-wave (live tab-capture amplitudes; no ffmpeg needed).
import audio_chromatize as chroma  # type: ignore  # noqa: E402

# Connectors — DO NOT duplicate their logic; we just wire them.
from third_party.stripe_mcp import StripeMCPConnector  # type: ignore  # noqa: E402
from third_party.sui_mcp import SuiMCPConnector  # type: ignore  # noqa: E402
from third_party.tensorchain_mcp import TensorChainMCPConnector  # type: ignore  # noqa: E402

TEMPLATES = _HERE / "templates"
PRODUCTS_DIR = _PROJECT_ROOT / "studio" / "assets" / "_products"

# Recorded livestream video lands here; the stream registry lives next to the
# wallet-map store so the graph + the streams share one home.
VIDEO_DIR = _PROJECT_ROOT / "studio" / "media" / "Media" / "Video"
import pathlib as _pl  # noqa: E402
_CC_HOME = _pl.Path(os.environ.get("CC_HOME", str(_pl.Path.home() / ".cc")))
STREAMS_FILE = _CC_HOME / "wallet_map" / "streams.jsonl"
GEN3D_DIR = _CC_HOME / "gen3d"   # GLBs produced by generative_mcp.generate_3d
MAX_VIDEO_BYTES = int(os.environ.get("MSPC_MAX_VIDEO_BYTES", str(2 * 1024 ** 3)))  # 2 GiB

# Sui USDC leverage-loop dry-run simulator (flat HTML; web is always dry-run).
_DEFI_LOOP_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MySpace++ · Sui USDC Leverage Loop (dry-run)</title>
<style>
 body{margin:0;background:#0b0e14;color:#cbd5e1;font:14px/1.6 ui-monospace,Menlo,monospace;padding:20px;max-width:760px}
 h1{font-size:18px;color:#e2e8f0}.muted{color:#64748b}
 label{display:block;margin:12px 0 4px}input[type=number]{width:140px}
 input,button{background:#111824;border:1px solid #243140;color:#cbd5e1;border-radius:6px;padding:6px 8px;font:inherit}
 button{background:#134e4a;border-color:#2dd4bf;color:#a7f3eb;cursor:pointer;margin-top:14px}
 table{width:100%;border-collapse:collapse;margin-top:16px}td,th{border-bottom:1px solid #1c2530;padding:6px;text-align:left;font-size:13px}
 .badge{display:inline-block;padding:2px 8px;border-radius:10px;background:#1c2530}
 #lev{vertical-align:middle}.warn{color:#f59e0b}
</style></head><body>
<h1>Sui USDC leverage loop <span class="muted">— dry-run preview</span></h1>
<p class="muted">Models the deposit→borrow→re-deposit loop. The web preview is <b>always dry-run</b> —
real looping is CLI + confirm-gated. Lending requires <code>SUI_LENDING_PACKAGE_ID</code>.</p>
<label>Collateral (USDC)</label><input id="collateral" type="number" value="100" min="1">
<label>Target leverage: <span id="levv">2.0</span>x</label>
<input id="lev" type="range" min="1" max="5" step="0.1" value="2.0" oninput="levv.textContent=this.value">
<label>Max iterations</label><input id="iters" type="number" value="4" min="1" max="12">
<button onclick="run()">Simulate loop</button>
<div id="out"></div>
<script>
async function run(){
 const body={collateral_usdc:+collateral.value,leverage:+document.getElementById('lev').value,max_iters:+iters.value};
 out.innerHTML='<p class="muted">simulating…</p>';
 const r=await fetch('/dapp/api/defi/loop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const j=await r.json();
 if(!j.ok){out.innerHTML='<p class="warn">error: '+(j.error||'?')+'</p>';return;}
 const res=j.result||{};const steps=res.steps||[];
 let h='<p>achieved leverage <span class="badge">'+(res.achieved_leverage||1).toFixed?(res.achieved_leverage).toFixed(2):res.achieved_leverage+'</span>'
   +'x · stop: <span class="badge">'+(res.stop_reason||'?')+'</span> · steps: '+steps.length+' <span class="muted">(dry-run)</span></p>';
 if(steps.length){h+='<table><tr><th>#</th><th>action</th><th>amount</th><th>cumulative</th></tr>';
  steps.forEach((s,i)=>{h+='<tr><td>'+i+'</td><td>'+(s.action||s.op||'')+'</td><td>'+(s.amount_micro!=null?(s.amount_micro/1e6).toFixed(2):'')+'</td><td>'+(s.cumulative_collateral_micro!=null?(s.cumulative_collateral_micro/1e6).toFixed(2):'')+'</td></tr>';});
  h+='</table>';}
 out.innerHTML=h;
}
</script></body></html>"""

# CORS for the solscan-map browser extension (content script runs on solscan.io
# but the public RFC allows null/extension origins too; we echo a permissive
# allow since the endpoint is read-only-additive and local-only).
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}

# Live wallet-map page — flat HTML + inline SVG + tiny vanilla force layout.
# No framework, no build step (project frontend rule). Polls wallet-map-data.
_WALLET_MAP_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MySpace++ · Wallet Map</title>
<style>
  :root{color-scheme:dark}
  body{margin:0;background:#0b0e14;color:#9fb3c8;font:13px/1.5 ui-monospace,Menlo,monospace}
  header{padding:10px 16px;border-bottom:1px solid #1c2530;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
  header b{color:#e2e8f0}
  #stat{color:#64748b}
  .legend span{margin-right:12px}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px;vertical-align:middle}
  svg{width:100vw;height:calc(100vh - 46px);display:block;cursor:grab}
  circle{stroke:#0b0e14;stroke-width:0.5}
  line{stroke:#334155;stroke-width:0.5;opacity:.45}
  input{background:#111824;border:1px solid #243140;color:#cbd5e1;padding:3px 6px;border-radius:4px;width:340px}
</style></head>
<body>
<header>
  <b>wallet map</b>
  <input id="token" placeholder="filter by token mint (blank = all)">
  <span class="legend">
    <span><i class="dot" style="background:#f59e0b"></i>token</span>
    <span><i class="dot" style="background:#a78bfa"></i>program</span>
    <span><i class="dot" style="background:#38bdf8"></i>wallet</span>
  </span>
  <span id="stat">loading…</span>
</header>
<svg id="g"><g id="edges"></g><g id="nodes"></g></svg>
<script>
const SVG=document.getElementById('g'),GE=document.getElementById('edges'),GN=document.getElementById('nodes');
const NS='http://www.w3.org/2000/svg';
let W=innerWidth,H=innerHeight-46,nodes=new Map(),edges=[],els=new Map(),lns=[];
function color(k){return k==='token'?'#f59e0b':k==='program'?'#a78bfa':'#38bdf8'}
function rad(k){return k==='token'?10:k==='program'?7:4}
function merge(data){
  const incoming=new Set();
  for(const n of data.nodes){incoming.add(n.addr);
    if(!nodes.has(n.addr)){nodes.set(n.addr,{...n,x:W/2+(Math.random()-.5)*200,y:H/2+(Math.random()-.5)*200,vx:0,vy:0});}
    else Object.assign(nodes.get(n.addr),{kind:n.kind,hits:n.hits});}
  edges=data.edges.filter(e=>nodes.has(e.from)&&nodes.has(e.to));
  // (re)build dom
  GN.innerHTML='';GE.innerHTML='';els.clear();lns=[];
  for(const e of edges){const l=document.createElementNS(NS,'line');
    if(e.kind==='signs')l.style.stroke='#2dd4bf';GE.appendChild(l);lns.push([l,e]);}
  for(const n of nodes.values()){const c=document.createElementNS(NS,'circle');
    c.setAttribute('r',rad(n.kind));c.setAttribute('fill',color(n.kind));
    const t=document.createElementNS(NS,'title');t.textContent=n.addr+' ('+n.kind+', hits='+n.hits+')';
    c.appendChild(t);c.onclick=()=>window.open('https://solscan.io/account/'+n.addr,'_blank');
    GN.appendChild(c);els.set(n.addr,c);}
  document.getElementById('stat').textContent=nodes.size+' wallets · '+edges.length+' edges';
}
function tick(){
  const arr=[...nodes.values()];
  for(let i=0;i<arr.length;i++){const a=arr[i];
    for(let j=i+1;j<arr.length;j++){const b=arr[j];
      let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy||1,f=320/d2;
      let d=Math.sqrt(d2);dx/=d;dy/=d;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f;}}
  for(const e of edges){const a=nodes.get(e.from),b=nodes.get(e.to);
    let dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)||1,f=(d-70)*0.005;
    dx/=d;dy/=d;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f;}
  for(const n of nodes.values()){
    n.vx+=(W/2-n.x)*0.0012;n.vy+=(H/2-n.y)*0.0012;
    if(n.kind==='token'){n.x=W/2;n.y=H/2;n.vx=n.vy=0;continue;}
    n.vx*=0.85;n.vy*=0.85;n.x+=n.vx;n.y+=n.vy;
    n.x=Math.max(8,Math.min(W-8,n.x));n.y=Math.max(8,Math.min(H-8,n.y));
    const c=els.get(n.addr);if(c){c.setAttribute('cx',n.x);c.setAttribute('cy',n.y);}}
  for(const [l,e] of lns){const a=nodes.get(e.from),b=nodes.get(e.to);
    l.setAttribute('x1',a.x);l.setAttribute('y1',a.y);l.setAttribute('x2',b.x);l.setAttribute('y2',b.y);}
  requestAnimationFrame(tick);
}
async function poll(){try{const t=document.getElementById('token').value.trim();
  const r=await fetch('/dapp/api/wallet-map-data?limit=600'+(t?'&token='+encodeURIComponent(t):''));
  merge(await r.json());}catch(e){document.getElementById('stat').textContent='poll error: '+e;}}
addEventListener('resize',()=>{W=innerWidth;H=innerHeight-46;});
poll();tick();setInterval(poll,5000);
document.getElementById('token').addEventListener('change',()=>{nodes.clear();poll();});
</script>
</body></html>"""

# Godot Instant Games — HTML5 build path (future export target).
GODOT_BUILD_DIR = _PROJECT_ROOT / "studio" / "godot" / "builds" / "web_instant_games"
GODOT_BUILD_INDEX = GODOT_BUILD_DIR / "index.html"
GODOT_BUILD_EMBED_SRC = "/studio/godot/builds/web_instant_games/index.html"

# Facebook Instant Games launcher.
FB_INSTANT_APP_ID = os.environ.get("FB_INSTANT_APP_ID", "").strip()

# Limits + magic bytes for image sniffing.
MAX_PHOTO_BYTES = 8 * 1024 * 1024  # 8 MB
_IMAGE_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff",       "image/jpeg"),
    (b"GIF87a",             "image/gif"),
    (b"GIF89a",             "image/gif"),
    (b"RIFF",               "image/webp"),  # WEBP starts with RIFF....WEBP
    (b"BM",                 "image/bmp"),
]

# Single-tenant branding constants (mirrors freetier_callback shape).
BRANDING: Dict[str, str] = {
    "brand_name":  "MySpace++",
    "brand_sub":   "dApp · single-tenant",
    "brand_mark":  "M",
    "brand_bg":    "#5b8def",
    "brand_fg":    "#ffffff",
    "theme_color": "#5b8def",
}


# ---------------------------------------------------------------------------
# Template render (stdlib, no Jinja)
# ---------------------------------------------------------------------------

def _read_template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _substitute(text: str, mapping: Dict[str, str]) -> str:
    for k, v in mapping.items():
        text = text.replace("{" + k + "}", v)
    return text


def _render_page(inner_template: str, inner_vars: Dict[str, str],
                  title_suffix: str = "") -> str:
    inner = _substitute(_read_template(inner_template), {**BRANDING, **inner_vars})
    title = BRANDING["brand_name"] + (f" · {title_suffix}" if title_suffix else "")
    return _substitute(_read_template("base.html"),
                          {**BRANDING, "content": inner, "title": title})


def _render_inner(inner_template: str, inner_vars: Dict[str, str]) -> str:
    """Render just the inner template (for HTMX swaps)."""
    return _substitute(_read_template(inner_template), {**BRANDING, **inner_vars})


# ---------------------------------------------------------------------------
# Product card loading
# ---------------------------------------------------------------------------

def _load_products() -> List[Dict[str, Any]]:
    """Read every product card JSON from studio/assets/_products/."""
    products: List[Dict[str, Any]] = []
    if not PRODUCTS_DIR.exists():
        return products
    for p in sorted(PRODUCTS_DIR.glob("*.json")):
        try:
            products.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            sys.stderr.write(f"warn: bad product card {p.name}: {e}\n")
    return products


def _render_product_card(prod: Dict[str, Any]) -> str:
    """Produce one card's HTML block for /dapp/services."""
    name = html.escape(str(prod.get("name", "(unnamed)")))
    tagline = html.escape(str(prod.get("tagline", "")))
    status = html.escape(str(prod.get("status", "")))
    monthly = prod.get("monthly_recurring_usd", []) or []
    monetization = prod.get("monetization_channels", []) or []
    mon_html = "".join(
        f'<li><code>{html.escape(str(m))}</code></li>' for m in monetization
    ) or '<li class="meta">(none)</li>'

    # Default price: first non-zero monthly_recurring_usd (in cents),
    # else 100 ($1.00) as a smoke fallback.
    price_cents = 100
    for v in monthly:
        try:
            iv = int(v)
            if iv > 0:
                price_cents = iv * 100
                break
        except Exception:
            continue
    price_str = f"${price_cents/100:.2f}"

    return _substitute(_read_template("_product_card.html"), {
        "name":            name,
        "tagline":         tagline,
        "status":          status,
        "monetization":    mon_html,
        "price_str":       html.escape(price_str),
        "price_cents":     str(price_cents),
        "amount_micro":    str(price_cents * 10_000),  # cents → USDC micro (6 dec)
        "product_slug":    html.escape(str(prod.get("name", ""))),
        **BRANDING,
    })


# ---------------------------------------------------------------------------
# Photo upload helpers
# ---------------------------------------------------------------------------

def _sniff_image_mime(data: bytes) -> str:
    """Return image/* MIME from magic bytes, or '' if not an image."""
    for magic, mime in _IMAGE_MAGIC:
        if data.startswith(magic):
            # WEBP: confirm 'WEBP' at offset 8
            if mime == "image/webp" and not (len(data) >= 12 and data[8:12] == b"WEBP"):
                continue
            return mime
    return ""


# ---------------------------------------------------------------------------
# Godot Instant Games · SDK bridge JS (served at /dapp/play/sdk-bridge.js)
# ---------------------------------------------------------------------------

_SDK_BRIDGE_JS = """(function(){
  window.MspcDappBridge = {
    token: window.__mspc_freetier_token || '',
    setToken: function(t) { window.__mspc_freetier_token = t; this.token = t; localStorage.setItem('mspc_freetier_token', t); },
    loadToken: function() { var t = localStorage.getItem('mspc_freetier_token'); if (t) this.token = t; return this.token; },
    sendEvent: function(event_name, player_id, context_id, signed_data, payload) {
      return fetch('/dapp/api/fb_event', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + this.token,
          'Content-Type': 'application/json',
          'HX-Request': 'false'
        },
        body: JSON.stringify({event_name: event_name, player_id: player_id, context_id: context_id, signed_data: signed_data, payload: payload})
      }).then(function(r){ return r.json(); });
    },
    fetchSocialGraph: function(player_id) {
      return fetch('/dapp/api/social_graph?player_id=' + encodeURIComponent(player_id), {
        headers: {'Authorization': 'Bearer ' + this.token}
      }).then(function(r){ return r.json(); });
    }
  };
  window.MspcDappBridge.loadToken();
})();
"""


def _fb_play_url() -> str:
    """Return the public FB Instant Games launcher URL, or the local embed fallback."""
    if FB_INSTANT_APP_ID:
        return f"https://www.facebook.com/instantgames/play/{FB_INSTANT_APP_ID}"
    return "/dapp/play/embed"


def _godot_build_present() -> bool:
    try:
        return GODOT_BUILD_INDEX.is_file()
    except Exception:
        return False


def _seed_social_graph(player_id: str) -> Dict[str, Any]:
    """Deterministic seed for /dapp/api/social_graph when social_graph_persistence is absent."""
    seed_players = [
        {"id": "tom",     "display_name": "tom",     "planet_color": "#5b8def", "sun": True},
        {"id": "alice",   "display_name": "alice",   "planet_color": "#f0b04a"},
        {"id": "bob",     "display_name": "bob",     "planet_color": "#a45bf0"},
        {"id": "carol",   "display_name": "carol",   "planet_color": "#4af0a8"},
    ]
    seed_friendships = [
        {"a": player_id or "tom", "b": "alice", "strength": 0.84},
        {"a": player_id or "tom", "b": "bob",   "strength": 0.61},
        {"a": player_id or "tom", "b": "carol", "strength": 0.42},
        {"a": "alice", "b": "bob",   "strength": 0.33},
    ]
    return {
        "players":     seed_players,
        "friendships": seed_friendships,
        "source":      "seed",
        "player_id":   player_id,
    }


def _load_social_graph(player_id: str) -> Dict[str, Any]:
    """Try social_graph_persistence; fall back to seed. Never raises."""
    try:
        import social_graph_persistence  # type: ignore  # noqa: F401
        load_fn = (
            getattr(social_graph_persistence, "load_graph", None)
            or getattr(social_graph_persistence, "get_graph", None)
            or getattr(social_graph_persistence, "load", None)
        )
        if callable(load_fn):
            result = load_fn(player_id) if player_id else load_fn()
            if isinstance(result, dict):
                result.setdefault("source", "social_graph_persistence")
                result.setdefault("player_id", player_id)
                return result
    except Exception as e:
        sys.stderr.write(f"warn: social_graph_persistence unavailable: "
                          f"{type(e).__name__}: {e}\n")
    return _seed_social_graph(player_id)


def _record_fb_event(event_name: str, player_id: str, context_id: str,
                       signed_data: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Try FBInstantGamesConnector.record_event; fall back to no-op. Never raises."""
    try:
        import fb_instant_games  # type: ignore
        connector_cls = getattr(fb_instant_games, "FBInstantGamesConnector", None)
        if connector_cls is None:
            return {"ok": False, "backend": "missing_class",
                      "error": "FBInstantGamesConnector not in fb_instant_games"}
        connector = connector_cls()
        record_fn = getattr(connector, "record_event", None)
        if not callable(record_fn):
            return {"ok": False, "backend": "missing_method",
                      "error": "record_event not callable"}
        result = record_fn(
            event_name=event_name,
            player_id=player_id,
            context_id=context_id,
            signed_data=signed_data,
            payload=payload,
        )
        if isinstance(result, dict):
            result.setdefault("ok", True)
            result.setdefault("backend", "fb_instant_games")
            return result
        return {"ok": True, "backend": "fb_instant_games", "result": str(result)[:120]}
    except Exception as e:
        return {"ok": False, "backend": "exception",
                  "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Morph plan resolver — identity_resolver + morph_game_runtime (both lazy)
# ---------------------------------------------------------------------------

def _stub_morph_plan(persona_id: str) -> Dict[str, Any]:
    """Returned when identity_resolver or morph_game_runtime aren't available
    yet. Shape mirrors the future ScenePlan asdict() so the Godot loader and
    play_morph.html JS branches don't break.
    """
    return {
        "persona_id":      persona_id or "unknown",
        "inferred_role":   "unknown",
        "primary_face":    "play_default",
        "godot_scene":     "scenes/main.tscn",
        "crystal":         "",
        "custom_css_vars": {"--accent": BRANDING["brand_bg"]},
        "stub":            True,
    }


def _build_morph_plan(claims: "TokenClaims") -> Dict[str, Any]:
    """Resolve persona → ScenePlan via identity_resolver + morph_game_runtime.
    On any import or resolution failure: return a stub plan (status still 200)
    so the Godot side and the morph HTMX panel keep functioning. Inline logs
    to inference_logger when available; never raises.
    """
    persona_id_seed = getattr(claims, "user_id", "") or "unknown"
    plan_dict: Dict[str, Any]
    try:
        import identity_resolver  # type: ignore
        import morph_game_runtime  # type: ignore
        resolve_fn = getattr(identity_resolver, "resolve", None)
        plan_for = getattr(morph_game_runtime, "plan_for", None)
        if not callable(resolve_fn) or not callable(plan_for):
            raise RuntimeError("identity_resolver.resolve or morph_game_runtime.plan_for missing")
        # Pass the raw bearer-side proxy: claims (and user_id) is what
        # identity_resolver consumes — agent F may choose either token-or-claims.
        persona = resolve_fn(persona_id_seed)
        plan = plan_for(persona)
        # Prefer dataclass-style asdict() output; fall back to whatever shape.
        try:
            from dataclasses import asdict, is_dataclass
            if is_dataclass(plan):
                plan_dict = asdict(plan)
            elif isinstance(plan, dict):
                plan_dict = dict(plan)
            else:
                plan_dict = {"persona_id": persona_id_seed, "raw": str(plan)[:256]}
        except Exception:
            plan_dict = (plan if isinstance(plan, dict)
                         else {"persona_id": persona_id_seed, "raw": str(plan)[:256]})
        plan_dict.setdefault("persona_id", persona_id_seed)
        plan_dict.setdefault("inferred_role", "unknown")
        plan_dict.setdefault("primary_face", "play_default")
        plan_dict.setdefault("godot_scene", "scenes/main.tscn")
        plan_dict.setdefault("crystal", "")
        plan_dict.setdefault("custom_css_vars",
                              {"--accent": BRANDING["brand_bg"]})
    except Exception as e:
        sys.stderr.write(
            f"warn: morph_plan stubbed — {type(e).__name__}: {e}\n"
        )
        plan_dict = _stub_morph_plan(persona_id_seed)

    # Inline log — never blocks the response.
    try:
        from inference_logger import InferenceLogger  # type: ignore
        InferenceLogger().log(
            original_prompt=f"dapp.morph_plan:{persona_id_seed}",
            enhanced_prompt=json.dumps(
                {"persona_id": plan_dict.get("persona_id"),
                 "inferred_role": plan_dict.get("inferred_role"),
                 "primary_face": plan_dict.get("primary_face")},
                separators=(",", ":"), default=str,
            )[:512],
            output_text=json.dumps(
                {"godot_scene": plan_dict.get("godot_scene"),
                 "stub": plan_dict.get("stub", False)},
                separators=(",", ":"), default=str,
            )[:256],
            tier="morph_plan_served",
            model="dapp_morph_route",
            scope="morph_plan_get",
            tokens_in=0, tokens_out=0, latency_ms=0,
            source_file=f"user:{persona_id_seed}",
            source_action="dapp.morph_plan",
            done_flag=True, rc=0,
        )
    except Exception as e:
        sys.stderr.write(
            f"warn: morph_plan inference log skipped: {type(e).__name__}: {e}\n"
        )
    return plan_dict


# ---------------------------------------------------------------------------
# pump_surf — WaveFrame resolver (parallel agents A + F + B/C/D outputs)
# ---------------------------------------------------------------------------

PUMP_STREAM_DIR = Path.home() / ".cc" / "pump_stream"
PUMP_GATE_DECISIONS = Path.home() / ".cc" / "pump_surf_gate_decisions.json"


def _stub_wave_frame() -> Dict[str, Any]:
    """Returned when pump_visualizer_3d or events aren't available yet.
    Shape mirrors the future WaveFrame so the Godot loader + HTMX panel
    don't break.
    """
    return {
        "surf_state":         "no_signal",
        "bot_density_avg":    0,
        "human_inflow_score": 0,
        "ripples":            [],
        "crystal":            "",
        "stub":               True,
    }


def _latest_pump_events_path() -> Optional[Path]:
    """Return the most-recent .jsonl events file in ~/.cc/pump_stream/, or None."""
    try:
        if not PUMP_STREAM_DIR.is_dir():
            return None
        candidates = sorted(
            (p for p in PUMP_STREAM_DIR.glob("*.jsonl") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None
    except Exception:
        return None


def _load_pump_events(window_seconds: int = 60) -> List[Dict[str, Any]]:
    """Load the latest pump events. Tries pump_stream_ingest.replay_jsonl when
    importable; otherwise reads the latest .jsonl by mtime line-by-line. Never
    raises. Returns [] on any failure.
    """
    path = _latest_pump_events_path()
    if path is None:
        return []
    # Prefer the canonical replay path when agent A's module is present.
    try:
        import pump_stream_ingest  # type: ignore
        replay_fn = getattr(pump_stream_ingest, "replay_jsonl", None)
        if callable(replay_fn):
            result = replay_fn(str(path))
            if isinstance(result, list):
                return result
            # generator → list
            try:
                return list(result)
            except Exception:
                pass
    except Exception as e:
        sys.stderr.write(
            f"warn: pump_stream_ingest.replay_jsonl unavailable: "
            f"{type(e).__name__}: {e}\n"
        )
    # Fallback: read the JSONL directly.
    events: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        sys.stderr.write(
            f"warn: pump_stream jsonl read failed: {type(e).__name__}: {e}\n"
        )
    return events


def _load_pump_gate_decisions() -> Dict[str, Any]:
    """Load ~/.cc/pump_surf_gate_decisions.json (sibling agents B+C+D output).
    Returns {} when absent or malformed. Never raises.
    """
    try:
        if not PUMP_GATE_DECISIONS.is_file():
            return {}
        with PUMP_GATE_DECISIONS.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {"_raw": data}
    except Exception as e:
        sys.stderr.write(
            f"warn: pump_surf_gate_decisions read failed: {type(e).__name__}: {e}\n"
        )
        return {}


def _build_pump_wave(claims: "TokenClaims") -> Dict[str, Any]:
    """Resolve the latest WaveFrame via pump_visualizer_3d.build_wave_frame.
    On any import or build failure: return a stub WaveFrame (status still 200)
    so the Godot side + the HTMX surf radar keep functioning. Inline log to
    inference_logger when available; never raises.
    """
    events = _load_pump_events()
    gates = _load_pump_gate_decisions()
    frame_dict: Dict[str, Any]
    try:
        import pump_visualizer_3d  # type: ignore
        build_fn = getattr(pump_visualizer_3d, "build_wave_frame", None)
        if not callable(build_fn):
            raise RuntimeError("pump_visualizer_3d.build_wave_frame missing")
        frame = build_fn(events, gates, window_seconds=60)
        try:
            from dataclasses import asdict, is_dataclass
            if is_dataclass(frame):
                frame_dict = asdict(frame)
            elif isinstance(frame, dict):
                frame_dict = dict(frame)
            else:
                frame_dict = {"raw": str(frame)[:256]}
        except Exception:
            frame_dict = (frame if isinstance(frame, dict)
                          else {"raw": str(frame)[:256]})
        frame_dict.setdefault("surf_state",         "no_signal")
        frame_dict.setdefault("bot_density_avg",    0)
        frame_dict.setdefault("human_inflow_score", 0)
        frame_dict.setdefault("ripples",            [])
        frame_dict.setdefault("crystal",            "")
    except Exception as e:
        sys.stderr.write(
            f"warn: pump_wave stubbed — {type(e).__name__}: {e}\n"
        )
        frame_dict = _stub_wave_frame()

    # Inline log — never blocks the response.
    try:
        from inference_logger import InferenceLogger  # type: ignore
        InferenceLogger().log(
            original_prompt=f"dapp.pump_wave:{getattr(claims, 'user_id', '')}",
            enhanced_prompt=json.dumps(
                {"events": len(events),
                 "gates_present": bool(gates),
                 "surf_state": frame_dict.get("surf_state")},
                separators=(",", ":"), default=str,
            )[:512],
            output_text=json.dumps(
                {"bot_density_avg": frame_dict.get("bot_density_avg"),
                 "human_inflow_score": frame_dict.get("human_inflow_score"),
                 "ripples_n": len(frame_dict.get("ripples") or []),
                 "stub": frame_dict.get("stub", False)},
                separators=(",", ":"), default=str,
            )[:256],
            tier="pump_wave_served",
            model="dapp_pump_route",
            scope="wave_get",
            tokens_in=0, tokens_out=0, latency_ms=0,
            source_file=f"user:{getattr(claims, 'user_id', '')}",
            source_action="dapp.pump_wave",
            done_flag=True, rc=0,
        )
    except Exception as e:
        sys.stderr.write(
            f"warn: pump_wave inference log skipped: {type(e).__name__}: {e}\n"
        )
    return frame_dict


# ---------------------------------------------------------------------------
# Crystal-anchor every action (defensive — never blocks the response)
# ---------------------------------------------------------------------------

def _anchor(tier: str, model: str, scope: str, source_file: str,
              payload: Dict[str, Any], rc: int = 0) -> str:
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=f"dapp.{model}",
            enhanced_prompt=json.dumps(
                {k: v for k, v in payload.items() if k != "photo_b64"},
                separators=(",", ":"), default=str,
            )[:512],
            output_text=json.dumps({"scope": scope, "rc": rc},
                                     separators=(",", ":"))[:256],
            tier=tier, model=model, scope=scope,
            tokens_in=0, tokens_out=0, latency_ms=0,
            source_file=source_file or "",
            source_action=f"dapp.{model}",
            done_flag=(rc == 0), rc=rc,
        ) or ""
    except Exception as e:
        sys.stderr.write(f"warn: dapp crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Stream registry + sidecar (append-only JSONL; mirrors media/.tools/sidecar)
# ---------------------------------------------------------------------------

def _load_streams() -> List[Dict[str, Any]]:
    if not STREAMS_FILE.exists():
        return []
    by_id: Dict[str, Dict[str, Any]] = {}
    for line in STREAMS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        sid = r.get("stream_id")
        if not sid:
            continue
        if sid in by_id:
            by_id[sid].update(r)  # last write wins (lets us patch video_path)
        else:
            by_id[sid] = r
    return list(by_id.values())


def _append_stream(rec: Dict[str, Any]) -> None:
    STREAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STREAMS_FILE.open("a") as f:
        f.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")


def _update_stream(stream_id: str, patch: Dict[str, Any]) -> None:
    patch = {"stream_id": stream_id, **patch}
    _append_stream(patch)


def _glb_anim_count(path: Path) -> int:
    """Cheap: read a .glb's JSON chunk and count animations (no full parse)."""
    try:
        import struct
        with path.open("rb") as f:
            if f.read(4) != b"glTF":
                return 0
            f.read(8)  # version + total length
            jlen = struct.unpack("<I", f.read(4))[0]
            f.read(4)  # chunk type
            doc = json.loads(f.read(jlen))
        return len(doc.get("animations", []) or [])
    except Exception:
        return 0


def _list_assets3d() -> List[Dict[str, Any]]:
    if not GEN3D_DIR.exists():
        return []
    out = []
    for glb in sorted(GEN3D_DIR.glob("*.glb"), reverse=True):
        try:
            st = glb.stat()
        except OSError:
            continue
        anims = _glb_anim_count(glb)
        out.append({"stem": glb.stem, "bytes": st.st_size,
                    "mtime": st.st_mtime, "animated": anims > 0,
                    "animations": anims,
                    "url": f"/dapp/api/asset3d?stem={glb.stem}"})
    return out


def _write_sidecar(media_path: Path, **fields: Any) -> Path:
    """Minimal JSON sidecar next to a media file (mirrors the shape of
    studio/media/.tools/sidecar.write without importing the dotted-dir module)."""
    side = media_path.with_suffix(media_path.suffix + ".json")
    data = {"media": media_path.name, "written_at": time.time(), **fields}
    side.write_text(json.dumps(data, indent=2, default=str))
    return side


# ---------------------------------------------------------------------------
# LOOM fragment builders
# ---------------------------------------------------------------------------
# loom_ui.py owns the full shell page (loom_html / shell_page). The HTMX
# endpoints below need small HTML *fragments* (shelf icon, chat reply, scope
# card deck) that match the CSS classes loom_ui.py already defines. We render
# them here in server.py (the integrator file) following the §4.3/4.4/4.5
# HTML contracts so the two halves stay in lockstep without editing loom_ui.

def _loom_shelf_icon(scope: Dict[str, Any]) -> str:
    """§4.5 — one shelf <button> for a minted scope. hx-get loads its card."""
    sid   = html.escape(str(scope.get("scope_id", "")))
    label = html.escape(str(scope.get("label", "")))
    arche = html.escape(str(scope.get("archetype", "")))
    glyph = html.escape(str(scope.get("glyph", "◆")))
    return (
        f'<button class="scope-icon" title="{label} · {arche}" '
        f'hx-get="/dapp/api/loom/scope?id={urllib.parse.quote(str(scope.get("scope_id","")))}" '
        f'hx-target="#workspace" hx-swap="innerHTML">{glyph}</button>'
    )


def _loom_shelf_icons(scopes: List[Dict[str, Any]]) -> str:
    """The #shelf-scopes fill (HTMX load). Empty list -> empty string."""
    return "".join(_loom_shelf_icon(s) for s in scopes)


def _loom_chat_reply_fragment(intent: str, g: Dict[str, Any]) -> str:
    """§4.3 — user bubble + assistant bubble (reply + kernel chips) + a Confirm
    <form> pre-filled with proposed_label/proposed_chain_spec that hx-posts mint."""
    reply  = html.escape(str(g.get("reply", "")))
    label  = html.escape(str(g.get("proposed_label", "")))
    spec   = html.escape(str(g.get("proposed_chain_spec", "")))
    arche  = html.escape(str(g.get("proposed_archetype", "morph")))
    chips = "".join(
        f'<span class="chip">{html.escape(str(k.get("id","")))}</span>'
        for k in (g.get("candidate_kernels") or [])
    )
    val = g.get("validation") or {}
    bound = val.get("kernels_bound", 0)
    errs  = val.get("errors") or []
    val_cls = "ok" if val.get("ok") else "bad"
    val_txt = f"{bound} kernels bound"
    if errs:
        val_txt += " · " + html.escape("; ".join(str(e) for e in errs[:3]))
    return (
        f'<div class="bubble user">{html.escape(intent)}</div>'
        f'<div class="bubble bot">'
        f'<p>{reply}</p>'
        f'<div class="chips">{chips}</div>'
        f'<form class="confirm" hx-post="/dapp/api/loom/mint" '
        f'hx-target="#shelf-scopes" hx-swap="beforeend" '
        f'hx-on::after-request="if(event.detail.successful){{'
        f"document.getElementById('chat-panel').hidden=true;}}\">"
        f'<input type="hidden" name="intent" value="{html.escape(intent)}">'
        f'<input type="hidden" name="archetype" value="{arche}">'
        f'<label>name<input name="label" value="{label}"></label>'
        f'<label>pipeline<input name="chain_spec" value="{spec}"></label>'
        f'<div class="val {val_cls}">{val_txt}</div>'
        f'<button type="submit">Confirm → mint scope</button>'
        f'</form>'
        f'</div>'
    )


def _loom_msg_bubble(m: Dict[str, Any]) -> str:
    """One chat-hub message bubble. A 'you' message = user bubble; bot/governor
    = bot bubble (with a Confirm→mint form when the bot proposed a scope)."""
    author = str(m.get("author", ""))
    text = html.escape(str(m.get("text", "")))
    if author == "you":
        return f'<div class="bubble user">{text}</div>'
    cls = "bot gov" if author == "governor" else "bot"
    who = html.escape(author or "bot")
    extra = ""
    if m.get("action") == "confirm_mint" and m.get("proposed_chain_spec"):
        label = html.escape(str(m.get("proposed_label", "")))
        spec = html.escape(str(m.get("proposed_chain_spec", "")))
        extra = (
            f'<form class="confirm" hx-post="/dapp/api/loom/mint" '
            f'hx-target="#shelf-scopes" hx-swap="beforeend">'
            f'<input type="hidden" name="intent" value="{text}">'
            f'<label>name<input name="label" value="{label}"></label>'
            f'<label>pipeline<input name="chain_spec" value="{spec}"></label>'
            f'<button type="submit">Confirm → mint scope</button></form>')
    return f'<div class="bubble {cls}"><span class="who">{who}</span><p>{text}</p>{extra}</div>'


def _loom_messages_fragment(msgs: List[Dict[str, Any]]) -> str:
    return "".join(_loom_msg_bubble(m) for m in msgs) or \
        '<div class="muted" style="color:#475569;font-size:12px">no messages yet</div>'


def _loom_widget_html(w: Dict[str, Any]) -> str:
    """Render one to_cards widget as a labelled read-only control (first cut)."""
    name = html.escape(str(w.get("name", "")))
    kind = str(w.get("widget", "text"))
    val  = html.escape(str(w.get("value", "")))
    opts = w.get("options") or []
    if kind == "select" and opts:
        body = "".join(
            f'<option{" selected" if str(o) == str(w.get("value","")) else ""}>'
            f'{html.escape(str(o))}</option>' for o in opts
        )
        ctrl = f'<select disabled>{body}</select>'
    elif kind == "toggle":
        checked = " checked" if str(w.get("value")).lower() in ("1", "true", "yes", "on") else ""
        ctrl = f'<input type="checkbox" disabled{checked}>'
    else:
        ctrl = f'<input type="text" value="{val}" readonly>'
    return f'<label>{name}{ctrl}</label>'


def _loom_card_html(card: Dict[str, Any]) -> str:
    """One morph.engine card (§4.4)."""
    kind  = str(card.get("kind", "transform"))
    cls   = "card decision" if card.get("hitl") else f"card {html.escape(kind)}"
    title = html.escape(str(card.get("title", "")))
    when  = html.escape(str(card.get("when", "")))
    why   = html.escape(str(card.get("why", "")))
    widgets = "".join(_loom_widget_html(w) for w in (card.get("widgets") or []))
    return (
        f'<article class="{cls}">'
        f'<header>{title}<span class="when">{when}</span></header>'
        f'<p class="why">{why}</p>'
        f'<div class="widgets">{widgets}</div>'
        f'</article>'
    )


def _loom_workspace_card(scope: Dict[str, Any], cards: List[Dict[str, Any]]) -> str:
    """§4.4 — scope header + the stacked morph deck (.deck is column-reverse in
    loom_ui CSS, so node 0 sits at the bottom; we emit cards in file order)."""
    glyph = html.escape(str(scope.get("glyph", "◆")))
    label = html.escape(str(scope.get("label", "")))
    arche = html.escape(str(scope.get("archetype", "")))
    spec  = html.escape(str(scope.get("chain_spec", "")))
    deck = "".join(_loom_card_html(c) for c in cards)
    return (
        f'<div class="scope-head"><span class="glyph">{glyph}</span>'
        f'<b>{label}</b> <span class="arch">{arche}</span>'
        f'<code class="spec">{spec}</code>'
        f'<button class="home" hx-get="/dapp/api/loom/hub" '
        f'hx-target="#workspace" hx-swap="innerHTML">⌂ chat</button></div>'
        f'<div class="deck">{deck}</div>'
    )


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class DappHandler(BaseHTTPRequestHandler):
    server_version = "MspcDapp/0.1"

    # ---- response helpers ------------------------------------------------

    def _send(self, status: int, body: str,
                content_type: str = "text/html; charset=utf-8",
                extra_headers: Optional[Dict[str, str]] = None) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, default=str),
                     content_type="application/json")

    def _headers_dict(self) -> Dict[str, str]:
        return {k: v for k, v in self.headers.items()}

    def _is_htmx(self) -> bool:
        return self.headers.get("HX-Request", "").lower() == "true"

    def _claims_or_unauth(self) -> Optional[TokenClaims]:
        """Return claims if Authorization bearer is valid, else 401 + None."""
        claims = require_token(self._headers_dict())
        if claims is None:
            if self._is_htmx():
                self._send(401, _render_inner("unauthed.html", BRANDING))
            else:
                self._send(401, _render_page("unauthed.html", {}, "unauthorized"))
            return None
        return claims

    def _client_ip(self) -> str:
        xff = self.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0]

    # ---- GET --------------------------------------------------------------

    def _loom_tenant(self, parsed) -> None:
        """Isolate this request to its tenant (X-Loom-Tenant header or ?tenant=).
        Clones never see root's state; default tenant is 'root'."""
        if "/loom" not in parsed.path:
            return
        try:
            import loom
            t = (self.headers.get("X-Loom-Tenant", "")
                 or urllib.parse.parse_qs(parsed.query).get("tenant", ["root"])[0]
                 or "root")
            loom.set_tenant(t)
        except Exception:
            pass

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        self._loom_tenant(parsed)

        if path == "/dapp/healthz":
            self._send_json(200, {"ok": True, "service": "dapp_server"})
            return

        if path == "/dapp/" or path == "/dapp":
            self.send_response(302)
            self.send_header("Location", "/dapp/services")
            self.end_headers()
            return

        if path == "/dapp/api/products":
            self._send_json(200, {"products": _load_products()})
            return

        if path == "/dapp/api/balance":
            addr = (query.get("addr", [""])[0] or "").strip()
            if not addr:
                self._send_json(400, {"error": "missing addr query param"})
                return
            self._send_json(200, self._fanout_balance(addr))
            return

        if path == "/dapp/services":
            cards = "".join(_render_product_card(p) for p in _load_products())
            inner_vars = {"product_cards": cards or '<p class="meta">No products configured.</p>'}
            if self._is_htmx():
                self._send(200, _render_inner("services.html", inner_vars))
            else:
                self._send(200, _render_page("services.html", inner_vars, "services"))
            return

        if path == "/dapp/mint":
            self._send(200, _render_page("mint.html", {}, "mint"))
            return

        if path == "/dapp/wallet":
            self._send(200, _render_page("wallet.html", {}, "wallet"))
            return

        if path == "/dapp/play":
            inner_vars = {"fb_play_url": html.escape(_fb_play_url())}
            if self._is_htmx():
                self._send(200, _render_inner("play.html", inner_vars))
            else:
                self._send(200, _render_page("play.html", inner_vars, "play"))
            return

        if path == "/dapp/play/embed":
            if not _godot_build_present():
                inner_vars = {
                    "expected_path": html.escape(str(GODOT_BUILD_INDEX)),
                }
                self._send(200, _render_page("play_no_build.html", inner_vars, "play"))
                return
            inner_vars = {"embed_src": html.escape(GODOT_BUILD_EMBED_SRC)}
            self._send(200, _render_page("play_embed.html", inner_vars, "play"))
            return

        if path == "/dapp/play_morph":
            # PUBLIC — page itself renders fine without a token; the HTMX call
            # to /dapp/api/morph_plan from inside is bearer-gated.
            if not _godot_build_present():
                inner_vars = {
                    "expected_path": html.escape(str(GODOT_BUILD_INDEX)),
                }
                self._send(200, _render_page("play_no_build.html", inner_vars, "play"))
                return
            inner_vars = {
                "embed_src": html.escape(
                    GODOT_BUILD_EMBED_SRC + "?scene=morphing_game"
                ),
            }
            self._send(200, _render_page("play_morph.html", inner_vars, "play_morph"))
            return

        if path == "/dapp/api/morph_plan":
            claims = self._claims_or_unauth()
            if not claims:
                return
            self._send_json(200, _build_morph_plan(claims))
            return

        if path == "/dapp/pump_surf":
            # PUBLIC — page itself renders without a token; the in-page HTMX
            # poll to /dapp/api/pump_wave is bearer-gated.
            inner_vars = {
                "embed_src": html.escape(
                    GODOT_BUILD_EMBED_SRC + "?scene=pump_surf"
                ),
                "godot_build_present": "yes" if _godot_build_present() else "no",
            }
            self._send(200, _render_page("pump_surf.html", inner_vars, "pump_surf"))
            return

        if path == "/dapp/api/pump_wave":
            claims = self._claims_or_unauth()
            if not claims:
                return
            self._send_json(200, _build_pump_wave(claims))
            return

        if path == "/dapp/play/sdk-bridge.js":
            self._send(200, _SDK_BRIDGE_JS,
                         content_type="application/javascript; charset=utf-8",
                         extra_headers={"Cache-Control": "no-cache"})
            return

        if path == "/dapp/api/social_graph":
            claims = self._claims_or_unauth()
            if not claims:
                return
            player_id = (query.get("player_id", [""])[0] or "").strip()[:128]
            graph = _load_social_graph(player_id)
            if self._is_htmx():
                players = graph.get("players") or []
                friendships = graph.get("friendships") or []
                n_friends = sum(
                    1 for f in friendships
                    if isinstance(f, dict) and (
                        f.get("a") == player_id or f.get("b") == player_id
                    )
                )
                src = html.escape(str(graph.get("source", "?")))
                self._send(
                    200,
                    f'Friends in your graph: <b>{n_friends}</b> · '
                    f'players={len(players)} · source=<code>{src}</code> — '
                    f'<a class="link" href="/dapp/play/embed">open the planet map</a>',
                )
                return
            self._send_json(200, graph)
            return

        if path == "/dapp/wallet-map":
            # PUBLIC, read-only — live wallet-interaction graph (flat HTML+SVG).
            self._send(200, _WALLET_MAP_HTML)
            return

        if path == "/dapp/api/streams":
            self._send(200, json.dumps({"streams": _load_streams()}),
                       content_type="application/json",
                       extra_headers=_CORS_HEADERS)
            return

        if path == "/dapp/defi_loop":
            self._send(200, _DEFI_LOOP_HTML)  # PUBLIC dry-run simulator page
            return

        if path == "/dapp/api/assets3d":
            self._send(200, json.dumps({"assets": _list_assets3d()}),
                       content_type="application/json", extra_headers=_CORS_HEADERS)
            return

        if path == "/dapp/api/asset3d":
            stem = (query.get("stem", [""])[0] or "").strip()
            if not stem or "/" in stem or ".." in stem:
                self._send(400, json.dumps({"error": "bad stem"}),
                           content_type="application/json"); return
            glb = GEN3D_DIR / f"{stem}.glb"
            if not glb.exists():
                self._send(404, json.dumps({"error": "not found"}),
                           content_type="application/json"); return
            data = glb.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Content-Length", str(len(data)))
            for k, v in _CORS_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/dapp/api/wallet-map-data":
            token = (query.get("token", [""])[0] or "").strip()
            try:
                limit = int(query.get("limit", ["400"])[0])
            except ValueError:
                limit = 400
            graph = wmap.load_graph(token=token, limit=limit)
            self._send_json(200, graph)
            return

        # ---- LOOM shell (the first shippable face) ------------------------
        # PUBLIC — Loom is the free shell; the gear/account gate is a stub.
        # Each handler degrades to a clean JSON 500 (never a stack trace).
        if path == "/dapp/loom":
            try:
                import loom, loom_ui
                scopes = loom.list_scopes()
                self._send(200, loom_ui.shell_page(scopes))
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False,
                                      "error": f"{type(exc).__name__}: {exc}"})
            return

        if path == "/dapp/api/loom/scopes":
            try:
                import loom
                scopes = loom.list_scopes()
                if self._is_htmx():
                    self._send(200, _loom_shelf_icons(scopes))
                else:
                    self._cors_json(200, {"ok": True, "scopes": scopes})
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False,
                                      "error": f"{type(exc).__name__}: {exc}"})
            return

        if path == "/dapp/api/loom/connections":
            try:
                import loom
                self._cors_json(200, {"ok": True, "connections": loom.connections()})
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return

        if path == "/dapp/api/loom/hub":
            try:
                import loom_ui
                self._send(200, loom_ui.hub_html())
            except Exception as exc:  # noqa: BLE001
                self._send(500, f"<div class='muted'>hub error: {html.escape(str(exc))}</div>")
            return

        if path == "/dapp/api/loom/channels":
            try:
                import loom
                self._cors_json(200, {"ok": True, "channels": loom.channels()})
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return

        if path == "/dapp/api/loom/tenants":
            try:
                import loom
                self._cors_json(200, {"ok": True, "tenants": loom.tenants()})
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return

        if path == "/dapp/api/loom/messages":
            try:
                import loom
                ch = (query.get("channel", ["general"])[0] or "general").strip()
                msgs = loom.messages(ch)
                if self._is_htmx():
                    self._send(200, _loom_messages_fragment(msgs))
                else:
                    self._cors_json(200, {"ok": True, "channel": ch, "messages": msgs})
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return

        if path == "/dapp/api/loom/scope":
            try:
                import loom, morph_chain
                sid = (query.get("id", [""])[0] or "").strip()
                scope = loom.get_scope(sid)
                if not scope:
                    self._cors_json(404, {"ok": False, "error": "no such scope"})
                    return
                mc = (morph_chain.load(scope["morph_chain_id"])
                      or morph_chain.parse_spec(scope["chain_spec"]))
                cards = morph_chain.to_cards(mc)
                if self._is_htmx():
                    self._send(200, _loom_workspace_card(scope, cards))
                else:
                    self._cors_json(200, {"ok": True, "scope": scope, "cards": cards})
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False,
                                      "error": f"{type(exc).__name__}: {exc}"})
            return

        self._send(404, "<h1>404</h1><p>Path not found on this dApp.</p>")

    # ---- OPTIONS (CORS preflight for the extension ingest) ---------------

    def do_OPTIONS(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/dapp/api/"):
            self.send_response(204)
            for k, v in _CORS_HEADERS.items():
                self.send_header(k, v)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    # ---- POST -------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        self._loom_tenant(parsed)

        if path == "/dapp/api/buy":
            claims = self._claims_or_unauth()
            if not claims:
                return
            self._handle_buy(claims)
            return

        if path == "/dapp/api/mint":
            claims = self._claims_or_unauth()
            if not claims:
                return
            self._handle_mint(claims)
            return

        if path == "/dapp/api/fb_event":
            claims = self._claims_or_unauth()
            if not claims:
                return
            self._handle_fb_event(claims)
            return

        if path.startswith("/dapp/api/fb/"):
            # Facebook Games dev surface (debug_token/leaderboard/notification/...).
            # Gated on FB_INSTANT_APP_ID — returns fb_not_configured until you
            # create the FB app and set the env (user-action).
            self._handle_fb_games(path.rsplit("/", 1)[-1])
            return

        if path == "/dapp/api/solscan-ingest":
            # PUBLIC (no bearer) — the browser extension POSTs scraped wallets
            # from solscan.io. Read-only on chain; we just record what it saw.
            self._handle_solscan_ingest()
            return

        if path == "/dapp/api/stream-chroma":
            # PUBLIC — extension posts {token,page_url,duration,amps,...} on
            # stop. We chromatize the amplitudes and link the stream to the
            # page's token (→ its wallets) in the wallet map.
            self._handle_stream_chroma()
            return

        if path == "/dapp/api/stream-video":
            # PUBLIC — raw webm body for a stream_id registered by stream-chroma.
            self._handle_stream_video(parsed)
            return

        if path == "/dapp/api/defi/loop":
            # PUBLIC dry-run simulator only — web NEVER executes on-chain
            # (dry_run forced True regardless of body). Live looping is CLI +
            # confirm-gated (defi_loop.run_loop) by design.
            self._handle_defi_loop()
            return

        if path == "/dapp/api/swap":
            # PUBLIC dry-run quote/route only — web NEVER executes on-chain.
            # Live execution requires CLI + MSPC_SWAP_LIVE=1 + --confirm
            # (swap_router.execute) by design. Same gating shape as defi/loop.
            self._handle_swap()
            return

        if path == "/dapp/api/loom/snapshot":
            # PUBLIC — receives a base64 PNG from a Loom card's canvas and
            # kicks off the blob_to_unreal 5-pass pipeline (dry-run UDP by
            # default; web NEVER sends real UDP without MSPC_UNREAL_LIVE=1).
            self._handle_loom_snapshot()
            return

        # ---- LOOM chat + mint ---------------------------------------------
        # PUBLIC — Loom is the free shell. chat = ground() grounding; mint =
        # parse+save a starter MorphChain + append a scope row. Nothing here
        # spends money / trades / deploys. Each degrades to a clean JSON 500.
        if path == "/dapp/api/loom/chat":
            try:
                body = self._parse_json_or_form()
                intent = str(body.get("intent", "")).strip()[:1000]
                if not intent:
                    self._cors_json(400, {"ok": False, "error": "intent required"})
                    return
                import loom
                res = loom.ground(intent)
                if self._is_htmx():
                    self._send(200, _loom_chat_reply_fragment(intent, res))
                else:
                    self._cors_json(200, {"ok": True, **res})
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False,
                                      "error": f"{type(exc).__name__}: {exc}"})
            return

        if path == "/dapp/api/loom/mint":
            try:
                body = self._parse_json_or_form()
                spec   = str(body.get("chain_spec", "")).strip()
                label  = str(body.get("label", "")).strip()[:120]
                intent = str(body.get("intent", "")).strip()[:1000]
                arche  = str(body.get("archetype", "")).strip().lower()
                if not spec:
                    self._cors_json(400, {"ok": False, "error": "chain_spec required"})
                    return
                import loom, morph_chain
                scope = loom.mint(intent, spec, label=label, archetype=arche)
                mc = (morph_chain.load(scope["morph_chain_id"])
                      or morph_chain.parse_spec(scope["chain_spec"]))
                cards = morph_chain.to_cards(mc)
                if self._is_htmx():
                    self._send(
                        200, _loom_shelf_icon(scope),
                        extra_headers={"HX-Trigger": json.dumps(
                            {"loom-minted": scope["scope_id"]})})
                else:
                    self._cors_json(200, {"ok": True, "scope": scope, "cards": cards})
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False,
                                      "error": f"{type(exc).__name__}: {exc}"})
            return

        if path == "/dapp/api/loom/connect":
            # the inbox: an observed connection (login/session/email). The
            # governor (engine.morpher) auto-mints the matching scope onto the
            # shelf — "login collects and binds the workflow as they go."
            try:
                body = self._parse_json_or_form()
                service = str(body.get("service", "")).strip()[:120]
                kind = str(body.get("kind", "session")).strip().lower()
                label = str(body.get("label", "")).strip()[:120]
                if not service:
                    self._cors_json(400, {"ok": False, "error": "service required"})
                    return
                import loom
                res = loom.connect(service, kind=kind, label=label)
                self._cors_json(200, {"ok": True, **res})
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False,
                                      "error": f"{type(exc).__name__}: {exc}"})
            return

        if path == "/dapp/api/loom/clone":
            # launch an isolated clone tenant — inherits the engine, not the state
            try:
                body = self._parse_json_or_form()
                tid = str(body.get("tenant", "")).strip()[:48]
                label = str(body.get("label", "")).strip()[:120]
                if not tid:
                    self._cors_json(400, {"ok": False, "error": "tenant id required"})
                    return
                import loom
                self._cors_json(200, {"ok": True, "clone": loom.create_clone(tid, label)})
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False,
                                      "error": f"{type(exc).__name__}: {exc}"})
            return

        if path == "/dapp/api/loom/post":
            # post a message; in the bot DM ('loom') the governor grounds + offers mint
            try:
                body = self._parse_json_or_form()
                ch = str(body.get("channel", "general")).strip()[:64] or "general"
                text = str(body.get("text", "")).strip()[:4000]
                if not text:
                    self._cors_json(400, {"ok": False, "error": "text required"})
                    return
                import loom
                # post under the request's tenant (already set by _loom_tenant)
                res = loom.post(ch, text)
                if self._is_htmx():
                    frag = _loom_msg_bubble(res["message"])
                    if res.get("bot_reply"):
                        frag += _loom_msg_bubble(res["bot_reply"])
                    self._send(200, frag)
                else:
                    self._cors_json(200, {"ok": True, **res})
            except Exception as exc:  # noqa: BLE001
                self._cors_json(500, {"ok": False,
                                      "error": f"{type(exc).__name__}: {exc}"})
            return

        self._send(404, "<h1>404</h1>")

    def _handle_swap(self) -> None:
        """Quote + dry-run swap result over the 6 supported routes.
        Body: {"from_token": "SOL", "to_token": "USDC.sol", "amount": 1.0,
                "slippage_bps": 50}. Returns quote (Jupiter / Cetus / Wormhole)
        + dry-run SwapResult. Never executes a real swap from the web."""
        body = self._parse_json_or_form()
        try:
            from_token = str(body.get("from_token", "")).strip()
            to_token   = str(body.get("to_token", "")).strip()
            amount     = float(body.get("amount", 0))
            slippage   = int(body.get("slippage_bps", 50))
        except Exception as exc:
            self._cors_json(400, {"ok": False, "error": f"bad_body: {exc!r}"})
            return
        if not from_token or not to_token or amount <= 0:
            self._cors_json(400, {"ok": False,
                                    "error": "from_token/to_token/amount required"})
            return
        # Defensive import — swap_router is light but we want graceful 503 if it fails
        try:
            import sys as _sys
            from pathlib import Path as _Path
            _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]
                                     / "core" / "lib"))
            import swap_router  # type: ignore
        except Exception as exc:
            self._cors_json(503, {"ok": False, "error": f"swap_router_unavailable:{exc!r}"})
            return
        try:
            q = swap_router.quote(from_token, to_token, amount,
                                    slippage_bps=slippage)
        except ValueError as exc:
            self._cors_json(400, {"ok": False, "error": str(exc),
                                    "hint": "supported pairs: USDC.sol↔SOL, USDC.sui↔SUI, SOL↔SUI"})
            return
        # Always dry-run from the web — web NEVER executes on-chain.
        result = swap_router.execute(q, dry_run=True)
        from dataclasses import asdict as _asdict
        self._cors_json(200, {
            "ok": True,
            "quote": _asdict(q),
            "result": _asdict(result),
            "live_execute_path": "CLI only — cc swap-execute <from> <to> <amount> --confirm AND MSPC_SWAP_LIVE=1",
        })

    def _handle_loom_snapshot(self) -> None:
        """Receive base64 PNG from a Loom canvas + run blob_to_unreal pipeline.
        Body: {"png_b64": "<base64>", "card_crystal": "...", "duration_s": 5,
                "fps": 30, "subject_name": "MspcBlob"}.
        Returns the PipelineResult. UDP is dry-run unless MSPC_UNREAL_LIVE=1."""
        import base64 as _b64
        body = self._parse_json_or_form()
        try:
            png_b64 = body.get("png_b64", "")
            if png_b64.startswith("data:image/"):
                png_b64 = png_b64.split(",", 1)[-1]
            png_bytes = _b64.b64decode(png_b64)
        except Exception as exc:
            self._cors_json(400, {"ok": False, "error": f"bad_png_b64:{exc!r}"})
            return
        if len(png_bytes) < 64:
            self._cors_json(400, {"ok": False, "error": "png_too_small"})
            return
        # Lazy-import the orchestrator
        try:
            import sys as _sys
            from pathlib import Path as _Path
            _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]
                                     / "core" / "lib"))
            import blob_to_unreal  # type: ignore
        except Exception as exc:
            self._cors_json(503, {"ok": False,
                                    "error": f"blob_to_unreal_unavailable:{exc!r}"})
            return
        try:
            import os as _os
            live_udp = _os.environ.get("MSPC_UNREAL_LIVE", "0") == "1"
            res = blob_to_unreal.run_pipeline(
                png_bytes,
                card_crystal=str(body.get("card_crystal", "")),
                duration_s=float(body.get("duration_s", 5.0)),
                fps=int(body.get("fps", 30)),
                subject_name=str(body.get("subject_name", "MspcBlob")),
                unreal_host=str(body.get("unreal_host", "127.0.0.1")),
                unreal_port=int(body.get("unreal_port", 11111)),
                dry_run=not live_udp,
            )
        except Exception as exc:
            self._cors_json(500, {"ok": False, "error": f"pipeline:{exc!r}"})
            return
        from dataclasses import asdict as _asdict
        self._cors_json(200, {"ok": True, "result": _asdict(res),
                                "live_udp_path": "CLI only — set MSPC_UNREAL_LIVE=1 in the dApp server's env to send real UDP packets to UE5."})

    def _handle_fb_games(self, tool: str) -> None:
        body = self._parse_json_or_form()
        if not FB_INSTANT_APP_ID:
            self._cors_json(200, {"ok": False, "error": "fb_not_configured",
                                  "hint": "create a Facebook app, set FB_INSTANT_APP_ID + FB_APP_SECRET"})
            return
        try:
            sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))
            from third_party.facebook_games_sdk import FacebookGamesSDKConnector  # type: ignore
            conn = FacebookGamesSDKConnector()
            try:
                conn.connect()
            except Exception:
                pass
            res = conn.send(tool, json.dumps(body if isinstance(body, dict) else {}))
            self._cors_json(200 if getattr(res, "success", False) else 502, {
                "ok": bool(getattr(res, "success", False)), "tool": tool,
                "output": getattr(res, "message_preview", ""),
                "metadata": getattr(res, "metadata", {}) or {},
                "error": getattr(res, "error", None)})
        except Exception as e:
            self._cors_json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def _handle_defi_loop(self) -> None:
        body = self._parse_json_or_form()
        try:
            collateral = float(body.get("collateral_usdc", 100))
            leverage = float(body.get("leverage", 2.0))
            max_iters = int(body.get("max_iters", 4))
        except (TypeError, ValueError):
            self._cors_json(400, {"error": "bad numeric inputs"})
            return
        collateral = max(1.0, min(collateral, 1_000_000.0))
        leverage = max(1.0, min(leverage, 5.0))
        max_iters = max(1, min(max_iters, 12))
        pool_id = str(body.get("pool_id", "") or os.environ.get("SUI_LENDING_POOL_ID", "0xPOOL"))
        try:
            sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))
            import defi_loop  # type: ignore
            from dataclasses import asdict
            res = defi_loop.run_loop(
                pool_id=pool_id,
                base_collateral_micro=int(collateral * 1_000_000),
                target_leverage=leverage,
                max_iters=max_iters,
                dry_run=True,                 # web is ALWAYS dry-run (build-safe)
                confirm_above_2x=True,        # allow the preview to model >2x
            )
            out = asdict(res)
        except Exception as e:
            self._cors_json(500, {"error": f"{type(e).__name__}: {e}"})
            return
        _anchor(tier="defi_loop", model="sui_lending", scope="defi_loop_preview",
                source_file="dapp", payload={"collateral": collateral, "leverage": leverage})
        self._cors_json(200, {"ok": True, "dry_run": True, "inputs": {
            "collateral_usdc": collateral, "target_leverage": leverage,
            "max_iters": max_iters}, "result": out})

    def _cors_json(self, status: int, payload: Dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, default=str),
                   content_type="application/json", extra_headers=_CORS_HEADERS)

    def _handle_stream_chroma(self) -> None:
        body = self._parse_json_or_form()
        if not isinstance(body, dict):
            self._cors_json(400, {"error": "bad body"})
            return
        token = str(body.get("token", "")).strip()
        page_url = str(body.get("page_url", ""))[:512]
        try:
            duration = float(body.get("duration", 0) or 0)
        except (TypeError, ValueError):
            duration = 0.0
        amps = body.get("amps") or []
        if not isinstance(amps, list) or not amps:
            self._cors_json(400, {"error": "missing amps[]"})
            return
        ts = time.time()
        tok8 = token[:6] if token else "notoken"
        stream_id = f"stream_{int(ts)}_{tok8}"
        try:
            out = chroma.chromatize_series(
                [float(a) for a in amps], duration, stem=stream_id,
                label=page_url or stream_id)
        except Exception as e:
            self._cors_json(500, {"error": f"chroma: {type(e).__name__}: {e}"})
            return
        out.pop("frames", None)

        # link the stream into the wallet map: stream node + stream→token edge.
        try:
            wmap.add_nodes([{"addr": stream_id, "kind": "stream",
                             "label": (page_url or stream_id)[:80], "ts": ts}],
                           source="stream")
            if token:
                wmap.add_nodes([{"addr": token, "kind": "token",
                                 "label": token[:8], "ts": ts}], source="stream")
                wmap.add_edges([{"from": stream_id, "to": token,
                                 "kind": "stream", "ts": ts}], source="stream")
        except Exception as e:
            sys.stderr.write(f"warn: wallet-map link failed: {e}\n")

        rec = {
            "stream_id": stream_id, "token": token, "page_url": page_url,
            "started_at": ts, "duration_s": round(duration, 3),
            "chroma_svg": out.get("svg", ""), "chroma_jsonl": out.get("jsonl", ""),
            "peak_hex": out.get("peak_hex", ""), "buckets": out.get("buckets", 0),
            "video_path": "",
        }
        _append_stream(rec)
        _anchor(tier="external_chain_event", model="stream_chroma",
                scope="stream", source_file=page_url,
                payload={"stream_id": stream_id, "token": token,
                         "buckets": rec["buckets"]})
        self._cors_json(200, {"ok": True, **rec})

    def _handle_stream_video(self, parsed) -> None:
        q = urllib.parse.parse_qs(parsed.query)
        stream_id = (q.get("stream_id", [""])[0] or "").strip()
        if not stream_id or "/" in stream_id or ".." in stream_id:
            self._cors_json(400, {"error": "bad/missing stream_id"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._cors_json(400, {"error": "empty body"})
            return
        if length > MAX_VIDEO_BYTES:
            self._cors_json(413, {"error": f"video > {MAX_VIDEO_BYTES} bytes"})
            return
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        dest = VIDEO_DIR / f"{stream_id}.webm"
        remaining = length
        with dest.open("wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 256, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        _write_sidecar(dest, source_url=q.get("page_url", [""])[0],
                       source_kind="livestream", category="Media/Video",
                       label=stream_id, tags=["livestream", "tab-capture"])
        _update_stream(stream_id, {"video_path": str(dest),
                                   "video_bytes": dest.stat().st_size})
        self._cors_json(200, {"ok": True, "stream_id": stream_id,
                              "video_path": str(dest),
                              "bytes": dest.stat().st_size})

    def _handle_solscan_ingest(self) -> None:
        body = self._parse_json_or_form()
        if not isinstance(body, dict):
            self._send(400, json.dumps({"error": "bad body"}),
                       content_type="application/json",
                       extra_headers=_CORS_HEADERS)
            return
        try:
            merged = wmap.ingest_dom(body)
        except Exception as e:
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}),
                       content_type="application/json",
                       extra_headers=_CORS_HEADERS)
            return
        self._send(200, json.dumps({"ok": True, **merged}),
                   content_type="application/json",
                   extra_headers=_CORS_HEADERS)

    # ---- POST handlers ---------------------------------------------------

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _parse_json_or_form(self) -> Dict[str, Any]:
        raw = self._read_body()
        if not raw:
            return {}
        ctype = (self.headers.get("Content-Type") or "").lower()
        if "application/json" in ctype:
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}
        # form-encoded fallback (HTMX default)
        try:
            return dict(urllib.parse.parse_qsl(raw.decode("utf-8"),
                                                  keep_blank_values=True))
        except Exception:
            return {}

    def _handle_buy(self, claims: TokenClaims) -> None:
        """POST /dapp/api/buy {product, payment_method, amount_cents}."""
        body = self._parse_json_or_form()
        product = str(body.get("product", "")).strip()[:128]
        method = str(body.get("payment_method", "stripe")).strip().lower()
        try:
            amount_cents = int(body.get("amount_cents", 0))
        except (TypeError, ValueError):
            amount_cents = 0

        if not product or amount_cents <= 0:
            self._send_json(400, {"error": "missing product / amount_cents"})
            return
        if method not in ("stripe", "sui", "sui_usdc"):
            self._send_json(400, {"error": f"unsupported payment_method: {method}"})
            return

        rail = "stripe" if method == "stripe" else "sui_usdc"
        scope = f"dapp_{rail}"

        # Dispatch
        if method == "stripe":
            tx_summary, ok, err = self._buy_stripe(product, amount_cents, claims)
        else:
            tx_summary, ok, err = self._buy_sui(product, body, claims)

        rc = 0 if ok else 1
        crystal = _anchor(
            tier="monetization", model="dapp_buy", scope=scope,
            source_file=f"user:{claims.user_id}",
            payload={"product": product, "method": method,
                       "amount_cents": amount_cents, **tx_summary},
            rc=rc,
        )

        if not ok:
            self._send_json(502, {"error": err, "rail": rail, "crystal": crystal})
            return

        inner_vars = {
            "product":     html.escape(product),
            "rail":        html.escape(rail),
            "amount_str":  html.escape(f"${amount_cents/100:.2f}"),
            "tx_id":       html.escape(str(tx_summary.get("tx_id", ""))[:80]),
            "client_secret": html.escape(str(tx_summary.get("client_secret", ""))[:80]),
            "crystal":     html.escape(crystal[:24]),
        }
        if self._is_htmx():
            self._send(200, _render_inner("buy_success.html", inner_vars))
        else:
            self._send(200, _render_page("buy_success.html", inner_vars, "purchase"))

    def _buy_stripe(self, product: str, amount_cents: int,
                     claims: TokenClaims) -> Tuple[Dict[str, Any], bool, str]:
        c = StripeMCPConnector()
        r = c.send("create_payment_intent", json.dumps({
            "amount_cents": amount_cents,
            "currency": "usd",
            "description": f"MySpace++ dApp · {product} · user={claims.user_id}",
            "metadata": {"product": product, "user_id": claims.user_id,
                          "domain": claims.domain},
        }))
        if not r.success:
            return {}, False, r.error or "stripe_failed"
        return {
            "tx_id": r.metadata.get("stripe_id", ""),
            "client_secret": r.metadata.get("client_secret", "")[:64],
            "status": r.metadata.get("stripe_status", ""),
        }, True, ""

    def _buy_sui(self, product: str, body: Dict[str, Any],
                  claims: TokenClaims) -> Tuple[Dict[str, Any], bool, str]:
        to = str(body.get("to") or body.get("recipient") or "").strip()
        amount_micro = body.get("amount_micro")
        input_coins = body.get("input_coins") or body.get("coin_object_ids") or []
        if not to or amount_micro is None:
            return {}, False, "sui requires to + amount_micro (USDC micro-units)"
        c = SuiMCPConnector()
        msg = {"to": to, "amount_micro": amount_micro, "input_coins": input_coins}
        if body.get("confirm"):
            msg["confirm"] = True
        r = c.send("transfer_usdc", json.dumps(msg))
        if not r.success:
            return {}, False, r.error or "sui_failed"
        return {
            "tx_id": r.metadata.get("digest", ""),
            "status": r.metadata.get("status", ""),
        }, True, ""

    def _handle_mint(self, claims: TokenClaims) -> None:
        """POST /dapp/api/mint {photo_b64, tier}."""
        body = self._parse_json_or_form()
        photo_b64 = str(body.get("photo_b64", "")).strip()
        tier_label = str(body.get("tier", "free")).strip()[:32] or "free"

        if not photo_b64:
            self._send_json(400, {"error": "missing photo_b64"})
            return

        # Decode + MIME-sniff. Limit to 8 MB.
        try:
            # Strip data-URL prefix if present.
            if photo_b64.startswith("data:"):
                _, _, photo_b64 = photo_b64.partition(",")
            photo_bytes = base64.b64decode(photo_b64, validate=False)
        except Exception as e:
            self._send_json(400, {"error": f"bad_base64: {type(e).__name__}"})
            return

        if len(photo_bytes) > MAX_PHOTO_BYTES:
            self._send_json(413, {
                "error": f"photo too large: {len(photo_bytes)}B > {MAX_PHOTO_BYTES}B",
            })
            return

        mime = _sniff_image_mime(photo_bytes[:16])
        if not mime:
            self._send_json(415, {"error": "unsupported_media_type (not an image)"})
            return

        # tensorchain.mint_nft with SUI_FALLBACK env honored by the connector.
        c = TensorChainMCPConnector()
        # metadata_uri is a placeholder until IPFS pin is wired (future A.7);
        # the dApp still anchors crystal + returns the digest.
        photo_short = photo_b64[:32]
        attrs = {
            "owner": claims.user_id,
            "tier": tier_label,
            "mime": mime,
            "bytes": len(photo_bytes),
            "photo_hash_prefix": photo_short,
        }
        r = c.send("mint_nft", json.dumps({
            "metadata_uri": f"data:{mime};b64:{photo_short}",
            "royalty_bps": 500,
            "owner": claims.user_id,
            "attrs": attrs,
        }))

        ok = bool(r.success)
        rc = 0 if ok else 1
        crystal = _anchor(
            tier="monetization", model="dapp_mint", scope="dapp_mint",
            source_file=f"user:{claims.user_id}",
            payload={
                "tier_label": tier_label, "mime": mime,
                "bytes": len(photo_bytes),
                "tx_hash": r.metadata.get("tx_hash", ""),
                "asset_id": r.metadata.get("asset_id", ""),
                "backend": r.metadata.get("backend", ""),
                "sui_fallback_used": r.metadata.get("sui_fallback_used", False),
            },
            rc=rc,
        )

        if not ok:
            self._send_json(502, {
                "error": r.error or "mint_failed",
                "backend": r.metadata.get("backend", ""),
                "crystal": crystal,
            })
            return

        inner_vars = {
            "tier_label":    html.escape(tier_label),
            "asset_id":      html.escape(str(r.metadata.get("asset_id", ""))[:80]),
            "tx_hash":       html.escape(str(r.metadata.get("tx_hash", ""))[:80]),
            "ipfs_uri":      html.escape(f"data:{mime};b64:{photo_short}"),
            "backend":       html.escape(str(r.metadata.get("backend", ""))),
            "sui_fallback":  "yes" if r.metadata.get("sui_fallback_used") else "no",
            "crystal":       html.escape(crystal[:24]),
        }
        if self._is_htmx():
            self._send(200, _render_inner("mint_success.html", inner_vars))
        else:
            self._send(200, _render_page("mint_success.html", inner_vars, "mint"))

    # ---- fb_event ---------------------------------------------------------

    def _handle_fb_event(self, claims: TokenClaims) -> None:
        """POST /dapp/api/fb_event {event_name, player_id, context_id, signed_data, payload}."""
        body = self._parse_json_or_form()
        event_name = str(body.get("event_name", "")).strip()[:64] or "unknown"
        player_id = str(body.get("player_id", "")).strip()[:128]
        context_id = str(body.get("context_id", "")).strip()[:128]
        signed_data = str(body.get("signed_data", "")).strip()[:512]
        raw_payload = body.get("payload", {}) or {}
        if isinstance(raw_payload, str):
            try:
                raw_payload = json.loads(raw_payload)
            except Exception:
                raw_payload = {"_raw": raw_payload[:256]}
        if not isinstance(raw_payload, dict):
            raw_payload = {"_value": str(raw_payload)[:256]}

        record = _record_fb_event(
            event_name=event_name,
            player_id=player_id,
            context_id=context_id,
            signed_data=signed_data,
            payload=raw_payload,
        )
        ok = bool(record.get("ok", False))
        rc = 0 if ok else 1

        crystal = _anchor(
            tier="fb_event",
            model="dapp_fb_bridge",
            scope=f"dapp_{event_name}",
            source_file=f"user:{claims.user_id}",
            payload={
                "event_name":  event_name,
                "player_id":   player_id,
                "context_id":  context_id,
                "backend":     str(record.get("backend", "")),
                "ok":          ok,
                "error":       str(record.get("error", "")),
            },
            rc=rc,
        )
        self._send_json(200 if ok else 502, {
            "ok":         ok,
            "event_name": event_name,
            "backend":    record.get("backend", ""),
            "error":      record.get("error", ""),
            "crystal":    crystal,
        })

    # ---- balance fanout ---------------------------------------------------

    def _fanout_balance(self, addr: str) -> Dict[str, Any]:
        """Query both Sui + TensorChain for an address. Never raises."""
        out: Dict[str, Any] = {"address": addr, "sui": {}, "tensorchain": {}}
        # Sui (SUI native coin balance)
        try:
            sc = SuiMCPConnector()
            sr = sc.send("query_balance", json.dumps({"addr": addr}))
            out["sui"] = {
                "success": sr.success,
                "total_balance": sr.metadata.get("total_balance", ""),
                "coin_object_count": sr.metadata.get("coin_object_count", 0),
                "network": sr.metadata.get("network", ""),
                "error": sr.error or "",
            }
        except Exception as e:
            out["sui"] = {"success": False, "error": f"{type(e).__name__}: {e}"}
        # TensorChain
        try:
            tc = TensorChainMCPConnector()
            tr = tc.send("query_balance", json.dumps({"addr": addr}))
            out["tensorchain"] = {
                "success": tr.success,
                "balance": tr.metadata.get("balance", ""),
                "backend": tr.metadata.get("backend", ""),
                "sui_fallback_used": tr.metadata.get("sui_fallback_used", False),
                "error": tr.error or "",
            }
        except Exception as e:
            out["tensorchain"] = {"success": False, "error": f"{type(e).__name__}: {e}"}
        return out

    # ---- logging ----------------------------------------------------------

    def log_message(self, format: str, *args) -> None:
        if os.environ.get("MSPC_DAPP_LOG", "") == "quiet":
            return
        sys.stderr.write(f"{self.address_string()} {format % args}\n")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="dapp_server")
    ap.add_argument("--port", type=int,
                      default=int(os.environ.get("MSPC_DAPP_PORT", "8520")))
    ap.add_argument("--bind", default="127.0.0.1",
                      help="bind address; 127.0.0.1 only — Caddy fronts TLS")
    args = ap.parse_args()

    sys.stderr.write(
        f"dapp_server listening on {args.bind}:{args.port}\n"
        f"  routes:  /dapp/services /dapp/mint /dapp/wallet\n"
        f"           /dapp/api/products /dapp/api/balance /dapp/api/buy /dapp/api/mint\n"
        f"           /dapp/healthz\n"
        f"           /dapp/play /dapp/play/embed /dapp/play/sdk-bridge.js\n"
        f"           /dapp/api/fb_event /dapp/api/social_graph\n"
        f"           /dapp/play_morph /dapp/api/morph_plan\n"
        f"           /dapp/pump_surf /dapp/api/pump_wave\n"
        f"           /dapp/loom /dapp/api/loom/{{chat,mint,scopes,scope}}\n"
    )
    srv = ThreadingHTTPServer((args.bind, args.port), DappHandler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
