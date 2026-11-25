// background.js (service worker) — receives scrape batches from content.js and
// POSTs them to the local MySpace++ wallet-map ingest. The fetch happens here
// (not the content script) so it runs with the extension's host_permissions
// and is not blocked by the solscan.io page's CORS policy.
"use strict";

const INGEST_URL = "http://127.0.0.1:8520/dapp/api/solscan-ingest";

async function getState() {
  const s = await chrome.storage.local.get({ enabled: true, sent: 0, lastErr: "" });
  return s;
}

async function bump(nodes) {
  const s = await getState();
  const sent = s.sent + nodes;
  await chrome.storage.local.set({ sent });
  try {
    await chrome.action.setBadgeText({ text: sent > 999 ? "999+" : String(sent) });
    await chrome.action.setBadgeBackgroundColor({ color: "#2dd4bf" });
  } catch (_) {}
}

// ── tab recording (Feature B) ────────────────────────────────────────────────
const B58 = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
function tokenFromUrl(url) {
  try {
    const u = new URL(url);
    for (const seg of u.pathname.split("/")) {
      const s = (seg || "").split("?")[0];
      if (B58.test(s)) return s; // pump.fun/coin/<mint>, solscan/token/<mint>, …
    }
  } catch (_) {}
  return "";
}

async function ensureOffscreen() {
  const has = chrome.offscreen.hasDocument ? await chrome.offscreen.hasDocument() : false;
  if (has) return;
  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["USER_MEDIA"],
    justification: "Record the captured tab stream and sample its audio amplitude.",
  });
}

async function startRecording() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) throw new Error("no active tab");
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
  const token = tokenFromUrl(tab.url || "");
  await ensureOffscreen();
  await chrome.runtime.sendMessage({
    target: "offscreen", type: "offscreen-start",
    streamId, token, page_url: tab.url || "",
  });
  await chrome.storage.local.set({ recording: true, recToken: token });
  await chrome.action.setBadgeText({ text: "REC" });
  await chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
}

async function stopRecording() {
  await chrome.runtime.sendMessage({ target: "offscreen", type: "offscreen-stop" });
  await chrome.storage.local.set({ recording: false });
  await chrome.action.setBadgeText({ text: "" });
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg) return;
  if (msg.target === "offscreen") return; // not for us — the offscreen doc handles it

  if (msg.type === "record-start") {
    startRecording().then(() => sendResponse({ ok: true }))
      .catch((e) => { chrome.storage.local.set({ lastErr: String(e), recording: false });
                      sendResponse({ ok: false, error: String(e) }); });
    return true;
  }
  if (msg.type === "record-stop") {
    stopRecording().then(() => sendResponse({ ok: true }))
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  if (msg.type === "record-done") {
    chrome.storage.local.get({ streamsRec: 0 }).then((s) =>
      chrome.storage.local.set({ streamsRec: s.streamsRec + 1, recording: false }));
    chrome.action.setBadgeText({ text: "" });
    return;
  }
  if (msg.type === "record-error") {
    chrome.storage.local.set({ lastErr: msg.error, recording: false });
    chrome.action.setBadgeText({ text: "" });
    return;
  }

  if (msg.type !== "scrape") return;
  (async () => {
    const s = await getState();
    if (!s.enabled) {
      sendResponse({ ok: false, disabled: true });
      return;
    }
    try {
      const r = await fetch(INGEST_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(msg.payload),
      });
      const j = await r.json();
      await bump((msg.payload.nodes || []).length);
      await chrome.storage.local.set({ lastErr: "" });
      sendResponse({ ok: true, server: j });
    } catch (e) {
      await chrome.storage.local.set({ lastErr: String(e) });
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true; // keep the message channel open for the async response
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.action.setBadgeText({ text: "" });
});
