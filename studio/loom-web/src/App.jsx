import React, { useEffect, useRef, useState, useCallback } from "react";
import { api } from "./api.js";
import MorphEngine from "./MorphEngine.jsx";

const CHANNELS = ["loom", "general", "activity"];

export default function App() {
  const [scopes, setScopes] = useState([]);
  const [view, setView] = useState("hub");          // hub | scope | viewport
  const [active, setActive] = useState(null);        // {scope, cards}
  const [channel, setChannel] = useState("loom");
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const streamRef = useRef(null);

  const loadScopes = useCallback(() => { api.scopes().then(setScopes).catch(() => {}); }, []);
  const loadMessages = useCallback(() => {
    api.messages(channel).then(setMessages).catch(() => {});
  }, [channel]);

  useEffect(() => { loadScopes(); }, [loadScopes]);

  // poll the active channel while in the hub
  useEffect(() => {
    if (view !== "hub") return;
    loadMessages();
    const t = setInterval(loadMessages, 3000);
    return () => clearInterval(t);
  }, [view, channel, loadMessages]);

  useEffect(() => {
    if (streamRef.current) streamRef.current.scrollTop = streamRef.current.scrollHeight;
  }, [messages]);

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setBusy(true); setDraft("");
    try {
      const res = await api.post(channel, text);
      setMessages((m) => [...m, res.message, ...(res.bot_reply ? [res.bot_reply] : [])]);
    } catch (e) { /* shown via reload */ } finally { setBusy(false); loadMessages(); }
  }

  async function confirmMint(label, spec, intent) {
    try { await api.mint(intent || label, label, spec); loadScopes(); } catch (e) {}
  }

  async function openScope(id) {
    try { const d = await api.scope(id); setActive(d); setView("scope"); } catch (e) {}
  }

  return (
    <div className="app">
      <nav className="shelf">
        <button className="add" title="open the chat hub"
          onClick={() => { setView("hub"); setChannel("loom"); }}>+</button>
        <div className="scopes">
          {scopes.map((s) => (
            <button key={s.scope_id}
              className={"scope" + (active?.scope?.scope_id === s.scope_id ? " active" : "")}
              title={`${s.label} · ${s.archetype}`} onClick={() => openScope(s.scope_id)}>
              {s.glyph || "◆"}
            </button>
          ))}
        </div>
        <button className="gear" disabled title="account · billing (stub)">⚙</button>
      </nav>

      <main className="center">
        {view === "hub" && (
          <Hub channel={channel} setChannel={setChannel} messages={messages}
            streamRef={streamRef} draft={draft} setDraft={setDraft} send={send}
            busy={busy} onConfirm={confirmMint} />
        )}
        {view === "scope" && active && (
          <MorphEngine data={active} onHome={() => setView("hub")} />
        )}
      </main>
    </div>
  );
}

function Hub({ channel, setChannel, messages, streamRef, draft, setDraft, send, busy, onConfirm }) {
  return (
    <>
      <div className="tabs">
        {CHANNELS.map((c) => (
          <button key={c} className={"tab" + (c === channel ? " on" : "")}
            onClick={() => setChannel(c)}># {c}</button>
        ))}
        <span className="hint">#loom = describe a tool → Confirm mints it</span>
      </div>
      <div className="stream" ref={streamRef}>
        {messages.length === 0 && <div className="empty">no messages — say something in #{channel}</div>}
        {messages.map((m) => <Bubble key={m.msg_id} m={m} onConfirm={onConfirm} />)}
      </div>
      <div className="composer">
        <input value={draft} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") send(); }}
          placeholder={`message #${channel}${channel === "loom" ? " — describe a tool" : ""}`} />
        <button onClick={send} disabled={busy}>{busy ? "···" : "send"}</button>
      </div>
    </>
  );
}

function Bubble({ m, onConfirm }) {
  const author = m.author || "bot";
  if (author === "you") return <div className="bubble user">{m.text}</div>;
  const cls = author === "governor" ? "bubble gov" : "bubble bot";
  return (
    <div className={cls}>
      <span className="who">{author}</span>
      <p>{m.text}</p>
      {m.action === "confirm_mint" && m.proposed_chain_spec && (
        <Confirm m={m} onConfirm={onConfirm} />
      )}
    </div>
  );
}

function Confirm({ m, onConfirm }) {
  const [label, setLabel] = useState(m.proposed_label || "");
  const [spec, setSpec] = useState(m.proposed_chain_spec || "");
  const [done, setDone] = useState(false);
  if (done) return <div className="why">✓ minted “{label}” → check the shelf</div>;
  return (
    <div className="confirm">
      <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="name" />
      <input value={spec} onChange={(e) => setSpec(e.target.value)} placeholder="pipeline" />
      <button onClick={() => { onConfirm(label, spec, m.text); setDone(true); }}>Confirm → mint scope</button>
    </div>
  );
}

