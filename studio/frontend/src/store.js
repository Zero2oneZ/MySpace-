import { create } from 'zustand'
import { applyNodeChanges, applyEdgeChanges, addEdge } from '@xyflow/react'
import { api, streamRun } from './api'

let seq = 0
const uid = (nodeId) => `${nodeId}-${(seq++).toString(36)}${Math.floor(Math.random() * 1e4).toString(36)}`

export const useStore = create((set, get) => ({
  // catalogue
  byId: {},
  list: [],
  portColors: {},
  glyph: {},
  coercions: {},
  recipes: { multi: [], single: [] },
  flows: [],
  saved: [],
  loaded: false,

  // graph (react-flow controlled)
  nodes: [],
  edges: [],
  selected: null,
  running: false,
  status: {}, // uid -> {status, artifact, ms}

  async init() {
    const [cat, rec, fl, sv] = await Promise.all([
      api.catalogue(), api.recipes(), api.flows(), api.listGraphs(),
    ])
    const byId = Object.fromEntries(cat.nodes.map((n) => [n.id, n]))
    set({
      byId, list: cat.nodes, portColors: cat.port_colors, glyph: cat.type_glyph,
      coercions: cat.coercions, recipes: rec, flows: fl, saved: sv, loaded: true,
    })
  },

  // ─ type system ─
  portType(nodeId, port, dir) {
    const spec = get().byId[nodeId]
    if (!spec) return null
    const arr = dir === 'in' ? spec.inputs : spec.outputs
    return (arr.find((p) => p.name === port) || {}).type || null
  },
  compatible(prod, cons) {
    if (!prod || !cons) return false
    if (prod === cons) return true
    return (get().coercions[prod] || []).includes(cons)
  },

  // ─ node ops ─
  addNode(nodeId, position) {
    const spec = get().byId[nodeId]
    if (!spec) return null
    const params = {}
    spec.params.forEach((p) => { if ('default' in p) params[p.name] = p.default })
    const id = uid(nodeId)
    const pos = position || { x: 120 + get().nodes.length * 40, y: 80 + get().nodes.length * 30 }
    const rfNode = { id, type: 'model', position: pos, data: { nodeId, params } }
    set((s) => ({ nodes: [...s.nodes, rfNode], selected: id }))
    return id
  },
  removeNode(id) {
    set((s) => ({
      nodes: s.nodes.filter((n) => n.id !== id),
      edges: s.edges.filter((e) => e.source !== id && e.target !== id),
      selected: s.selected === id ? null : s.selected,
    }))
  },
  setParam(id, name, value) {
    set((s) => ({
      nodes: s.nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, params: { ...n.data.params, [name]: value } } } : n),
    }))
  },
  select(id) { set({ selected: id }) },

  onNodesChange(changes) { set((s) => ({ nodes: applyNodeChanges(changes, s.nodes) })) },
  onEdgesChange(changes) { set((s) => ({ edges: applyEdgeChanges(changes, s.edges) })) },
  onConnect(c) {
    const { nodes, portType, compatible, portColors } = get()
    const src = nodes.find((n) => n.id === c.source)
    const dst = nodes.find((n) => n.id === c.target)
    if (!src || !dst) return
    const pt = portType(src.data.nodeId, c.sourceHandle, 'out')
    const ct = portType(dst.data.nodeId, c.targetHandle, 'in')
    if (!compatible(pt, ct)) {
      set({ toast: `✗ ${pt} cannot feed a ${ct} input` })
      setTimeout(() => set({ toast: null }), 2200)
      return
    }
    set((s) => ({
      edges: addEdge(
        { ...c, animated: false, style: { stroke: portColors[pt] || '#888', strokeWidth: 2 } },
        s.edges),
    }))
  },

  // ─ recipes / layout ─
  loadChain(chain) {
    seq += 1
    const newNodes = []
    chain.forEach((nodeId, i) => {
      const spec = get().byId[nodeId]
      if (!spec) return
      const params = {}
      spec.params.forEach((p) => { if ('default' in p) params[p.name] = p.default })
      newNodes.push({ id: uid(nodeId), type: 'model', position: { x: i * 290, y: 60 + (i % 2) * 40 }, data: { nodeId, params } })
    })
    set({ nodes: newNodes, edges: [], status: {}, selected: newNodes[0]?.id || null })
    get().autoWire()
  },
  autoWire() {
    const { nodes, byId, compatible, portColors } = get()
    const ordered = [...nodes].sort((a, b) => a.position.x - b.position.x)
    const edges = []
    ordered.forEach((n, idx) => {
      const spec = byId[n.data.nodeId]
      spec.inputs.forEach((inp) => {
        for (let j = idx - 1; j >= 0; j--) {
          const up = byId[ordered[j].data.nodeId]
          const op = up.outputs.find((o) => compatible(o.type, inp.type))
          if (op) {
            edges.push({
              id: `${ordered[j].id}.${op.name}->${n.id}.${inp.name}`,
              source: ordered[j].id, target: n.id,
              sourceHandle: op.name, targetHandle: inp.name,
              style: { stroke: portColors[op.type] || '#888', strokeWidth: 2 },
            })
            break
          }
        }
      })
    })
    set({ edges })
  },
  clear() { set({ nodes: [], edges: [], status: {}, selected: null }) },

  // ─ serialization ─
  toGraph() {
    const { nodes, edges } = get()
    return {
      nodes: nodes.map((n) => ({ uid: n.id, node_id: n.data.nodeId, params: n.data.params, position: n.position })),
      edges: edges.map((e) => ({ src_uid: e.source, dst_uid: e.target, src_port: e.sourceHandle, dst_port: e.targetHandle })),
    }
  },
  fromGraph(doc) {
    const nodes = (doc.nodes || []).map((n, i) => ({
      id: n.uid, type: 'model',
      position: n.position || { x: i * 290, y: 80 },
      data: { nodeId: n.node_id, params: n.params || {} },
    }))
    const { byId, portColors } = get()
    const edges = (doc.edges || []).map((e) => {
      const up = byId[(nodes.find((n) => n.id === e.src_uid) || {}).data?.nodeId]
      const pt = up?.outputs.find((o) => o.name === e.src_port)?.type
      return {
        id: `${e.src_uid}.${e.src_port}->${e.dst_uid}.${e.dst_port}`,
        source: e.src_uid, target: e.dst_uid, sourceHandle: e.src_port, targetHandle: e.dst_port,
        style: { stroke: portColors[pt] || '#888', strokeWidth: 2 },
      }
    })
    set({ nodes, edges, status: {}, selected: nodes[0]?.id || null })
  },

  async save(name) {
    await api.saveGraph(name, get().toGraph())
    set({ saved: await api.listGraphs() })
  },
  async load(name) { get().fromGraph(await api.loadGraph(name)) },

  // ─ run ─
  async run() {
    if (get().running) return
    const g = get().toGraph()
    set({ running: true, status: {} })
    const { run_id } = await api.startRun(g.nodes, g.edges)
    streamRun(run_id,
      (ev) => {
        if (ev.event === 'node') {
          set((s) => ({ status: { ...s.status, [ev.uid]: { status: ev.status, artifact: ev.artifact, ms: ev.ms } } }))
        } else if (ev.event === 'error') {
          set({ toast: (ev.errors || ['error']).join('; ') })
          setTimeout(() => set({ toast: null }), 4000)
        }
      },
      () => set({ running: false }))
  },

  toast: null,
}))
