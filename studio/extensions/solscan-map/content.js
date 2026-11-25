// content.js — scrape solscan.io for Solana addresses + relations, hand the
// batch to the background service worker (which does the cross-origin POST).
// Read-only: we only read the DOM of pages you are already viewing.
(() => {
  "use strict";

  // Single place to re-tune if solscan's markup drifts. We scrape anchor hrefs
  // (stable) rather than CSS classes (volatile), and fall back to all matching
  // hrefs on the page so it degrades gracefully.
  const SELECTORS = {
    addrHref: 'a[href*="/account/"], a[href*="/address/"]',
    tokenHref: 'a[href*="/token/"]',
    txHref: 'a[href*="/tx/"]',
    // transfer/holder rows: each row's two address anchors form an edge
    rowAddrHref: 'tr a[href*="/account/"], tr a[href*="/address/"]',
  };

  const B58 = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
  const isAddr = (s) => typeof s === "string" && B58.test(s);

  // Pull the trailing base58 id out of a solscan URL path.
  function idFromHref(href) {
    try {
      const u = new URL(href, location.origin);
      const seg = u.pathname.split("/").filter(Boolean);
      const last = seg[seg.length - 1] || "";
      return last.split("?")[0];
    } catch (_) {
      return "";
    }
  }

  function focusFromUrl() {
    const seg = location.pathname.split("/").filter(Boolean);
    const kind = seg[0]; // token | account | address | tx
    const id = (seg[1] || "").split("?")[0];
    if (kind === "token") return { focus: id, focus_kind: "token" };
    if (kind === "account" || kind === "address")
      return { focus: id, focus_kind: "wallet" };
    if (kind === "tx") return { focus: "", focus_kind: "tx", signature: id };
    return { focus: "", focus_kind: "" };
  }

  function scrape() {
    const f = focusFromUrl();
    const nodes = new Map(); // addr -> {addr, kind, label}
    const edges = new Map(); // "a|b|kind" -> {from,to,kind}

    const addNode = (addr, kind) => {
      if (!isAddr(addr)) return;
      if (!nodes.has(addr)) nodes.set(addr, { addr, kind, label: "" });
    };
    const addEdge = (a, b, kind) => {
      if (!isAddr(a) || !isAddr(b) || a === b) return;
      edges.set(`${a}|${b}|${kind}`, { from: a, to: b, kind });
    };

    // focus node
    if (isAddr(f.focus)) addNode(f.focus, f.focus_kind === "token" ? "token" : "wallet");

    // every wallet/account anchor → node + edge to focus
    document.querySelectorAll(SELECTORS.addrHref).forEach((a) => {
      const id = idFromHref(a.getAttribute("href"));
      if (!isAddr(id)) return;
      addNode(id, "wallet");
      if (isAddr(f.focus)) addEdge(id, f.focus, "interacts");
    });

    // token anchors → token nodes
    document.querySelectorAll(SELECTORS.tokenHref).forEach((a) => {
      const id = idFromHref(a.getAttribute("href"));
      addNode(id, "token");
      if (isAddr(f.focus) && id !== f.focus) addEdge(f.focus, id, "interacts");
    });

    // table rows with two addresses → from→to transfer edges
    document.querySelectorAll("tr").forEach((tr) => {
      const addrs = [];
      tr.querySelectorAll(SELECTORS.rowAddrHref).forEach((a) => {
        const id = idFromHref(a.getAttribute("href"));
        if (isAddr(id)) addrs.push(id);
      });
      if (addrs.length >= 2) {
        addNode(addrs[0], "wallet");
        addNode(addrs[1], "wallet");
        addEdge(addrs[0], addrs[1], "transfer");
      }
    });

    return {
      focus: f.focus,
      focus_kind: f.focus_kind,
      page_url: location.href,
      ts: Math.floor(Date.now() / 1000),
      nodes: [...nodes.values()],
      edges: [...edges.values()],
    };
  }

  let lastSig = "";
  function send() {
    const batch = scrape();
    if (!batch.nodes.length && !batch.edges.length) return;
    const sig = batch.nodes.length + ":" + batch.edges.length + ":" + location.pathname;
    if (sig === lastSig) return; // nothing new since last scrape
    lastSig = sig;
    try {
      chrome.runtime.sendMessage({ type: "scrape", payload: batch });
    } catch (_) {
      /* extension context invalidated on navigation — ignore */
    }
  }

  // initial + debounced re-scrape as solscan hydrates its SPA content
  let t = null;
  const debounced = () => {
    clearTimeout(t);
    t = setTimeout(send, 800);
  };
  send();
  const mo = new MutationObserver(debounced);
  mo.observe(document.body, { childList: true, subtree: true });
})();
