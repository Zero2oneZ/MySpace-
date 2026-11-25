# Facebook Instant Games — MySpace++ Playbook

> The single doc that explains every Facebook-side moving part of MySpace++.
> Read this end-to-end before you touch anything in `studio/godot/` or any
> `core/lib/third_party/facebook_*.py` / `core/lib/third_party/fb_*.py` module.
>
> Sibling docs you should know about:
> - `studio/docs/TWINS-MASTER.md` — the global MySpace++ architecture map
> - `studio/docs/PASSES_DAG.md` — inference passes
> - `studio/docs/NOTES-FOR-INFERANCE.md` — cross-half comm channel with GentlyOS
> - `studio/godot/templates/instant_games_manifest.json` — the submitted manifest

---

## §1 — Overview

### What Facebook Instant Games is
Facebook Instant Games is Meta's HTML5-game platform embedded directly inside
**Messenger threads** and the **News Feed**. A game is shipped as a static HTML
bundle (`index.html` + `.wasm` + `.pck` + assets). The platform serves it inside
a sandboxed iframe and exposes the **FBInstant JS SDK** (we ship against
`fbinstant.7.1.js`) for identity, friends, contexts, leaderboards, payments,
and analytics.

Key platform contracts (these drive almost every decision in this doc):

| Contract                  | What it means in practice                                      |
| ------------------------- | --------------------------------------------------------------- |
| Iframe-only delivery      | Our HTML shell must accept `frame-ancestors facebook.com,messenger.com` and we cannot rely on top-level navigation. |
| FBInstant lifecycle       | `initializeAsync` → `setLoadingProgress` → `startGameAsync` is mandatory; skipping `startGameAsync` leaves the loading splash up forever. |
| App-scoped player IDs     | `FBInstant.player.getID()` is NOT a Facebook UID; it is per-app and stable per (app × user). |
| `signedPlayerInfo`        | Server-validated identity: HMAC-SHA256 over the payload using `FB_APP_SECRET`. We verify with stdlib `hmac.compare_digest` — never trust the client. |
| `getConnectedPlayersAsync`| Returns **only app-using friends** since the 2014 Platform v2.0 deprecation. With a single OAuth grant we get the subset of friends already playing — usually 30–80% of the active social graph. |
| COOP/COEP requirement     | Godot 4 threaded WebAssembly needs SharedArrayBuffer → COEP `require-corp` + COOP `same-origin`. Meta's iframe already sets these; we re-assert in Caddy for direct loads. |
| Manifest-driven listing   | `instant_games_manifest.json` is what Meta indexes. Editing it = re-submission. |

### Why we picked this path
1. **Lowest-friction friend acquisition.** One OAuth grant for `public_profile`
   + `user_friends` gives us a real, signed slice of the user's social graph
   inside our own audit log — without ever building a friend-discovery UX.
2. **Distribution piggyback.** Meta surfaces Instant Games in Messenger inboxes
   and feed shares. Every `FBInstant.context.chooseAsync` puts our game into a
   friend chat for free.
3. **Existing Godot pipeline.** We already export Godot 4.6.3 web builds. The
   Instant Games preset (`preset.3`) is a small delta on top of the standard
   web export — same WASM, same `.pck`, different HTML shell.
4. **GDPR-defensible by construction.** Every consent + every friend record is
   crystal-anchored. The same chain that proves the inference history proves
   the consent history.

### Where it lives in our substrate
```
Godot 4.6 (planet_map_scene)
        │  exports
        ▼
studio/godot/build/web_instant_games/
        index.html (rendered from myspace_instant_games_shell.html)
        .wasm + .pck + assets
        │  rsync'd by sync-games-build.sh
        ▼
DO droplet:/opt/mspc-public/games/myspace_pp/
        │  served by Caddy at  trollz.fun/play/myspace_pp/
        │  + GentlyOS.io/play/myspace_pp/
        ▼
Facebook iframe (Messenger / News Feed)
   FBInstant SDK ──► POST /dapp/api/fb_event ──► fb_instant_games.py
                                                  ├─► event sink (JSONL)
                                                  ├─► crystal chain (fb_event)
                                                  └─► facebook_friends_graph.py
                                                       └─► social_graph_persistence
```

---

## §2 — The full stack

Every file path here is real. Paths starting with `studio/` are relative to
`/data/Projects/MySpace++/`; paths starting with `core/` are relative to
`/data/Projects/MySpace++/`.

### 2.1 Godot side (the client)

