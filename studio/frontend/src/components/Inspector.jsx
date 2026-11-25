import React from 'react'
import { useStore } from '../store'
import Viewer from './Viewer'

function Param({ uid, p, value, set }) {
  const common = { id: `${uid}-${p.name}` }
  if (p.type === 'int' || p.type === 'float') {
    return (
      <label className="prm">
        <span>{p.name}</span>
        <div className="row">
          <input type="range" min={p.min} max={p.max} step={p.step || (p.type === 'int' ? 1 : 0.01)}
            value={value ?? p.default ?? p.min}
            onChange={(e) => set(p.name, p.type === 'int' ? +e.target.value : parseFloat(e.target.value))} {...common} />
          <input type="number" className="num" value={value ?? p.default ?? 0}
            onChange={(e) => set(p.name, p.type === 'int' ? +e.target.value : parseFloat(e.target.value))} />
        </div>
      </label>
    )
  }
  if (p.type === 'bool') {
    return (
      <label className="prm row">
        <input type="checkbox" checked={!!value} onChange={(e) => set(p.name, e.target.checked)} />
        <span>{p.name}</span>
      </label>
    )
  }
  if (p.type === 'enum') {
    return (
      <label className="prm">
        <span>{p.name}</span>
        <select value={value ?? p.default} onChange={(e) => set(p.name, e.target.value)}>
          {p.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </label>
    )
  }
  if (p.type === 'text') {
    return (
      <label className="prm">
        <span>{p.name}</span>
        <textarea value={value ?? ''} rows={3} onChange={(e) => set(p.name, e.target.value)} />
      </label>
    )
  }
  if (p.type === 'file') {
    return (
      <label className="prm">
        <span>{p.name}</span>
        <input type="text" placeholder="/path/to/file (or upload via adapter)"
          value={value?.path || value || ''} onChange={(e) => set(p.name, e.target.value)} />
      </label>
    )
  }
  return null
}

export default function Inspector() {
  const selected = useStore((s) => s.selected)
  const nodes = useStore((s) => s.nodes)
  const byId = useStore((s) => s.byId)
  const setParam = useStore((s) => s.setParam)
  const status = useStore((s) => (selected ? s.status[selected] : null))
  const removeNode = useStore((s) => s.removeNode)

  const inst = nodes.find((n) => n.id === selected)
  if (!inst) return <div className="inspector"><div className="ititle">Inspector</div><p className="muted">No node selected.</p></div>
  const spec = byId[inst.data.nodeId]

  return (
    <div className="inspector">
      <div className="ititle">
        {spec.name}
        <button className="x" onClick={() => removeNode(inst.id)} title="remove">✕</button>
      </div>
      <div className="imeta">
        kind {spec.kind} · {spec.vram_gb ? `${spec.vram_gb}GB` : 'cpu'} ·
        adapter <b className={spec.adapter}>{spec.adapter}</b>
        {spec.dir && <div className="dir">{spec.dir}</div>}
      </div>

      <div className="isec">Parameters</div>
      {spec.params.length === 0 && <p className="muted">No params.</p>}
      {spec.params.map((p) => (
        <Param key={p.name} uid={inst.id} p={p} value={inst.data.params[p.name]}
          set={(name, v) => setParam(inst.id, name, v)} />
      ))}

      <div className="isec">Output</div>
      <Viewer artifact={status?.artifact} />
    </div>
  )
}
