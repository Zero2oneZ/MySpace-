#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        loom_ui (dapp shell)
# role:        HTTP · LOOM_SHELL_FACE  (the first morph.engine, as a chat hub)
# tier:        L0
# substrate:   the shippable face — a local self-hosted Slack-clone. Left icon
#              tool-shelf ("+" top opens/focuses the bot DM, gear bottom = stub).
#              Center = the CHAT HUB: #loom (the bot — describe a tool, it grounds
#              + offers Confirm→mint), #general (people), #activity (the governor
#              narrates every auto-mint). Selecting a minted scope icon swaps the
#              center to that scope's morph.engine card deck.
# storage:     none — pure string builder. State lives in core/lib/loom.py
#              (~/.cc/loom/{scopes,connections,messages}.jsonl).
# ----------------------------------------------------------------------------
# Two functions: loom_html() -> full page ; hub_html() -> the chat-hub fragment
# (also served at GET /dapp/api/loom/hub so "+"/home can restore it).
# Frontend rule (hard): flat HTML + HTMX only, no framework, no build. Mobile-first.
# ============================================================================
"""loom_ui.py — the Loom shell page + chat-hub fragment (flat HTML + HTMX)."""
from __future__ import annotations


def hub_html() -> str:
    """The chat-hub center: channel tabs + message stream + composer.
    Served inline in loom_html() and at GET /dapp/api/loom/hub (to restore)."""
    return """<div id="hub">
  <div id="channels">
    <button class="ch active" data-ch="loom"    onclick="loomSetCh(this)"
            hx-get="/dapp/api/loom/messages?channel=loom"    hx-target="#stream" hx-swap="innerHTML"># loom</button>
    <button class="ch" data-ch="general" onclick="loomSetCh(this)"
            hx-get="/dapp/api/loom/messages?channel=general" hx-target="#stream" hx-swap="innerHTML"># general</button>
    <button class="ch" data-ch="activity" onclick="loomSetCh(this)"
            hx-get="/dapp/api/loom/messages?channel=activity" hx-target="#stream" hx-swap="innerHTML"># activity</button>
    <span class="ch-hint">#loom = describe a tool → the bot grounds it → Confirm mints it</span>
  </div>
  <div id="stream"
       hx-get="/dapp/api/loom/messages?channel=loom"
       hx-trigger="load, every 4s"
       hx-swap="innerHTML"
       hx-on::after-swap="this.scrollTop=this.scrollHeight"></div>
  <form id="composer"
        hx-post="/dapp/api/loom/post" hx-target="#stream" hx-swap="beforeend"
        hx-on::after-request="if(event.detail.successful){this.querySelector('input[name=text]').value='';var s=document.getElementById('stream');s.scrollTop=s.scrollHeight;}">
    <input type="hidden" name="channel" id="cur-channel" value="loom">
    <input name="text" autocomplete="off" required
           placeholder="message #loom — describe a tool, or just chat">
    <button type="submit">send <span class="htmx-indicator">&middot;&middot;&middot;</span></button>
  </form>
</div>"""