| File                                                       | Role                                                                                      |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `studio/godot/project/scenes/planet_map.tscn`              | The scene that ships first. 3D Earth + per-player spheres + great-circle friend arcs.     |
| `studio/godot/project/src/planet_map_controller.gd`        | Drives `_fetch_data → _build_nodes → _build_edges → _spin_camera`. Attached to scene root.|
| `studio/godot/project/src/geo_to_xyz.gd`                   | Pure math: `(lat, lon) → Vector3` + great-circle arc samplers (slerp + lift).             |
| `studio/godot/project/src/friend_graph_fetcher.gd`         | HTTP fetch of `/dapp/api/social_graph?player_id=...`. Falls back to a 5-city seed graph.  |
| `studio/godot/project/src/facebook_sdk_bridge.gd`          | Web-build autoload. Injects `connect.facebook.net/en_US/sdk.js`, wires FB.AppEvents/login/share. Mirrors every call into `~/.cc/godot_fb_events.jsonl` for the cc side. |
| `studio/godot/project/src/meta_xr_bridge.gd`               | OpenXR autoload (Meta Quest, deferred). Stubs cleanly when no XR runtime is present.      |

Note the distinction: `facebook_sdk_bridge.gd` is for the **standard Facebook
JS SDK** (`connect.facebook.net/en_US/sdk.js`, used by the dApp embed path).
The **Instant Games SDK** (`fbinstant.7.1.js`) is loaded by the
`myspace_instant_games_shell.html` shell directly and bridged via
`window.MspcFBInstant.*` rather than through `facebook_sdk_bridge.gd`. Both
paths POST their events to the same backend (`/dapp/api/fb_event`).

### 2.2 Export pipeline

| File                                                              | Role                                                                                  |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `studio/godot/templates/myspace_instant_games_shell.html`         | The HTML5 shell used by `preset.3`. Loads `fbinstant.7.1.js`, drives `initializeAsync → bootGodot → startGameAsync`, exposes `window.MspcFBInstant`. Forwards every SDK event via `mspcFbForward()` → `POST /dapp/api/fb_event`. CSP allows `connect.facebook.net`, `*.facebook.com`, `*.fbcdn.net`. |
| `studio/godot/templates/myspace_web_shell.html`                   | The standard web-embed shell used by `preset.2` (the `/dapp/play/embed` iframe).      |
| `studio/godot/templates/instant_games_manifest.json`              | The manifest submitted to Meta: `name`, `description`, `platform_url`, `icon_url`, `screen_orientation`, `sdk_version: "7.1"`, `engine: "godot"`, `engine_version: "4.6.3-stable"`. Edit + re-submit for any production change. |
| `studio/godot/project/export_presets.cfg` `[preset.3]`            | `name="Web (Facebook Instant Games)"`, `custom_features="fb_instant_games,web"`, `export_path="../build/web_instant_games/index.html"`, `html/custom_html_shell="res://../templates/myspace_instant_games_shell.html"`, `progressive_web_app/ensure_cross_origin_isolation_headers=true`. |

### 2.3 Python connectors (the server)

| File                                                  | Role                                                                                            |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `core/lib/third_party/fb_instant_games.py`            | `FBInstantGamesConnector` — companion to the JS SDK. Tools: `record_event`, `verify_signed_data`, `manifest`, `event_stats`. Verifies `signed_player_info` HMAC with `FB_APP_SECRET`. Crystal-anchors every event with `tier='fb_event'`. Sinks to `~/.cc/fb_instant_events.jsonl`. Hands off `instant.friends.list_pulled` to the friends harvester. |
| `core/lib/third_party/facebook_friends_graph.py`      | `FacebookFriendsGraphConnector` — friends harvester. Tools: `harvest_for`, `check_permissions`, `revoke_check`, `friend_of_friend`, `nearby_active_friends`, `verify_credentials`. Two sources: `graph_api` (paginates `GET /me/friends?fields=id,name,picture.type(large)&limit=5000`) and `fb_instant` (consumes the `getConnectedPlayersAsync` payload). Safety rail: refuses `graph_api` unless `/me/permissions` reports `user_friends` GRANTED. Adds `appsecret_proof` to every `/me/*` call. |
| `core/lib/third_party/facebook_games_sdk.py`          | `FacebookGamesSDKConnector` — REST-side developer surface. Tools: `debug_token`, `send_app_event`, `register_instant_game`, `leaderboard_get`, `notification_send`, `graph_get_me`, `app_secret_proof_compute`, `verify_credentials`. This is what you call from server-side jobs that don't have a live iframe context. |
| `core/lib/third_party/facebook.py`                    | The pre-existing generic Facebook posting connector (Page posts etc.). Kept for parity; the three modules above are the canonical surface for games. |
| `core/lib/third_party/base.py`                        | `ThirdPartyConnector`, `ConnectionConfig`, `SendResult` — the shared connector shape every module above extends. |
| `core/lib/freetier_gate.py`                           | `issue_token(..., friends_consent=True)` stamps the consent claim; `verify_token` decodes it. Bearer-gates every `/dapp/api/fb_event` and `/dapp/api/social_graph` POST. |

