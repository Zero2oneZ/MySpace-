// offscreen.js — records the captured tab stream and samples its audio
// amplitude live (Web Audio AnalyserNode), so the server never has to decode
// video to colourise the sound wave. On stop it POSTs the amplitude series
// (→ rgb/hex chroma) and then the recorded webm to the local server.
"use strict";

const CHROMA_URL = "http://127.0.0.1:8520/dapp/api/stream-chroma";
const VIDEO_URL = "http://127.0.0.1:8520/dapp/api/stream-video";

let recorder = null, chunks = [], audioCtx = null, ampTimer = null;
let amps = [], startTs = 0, meta = {};

chrome.runtime.onMessage.addListener((m) => {
  if (!m || m.target !== "offscreen") return;
  if (m.type === "offscreen-start") start(m).catch(reportErr);
  else if (m.type === "offscreen-stop") stop();
});

async function start(m) {
  meta = { token: m.token || "", page_url: m.page_url || "" };
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: m.streamId } },
    video: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: m.streamId } },
  });

  // sample amplitude ~30x/sec; also re-route audio to speakers so tabCapture
  // does not silence the tab the user is watching.
  audioCtx = new AudioContext();
  const src = audioCtx.createMediaStreamSource(stream);
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 512;
  src.connect(analyser);
  src.connect(audioCtx.destination);
  const buf = new Uint8Array(analyser.fftSize);
  amps = [];
  ampTimer = setInterval(() => {
    analyser.getByteTimeDomainData(buf);
    let peak = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = Math.abs(buf[i] - 128) / 128;
      if (v > peak) peak = v;
    }
    amps.push(peak);
  }, 33);

  chunks = [];
  const mime = MediaRecorder.isTypeSupported("video/webm;codecs=vp9,opus")
    ? "video/webm;codecs=vp9,opus" : "video/webm";
  recorder = new MediaRecorder(stream, { mimeType: mime });
  recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
  recorder.onstop = () => { upload().catch(reportErr); stream.getTracks().forEach((t) => t.stop()); };
  startTs = Date.now();
  recorder.start(1000); // 1s timeslices
}

function stop() {
  if (ampTimer) { clearInterval(ampTimer); ampTimer = null; }
  if (recorder && recorder.state !== "inactive") recorder.stop();
}

async function upload() {
  const duration = (Date.now() - startTs) / 1000;
  try {
    const r = await fetch(CHROMA_URL, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: meta.token, page_url: meta.page_url, duration, amps }),
    });
    const j = await r.json();
    const blob = new Blob(chunks, { type: "video/webm" });
    await fetch(
      `${VIDEO_URL}?stream_id=${encodeURIComponent(j.stream_id)}` +
      `&page_url=${encodeURIComponent(meta.page_url)}`,
      { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: blob });
    chrome.runtime.sendMessage({ type: "record-done", stream_id: j.stream_id, bytes: blob.size });
  } catch (e) {
    reportErr(e);
  } finally {
    if (audioCtx) { try { await audioCtx.close(); } catch (_) {} audioCtx = null; }
    try { window.close(); } catch (_) {}
  }
}

function reportErr(e) {
  chrome.runtime.sendMessage({ type: "record-error", error: String(e) });
}
