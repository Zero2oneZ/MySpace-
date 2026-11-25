import React, { useMemo, useState } from "react";

// morph.engine = the EMBEDDED WORKFLOW card, rendered in the 3ds-Max modifier-
// stack idiom (the morph_engine(1).html chrome): bezel + chevron header, COL A
// the overlapping bottom-up stack, COL B the evaluated result up to the eval-
// point, COL C tools @ the selected step. The stack is WORKFLOW STEPS, not 3D.

const CTRL_GLYPH = { if: "◇", while: "↻", true: "◐", false: "◑", and: "∧", or: "∨", start: "▷", stop: "■", morph: "✦" };
function sig(n) { let h = ((n * 2654435761) >>> 0).toString(16).padStart(8, "0"); return "0x" + h.slice(0, 8); }

export default function MorphEngine({ data, onHome }) {
  const scope = data.scope || {};
  const cards = data.cards || [];
  const [sel, setSel] = useState(cards.length - 1);
  const [ser, setSer] = useState(false);
  const [closed, setClosed] = useState(false);
  const evalIdx = ser ? cards.length - 1 : sel;
  const m = cards[sel] || null;

  const evald = useMemo(() => {
    const upto = cards.slice(0, evalIdx + 1);
    const stages = [];
    upto.forEach((c) => {
      const parts = (c.title || "").includes("->") ? c.title.split("->") : [c.title || ""];
      if (!stages.length) stages.push(parts[0]);
      stages.push(parts[parts.length - 1]);
    });
    const tail = cards[evalIdx] || {};
    const kernel = (tail.widgets || []).find((w) => w.name === "model");
    return {
      pipeline: stages.filter(Boolean).join(" → ") || "—",
      produces: (tail.title || "").split("->").pop() || "—",
      kernel: kernel ? kernel.value : "—",
      gate: tail.hitl ? tail.why : "",
    };
  }, [cards, evalIdx]);

  return (
    <div className="cardpad">
      <div className={"embed-card" + (closed ? " closed" : "")}>
        <div className="ec-head" onClick={() => setClosed(!closed)}>
          <span className="chev">^</span>
          <span className="brand">morph.engine</span>
          <span className="sub">// {scope.label} · embedded workflow · bottom-up eval</span>
          <span className="flow">base ⇡ <b>steps</b> ⇡ top &nbsp;·&nbsp; data flows <b>up</b></span>
          <button className="home" onClick={(e) => { e.stopPropagation(); onHome(); }}>⌂ chat</button>
        </div>

        <div className="ec-body">
          {/* COL A — the workflow stack (bottom-up, overlapping) */}
          <section className="col">
            <div className="col-head">▤ workflow stack <span className="n">{cards.length} steps</span></div>
            <div className="chips">
              <div className="chip on"><span>{scope.glyph || "◆"}</span>{(scope.label || "scope").split(" ")[0]}</div>
            </div>
            <div className="stackwrap">
              <div className="cap">[ top — evaluates last ]</div>
              {cards.slice().reverse().map((c, ri) => {
                const i = cards.length - 1 - ri;
                return (
                  <div key={c.node}
                    className={"mod" + (i === sel ? " sel" : "") + (i === evalIdx && !ser ? " evalmark" : "") + (c.hitl ? " hitl" : "")}
                    onClick={() => setSel(i)}>
                    <div className="mrow">
                      <span className="mg">{c.hitl ? "⏸" : (CTRL_GLYPH[c.control] || "✦")}</span>
                      <span className="mname">{c.title}</span>
                      <span className="mnum">{i + 1}</span>
                    </div>
                  </div>
                );
              })}
              <div className="base">
                <div className="mrow">
                  <span className="mg">▣</span>
                  <span className="mname">{scope.label} · base</span>
                  <span className="tag">{(scope.profile?.planes || []).join(",") || "input"}</span>
                </div>
              </div>
              <div className="cap">[ bottom — base · foundation ]</div>
            </div>
            <div className="stacktools">
              <div className={"ser" + (ser ? " on" : "")} onClick={() => setSer(!ser)}>
                <span className="tube">⚗</span><span>show end result</span>
              </div>
              <div className="addmod"><span className="addbtn">+ step</span></div>
            </div>
          </section>

          {/* COL B — evaluated result up to the eval-point */}
          <section className="col mid">
            <div className="col-head colhead-abs"><span className="arrow">⇡</span> evaluated result</div>
            <div className="evalpane">
              <div className="eflow">{evald.pipeline}</div>
              <div className="emeta">
                <div><span className="k">produces</span>{evald.produces}</div>
                <div><span className="k">kernel</span>{evald.kernel}</div>
                {evald.gate && <div className="egate">⏸ {evald.gate}</div>}
              </div>
            </div>
            <div className="mhud tl">
              <div className="o">{scope.label}{m ? <span className="s"> · {m.title}</span> : <span className="s"> · base</span>}</div>
              <div className="h">sig {sig((evalIdx + 1) * 9301 + cards.length * 49297)}</div>
              <div className="e">eval ↑ {ser ? "end result" : (cards[evalIdx]?.title || "base")}</div>
            </div>
            <div className="mhud bl">bottom-up · lower step edits ripple up</div>
          </section>

          {/* COL C — tools @ the selected step */}
          <section className="col">
            <div className="col-head"><span className="arrow">⇢</span> tools @ step</div>
            <div className="tools">
              {!m ? <div className="toolctx">select a step</div> : (
                <>
                  <div className="toolctx">accessing · step {sel + 1} · {m.control === "morph" ? "transform" : m.control}</div>
                  {m.hitl && <div className="tcard dec">⏸ human gate · {m.why}</div>}
                  <div className="tcard">
                    <div className="th">{m.title}</div>
                    <div className="td">{m.why}</div>
                    {(m.widgets || []).map((w, k) => <Ctrl key={k} w={w} />)}
                  </div>
                  <div className="tcard">
                    <div className="th">⚙ stack ops</div>
                    <div className="ops">
                      <span className="op acc">enable</span><span className="op acc">↑ up</span>
                      <span className="op acc">↓ down</span><span className="op sov">collapse to</span>
                      <span className="op dan">✕ delete</span>
                    </div>
                  </div>
                </>
              )}
            </div>
          </section>
        </div>

        <div className="status">
          <span className="dot pulse" />
          <span>history = stack · changing a lower step ripples up</span>
          <span className="log">{scope.chain_spec}</span>
        </div>
      </div>
    </div>
  );
}

function Ctrl({ w }) {
  const opts = w.options || [];
  return (
    <div className="ctrl">
      <label>{w.name}</label>
      {w.widget === "select" ? (
        <select defaultValue={w.value}>{opts.map((o) => <option key={o}>{o}</option>)}</select>
      ) : w.widget === "toggle" ? (
        <input type="checkbox" defaultChecked={!!w.value} />
      ) : w.widget === "slider" ? (
        <input type="range" min={w.min || 0} max={w.max || 100} defaultValue={w.value || 0} />
      ) : w.widget === "buttons" ? (
        <span className="btnrow">{opts.map((o) => <span key={o} className="op acc">{o}</span>)}</span>
      ) : (
        <input type="text" defaultValue={String(w.value ?? "")} />
      )}
    </div>
  );
}