### 2.4 Social graph persistence

| File                                              | Status                                                                                              |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `core/lib/social_graph_persistence.py`            | SQLite-backed graph store at `~/.cc/social_graph.sqlite` with a JSONL audit at `~/.cc/social_graph.jsonl`. Surface: `upsert_player`, `upsert_edge`, `query_edges`, `query_geo_friends`, `load_graph`/`get_graph`/`load`, `export_for_planet_map`. Imported lazily by both `fb_instant_games.py` and `facebook_friends_graph.py` — if the module isn't installed yet, both connectors degrade to a no-op + warning (see `_persist_edge` in `facebook_friends_graph.py`). |

The connectors deliberately do not hard-import this module so that the FB stack
remains usable while persistence is in flight. Once `social_graph_persistence`
lands you should see:
- non-zero `persisted` counts in `harvest_for` results
- non-empty `edges` arrays in `friend_of_friend`
- `source: 'social_graph_persistence'` in `GET /dapp/api/social_graph` instead
  of `source: 'seed'`.

### 2.5 dApp side (the host)

| Route / file                                                  | Role                                                                                                  |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `studio/dapp/server.py`                                       | Single-tenant stdlib `ThreadingHTTPServer` on `127.0.0.1:8520`. Caddy fronts it with TLS.             |
| `GET  /dapp/play`                                             | Renders `play.html` with two launchers: "Play in Facebook" (deep link via `FB_INSTANT_APP_ID`) and "Play in browser" (`/dapp/play/embed`). |
| `GET  /dapp/play/embed`                                       | Renders `play_embed.html` — iframes the Godot Instant Games build, listens for `window.postMessage({type:'mspc_fb_event', ...})`, relays via `MspcDappBridge.sendEvent`. |
| `GET  /dapp/play/sdk-bridge.js`                               | Serves the `_SDK_BRIDGE_JS` constant. Exposes `window.MspcDappBridge` with `sendEvent`, `fetchSocialGraph`, `setToken`, `loadToken`. Token plumbed via `localStorage['mspc_freetier_token']`. |
| `POST /dapp/api/fb_event`                                     | Bearer-gated via `require_token`. Calls `FBInstantGamesConnector.record_event`. Returns `{ok, crystal, ...}`. |
| `GET  /dapp/api/social_graph?player_id=<id>`                  | Tries `social_graph_persistence.load_graph`; falls back to the deterministic seed graph in `_seed_social_graph`. Shape: `{players: [{id,display_name,planet_color,sun?}], friendships: [{a,b,strength}], source, player_id}`. |
| `studio/dapp/templates/play.html`                             | Launcher panel + SDK bridge documentation. |
| `studio/dapp/templates/play_embed.html`                       | iframe + event-log relay. |
| `studio/dapp/templates/play_no_build.html`                    | Friendly fallback when `GODOT_BUILD_INDEX` does not exist yet (no `web_instant_games` build present). |

### 2.6 Consent & callback

| File                                                     | Role                                                                                            |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `core/lib/freetier_gate.py` `TokenClaims.friends_consent`| Extra claim on the JWT-shaped freetier token. Defaults to `False` for backward compat.           |
| `core/lib/freetier_gate.py` `record_acceptance(...)`     | Records the legal acceptance event with `friends_consent` carried through to the crystal anchor (`tier='legal_acceptance'`). |
| `core/lib/freetier_gate.py` `issue_token(..., friends_consent=True)` | Issues a token stamped with the consent. The friends-graph harvester refuses to harvest unless this claim is `True` on the bearer. |
| `studio/auth/freetier_acceptances.sqlite`                | The on-host acceptance ledger (mode 600).                                                       |
| `studio/auth/keys.sqlite`                                | Salted-token registry. Per-host. Friends' tokens are valid only on the issuing host.            |

### 2.7 Serving

| File                                                            | Role                                                                                       |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `studio/deploy/freetier_public/Caddyfile.droplet`               | Two domains (`trollz.fun`, `GentlyOS.io`). Both have a `/play/*` handle that file-serves `/opt/mspc-public/games/<game_slug>/` with the `games_headers` + `games_mime` snippets (COEP, COOP, CORP, CSP frame-ancestors, `.wasm` MIME). |
| `studio/deploy/freetier_public/sync-games-build.sh`             | rsync helper that lifts `studio/godot/build/web_instant_games/` to `/opt/mspc-public/games/<slug>/` on the droplet. Honors `DRY_RUN=1` by default; flip to `DRY_RUN=0` to push. |
| `studio/deploy/freetier_public/deploy.sh`                       | Bootstrap deploy script for the freetier surface as a whole (Caddy + systemd units).        |
| `studio/deploy/freetier_public/mspc-callback.service`           | Systemd unit for `freetier_callback` (callback + terms server).                             |
| `studio/deploy/freetier_public/mspc-model-api.service`          | Systemd unit for the model API.                                                             |

