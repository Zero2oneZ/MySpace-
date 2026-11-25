# data_connector/ — scaffolding only

This is the **placeholder** for a future Node.js Lucid data connector
that fronts MySpace++ state. Today it contains:

- `manifest.json` — declarative shape of the connector (actions,
  collections with primary keys, OAuth scopes). Read this to see what
  the deployed connector would expose.
- `actions/` — empty. Each action handler would live here as
  `import.ts`, `refresh.ts`, `walk-identify.ts`, etc.
- `index.ts` — would register actions on a `DataConnector` instance
  via `defineAsynchronousAction(...)` and `defineAction(...)`.

## What the connector would do (when deployed)

1. **Run on the droplet**, accessible at a public HTTPS URL.
2. **Authenticated by Lucid**: every request is signed by Lucid; the
   connector verifies the signature (`lucid-extension-sdk` provides the
   helper).
3. **Bridges to local state**:
   - `studio/cache/dag/pieces.sqlite`        → `pieces` collection
   - `studio/cache/dag/tesseract_plan.sqlite` → plan steps as Lucid Cards
   - `studio/cache/dag/passes_timing.sqlite`  → timing on shapes
   - `studio/auth/keys.sqlite`                → token-by-friend lookup
   - `~/.cc/cc.db` chain_runs / chain_run_steps → chain state
4. **OAuth provider**: reuses the salted-token registry. A friend's
   `mspc_claude_<id>_<hmac>` token resolves to a Lucid OAuth scope.
   They can read/walk/run only what their token allows.

## How to bring it up (when ready)

```bash
# 1. Register a Lucid OAuth client (https://developer.lucid.co/docs/oauth-20-client-creation)
# 2. From this dir:
npm init -y
npm install --save lucid-extension-sdk
npx lucid-package@latest init data-connector --name myspace-tesseract
# 3. Fill in actions/<name>.ts files. The `defineAsynchronousAction` pattern is at:
#    https://developer.lucid.co/docs/building-a-data-connector
# 4. Deploy behind the existing studio.Dockerfile in docker-compose
# 5. Drop the URL into manifest.json's callbackBaseUrl
# 6. From Lucid, install the package and add the data source
```

## Mapping of actions to handlers

| Action            | URL              | What it does | Reads | Writes |
|-------------------|------------------|--------------|-------|--------|
| `import`          | `/import`        | initial pull of every node + edge | tesseract.inventory.build_inventory() | — |
| `refresh`         | `/refresh`       | incremental sync of changed records | inventory + walk-state | — |
| `walk-identify`   | `/walk/identify` | satisfy the walker contract for one node | request payload | tesseract.walker.identify() |
| `chain-run`       | `/chain/run`     | invoke `cc -chain {{ ... }}` from inside Lucid | request payload | cc chain runtime |
| `pass-run`        | `/pass/run`      | invoke a pass on an asset, return piece ids | request payload | studio/media/.tools/import_pipeline.py |
| `search-pieces`   | `/pieces/search` | search the pre-computed piece index | passes.pieces_index.search() | — |

## Reference

- Lucid data connector docs: https://developer.lucid.co/docs/data-connectors
- Building one: https://developer.lucid.co/docs/building-a-data-connector
- Action handlers: https://lucid.readme.io/docs/data-actions
- The big-picture mapping: ../docs/LUCID_INTEGRATION.md

---

**This directory is scaffolding only — `cc -tesseract-*` continues to
work without the connector being deployed.** The Standard Import
converter (`../standard_import.py`) is the working bridge today.
