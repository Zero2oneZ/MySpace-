# ATLAS HUB README — how this project reaches the bridge

You are operating in **MySpace++** — a BODY part of the ship.

**ATLAS is the BRIDGE.** It holds the canon, runs the wire, owns the asset
store and the intelligence graph. Your job is to row, fish, navigate, build —
ATLAS's job is to keep the charts and route the signals.

## Reach INTO ATLAS for canon

Canonical doctrine + schemas live at `/data/Projects/ATLAS/canon/` (mirror of
`/data/Projects/ATLAS/passes/`). Read these as the source of truth — do NOT
fork a local copy. If you need a new field, emit a `canon_update_request`
event (see below); the claude-cleaner sub-agent routes it.

Common reads:

- `/data/Projects/ATLAS/canon/cleanly_kinds_v0.json` — every cleanly event
  kind this project is allowed to emit or subscribe to
- `/data/Projects/ATLAS/canon/contrib_kind_registry_v0.json` — canonical
  ContributionStream kinds
- `/data/Projects/ATLAS/canon/game_asset_schema_v0.json` — asset layout
  (MTG-style props · mana=GPU · cook_depth_score)
- `/data/Projects/ATLAS/passes/*.json` — full substrate (canon is a curated
  subset; passes is the raw vault)

HTTP form (cross-language, cross-host):

```
GET http://localhost:<atlas_port>/canon/<file>.json
GET http://localhost:<atlas_port>/canon/index
```

## Subscribe to canon updates

```
bin/atlas_cleanly subscribe \
  --path /data/Projects/ATLAS/canon \
  --subscriber_path /data/Projects/MySpace++
```

Subscription state is stored in `.shared/cleanly/subscriptions.sqlite`.
When canon changes, this project receives a `canon_updated` event with the
changed file + before/after CIDs.

## Emit YOUR changes back to the hub

When this project produces a hub-relevant artifact (a new crate published, a
LoRA trained, a dataset frozen, a scene rendered, a contract minted, etc.),
emit it so other body-parts and the bridge can react:

```
bin/atlas_cleanly emit \
  --path <changed_file> \
  --kind <K> \
  --summary "what changed and why"
```

`<K>` MUST be a kind defined in `passes/cleanly_kinds_v0.json`. The
claude-cleaner sub-agent validates every emit; off-doctrine kinds get
auto-rejected with a hint to register the kind first.

## The reading order (per ATLAS doctrine)

Before doing hub-touching work, read in this order:

1. `/data/Projects/ATLAS/docs/HUB_DOCTRINE_2026-06-23.md` — **full doctrine**
2. `/data/Projects/ATLAS/passes/agents_canon_v0.json` — every sub-agent
   identity, scope, capability set
3. `/data/Projects/ATLAS/passes/cleanly_kinds_v0.json` — every event kind
4. `/data/Projects/ATLAS/passes/game_asset_schema_v0.json` — asset layout

Then operate. The bridge will see your emits and the rest of the body will
see what changed.

— ATLAS Hub Doctrine · auto-generated · do not hand-edit