### 2.8 Audit surfaces

Every meaningful event lands in three places:

1. **Local JSONL sink** for at-a-glance inspection:
   - `~/.cc/fb_instant_events.jsonl`            — every SDK event recorded
   - `~/.cc/third_party_logs/fb_instant_games_sends.jsonl`
   - `~/.cc/third_party_logs/facebook_friends_sends.jsonl`
   - `~/.cc/godot_fb_events.jsonl`              — Godot bridge mirror
2. **Crystal chain** for cryptographic audit:
   - `tier='fb_event'`         (every SDK event)
   - `tier='social_graph'`     (every friend upsert)
   - `tier='legal_acceptance'` (every consent acceptance — `friends_consent` flag included)
3. **SQLite** for queryable state:
   - `~/.cc/social_graph.sqlite` (once `social_graph_persistence` lands)
   - `studio/auth/freetier_acceptances.sqlite`
   - `studio/auth/keys.sqlite`

---

## §3 — Data flow

### 3.1 User enters via FB Messenger
A user taps the game in a Messenger thread or feed entry. Facebook opens an
iframe pointing at `https://trollz.fun/play/myspace_pp/` (or
`https://GentlyOS.io/play/myspace_pp/`). The Caddy `/play/*` block file-serves
`/opt/mspc-public/games/myspace_pp/index.html` (our rendered shell) with
`COEP: require-corp` + `COOP: same-origin`. The shell loads
`fbinstant.7.1.js` from `connect.facebook.net` first, then calls
`FBInstant.initializeAsync()`, then bootstraps the Godot WASM with
`engine.startGame(...)`. As bytes download, `onProgress` feeds
`FBInstant.setLoadingProgress(p*100)` so Meta's loading-bar UI advances.
Once the engine resolves, `FBInstant.startGameAsync()` dismisses the splash
and the player sees the planet map.

### 3.2 Player ID + signed info
Inside the shell, `MspcFBInstant.getPlayerID()` reads
`FBInstant.player.getID()` — an app-scoped string, not the user's Facebook UID.
The shell also calls `MspcFBInstant.getSignedPlayerInfo(payload)`, which
invokes `FBInstant.player.getSignedPlayerInfoAsync(...)` and stashes the
returned `<sig_b64url>.<payload_b64url>` string in `window.__mspc_fb_signed`.
Every subsequent `mspcFbForward(event_name, payload)` includes that signed
blob plus the player ID + context ID. The bearer is the freetier token the
host page stamped into `window.__mspc_freetier_token` before the iframe loaded.
The POST lands at `/dapp/api/fb_event`; `dapp/server.py._handle_fb_event`
extracts the token via `require_token`, then calls
`FBInstantGamesConnector.record_event(...)`. Inside `_tool_record_event`,
`verify_signed_data(signed_data, fb_app_secret)` recomputes the HMAC with
`hmac.compare_digest` and surfaces `signed_valid: True/False` in the response
metadata. If the FB-asserted `player_id` differs from the caller-claimed one,
we surface a `player_id_mismatch` diagnostic but accept the FB-asserted ID.
Then `_log_fb_event` crystal-anchors the event and `_append_event_sink` adds
it to `~/.cc/fb_instant_events.jsonl`.

### 3.3 Friends-list harvest
When the user is in a chat context, the shell calls
`MspcFBInstant.fetchConnectedPlayers()` which wraps
`FBInstant.player.getConnectedPlayersAsync()`. Facebook returns ONLY the
subset of the user's friends who already play this app (post-2014 platform
policy). The shell builds an array of `{id, name, photo}` per player,
forwards `event_name: 'connected_players_fetched'` via `mspcFbForward`,
and the server-side dispatcher sees `event_name == 'instant.friends.list_pulled'`
(our canonical name), calls `_handoff_friends_to_graph(player_id, payload, crystal_id)`
in `fb_instant_games.py`, which imports `facebook_friends_graph.ingest_friends_list`
(or the equivalent `harvest_for(source='fb_instant')` entry) and calls
`social_graph_persistence.upsert_edge(player_id, friend_id, ...)` for each
friend. Every friend record crystal-anchors at `tier='social_graph'`.

