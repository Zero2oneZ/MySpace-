const J = (r) => r.json()

export const api = {
  catalogue: () => fetch('/api/catalogue').then(J),
  recipes: () => fetch('/api/recipes').then(J),
  flows: () => fetch('/api/flows').then(J),
  listGraphs: () => fetch('/api/graphs').then(J),
  loadGraph: (name) => fetch(`/api/graphs/${name}`).then(J),
  saveGraph: (name, doc) =>
    fetch(`/api/graphs/${encodeURIComponent(name)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(doc),
    }).then(J),
  startRun: (nodes, edges) =>
    fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nodes, edges }),
    }).then(J),
}

// open an SSE stream for a run; onEvent receives parsed event objects.
export function streamRun(runId, onEvent, onDone) {
  const es = new EventSource(`/api/run/${runId}/stream`)
  es.onmessage = (e) => {
    try { onEvent(JSON.parse(e.data)) } catch {}
  }
  es.addEventListener('eof', () => { es.close(); onDone && onDone() })
  es.onerror = () => { es.close(); onDone && onDone() }
  return es
}
