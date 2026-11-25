"use strict";
const MAP_URL = "http://127.0.0.1:8520/dapp/wallet-map";
const INGEST_URL = "http://127.0.0.1:8520/dapp/api/solscan-ingest";

// The user-provided Padre container selector is the default. The css-* emotion
// hashes change between builds, so the injected grabber tries this first, then
// the stable `.padre-no-scroll` class, then the whole document.
const DEFAULT_SELECTOR =
  "#root > div:nth-child(4) > div.MuiStack-root.css-fampf7 > div > div > " +
  "div.MuiStack-root.padre-no-scroll.css-kuxdc4 > div > div";

// ── injected into the active tab (must be self-contained / serializable) ──────
function grabWalletsInPage(selector) {
  const FULL = /\b[1-9A-HJ-NP-Za-km-z]{32,44}\b/g;
  const TRUNC = /[1-9A-HJ-NP-Za-km-z]{3,8}(?:\.{2,3}|…)[1-9A-HJ-NP-Za-km-z]{3,8}/g;
  const isAddr = (s) => /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(s);

  let container = null;
  let how = "document";
  try { container = selector && document.querySelector(selector); } catch (_) {}
  if (container) how = "selector";
  if (!container) { container = document.querySelector(".padre-no-scroll"); if (container) how = ".padre-no-scroll"; }
  if (!container) { container = document.body; how = "document"; }

  const addrs = new Set();
  const tail = (href) => {
    try { const p = new URL(href, location.origin).pathname.split("/").filter(Boolean);
      return (p[p.length - 1] || "").split("?")[0]; } catch (_) { return ""; }
  };

  // 1) attributes most likely to hold the FULL address even when text is cut
  container.querySelectorAll("*").forEach((el) => {
    const cands = [];
    if (el.getAttribute) {
      cands.push(el.getAttribute("href"), el.getAttribute("title"),
                 el.getAttribute("aria-label"), el.getAttribute("data-address"),
                 el.getAttribute("data-pubkey"), el.getAttribute("data-id"));
    }
    if (el.dataset) for (const k in el.dataset) cands.push(el.dataset[k]);
    for (const c of cands) {
      if (!c) continue;
      if (isAddr(c)) addrs.add(c);
      const t = tail(c); if (isAddr(t)) addrs.add(t);
      const m = String(c).match(FULL); if (m) m.forEach((x) => addrs.add(x));
    }
  });

  // 2) raw text (catches full addresses rendered inline)
  const text = container.innerText || container.textContent || "";
  const mt = text.match(FULL); if (mt) mt.forEach((x) => addrs.add(x));

  // 3) how many addresses are only shown truncated (cannot be resolved here)
  const truncated = (text.match(TRUNC) || []).length;

  return {
    addrs: [...addrs].filter(isAddr),
    truncated,
    container_via: how,
    page_url: location.href,
    host: location.host,
  };
}

// ── popup wiring ──────────────────────────────────────────────────────────────
async function refresh() {
  const s = await chrome.storage.local.get(
    { enabled: true, sent: 0, lastErr: "", selector: DEFAULT_SELECTOR,
      recording: false, streamsRec: 0 });
  document.getElementById("sent").textContent = s.sent;
  document.getElementById("enabled").checked = s.enabled;
  document.getElementById("selector").value = s.selector || DEFAULT_SELECTOR;
  document.getElementById("err").textContent = s.lastErr ? "last error: " + s.lastErr : "";
  document.getElementById("streams").textContent = s.streamsRec;
  const rec = document.getElementById("record");
  if (s.recording) { rec.textContent = "■ Stop recording"; rec.classList.add("primary"); }
  else { rec.textContent = "● Record this tab (video + sound)"; rec.classList.remove("primary"); }
}

document.getElementById("record").addEventListener("click", async () => {
  const s = await chrome.storage.local.get({ recording: false });
  const type = s.recording ? "record-stop" : "record-start";
  const resp = await chrome.runtime.sendMessage({ type });
  if (resp && resp.error) {
    await chrome.storage.local.set({ lastErr: resp.error });
  }
  setTimeout(refresh, 300);
});

document.getElementById("selector").addEventListener("change", async (e) => {
  await chrome.storage.local.set({ selector: e.target.value });
});

document.getElementById("enabled").addEventListener("change", async (e) => {
  await chrome.storage.local.set({ enabled: e.target.checked });
});

document.getElementById("open").addEventListener("click", () => {
  chrome.tabs.create({ url: MAP_URL });
});

document.getElementById("reset").addEventListener("click", async () => {
  await chrome.storage.local.set({ sent: 0 });
  try { await chrome.action.setBadgeText({ text: "" }); } catch (_) {}
  refresh();
});

document.getElementById("grab").addEventListener("click", async () => {
  const result = document.getElementById("result");
  const errEl = document.getElementById("err");
  errEl.textContent = "";
  result.textContent = "scanning…";
  const selector = document.getElementById("selector").value.trim();
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || /^(chrome|edge|brave|about):/.test(tab.url || "")) {
      throw new Error("open a normal web page tab first");
    }
    const [{ result: r }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: grabWalletsInPage,
      args: [selector],
    });
    if (!r || !r.addrs.length) {
      result.textContent =
        `0 full addresses (via ${r ? r.container_via : "?"}` +
        (r && r.truncated ? `, ${r.truncated} shown truncated` : "") + ")";
      return;
    }
    const payload = {
      focus: "", focus_kind: "",
      page_url: r.page_url,
      ts: Math.floor(Date.now() / 1000),
      nodes: r.addrs.map((a) => ({ addr: a, kind: "wallet", label: r.host })),
      edges: [],
    };
    const resp = await fetch(INGEST_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const j = await resp.json();
    const s = await chrome.storage.local.get({ sent: 0 });
    const sent = s.sent + r.addrs.length;
    await chrome.storage.local.set({ sent, lastErr: "" });
    try {
      await chrome.action.setBadgeText({ text: sent > 999 ? "999+" : String(sent) });
      await chrome.action.setBadgeBackgroundColor({ color: "#2dd4bf" });
    } catch (_) {}
    result.textContent =
      `✓ ${r.addrs.length} wallets sent (via ${r.container_via}` +
      (r.truncated ? `; ${r.truncated} truncated skipped` : "") +
      `). server merged ${j.merged_nodes}.`;
    refresh();
  } catch (e) {
    await chrome.storage.local.set({ lastErr: String(e) });
    result.textContent = "";
    errEl.textContent = "grab failed: " + e;
  }
});

refresh();