### 3.4 Planet map render
`planet_map_controller._fetch_data` invokes
`friend_graph_fetcher.fetch_for_current_player(player_id)`. When `use_http`
is `True`, the fetcher opens an `HTTPClient` to `127.0.0.1:8520` and hits
`GET /dapp/api/social_graph?player_id=<id>`. `dapp/server.py._load_social_graph`
tries `social_graph_persistence.load_graph(player_id)`; if the module isn't
importable yet, it returns the deterministic 5-city seed graph
(`_seed_social_graph`). The shape returned in both cases is
`{players, friendships, source, player_id}`. The controller then:
- Iterates `connected_players`, converts each `(lat, lon)` to a `Vector3` via
  `geo_to_xyz.lat_lon_to_xyz(lat, lon, sphere_radius * 1.01)`, instantiates a
  small per-player `SphereMesh` colored by `id_str.hash() % 1000 → HSV`.
- Iterates `friendships`, samples 24 great-circle points lifted 6% above the
  surface via `geo_to_xyz.great_circle_arc_lifted(a, b, 24, 0.06)`, builds an
  `ImmediateMesh` `LINE_STRIP`, attaches an unlit cyan material.
- Updates the HUD label and starts an infinite 60-second camera orbit tween.

### 3.5 Friend invites
The shell exposes `MspcFBInstant.chooseContextAsync()`, which wraps
`FBInstant.context.chooseAsync()`. Facebook opens its native chat-picker UI;
the player picks a friend (or a group), and the game now runs in **that**
context's thread. After the picker resolves we forward
`event_name: 'context_chosen'` with the new `context_id`. Inside the new
context, every subsequent `getConnectedPlayersAsync()` returns the players
**in this chat** who use the app — a smaller, more targeted graph. This is
how the harvest snowballs: each shared chat seeds another harvest.

---

## §4 — Required Facebook Developer setup (USER-PROVISIONED)

Tom owns these tasks. They cannot be automated.

1. **Create the app.** Go to <https://developers.facebook.com/apps>, create a
   new App, choose the **Gaming** vertical, then add the **Instant Games**
   product.
2. **App Domains.** Set the App Domain field to `trollz.fun` AND `GentlyOS.io`
   (both, comma-separated). Whitelist both domains under
   *Settings → Basic → App Domains*.
3. **Game URL.** Set *Instant Games → Web Hosting → Game URL* to
   `https://trollz.fun/play/myspace_pp/`. (Optional secondary URL on
   `GentlyOS.io/play/myspace_pp/`.)
4. **Manifest.** Upload `studio/godot/templates/instant_games_manifest.json`.
   The key fields Meta cares about:
   - `name`, `description`, `categories`
   - `platform_url` = `https://trollz.fun/play/myspace_pp`
   - `icon_url`, `screen_orientation`, `sdk_version: "7.1"`
   - `developer.privacy_url` = `https://trollz.fun/privacy`
   - `developer.terms_url`   = `https://trollz.fun/terms`
5. **Permissions.** Request:
   - `public_profile` (always granted at OAuth time, no review)
   - `user_friends`   (App Review required; see §5 for the demo we have to
     ship to Meta — usually a 1–2 week turnaround)
6. **Privacy + terms URLs.** Already served by `freetier_callback` at
   `https://trollz.fun/terms/policies/` and `https://trollz.fun/terms/`.
7. **Credentials → `.env`.** From *Settings → Basic*, copy the App ID and the
   App Secret. Add them to **both** sides of the mirrored `.env`:
   - `/data/Projects/MySpace++/.env`
   - `/data/Projects/gently/.env`
   ```
   FB_APP_ID=...
   FB_APP_SECRET=...
   FB_INSTANT_APP_ID=...    # the same value as FB_APP_ID; used to render the public launcher URL
   # Optional: a tester / dev token for offline harvest experiments
   FB_USER_ACCESS_TOKEN=...
   FB_GRAPH_API_VERSION=v18.0   # default; override if/when Meta forces an upgrade
   ```
   Both `fb_instant_games.py` and `facebook_friends_graph.py` resolve these via
   `studio/auth/keys.load_env()` first, then `os.environ` — so `.env` is
   sufficient; you don't need to `export` anything.
8. **Tester accounts.** Add at least two tester accounts under
   *Roles → Roles → Testers* so you can do a real two-player harvest demo
   for App Review.
9. **App Review submission.** Submit the `user_friends` scope with:
   - A screen recording showing the game running inside Messenger
   - A reviewer login note explaining: "Connected players form the nodes
     of the planet-map social-graph visualization, and friend graph data is
     used to recommend collaborators inside the MySpace++ studio."
   - The `friends_consent` checkbox we surface on
     `https://trollz.fun/terms/policies/` (Meta reviewers look for it)
   Expect a 1–2 week turnaround. `public_profile` works immediately.

