# MySpace++ Wallet Map — Solscan browser extension

Scrapes Solana addresses (wallets, token mints, tx signatures) and their
relationships from **solscan.io** pages *as you browse*, and feeds them to the
local MySpace++ wallet map. Read-only: it never touches keys, never signs, and
only reads the DOM of pages you are already viewing.

## How it fits together

```
solscan.io page ──content.js (scrape)──▶ background.js (service worker)
                                              │ POST
                                              ▼
                    http://127.0.0.1:8520/dapp/api/solscan-ingest   (dapp_server)
                                              │ merge
                                              ▼
                    ~/.cc/wallet_map/{wallets,edges}.jsonl  ◀── cc wallet-map-scan (on-chain)
                                              │
                                              ▼
                    http://127.0.0.1:8520/dapp/wallet-map     (live graph)
```

The `fetch` runs in the **background service worker** (not the content script)
so it uses the extension's `host_permissions` and is not blocked by solscan's
page CORS.

## Install (Brave / Chrome / Edge — Chromium MV3)

1. Start the local server: `cc wallet-map-serve` (or
   `MSPC_DAPP_PORT=8520 python3 studio/dapp/server.py`).
2. Open `brave://extensions` (or `chrome://extensions`).
3. Toggle **Developer mode** (top-right).
4. Click **Load unpacked** and select this folder:
   `studio/extensions/solscan-map/`.
5. Browse to e.g. `https://solscan.io/token/So11111111111111111111111111111111111111112`.
   The toolbar badge counts addresses sent. Click the icon → **Open the map**.

## Grab all wallets on any page (Padre, GMGN, Photon, …)

Solscan auto-captures as you browse. For **other** MUI/React trading terminals,
use the on-demand grabber:

1. Open the page with the wallet list (e.g. Padre).
2. Click the extension icon → the **selector** box defaults to the Padre
   container; edit it for other sites if needed.
3. Click **⬇ Grab all wallets on this page**.

The grabber (injected via `activeTab` + `scripting`) finds the container — your
selector first, then the stable `.padre-no-scroll` class, then the whole page —
and extracts **full** base58 addresses from element text *and* attributes
(`href`, `title`, `aria-label`, `data-*`), which is where these apps usually
keep the un-truncated address. It reports how many addresses were only shown
**truncated** (`7xKX…gAsU`) and therefore could not be resolved.

Two known limits on these terminals:
- **Truncation:** if an address only ever appears truncated in the DOM (no full
  value in any attribute), it can't be captured — the count tells you how many.
- **Virtualization:** long lists render only the visible rows, so "all" means
  "all currently rendered". Scroll the list and click grab again to accumulate.

## Firefox

Firefox supports MV3 but uses a non-persistent background **script** rather than
a `service_worker`. To load there, change the `background` key in `manifest.json`
to `{ "scripts": ["background.js"] }` and load via `about:debugging` →
**This Firefox** → **Load Temporary Add-on**.

## Tuning when solscan's markup changes

All scraping keys live in the `SELECTORS` map at the top of `content.js`. It
targets anchor `href`s (stable) rather than CSS classes, and falls back to every
`/account/`, `/address/`, `/token/`, `/tx/` link on the page, so it degrades
gracefully if the layout shifts.

## Privacy / scope

- Only `https://solscan.io/*` pages are scraped (see `content_scripts.matches`).
- Data is POSTed only to `127.0.0.1:8520` (your machine).
- No wallet connection, no transaction signing, no private keys — observational
  graph building only.
