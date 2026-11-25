# Lucid ↔ MySpace++ integration

How Lucid's developer platform maps onto MySpace++. The headline:
**Lucid is a near-perfect external surface for the Tesseract.** Its document
model, formula engine, custom shapes, data connectors, and Cards
integration line up 1-to-1 with the abstractions we already have. Even
better, the things Lucid does natively (locks, formulas, reference
keys, OAuth-scoped read-only embed) are exactly the **unfuckability**
levers we want.

> Status: research + mapping. A working Standard Import converter is
> shipped under `studio/lucid/standard_import.py`. The data connector
> skeleton is scaffolding only.

## Sources

The full mapping was derived from these Lucid developer-docs pages
(May 2026):

- [Developer platform overview](https://developer.lucid.co/reference/overview)
- [Lucid Extension SDK](https://developer.lucid.co/docs/lucid-extension-sdk)
- [Core concepts](https://developer.lucid.co/docs/coreconcepts)
- [Custom shapes intro](https://developer.lucid.co/docs/custom-shapes-introduction)
- [Data connectors](https://developer.lucid.co/docs/data-connectors)
- [Building a data connector](https://developer.lucid.co/docs/building-a-data-connector)
- [Editor extension data](https://developer.lucid.co/docs/editor-extension-data)
- [Data actions](https://lucid.readme.io/docs/data-actions)
- [Standard Import reference (overview-si)](https://lucid.readme.io/reference/overview-si.md)
- [Data-backed shapes (-si)](https://lucid.readme.io/docs/data-backed-shapes-si)
- [Lucid Cards overview](https://lucid.readme.io/docs/lucid-cards-overview.md)
- [Card integrations](https://lucid.readme.io/docs/lucid-card-integrations.md)
- [Embed API FAQ](https://lucid.readme.io/docs/embed-api-faqs.md)
- [MCP support](https://lucid.readme.io/docs/mcp.md) + [AI tools](https://lucid.readme.io/docs/ai-tools.md)
- [Formulas overview](https://lucid.readme.io/docs/formulas.md) + [Relational formulas](https://lucid.readme.io/docs/connected.md)
- [Shape data properties](https://lucid.readme.io/docs/shape-data-properties.md)
- [Shape constraints](https://lucid.readme.io/docs/shape-constraints.md)
- [OAuth 2.0 client creation](https://lucid.readme.io/docs/oauth-20-client-creation.md)
- [LLM index (all URLs)](https://lucid.readme.io/llms.txt)

---

## TL;DR (the headline mapping)

| MySpace++ piece                                | Lucid primitive              | Why it fits |
|------------------------------------------------|------------------------------|-------------|
| Tesseract master SVG                           | Lucid document (1 doc, N pages) | Both already track shapes+lines+groups in XML/JSON |
| 8 source DAGs (opcode/model/recipe/flow/pass/template/subsystem/project_type) | 8 pages within the doc | Pages are Lucid's natural sub-namespace |
| Every node (253 of them)                       | Custom shape with data fields | Lucid custom shapes already have HJSON + data props |
| Edges (729 of them)                            | Lucid lines (typed endpoints) | Native primitive |
| Walker contract (data-walk-state etc)          | Shape data properties        | Lucid shapes carry arbitrary key/value data |
| `cc -chain` hashed runtime state               | Data connector + reference keys | Reference key = hash; Lucid auto-links shape → record |
| Plan steps (tesseract.plan)                    | Lucid Cards                  | Cards are first-class task/work tracking |
| Subsystem status colors (impl/partial/stub)    | Conditional formatting via formulas | Lucid formulas drive shape fill/stroke from data |
| Status-aware filtering (e.g. "show only impl") | Lucid formulas: `FILTER`, `IF` | Native |
| DAG traversal in walker.py                     | Lucid relational formulas    | `CONNECTED`, `UPSTREAM`, `DOWNSTREAM`, `ANCESTORS`, `DESCENDANTS` — built-in |
| Auth gate + salted keys                        | OAuth 2.0 + Lucid API keys   | Tom's claude_guest model → Lucid OAuth scope |
| Embedding the Tesseract in the wardrobe app    | Token-based embed API        | Renders a doc in an iframe with cookie or token auth |
| Friend collaboration (without running studio)  | Lucid native collab          | Friends just open a Lucid URL |
| Inference proxy for friends                    | Data connector OAuth tokens  | Lucid forwards the user's OAuth token on each action |

---

## The four-layer integration plan

### Layer 1 — Schema mirror (Standard Import)

Lucid's **Standard Import** is a documented JSON schema (the "-si" pages).
A converter that reads `tesseract.inventory.build_inventory()` and
emits valid Standard Import JSON is a self-contained, no-API-call piece.
The user opens Lucid → File → Import → drops the JSON → gets the
Tesseract as a Lucid document.

**Shipped today:** `studio/lucid/standard_import.py`. Runs offline,
no Lucid account required to test. Outputs `studio/docs/Tesseract.lucid-si.json`.
Roundtrips the 253 nodes + 729 edges as shapes + lines, one page per
DAG, with the node id, kind, source_dag, walk-state, and edges count as
shape data fields.

### Layer 2 — Data connector (hashed-chain bridge)

A Node.js data connector running on the droplet that exposes named
actions Lucid can call. Manifest declares actions like:

```jsonc
// studio/lucid/data_connector/manifest.json
{
  "name": "myspace-tesseract",
  "callbackBaseUrl": "https://droplet.tom/lucid/",
  "oauthProviderName": "myspace-friend-pass",
  "dataActions": {
    "import":         "/import",          // initial pull of all nodes
    "refresh":        "/refresh",         // sync changed nodes
    "walk-identify":  "/walk/identify",   // satisfy walker contract from inside Lucid
    "chain-run":      "/chain/run",       // invoke a cc -chain run from Lucid
    "pass-run":       "/pass/run"         // run a pass on an asset, return piece IDs
  }
}
```

Each action handler:
1. Verifies the request signature (Lucid signs every call).
2. Pulls or pushes data from our SQLite stores (`studio/cache/dag/*.sqlite`,
   `studio/auth/keys.sqlite`, `cc.db`).
3. Returns a typed response Lucid maps onto the bound shapes' data
   fields automatically.

**Reference keys are the unfuckability primitive.** Each chain step
gets a primary key = the chain hash. Lucid maps shape → record by
reference key. Even if a user moves, resizes, copies, or pastes the
shape, the record link survives. Deleting a record orphans the shape
(visible warning) but doesn't corrupt the underlying state.

**Shipped today:** `studio/lucid/data_connector/` skeleton — manifest +
empty actions folder + README pointing at the Lucid build guide.
**Not deployed.** Spinning this up needs a public URL, OAuth registration
with Lucid, and a TypeScript build. All deferred to when you commit to
the integration.

### Layer 3 — Custom shape library

Three custom shapes that exactly mirror MySpace++ abstractions:

| Shape name | Carries | Rendering |
|---|---|---|
| `mspc-pass` | input_kinds[], output_kind, cost_class, import_time, duration_ms_estimate | typed ports L/R, color by cost, instruction text below |
| `mspc-opcode` | task, category, layer, era, inputs[], outputs[] | hexagon, color by category |
| `mspc-subsystem` | name, status, files[], helps[] | tile, fill by status (green/yellow/orange/gray) |

Each is a `.lcsz` package (custom shape library, HJSON definitions).
Lucid users can drag these shapes from the palette into any document
and they automatically connect to our data connector.

**Not built today.** Custom shape libraries need the `lucid-package`
CLI + a Lucid developer account. They're a future deliverable.

### Layer 4 — Editor extension (in-Lucid panel)

A `lucid-extension-sdk` package that renders a side panel inside Lucid
showing live MySpace++ state:

- Current `cc -chain` runtime progress with status colors
- "Run pass on selected shape" button → calls our data connector's
  `/pass/run` action → records the result back as a piece, updates the
  shape's data
- Walk-mode toggle: when on, double-clicking a shape calls
  `/walk/identify` with the shape's neighbors auto-discovered via
  the `CONNECTED()` formula
- A status board summarizing how many nodes are processed across all 8 DAGs

This is where the **Tesseract walker contract** lives natively in Lucid.

**Not built today.** Editor extensions are the heaviest of the four
layers (full TypeScript app inside Lucid's iframe).

---

## Where Lucid is already better than what we have

### 1. Relational formulas as DAG traversal primitives

We wrote `walker.py` to identify a node's neighbors. Lucid has these
as formulas built into every shape:

| MySpace++ walker check                  | Lucid formula              |
|-----------------------------------------|----------------------------|
| neighbors_list for `identify()`         | `CONNECTED(THIS)` → array  |
| subjects.dag                            | `PAGENAME()` (page = DAG)  |
| upstream nodes                          | `UPSTREAM(THIS, depth=1)`  |
| downstream nodes                        | `DOWNSTREAM(THIS, depth=1)` |
| every node reachable from a source      | `DOWNSTREAMDEEP(THIS)`     |
| every node that helps reach this        | `UPSTREAMDEEP(THIS)`       |

`CONNECTED`, `UPSTREAM`, `DOWNSTREAM`, `ANCESTORS`, `DESCENDANTS`,
`CHILDREN`, `PARENT`, `SIBLINGS`, `CONTAINED`, `CONTAINER` —
[all documented](https://lucid.readme.io/docs/connected.md). They
**evaluate live** as the doc changes. Your walker contract becomes:

```
Required:
   data-walk-id           ← shape's own ID (Lucid auto-populates)
   data-walk-neighbors    ← =CONNECTED(THIS).Id    (formula)
   data-walk-subjects     ← ={"dag":PAGENAME(), "subsystem":@subsystem,
                            "project_types":CHILDREN()...}
   data-walk-state        ← user toggles, or formula
```

Three of our four required fields **populate automatically** from
formulas. The walker only has to verify the user/agent set the state.

### 2. Conditional formatting as status indicator

Our subsystem tiles render green/yellow/orange/gray by status. In
Lucid that's a one-line formula:

```
IF(@status="impl",    HEXCOLOR("#22c55e"),
IFS(@status="partial", HEXCOLOR("#facc15"),
    @status="stub",    HEXCOLOR("#fb923c")),
    HEXCOLOR("#94a3b8"))
```

Set as the shape's `fill` property. Status changes anywhere
auto-update everywhere.

### 3. Reference keys make state portable

Our `passes.pieces_index` uses a sha-derived piece_id as primary key.
Lucid data connectors use reference keys the same way: the shape on
canvas points to the **immutable hash**, not to a row position. A
shape can survive:
- being copy-pasted (both copies still reference the same piece)
- a Lucid document version revert (the connector re-resolves the
  ref key against current studio state)
- a user accidentally deleting + restoring it (the hash is what
  binds it back to its data)

That's the unfuckability story Tom asked for.

### 4. MCP support — Claude reads/writes Lucid directly

Lucid published [native MCP support](https://lucid.readme.io/docs/mcp.md)
and [an AI tools page](https://lucid.readme.io/docs/ai-tools.md)
pointing at [llms.txt](https://lucid.readme.io/llms.txt). That means
Claude (or any MCP-aware agent) can be configured to read + edit the
Tesseract Lucid doc directly — no extra glue code.

### 5. Embeds let friends view without running the studio

[Token-based embeds](https://lucid.readme.io/docs/tutorial-token-embeds)
let us iframe-embed a Lucid view of the Tesseract into the Wardrobe
Streamlit app. Friends visiting wardrobe see the live Tesseract too,
with their OAuth scope (read-only or read-write per their salted
token).

---

## The "unfuckability" guarantees

| Lever                                   | Lucid primitive               | What it prevents |
|-----------------------------------------|-------------------------------|------------------|
| Lock master nodes (can't delete)        | `shape-constraints`           | Accidental deletion |
| Pin sizes / positions                   | shape constraint properties   | Layout drift |
| Reference key = hash                    | data connector + collection   | Stale links |
| Validated schema on import              | Standard Import JSON schema   | Malformed state |
| Formula-driven validation               | `IF` + `ISEMPTY` + conditional fill | Missing required fields visible |
| Read-only OAuth scope                   | scope-restricted client       | Unauthorized writes |
| Signed data-connector requests          | Lucid signs every action call | Spoofed updates |
| Versioned documents                     | Lucid auto-versioning         | Lost edits |
| Auto-update from upstream state         | scheduled data sync           | Drift between studio + Lucid |

---

## What ships in this turn

```
studio/docs/LUCID_INTEGRATION.md        ← this file
studio/lucid/standard_import.py         ← Tesseract → Lucid JSON converter (works)
studio/docs/Tesseract.lucid-si.json     ← generated output, ready to drop into Lucid
studio/lucid/data_connector/            ← skeleton only — manifest + README
studio/lucid/data_connector/manifest.json
studio/lucid/data_connector/README.md
```

## What ships next (in order)

1. **Lucid developer account + OAuth client** — register at
   developer.lucid.co, get keys (manual, one-time)
2. **Deploy the data connector** — port the skeleton to a real Node.js
   service on the droplet, behind the existing studio.Dockerfile
   profile in docker-compose
3. **Define the custom shape library** — `lucid-package` CLI to
   build the `.lcsz`, publish privately, drag-and-drop in any doc
4. **Wire the editor extension** — side panel with the walker UI
5. **Embed the Tesseract Lucid doc** — iframe inside wardrobe + DAG canvas apps
6. **Configure Lucid MCP** — Claude reads/writes the doc directly

## Verification

```bash
$ cc -tesseract-build                    # rebuild inventory + master SVG
$ python3 studio/lucid/standard_import.py
wrote studio/docs/Tesseract.lucid-si.json (NN nodes / MM edges / 8 pages)

# In Lucid:
# 1. File → Import → Standard Import → choose Tesseract.lucid-si.json
# 2. Doc opens with 8 pages, one per DAG
# 3. Every shape carries data fields you can inspect via the right panel
```