---

## §5 — Legal & consent

### What `user_friends` actually returns
Since Platform v2.0 (April 2014), `GET /me/friends` and
`getConnectedPlayersAsync` return **only the user's friends who have also
installed (and granted permission to) the same app**. There is no path to
the user's full friend graph anymore, period. In practice this is still
**30–80% of typical active social graphs** because friend networks cluster
hard inside any given product.

### Explicit consent
A token without `friends_consent: true` is, by policy, a token that has not
authorized friend-graph harvesting. The flow:

1. User hits `https://trollz.fun/terms/policies/`.
2. The page shows a **`Permit user_friends scope harvesting`** checkbox
   (default unchecked). Reviewers see this checkbox on the same screen as the
   primary acceptance.
3. On submit, `freetier_callback` calls
   `record_acceptance(user_id, domain, friends_consent=<bool>)` and
   `issue_token(..., friends_consent=<bool>)`. The bool flows into the
   token payload AND into the crystal anchor for that acceptance.
4. `facebook_friends_graph._harvest_for` calls `_check_permissions(...)` to
   verify the FB-side `user_friends` permission is granted at the OAuth layer,
   AND callers of the dApp APIs are responsible for refusing harvest calls
   when the bearer's `claims.friends_consent` is `False`.

### Crystal-anchored audit trail
Every consent + revocation is recorded twice:
- in `studio/auth/freetier_acceptances.sqlite` (per-row source of truth)
- in the crystal chain at `tier='legal_acceptance'` (immutable audit)

Every friend harvest is similarly twinned:
- in `~/.cc/social_graph.sqlite` (when persistence lands)
- in the crystal chain at `tier='social_graph'`

This is the GDPR position: a regulator can request the full lineage of any
friend record. We can produce both the SQLite row and the crystal hash, and
walk from one to the other in either direction.

### Revocation
A user revokes at <https://www.facebook.com/settings?tab=applications>. The
next time we call any user-context endpoint we detect this:
`facebook_friends_graph._revoke_check` → `GET /me?fields=id` returns
`401` or `OAuthException code 190`. The response body gets
`token_valid: false` + `error_for_oauth_revoked: true`, and a follow-up call
to `_harvest_for` short-circuits at the same fence. We never write to the
persisted graph after a revocation. (We do **not** delete previously
harvested data on revocation by default — that's a separate, manual
"forget me" workflow that we run against `social_graph_persistence` once we
get a deletion request. Document the request in the crystal chain when you
run it.)

---

## §6 — Tom's "WAYYY into pushing data" notes

To be explicit: Facebook makes friend-graph harvest **trivially easy** for an
Instant Games developer. The three levers in particular:

1. **`user_friends` scope.** One OAuth grant during App Review.
2. **`signed_player_info`.** Server-validated identity for every event we
   record — so even if the client lies about a player ID, we catch it via
   `hmac.compare_digest`. No need to roll our own session layer.
3. **`getConnectedPlayersAsync`.** No pagination, no rate-limit gymnastics —
   one async call returns every app-using friend in the current context.

We use all three. We layer over them with **explicit checkbox consent**
(`friends_consent` claim), **per-event crystal anchors** (`tier='fb_event'`,
`tier='social_graph'`), and **deterministic JSONL sinks** (so a regulator can
read every event off disk without hitting a database). The harvester refuses
to operate unless the OAuth scope and the freetier consent flag both say yes,
and a revocation flips the kill switch on the next round-trip.

If a reviewer asks "why do you collect friends?" the answer is:
**"to draw the planet map and to recommend collaborators inside the
MySpace++ studio"** — both are in the manifest description and both are
demonstrated in the App Review video.

---

## §7 — Build + deploy

### 7.1 Export the Instant Games build

Manual (until the `cc` dispatcher gains `cmd_godot_export`):
```bash
cd /data/Projects/MySpace++/studio/godot/project
godot --headless --export-release "Web (Facebook Instant Games)" \
      ../build/web_instant_games/index.html
```

When the dispatcher lands:
```bash
cc godot-export web_instant_games
```

Expected output under `studio/godot/build/web_instant_games/`:
```
index.html              (rendered from myspace_instant_games_shell.html)
index.js                (Godot loader)
index.wasm              (Godot engine WASM)
index.pck               (project pack)
index.audio.worklet.js  (audio worklet)
index.icon.png
```

### 7.2 Sync to the droplet

