import React, { useEffect, useState } from 'react'

export default function Viewer({ artifact }) {
  const [text, setText] = useState(null)
  const url = artifact?.url
  const kind = artifact?.kind
  const isGif = url && url.endsWith('.gif')

  useEffect(() => {
    if (!url) return
    if (kind === 'text' || kind === 'json' || kind === 'embedding') {
      fetch(url).then((r) => r.text()).then(setText).catch(() => setText('(failed to load)'))
    }
  }, [url, kind])

  if (!artifact) return <div className="viewer empty">Run the graph to populate output.</div>

  const badge = (
    <div className="vbadge">
      <span className={`eng ${artifact.engine}`}>{artifact.engine}</span>
      <span>{artifact.type}</span>
      <a href={url} target="_blank" rel="noreferrer">open ↗</a>
    </div>
  )

  let body
  if (kind === 'image') body = <img src={url} alt="" />
  else if (kind === 'video') body = isGif ? <img src={url} alt="" /> : <video src={url} controls />
  else if (kind === 'audio') body = <audio src={url} controls />
  else if (kind === 'mesh') body = <div className="meshbox">3D mesh · <a href={url} download>download .obj</a></div>
  else if (kind === 'text' || kind === 'json' || kind === 'embedding')
    body = <pre className="txtout">{text ?? '…'}</pre>
  else body = <a href={url} target="_blank" rel="noreferrer">artifact ↗</a>

  return <div className="viewer">{badge}<div className="vbody">{body}</div></div>
}