def loom_html() -> str:
    """Return the full Loom shell page as a single self-contained string."""
    return """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Loom</title>
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
<style>
  :root{
    color-scheme:dark;
    --bg:#0b0e14; --panel:#111824; --b1:#1c2530; --b2:#243140;
    --t1:#cbd5e1; --t2:#9fb3c8; --mut:#64748b;
    --acc:#2dd4bf; --acc-dim:#134e4a; --acc-soft:#a7f3eb; --rail:64px;
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{
    margin:0; background:var(--bg); color:var(--t1);
    font:14px/1.6 ui-monospace,Menlo,Monaco,Consolas,monospace;
    display:grid; grid-template-columns:var(--rail) 1fr; overflow:hidden;
  }
  /* ---- LEFT SHELF ---- */
  #shelf{ grid-column:1; height:100vh; background:var(--panel);
    border-right:1px solid var(--b1); display:flex; flex-direction:column;
    align-items:center; padding:10px 0; gap:8px; }
  #shelf button{ width:44px; height:44px; flex:0 0 auto; display:flex;
    align-items:center; justify-content:center; background:#0d141e; color:var(--t2);
    border:1px solid var(--b2); border-radius:10px;
    font:20px/1 ui-monospace,Menlo,monospace; cursor:pointer;
    transition:border-color .12s,color .12s,background .12s; }
  #shelf button:hover{ border-color:var(--acc); color:var(--acc-soft) }
  #loom-add{ background:var(--acc-dim); border-color:var(--acc); color:var(--acc-soft); font-size:24px }
  #loom-add:hover{ background:#1a6b63 }
  #shelf-scopes{ flex:1 1 auto; width:100%; display:flex; flex-direction:column;
    align-items:center; gap:8px; overflow-y:auto; padding:8px 0; min-height:0; }
  #shelf-scopes::-webkit-scrollbar{ width:0 }
  .scope-icon.active{ border-color:var(--acc); color:var(--acc) }
  #loom-gear{ margin-top:auto; opacity:.45; cursor:not-allowed }
  .shelf-divider{ width:28px; height:1px; background:var(--b1); flex:0 0 auto }

  /* ---- CENTER ---- */
  #workspace{ grid-column:2; height:100vh; overflow:hidden; position:relative; }

  /* ---- CHAT HUB ---- */
  #hub{ height:100vh; display:flex; flex-direction:column; }
  #channels{ display:flex; align-items:center; gap:6px; padding:10px 14px;
    border-bottom:1px solid var(--b1); background:var(--panel); flex-wrap:wrap; }
  #channels .ch{ background:#0d141e; color:var(--t2); border:1px solid var(--b2);
    border-radius:8px; padding:4px 10px; font:13px ui-monospace,monospace; cursor:pointer; }
  #channels .ch:hover{ border-color:var(--acc); color:var(--acc-soft) }
  #channels .ch.active{ background:var(--acc-dim); border-color:var(--acc); color:var(--acc-soft) }
  #channels .ch-hint{ margin-left:auto; color:var(--mut); font-size:11px }
  #stream{ flex:1 1 auto; overflow-y:auto; padding:16px 18px; min-height:0;
    display:flex; flex-direction:column; gap:10px; max-width:760px; width:100%; }
  #composer{ border-top:1px solid var(--b1); padding:12px 16px; display:flex; gap:8px;
    background:var(--panel); }
  #composer input[name=text]{ flex:1 1 auto; background:var(--bg); border:1px solid var(--b2);
    color:var(--t1); border-radius:8px; padding:9px 12px; font:inherit; }
  #composer button{ background:var(--acc-dim); border:1px solid var(--acc); color:var(--acc-soft);
    border-radius:8px; padding:9px 14px; font:inherit; cursor:pointer; }
  #composer button:hover{ background:#1a6b63 }

  /* message bubbles */
  .bubble{ border-radius:10px; padding:9px 12px; font-size:13px; max-width:92% }
  .bubble.user{ align-self:flex-end; background:var(--acc-dim); color:var(--acc-soft); border:1px solid var(--acc) }
  .bubble.bot{ align-self:flex-start; background:#0d141e; border:1px solid var(--b2) }
  .bubble.gov{ align-self:flex-start; background:#0d1a17; border:1px solid var(--acc-dim) }
  .bubble .who{ display:block; font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:var(--mut); margin-bottom:3px }
  .bubble.gov .who{ color:var(--acc) }
  .bubble p{ margin:0 }
  .chips{ display:flex; flex-wrap:wrap; gap:5px; margin:6px 0 }
  .chip{ font-size:11px; color:var(--acc-soft); background:var(--acc-dim);
    border:1px solid var(--acc-dim); border-radius:10px; padding:1px 8px; }
  form.confirm{ margin-top:8px; display:flex; flex-direction:column; gap:7px }
  form.confirm label{ font-size:11px; color:var(--mut); display:flex; flex-direction:column; gap:3px }
  form.confirm input{ background:var(--bg); border:1px solid var(--b2); color:var(--t1);
    border-radius:6px; padding:6px 8px; font:inherit; }
  form.confirm button{ background:var(--acc-dim); border:1px solid var(--acc); color:var(--acc-soft);
    border-radius:8px; padding:8px 10px; font:inherit; cursor:pointer; }
  .htmx-indicator{ opacity:0 } .htmx-request .htmx-indicator{ opacity:1 }

  /* scope card deck (loaded when a shelf icon is clicked) */
  .scope-head{ padding:16px 20px; border-bottom:1px solid var(--b1); display:flex;
    align-items:center; gap:10px; flex-wrap:wrap; background:var(--panel); }
  .scope-head .glyph{ font-size:22px; color:var(--acc) }
  .scope-head b{ color:#e2e8f0; font-size:16px }
  .scope-head .arch{ font-size:11px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--acc); border:1px solid var(--acc-dim); border-radius:10px; padding:1px 8px; }
  .scope-head .home{ margin-left:auto; cursor:pointer; color:var(--mut);
    background:#0d141e; border:1px solid var(--b2); border-radius:8px; padding:3px 10px; }
  .scope-head .home:hover{ border-color:var(--acc); color:var(--acc-soft) }
  .deck{ display:flex; flex-direction:column-reverse; gap:10px; padding:18px 20px 40px; max-width:720px; }
  .card{ background:var(--panel); border:1px solid var(--b2); border-radius:12px; padding:12px 14px; }
  .card.decision{ border-color:var(--acc); box-shadow:0 0 0 1px var(--acc-dim) inset }
  .card header{ display:flex; align-items:center; gap:8px; color:#e2e8f0; font-weight:600 }
  .card header .when{ margin-left:auto; font-size:11px; color:var(--mut); font-weight:400 }
  .card .why{ color:var(--t2); font-size:12px; margin:6px 0 0 }

  @media (max-width:560px){
    :root{ --rail:54px }
    #shelf button{ width:38px; height:38px; font-size:18px }
    #channels .ch-hint{ display:none }
  }
</style>
</head>
<body
  hx-on:loom-minted="(function(ev){var id=ev.detail.value||ev.detail['loom-minted'];if(typeof id==='object'&&id)id=id.value||Object.values(id)[0];if(id){htmx.ajax('GET','/dapp/api/loom/scope?id='+encodeURIComponent(id),{target:'#workspace',swap:'innerHTML'});}})(event)">

  <!-- LEFT ICON TOOL-SHELF -->
  <nav id="shelf">
    <button id="loom-add" title="open the bot — describe what to build"
            hx-get="/dapp/api/loom/hub" hx-target="#workspace" hx-swap="innerHTML"
            hx-on::after-swap="var t=document.querySelector('#composer input[name=text]');if(t)t.focus();">+</button>
    <div class="shelf-divider"></div>
    <div id="shelf-scopes" hx-get="/dapp/api/loom/scopes" hx-trigger="load" hx-swap="innerHTML"></div>
    <button id="loom-gear" disabled title="account · billing — coming soon">&#9881;</button>
  </nav>

  <!-- CENTER: the chat hub (the first morph.engine, as a Slack clone) -->
  <main id="workspace">__HUB__</main>

<script>
  function loomSetCh(btn){
    document.querySelectorAll('#channels .ch').forEach(function(b){b.classList.remove('active');});
    btn.classList.add('active');
    var ch=btn.getAttribute('data-ch');
    var cur=document.getElementById('cur-channel'); if(cur) cur.value=ch;
    var s=document.getElementById('stream');
    if(s){ s.setAttribute('hx-get','/dapp/api/loom/messages?channel='+ch); htmx.process(s); htmx.trigger(s,'load'); }
    var ph=document.querySelector('#composer input[name=text]'); if(ph) ph.placeholder='message #'+ch+(ch==='loom'?' — describe a tool, or just chat':'');
  }
</script>
</body></html>""".replace("__HUB__", hub_html())


# spec alias — scopes load via HTMX; ignored for contract compatibility.
def shell_page(scopes=None) -> str:  # noqa: ARG001
    return loom_html()


if __name__ == "__main__":
    _doc = loom_html()
    _b = len(_doc.encode("utf-8"))
    assert 'id="loom-add"' in _doc and ">+<" in _doc, "missing top + button"
    assert 'id="loom-gear"' in _doc and "&#9881;" in _doc, "missing bottom gear"
    assert 'id="hub"' in _doc and 'id="composer"' in _doc, "missing chat hub"
    assert "# loom" in _doc and "# activity" in _doc, "missing channels"
    print(f"loom_html() ok: {_b} bytes; + / gear / hub / channels present")
    print(f"hub_html() ok: {len(hub_html())} bytes")