```bash
# Dry run first — preview rsync output without copying anything
bash studio/deploy/freetier_public/sync-games-build.sh myspace_pp

# Push for real
DRY_RUN=0 bash studio/deploy/freetier_public/sync-games-build.sh myspace_pp
```

Destination on the droplet: `/opt/mspc-public/games/myspace_pp/`. Caddy
serves it under both `trollz.fun/play/myspace_pp/` and
`GentlyOS.io/play/myspace_pp/`.

### 7.3 Caddy reload

Caddy auto-detects Caddyfile changes when the unit is configured with
`reload-on-change`. If you edited `Caddyfile.droplet`, force a reload:
```bash
ssh root@159.89.181.146 'systemctl reload caddy'
```

### 7.4 Test the surfaces

1. **Direct fetch** (sanity check that COOP/COEP/CORP headers are correct):
   ```bash
   curl -sI https://trollz.fun/play/myspace_pp/ | \
     grep -iE 'cross-origin|content-security-policy|content-type'
   ```
   Required headers:
   - `Cross-Origin-Embedder-Policy: require-corp`
   - `Cross-Origin-Opener-Policy:   same-origin`
   - `Cross-Origin-Resource-Policy: cross-origin`
   - `Content-Security-Policy: frame-ancestors 'self' https://www.facebook.com https://*.facebook.com https://www.messenger.com`
2. **WASM MIME**:
   ```bash
   curl -sI https://trollz.fun/play/myspace_pp/index.wasm | grep -i content-type
   # Expected: application/wasm
   ```
3. **Browser preview**: open `https://trollz.fun/play/myspace_pp/` in a
   regular tab. The FBInstant SDK loads but `initializeAsync` fails (no FB
   host). The shell falls into preview mode and still boots Godot.
4. **dApp embed**: navigate to `https://trollz.fun/dapp/play/embed`. The
   iframe should load and the event log should accumulate entries as you
   poke around.
5. **Inside Messenger**: send the game URL to a tester account; tap it; the
   game runs inside the iframe. Confirm in
   `tail -f ~/.cc/fb_instant_events.jsonl` that events land server-side.

---

## §8 — Future

- **Cloud Gaming wrap.** Meta's separate Cloud Gaming product hosts the same
  HTML5 bundle on remote-rendered hardware (heavier WebGL2 + audio). The
  manifest delta is small; defer until v2.
- **Meta Quest (XR).** The autoload at
  `studio/godot/project/src/meta_xr_bridge.gd` already probes OpenXR (Godot's
  `XRServer.find_interface("OpenXR")`) and queries `XR_FB_passthrough` +
  `XR_EXT_hand_tracking`. The export preset is deferred. When we ship this,
  it goes through `godot-openxr-vendors` rather than Instant Games.
- **Apple Game Center / Google Play Games.** Completely different SDKs; out
  of scope for this doc. We'll add `core/lib/third_party/apple_game_center.py`
  + `core/lib/third_party/google_play_games.py` when needed.
- **More games on the same FB app.** Meta lets one App ID host multiple game
  slugs. Just add another entry in `instant_games_manifest.json` and a second
  `<slug>/` under `/opt/mspc-public/games/`.
- **Realtime multiplayer.** `FBInstant.matchPlayerAsync(matchTag, switchContext)`
  is already in `SDK_MANIFEST['matchPlayerAsync']`. The dApp side just needs
  to wire a `recipient='match_make'` tool — see §2.3 for the connector shape.

---

## §9 — Crystal-chain queries

Every audit question collapses to a `cc inference-chain --tier <name>` query.

```bash
# Every FBInstant SDK event ever recorded
cc inference-chain --tier fb_event

# Every friend upsert (graph_api + fb_instant sources both land here)
cc inference-chain --tier social_graph

# Every legal acceptance that included friends_consent=true
cc inference-chain --tier legal_acceptance | grep -i friends_consent

# Today's events only
cc inference-chain --tier fb_event --since "$(date -I)"

# Drill into one player's harvest history
cc inference-chain --tier social_graph --scope friends_harvest | \
  jq 'select(.enhanced_prompt | contains("player_id\":\"<PID>"))'
```

For ad-hoc inspection without `cc`:
```bash
# Tail the local sink
tail -f ~/.cc/fb_instant_events.jsonl | jq .

# Count events by name (last 24h)
jq -r 'select(.ts > (now-86400)) | .event_name' \
   ~/.cc/fb_instant_events.jsonl | sort | uniq -c | sort -rn

# Inspect connector send log
tail ~/.cc/third_party_logs/fb_instant_games_sends.jsonl  | jq .
tail ~/.cc/third_party_logs/facebook_friends_sends.jsonl  | jq .
```

