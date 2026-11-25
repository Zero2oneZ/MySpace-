#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        token_wallet_mapper
# role:        SOLANA · ALL-WALLETS CAPTURE + WALLET-INTERACTION GRAPH STORE
# tier:        L0
# substrate:   Hydrates the signatures that program_monitor already records for
#              a watched token into actual signer wallet addresses, and merges
#              them with DOM-scraped wallets (browser extension) into a single
#              de-duplicated node/edge store that the dapp_server map reads.
# storage:     ~/.cc/wallet_map/{wallets.jsonl, edges.jsonl, dom/<date>.jsonl}
# reads:       ~/.cc/program_events/solana/*/*.jsonl   (program_monitor output)
# stdlib-only: getTransaction over urllib (mirrors program_registry.verify_live)
# ----------------------------------------------------------------------------
"""token_wallet_mapper — turn monitored signatures into a wallet graph.

The program_monitor stores only {signature, slot, action} per on-chain event —
never the wallets. This module closes that gap: it walks the recorded events
for a given token mint, hydrates each unique signature via the Solana JSON-RPC
`getTransaction`, extracts the *signer* wallets (fee-payer first), and appends
them to an append-only node/edge store. The browser extension feeds the same
store with addresses scraped from solscan.io pages. The merged, de-duplicated
graph is what `dapp_server` renders as the live wallet map.

CLI:
    python3 core/lib/token_wallet_mapper.py scan <mint> [--since TS]
                [--max-sigs N] [--rpc URL] [--delay SECS]
    python3 core/lib/token_wallet_mapper.py stats
    python3 core/lib/token_wallet_mapper.py svg [--out FILE] [--token MINT]
    python3 core/lib/token_wallet_mapper.py clear
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# ── layout ──────────────────────────────────────────────────────────────────

HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
PROGRAM_EVENTS = HOME / "program_events" / "solana"
WALLET_MAP_DIR = HOME / "wallet_map"
NODES_FILE = WALLET_MAP_DIR / "wallets.jsonl"
EDGES_FILE = WALLET_MAP_DIR / "edges.jsonl"
DOM_DIR = WALLET_MAP_DIR / "dom"
HYDRATED_FILE = WALLET_MAP_DIR / "_hydrated.txt"  # signatures already processed

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"

# base58 alphabet (matches program_registry._is_solana_addr)
_B58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def is_solana_addr(s: str) -> bool:
    return isinstance(s, str) and 32 <= len(s) <= 44 and all(c in _B58 for c in s)


# ── storage primitives (append-only; dedup on read — no rewrite races) ───────

def _ensure_dir() -> None:
    WALLET_MAP_DIR.mkdir(parents=True, exist_ok=True)
    DOM_DIR.mkdir(parents=True, exist_ok=True)


def add_nodes(nodes: Iterable[Dict[str, Any]], source: str) -> int:
    """Append node observations. Dedup happens at read time in load_graph()."""
    _ensure_dir()
    n = 0
    with NODES_FILE.open("a") as f:
        for nd in nodes:
            addr = (nd.get("addr") or "").strip()
            if not addr:
                continue
            row = {
                "addr": addr,
                "kind": nd.get("kind", "wallet"),
                "label": (nd.get("label") or "")[:80],
                "source": source,
                "ts": float(nd.get("ts", time.time())),
            }
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
            n += 1
    return n


def add_edges(edges: Iterable[Dict[str, Any]], source: str) -> int:
    _ensure_dir()
    n = 0
    with EDGES_FILE.open("a") as f:
        for e in edges:
            a = (e.get("from") or "").strip()
            b = (e.get("to") or "").strip()
            if not a or not b or a == b:
                continue
            row = {
                "from": a,
                "to": b,
                "kind": e.get("kind", "interacts"),
                "source": source,
                "signature": e.get("signature", ""),
                "ts": float(e.get("ts", time.time())),
            }
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
            n += 1
    return n


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def load_graph(token: str = "", limit: int = 0) -> Dict[str, Any]:
    """Merge + de-dup the append-only store into {nodes, edges}.

    Node dedup: by addr, keeping earliest ts, summing hits, preferring a
    non-'wallet' kind (token/program) and the first non-empty label.
    Edge dedup: by (from, to, kind).
    """
    nodes: Dict[str, Dict[str, Any]] = {}
    for r in _read_jsonl(NODES_FILE):
        addr = r.get("addr")
        if not addr:
            continue
        cur = nodes.get(addr)
        if cur is None:
            nodes[addr] = {
                "addr": addr,
                "kind": r.get("kind", "wallet"),
                "label": r.get("label", ""),
                "sources": {r.get("source", "?")},
                "first_seen_ts": float(r.get("ts", 0) or 0),
                "hits": 1,
            }
        else:
            cur["hits"] += 1
            cur["sources"].add(r.get("source", "?"))
            ts = float(r.get("ts", 0) or 0)
            if ts and (not cur["first_seen_ts"] or ts < cur["first_seen_ts"]):
                cur["first_seen_ts"] = ts
            if cur["kind"] == "wallet" and r.get("kind") in ("token", "program"):
                cur["kind"] = r["kind"]
            if not cur["label"] and r.get("label"):
                cur["label"] = r["label"]

    edges: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for r in _read_jsonl(EDGES_FILE):
        a, b, k = r.get("from"), r.get("to"), r.get("kind", "interacts")
        if not a or not b:
            continue
        key = (a, b, k)
        if key not in edges:
            edges[key] = {
                "from": a, "to": b, "kind": k,
                "source": r.get("source", "?"),
                "signature": r.get("signature", ""),
                "weight": 1,
            }
        else:
            edges[key]["weight"] += 1

    node_list = list(nodes.values())
    for nd in node_list:
        nd["sources"] = sorted(nd["sources"])
    edge_list = list(edges.values())

    if token:
        # keep the token node, its neighbours, and edges touching the token
        keep: Set[str] = {token}
        for e in edge_list:
            if e["from"] == token or e["to"] == token:
                keep.add(e["from"]); keep.add(e["to"])
        node_list = [n for n in node_list if n["addr"] in keep]
        edge_list = [e for e in edge_list
                     if e["from"] in keep and e["to"] in keep]

    if limit and len(node_list) > limit:
        node_list.sort(key=lambda n: n["hits"], reverse=True)
        node_list = node_list[:limit]
        addrs = {n["addr"] for n in node_list}
        edge_list = [e for e in edge_list
                     if e["from"] in addrs and e["to"] in addrs]

    return {"nodes": node_list, "edges": edge_list,
            "counts": {"nodes": len(node_list), "edges": len(edge_list)}}


# ── on-chain hydration ───────────────────────────────────────────────────────

def _rpc_http(rpc_wss_or_http: str = "") -> str:
    """Resolve an HTTP RPC URL. Accepts an explicit URL, else env, else public.

    SOLANA_RPC_WSS may be a wss:// URL — convert to https:// for getTransaction.
    """
    url = (rpc_wss_or_http
           or os.environ.get("SOLANA_RPC_HTTP", "")
           or os.environ.get("SOLANA_RPC_WSS", "")
           or PUBLIC_RPC)
    if url.startswith("wss://"):
        url = "https://" + url[len("wss://"):]
    elif url.startswith("ws://"):
        url = "http://" + url[len("ws://"):]
    return url


def hydrate_signature(sig: str, rpc_url: str = "",
                      timeout: float = 15.0) -> Dict[str, Any]:
    """getTransaction → {signers:[addr], accounts:[addr], slot, err, fetch_err}.

    Signers are accountKeys[0:numRequiredSignatures]; accountKeys[0] is the
    fee payer. Stdlib urllib only (mirrors program_registry.verify_live_solana).
    """
    rpc = _rpc_http(rpc_url)
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
        "params": [sig, {"encoding": "json",
                         "maxSupportedTransactionVersion": 0,
                         "commitment": "confirmed"}],
    }).encode()
    req = urllib.request.Request(rpc, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        return {"signers": [], "accounts": [], "fetch_err": f"http:{exc.code}"}
    except Exception as exc:
        return {"signers": [], "accounts": [], "fetch_err": repr(exc)[:120]}

    if resp.get("error"):
        return {"signers": [], "accounts": [],
                "fetch_err": f"rpc:{resp['error'].get('message', '?')[:80]}"}
    result = resp.get("result")
    if not result:
        return {"signers": [], "accounts": [], "fetch_err": "not-found"}
    msg = (result.get("transaction") or {}).get("message") or {}
    keys = msg.get("accountKeys") or []
    # versioned txs may give dicts {pubkey, signer, writable}; legacy gives str
    accounts: List[str] = []
    signer_flags: List[bool] = []
    for i, k in enumerate(keys):
        if isinstance(k, dict):
            accounts.append(k.get("pubkey", ""))
            signer_flags.append(bool(k.get("signer", False)))
        else:
            accounts.append(k)
            signer_flags.append(False)
    n_req = (msg.get("header") or {}).get("numRequiredSignatures", 0)
    if any(signer_flags):
        signers = [accounts[i] for i, s in enumerate(signer_flags) if s]
    else:
        signers = accounts[:n_req] if n_req else accounts[:1]
    signers = [s for s in signers if is_solana_addr(s)]
    accounts = [a for a in accounts if is_solana_addr(a)]
    return {
        "signers": signers,
        "accounts": accounts,
        "slot": result.get("slot", 0),
        "err": (result.get("meta") or {}).get("err") is not None,
        "fetch_err": "",
    }


def _iter_token_signatures(token: str, since_ts: float = 0.0) -> Iterable[Tuple[str, float]]:
    """Yield (signature, ts) for events whose program_id == token, newest dirs
    first. Dedup is left to the caller."""
    if not PROGRAM_EVENTS.exists():
        return
    for prog_dir in sorted(PROGRAM_EVENTS.iterdir()):
        if not prog_dir.is_dir():
            continue
        for jf in sorted(prog_dir.glob("*.jsonl")):
            for r in _read_jsonl(jf):
                if r.get("program_id") != token:
                    continue
                ts = float(r.get("ts", 0) or 0)
                if since_ts and ts < since_ts:
                    continue
                sig = r.get("signature")
                if sig:
                    yield sig, ts


def _load_hydrated() -> Set[str]:
    if not HYDRATED_FILE.exists():
        return set()
    return {ln.strip() for ln in HYDRATED_FILE.read_text().splitlines() if ln.strip()}


def _mark_hydrated(sigs: Iterable[str]) -> None:
    _ensure_dir()
    with HYDRATED_FILE.open("a") as f:
        for s in sigs:
            f.write(s + "\n")


def scan_token(token: str, since_ts: float = 0.0, max_sigs: int = 200,
               rpc_url: str = "", delay: float = 0.12,
               verbose: bool = True) -> Dict[str, Any]:
    """Hydrate up to max_sigs unhydrated signatures for `token` and append the
    resulting wallets/edges to the store. Resumable: already-hydrated
    signatures are skipped."""
    rpc = _rpc_http(rpc_url)
    if rpc == PUBLIC_RPC and verbose:
        print("[wallet-map] WARNING: using public mainnet RPC — it throttles "
              "bulk getTransaction. Set SOLANA_RPC_HTTP or pass --rpc for big "
              "scans.", file=sys.stderr)

    done = _load_hydrated()
    # token node first
    add_nodes([{"addr": token, "kind": "token",
                "label": "wSOL" if token.startswith("So1111") else token[:8],
                "ts": time.time()}], source="chain")

    seen: Set[str] = set()
    to_do: List[Tuple[str, float]] = []
    for sig, ts in _iter_token_signatures(token, since_ts):
        if sig in done or sig in seen:
            continue
        seen.add(sig)
        to_do.append((sig, ts))
        if len(to_do) >= max_sigs:
            break

    if verbose:
        print(f"[wallet-map] {len(to_do)} new signatures to hydrate "
              f"(skipping {len(done)} already done) via {rpc}", file=sys.stderr)

    hydrated_now: List[str] = []
    n_wallets = 0
    n_edges = 0
    errors = 0
    backoff = delay
    for i, (sig, ts) in enumerate(to_do, 1):
        info = hydrate_signature(sig, rpc_url=rpc)
        if info.get("fetch_err"):
            errors += 1
            if "http:429" in info["fetch_err"]:
                backoff = min(backoff * 2, 5.0)
                if verbose:
                    print(f"[wallet-map] 429 — backing off to {backoff:.1f}s",
                          file=sys.stderr)
                time.sleep(backoff)
                continue
            # transient/not-found: mark done so we don't loop forever
            hydrated_now.append(sig)
            time.sleep(delay)
            continue
        signers = info["signers"]
        if signers:
            n_wallets += add_nodes(
                ({"addr": s, "kind": "wallet", "ts": ts} for s in signers),
                source="chain")
            payer = signers[0]
            n_edges += add_edges(
                ({"from": s, "to": token,
                  "kind": "signs" if s == payer else "interacts",
                  "signature": sig, "ts": ts} for s in signers),
                source="chain")
        hydrated_now.append(sig)
        if verbose and i % 25 == 0:
            print(f"[wallet-map]   {i}/{len(to_do)} hydrated "
                  f"({n_wallets} wallets, {errors} errs)", file=sys.stderr)
        time.sleep(delay)

    if hydrated_now:
        _mark_hydrated(hydrated_now)

    summary = {
        "token": token, "rpc": rpc,
        "signatures_scanned": len(to_do),
        "new_wallets": n_wallets, "new_edges": n_edges,
        "errors": errors,
        "graph": load_graph(token=token)["counts"],
    }
    if verbose:
        print(f"[wallet-map] done: {json.dumps(summary['graph'])} "
              f"(+{n_wallets} wallet rows, +{n_edges} edges, {errors} errs)",
              file=sys.stderr)
    return summary


# ── DOM ingest (called by dapp_server on extension POST) ─────────────────────

def ingest_dom(payload: Dict[str, Any]) -> Dict[str, int]:
    """Merge a browser-extension scrape batch into the store + archive raw.

    payload = {focus, focus_kind, page_url, ts,
               nodes:[{addr,kind,label}], edges:[{from,to,kind}]}
    """
    _ensure_dir()
    ts = float(payload.get("ts", time.time()))
    # archive raw (audit trail; parallels ~/.cc/phantom_dom_events.jsonl)
    day = time.strftime("%Y-%m-%d", time.gmtime(ts))
    with (DOM_DIR / f"{day}.jsonl").open("a") as f:
        f.write(json.dumps(payload, separators=(",", ":"))[:20000] + "\n")

    nodes = [n for n in (payload.get("nodes") or [])
             if is_solana_addr((n.get("addr") or "").strip())]
    focus = (payload.get("focus") or "").strip()
    if focus and is_solana_addr(focus):
        nodes.append({"addr": focus,
                      "kind": payload.get("focus_kind", "wallet"),
                      "label": payload.get("focus_label", "")})
    edges = [e for e in (payload.get("edges") or [])
             if is_solana_addr((e.get("from") or "").strip())
             and is_solana_addr((e.get("to") or "").strip())]
    for n in nodes:
        n["ts"] = ts
    for e in edges:
        e.setdefault("ts", ts)
        e.setdefault("kind", "interacts")
    nw = add_nodes(nodes, source="dom")
    ne = add_edges(edges, source="dom")
    return {"merged_nodes": nw, "merged_edges": ne}


# ── stats + static SVG export ────────────────────────────────────────────────

def stats() -> Dict[str, Any]:
    g = load_graph()
    by_source: Dict[str, int] = {}
    for n in g["nodes"]:
        for s in n["sources"]:
            by_source[s] = by_source.get(s, 0) + 1
    by_kind: Dict[str, int] = {}
    for n in g["nodes"]:
        by_kind[n["kind"]] = by_kind.get(n["kind"], 0) + 1
    dom_files = sorted(p.name for p in DOM_DIR.glob("*.jsonl")) if DOM_DIR.exists() else []
    return {
        "nodes": g["counts"]["nodes"],
        "edges": g["counts"]["edges"],
        "nodes_by_source": by_source,
        "nodes_by_kind": by_kind,
        "hydrated_signatures": len(_load_hydrated()),
        "dom_days": dom_files,
        "store": str(WALLET_MAP_DIR),
    }


def _pseudo_xy(addr: str, w: int, h: int, pad: int = 40) -> Tuple[int, int]:
    """Deterministic position from address hash (stable across renders)."""
    hx = abs(hash(addr))
    x = pad + (hx % (w - 2 * pad))
    y = pad + ((hx // 7919) % (h - 2 * pad))
    return x, y


def to_svg(token: str = "", limit: int = 300) -> str:
    """Self-contained radial/scatter SVG of the wallet graph (no deps).

    friend_graph_visualizer loads only from the social-graph store by
    player_id, so we emit our own minimal SVG here.
    """
    g = load_graph(token=token, limit=limit)
    nodes = g["nodes"]
    edges = g["edges"]
    W, H = 1200, 760
    pos: Dict[str, Tuple[int, int]] = {}
    # center the token/program nodes, scatter wallets deterministically
    cx, cy = W // 2, H // 2
    for n in nodes:
        if n["kind"] in ("token", "program"):
            pos[n["addr"]] = (cx, cy)
        else:
            pos[n["addr"]] = _pseudo_xy(n["addr"], W, H)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="monospace">',
        f'<rect width="{W}" height="{H}" fill="#0b0e14"/>',
        f'<text x="20" y="30" fill="#9fb3c8" font-size="16">MySpace++ wallet map'
        f' · {len(nodes)} wallets · {len(edges)} edges'
        f'{" · " + token[:8] if token else ""}</text>',
    ]
    for e in edges:
        a = pos.get(e["from"]); b = pos.get(e["to"])
        if not a or not b:
            continue
        col = "#2dd4bf" if e["kind"] == "signs" else "#3b4a5a"
        parts.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" '
                     f'stroke="{col}" stroke-width="0.6" opacity="0.5"/>')
    for n in nodes:
        x, y = pos[n["addr"]]
        if n["kind"] == "token":
            r, col = 11, "#f59e0b"
        elif n["kind"] == "program":
            r, col = 8, "#a78bfa"
        else:
            r, col = 4, "#38bdf8"
        parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{col}">'
                     f'<title>{n["addr"]} ({n["kind"]}, hits={n["hits"]})</title>'
                     f'</circle>')
    parts.append("</svg>")
    return "\n".join(parts)


def clear() -> None:
    for p in (NODES_FILE, EDGES_FILE, HYDRATED_FILE):
        if p.exists():
            p.unlink()
    if DOM_DIR.exists():
        for f in DOM_DIR.glob("*.jsonl"):
            f.unlink()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]

    if cmd == "scan":
        if not args:
            print("usage: scan <mint> [--since TS] [--max-sigs N] [--rpc URL] "
                  "[--delay S]", file=sys.stderr)
            return 2
        token = args[0]
        if not is_solana_addr(token):
            print(f"[wallet-map] not a valid base58 mint: {token}", file=sys.stderr)
            return 2
        rpc = ""
        delay = 0.12
        i = 1
        since_ts = 0.0
        msigs = 200
        while i < len(args):
            a = args[i]
            if a == "--since" and i + 1 < len(args):
                since_ts = float(args[i + 1]); i += 2; continue
            if a == "--max-sigs" and i + 1 < len(args):
                msigs = int(args[i + 1]); i += 2; continue
            if a == "--rpc" and i + 1 < len(args):
                rpc = args[i + 1]; i += 2; continue
            if a == "--delay" and i + 1 < len(args):
                delay = float(args[i + 1]); i += 2; continue
            i += 1
        out = scan_token(token, since_ts=since_ts, max_sigs=msigs,
                         rpc_url=rpc, delay=delay)
        print(json.dumps(out, indent=2))
        return 0

    if cmd == "stats":
        print(json.dumps(stats(), indent=2))
        return 0

    if cmd == "svg":
        out = None
        token = ""
        i = 0
        while i < len(args):
            if args[i] == "--out" and i + 1 < len(args):
                out = args[i + 1]; i += 2; continue
            if args[i] == "--token" and i + 1 < len(args):
                token = args[i + 1]; i += 2; continue
            i += 1
        svg = to_svg(token=token)
        if out:
            Path(out).write_text(svg)
            print(f"[wallet-map] wrote {out} ({len(svg)} bytes)")
        else:
            sys.stdout.write(svg)
        return 0

    if cmd == "clear":
        clear()
        print("[wallet-map] store cleared")
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
