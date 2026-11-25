import React, { useEffect, useState } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap, ReactFlowProvider,
} from '@xyflow/react'
import { useStore } from './store'
import NodeCard from './components/NodeCard'
import Palette from './components/Palette'
import Inspector from './components/Inspector'

const nodeTypes = { model: NodeCard }

function Canvas() {
  const nodes = useStore((s) => s.nodes)
  const edges = useStore((s) => s.edges)
  const onNodesChange = useStore((s) => s.onNodesChange)
  const onEdgesChange = useStore((s) => s.onEdgesChange)
  const onConnect = useStore((s) => s.onConnect)
  const select = useStore((s) => s.select)

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onNodeClick={(_, n) => select(n.id)}
      onPaneClick={() => select(null)}
      fitView
      proOptions={{ hideAttribution: true }}
      defaultEdgeOptions={{ style: { strokeWidth: 2 } }}
    >
      <Background gap={24} color="#1b2030" />
      <MiniMap pannable zoomable nodeColor="#2a2f3a" maskColor="rgba(10,12,16,0.7)" />
      <Controls />
    </ReactFlow>
  )
}

function Topbar() {
  const run = useStore((s) => s.run)
  const running = useStore((s) => s.running)
  const autoWire = useStore((s) => s.autoWire)
  const clear = useStore((s) => s.clear)
  const save = useStore((s) => s.save)
  const load = useStore((s) => s.load)
  const saved = useStore((s) => s.saved)
  const nodes = useStore((s) => s.nodes)
  const [name, setName] = useState('pipeline.dag.json')

  return (
    <div className="topbar">
      <span className="brand">🧩 DAG Studio</span>
      <button className="run" disabled={running} onClick={run}>{running ? '… running' : '▶ Run'}</button>
      <button onClick={autoWire}>⟳ Auto-wire</button>
      <button onClick={clear}>Clear</button>
      <span className="spacer" />
      <span className="stat">{nodes.length} nodes</span>
      <input className="savename" value={name} onChange={(e) => setName(e.target.value)} />
      <button onClick={() => save(name)}>Save</button>
      <select onChange={(e) => e.target.value && load(e.target.value)} value="">
        <option value="">Load…</option>
        {saved.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
    </div>
  )
}

export default function App() {
  const init = useStore((s) => s.init)
  const loaded = useStore((s) => s.loaded)
  const toast = useStore((s) => s.toast)
  useEffect(() => { init() }, [init])

  if (!loaded) return <div className="boot">connecting to backend…</div>

  return (
    <ReactFlowProvider>
      <div className="app">
        <Topbar />
        <div className="body">
          <Palette />
          <div className="canvas"><Canvas /></div>
          <Inspector />
        </div>
        {toast && <div className="toast">{toast}</div>}
      </div>
    </ReactFlowProvider>
  )
}