CLI smoke (no host needed):
```bash
# Show connect status (keys present?)
python3 core/lib/third_party/fb_instant_games.py connect

# Print the full SDK manifest
python3 core/lib/third_party/fb_instant_games.py manifest

# Verify a signed_player_info blob locally
python3 core/lib/third_party/fb_instant_games.py verify-signed '<sig>.<payload>' --app-secret <secret>

# Probe permissions for a user token
python3 core/lib/third_party/facebook_friends_graph.py permissions --user-token <token>

# Probe whether a token has been revoked
python3 core/lib/third_party/facebook_friends_graph.py revoke-check --user-token <token>

# Run a real harvest (requires FB_APP_ID + FB_APP_SECRET + a valid user token
# whose permissions include user_friends)
python3 core/lib/third_party/facebook_friends_graph.py harvest <player_id> \
    --user-token <user_access_token> --source graph_api
```

---

## Appendix A — SDK call ↔ server event ↔ scope (canonical map)

Pulled from `SDK_MANIFEST` in `core/lib/third_party/fb_instant_games.py`.
The connector exposes this same table via `python3 fb_instant_games.py manifest`
so you never need to hardcode it elsewhere.

| FBInstant JS call                                | Server `event_name`                | Scope         |
| ------------------------------------------------ | ---------------------------------- | ------------- |
| `FBInstant.initializeAsync()`                    | `instant.initialized`              | none          |
| `FBInstant.startGameAsync()`                     | `instant.game_started`             | none          |
| `FBInstant.player.getID()`                       | `instant.player.id_read`           | none          |
| `FBInstant.player.getName()`                     | `instant.player.name_read`         | public_profile|
| `FBInstant.player.getPhoto()`                    | `instant.player.photo_read`        | public_profile|
| `FBInstant.player.getSignedPlayerInfoAsync()`    | `instant.signed_player_info`       | none          |
| `FBInstant.player.getConnectedPlayersAsync()`    | `instant.friends.list_pulled`      | **user_friends** |
| `FBInstant.context.getID()`                      | `instant.context.id_read`          | none          |
| `FBInstant.context.getType()`                    | `instant.context.type_read`        | none          |
| `FBInstant.context.switchAsync(contextID)`       | `instant.context.switched`         | none          |
| `FBInstant.context.chooseAsync(opts)`            | `instant.context.chosen`           | none          |
| `FBInstant.context.createAsync(playerID)`        | `instant.context.created`          | none          |
| `FBInstant.shareAsync(payload)`                  | `instant.shared`                   | none          |
| `FBInstant.updateAsync(payload)`                 | `instant.update_posted`            | none          |
| `FBInstant.payments.purchaseAsync(payload)`      | `instant.payment_attempted`        | none          |
| `FBInstant.payments.consumePurchaseAsync(token)` | `instant.payment_consumed`         | none          |
| `FBInstant.getLeaderboardAsync(name)`            | `instant.leaderboard_read`         | none          |
| `FBInstant.getEntryPointAsync()`                 | `instant.entry_point_read`         | none          |
| `FBInstant.getEntryPointData()`                  | `instant.entry_data_read`          | none          |
| `FBInstant.matchPlayerAsync(...)`                | `instant.match_requested`          | none          |
| `FBInstant.logEvent(name, value, params)`        | `instant.app_event_logged`         | none          |

---

## Appendix B — Files Tom must not touch lightly

These files are referenced by Meta directly or by the platform contract.
Any change to them requires either a re-submission to App Review or a
deploy-coordination step:

- `studio/godot/templates/instant_games_manifest.json` — re-submit on edit.
- `studio/godot/templates/myspace_instant_games_shell.html` — the CSP header
  is the source of truth for what scripts and connect targets are allowed
  inside the FB iframe. Loosen with care.
- `studio/deploy/freetier_public/Caddyfile.droplet` `games_headers` snippet —
  the COOP/COEP/CORP triplet here is what makes SharedArrayBuffer (and
  therefore Godot 4 threads) work. Don't relax `same-origin` or
  `require-corp`.
- `core/lib/freetier_gate.py` `TokenClaims.friends_consent` — the entire
  consent story rides on this single bool. Removing it would silently
  invalidate the App Review demo.
- `core/lib/third_party/fb_instant_games.py` `verify_signed_data(...)` — the
  HMAC-SHA256 verification is what justifies trusting any client-supplied
  player_id. Don't replace `hmac.compare_digest` with `==`.

---

*Last updated: cross-reference this file against `studio/docs/NOTES-FOR-INFERANCE.md`
after every Facebook-stack-touching session. Mark items `[x]` on the shared PLAN
when they ship.*
