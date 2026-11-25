import React from 'react'
import { Handle, Position } from '@xyflow/react'
import { useStore } from '../store'

const KIND_ACCENT = {
  input: '#1e3a8a', model: '#7c2d12', tool: '#14532d',
  lora: '#581c87', class: '#3f3f46', output: '#0c4a6e',
}
const STATUS_DOT = {
  idle: '#6b7280', queued: '#3b82f6', running: '#eab308',
  done: '#10b981', cached: '#22d3ee', error: '#ef4444',
}

function ports(list, dir, colors) {
  const n = list.length
  return list.map((p, i) => {
    const top = n === 1 ? 50 : 22 + (i * 56) / Math.max(n - 1, 1)
    return (
      <Handle
        key={`${dir}-${p.name}`}
        type={dir === 'in' ? 'target' : 'source'}
        position={dir === 'in' ? Position.Left : Position.Right}
        id={p.name}
        style={{
          top: `${top}%`, width: 12, height: 12,
          background: colors[p.type] || '#888',
          border: '2px solid #0b0d10',
        }}
        title={`${p.name}: ${p.type}`}
      />
    )
  })
}

export default function NodeCard({ id, data, selected }) {
  const byId = useStore((s) => s.byId)
  const colors = useStore((s) => s.portColors)
  const status = useStore((s) => s.status[id])
  const spec = byId[data.nodeId]
  if (!spec) return null
  const accent = KIND_ACCENT[spec.kind] || '#333'
  const st = status?.status || 'idle'
  const adapterTag = {
    pass: '● pass', llm: '● llm', pending: '○ pending',
    io: '· io', synth: '· synth', real: '● real',
  }[spec.adapter] || `· ${spec.adapter}`

  return (
    <div className={`node ${selected ? 'sel' : ''}`} style={{ borderTopColor: accent }}>
      {ports(spec.inputs, 'in', colors)}
      {ports(spec.outputs, 'out', colors)}
      <div className="node-head">
        <span className="dot" style={{ background: STATUS_DOT[st] }} />
        <span className="node-name">{spec.name}</span>
      </div>
      <div className="node-sub">
        <span className="kind-pill" style={{ background: accent }}>{spec.kind}</span>
        <span className="vram">{spec.vram_gb ? `${spec.vram_gb}GB` : 'cpu'}</span>
        <span className={`adapter ${spec.adapter}`}>{adapterTag}</span>
      </div>
      <div className="node-ports">
        <div className="pcol">
          {spec.inputs.map((p) => (
            <span key={p.name} className="ptag" style={{ color: colors[p.type] }}>◧ {p.type}</span>
          ))}
        </div>
        <div className="pcol right">
          {spec.outputs.map((p) => (
            <span key={p.name} className="ptag" style={{ color: colors[p.type] }}>{p.type} ◨</span>
          ))}
        </div>
      </div>
      {status?.ms != null && <div className="node-ms">{st} · {status.ms}ms</div>}
    </div>
  )
}
