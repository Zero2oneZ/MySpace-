import React, { useState } from 'react'
import { useStore } from '../store'

const KINDS = [
  ['input', 'Inputs'], ['model', 'Models'], ['tool', 'Tools'],
  ['lora', 'Loras'], ['class', 'Class'], ['output', 'Outputs'],
]

export default function Palette() {
  const list = useStore((s) => s.list)
  const colors = useStore((s) => s.portColors)
  const recipes = useStore((s) => s.recipes)
  const addNode = useStore((s) => s.addNode)
  const loadChain = useStore((s) => s.loadChain)
  const [q, setQ] = useState('')
  const [tab, setTab] = useState('nodes')

  const match = (n) => !q || n.name.toLowerCase().includes(q.toLowerCase())

  return (
    <div className="palette">
      <div className="seg">
        <button className={tab === 'nodes' ? 'on' : ''} onClick={() => setTab('nodes')}>Nodes</button>
        <button className={tab === 'recipes' ? 'on' : ''} onClick={() => setTab('recipes')}>Recipes</button>
      </div>

      {tab === 'nodes' && (
        <>
          <input className="search" placeholder="filter…" value={q} onChange={(e) => setQ(e.target.value)} />
          {KINDS.map(([kind, label]) => {
            const items = list.filter((n) => n.kind === kind && match(n))
            if (!items.length) return null
            return (
              <details key={kind} open={kind === 'input' || kind === 'model'}>
                <summary>{label} <span className="count">{items.length}</span></summary>
                {items.map((n) => (
                  <div key={n.id} className="pitem" onClick={() => addNode(n.id)} title="add to canvas">
                    <span className="pname">{n.name}</span>
                    <span className="pio">
                      {n.inputs.map((p) => <i key={'i' + p.name} style={{ background: colors[p.type] }} />)}
                      <em>→</em>
                      {n.outputs.map((p) => <i key={'o' + p.name} style={{ background: colors[p.type] }} />)}
                    </span>
                  </div>
                ))}
              </details>
            )
          })}
        </>
      )}

      {tab === 'recipes' && (
        <>
          <details open>
            <summary>Multi-hop <span className="count">{recipes.multi.length}</span></summary>
            {recipes.multi.map((r) => (
              <div key={r.id} className="ritem" onClick={() => loadChain(r.chain)} title={r.note}>
                <b>{r.id}</b> {r.name}
                <small>{r.note}</small>
              </div>
            ))}
          </details>
          <details>
            <summary>Single-hop <span className="count">{recipes.single.length}</span></summary>
            {recipes.single.map((r) => (
              <div key={r.id} className="ritem" onClick={() => loadChain(r.chain)}>
                <b>{r.id}</b> <small>{r.chain.join(' → ')}</small>
              </div>
            ))}
          </details>
        </>
      )}
    </div>
  )
}
