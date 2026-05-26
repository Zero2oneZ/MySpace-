# /home/tom/models — DAG-FLOW

Generated 2026-05-26.  Source of truth for **workflow chaining + GUI-card prediction**
on top of `DAG.md` (graph) and `DAG-GUI.md` (UX spec).

Where DAG-GUI.md specifies *what cards can exist*, DAG-FLOW.md specifies:
1. **Which sequences are deliberately offered as one-click flows**, and
2. **Which cards should be on deck** (predicted onto the right-side rail)
   given the current operation the user is touching.

The Streamlit app reads this file's structure via `flows.py`, so editing the
tables below changes runtime behaviour with no code change.

---

## 1. Vocabulary

| Term | Meaning |
|---|---|
| **Flow** | A named multi-step user goal. Each step = (node-id, deck-overlay). |
| **Step** | One stop on a flow. Owns a node + a deck of next-candidate GUI cards. |
| **Card** | Smallest GUI unit shown on the Deck (right rail). Mirrors a Palette item but is *predicted*, not browsed. |
| **Deck** | Ordered, deterministic list of cards predicted for the *current* operation. |
| **Anchor** | The node-id the user is currently inspecting. Deck is computed off the anchor. |
| **Bridge** | A node that converts type A → type B inserted to make a chain legal (e.g. `M_GEMMA` to bridge `EMB → TXT`). |

## 2. Prediction algorithm (deterministic)

Given anchor `A` (the inspected node) and graph `G`:

```
deck(A, G) :=
  let T = A.outputs                     # set of port-types A produces
  let consumers = ⋃_{t in T} nodes_accepting(t)
  let sinks = ⋃_{t in T} output_nodes_for(t)
  let bridges = ⋃_{t in T} bridges_from(t)    # only when no direct consumer matches downstream user-goal
  rank(consumers ∪ sinks ∪ bridges) by:
      1. flow_step_hit(A, G) overrides   (if A is mid-flow, the next step wins ties)
      2. same-kind preference (model→model, tool→tool)
      3. ascending vram_gb                (cheaper cards first)
      4. lexicographic node.name          (tie-break — stable across runs)
```

The algorithm has no randomness, no LLM call, no time component.  Identical
`(A, G)` always yields the same ordered deck.  This is the determinism contract.

## 3. Card schema

```yaml
card_id:      string         # mirrors node id (CARD-M_QTTS), or synthetic for bridges/sinks
title:        string         # short label
kind:         input|model|tool|lora|class|output|bridge|sink
accepts:      [PORT_TYPE]    # required input port-types
produces:     [PORT_TYPE]    # output port-types (empty for sinks)
deck_weight:  float          # static prior 0..1 (see §5 for defaults)
hint:         string         # one-line caption shown under the title
```

A card always resolves to either:
- a real node-id (`add_node(card_id)` instantiates it), **or**
- a recipe-fragment (a tiny sub-chain, e.g. *MD → gemma → TXT*).

## 4. Built-in flows

Flows are higher-level than recipes: a Flow is a *trajectory through the GUI*
that decides which cards to highlight at each step.  Recipe `C18` for example
becomes flow `F-NARRATE-VIDEO` below — same chain, but with explicit per-step
deck overlays so the user is *funneled* toward the next sensible operation.

| Flow id | Goal | Steps (node-id → deck overlay) |
|---|---|---|
| F-PHOTO-3D       | Image → 3D mesh                 | `IN_IMG` → {M_DEPTH★, T_CLIP, M_POSE}; `M_DEPTH` → {M_PX3D★}; `M_PX3D` → {OUT_3D★} |
| F-NARRATE-VIDEO  | Video → spoken summary          | `IN_VID` → {M_MAR★, M_STG, M_PEAV}; `M_MAR` → {M_GEMMA★, OUT_TXT}; `M_GEMMA` → {M_QTTS★}; `M_QTTS` → {OUT_AUD★, T_LCV} |
| F-AVATAR-RECAP   | Video → narrated talking-head   | `IN_VID` → {M_MAR★}; `M_MAR` → {M_GEMMA★}; `M_GEMMA` → {M_QTTS★}; `M_QTTS` → {IN_IMG-prompt, T_LCV★}; `T_LCV` → {OUT_VID★} |
| F-CAPTION-FAST   | Video → short caption           | `IN_VID` → {M_STG★, M_MAR}; `M_STG` → {OUT_TXT★, M_GEMMA} |
| F-FIND-MOMENT    | Video + query → (start,end)     | `IN_VID` → {IN_TXT★, M_MAR}; `IN_TXT` → {M_MAR★}; `M_MAR` → {OUT_TXT★} (mode=find pinned) |
| F-PDF-AUDIOBOOK  | PDF → spoken audiobook          | `IN_PDF` → {T_MINE★}; `T_MINE` → {M_GEMMA★}; `M_GEMMA` → {M_QTTS★}; `M_QTTS` → {OUT_AUD★} |
| F-VOICE-REPLY    | Voice memo → spoken reply       | `IN_AUD` → {M_UV★, T_VOX}; `M_UV` → {M_GEMMA★}; `M_GEMMA` → {M_QTTS★}; `M_QTTS` → {OUT_AUD★} |
| F-MOOD-MUSIC     | Image → mood music              | `IN_IMG` → {T_CLIP★}; `T_CLIP` → {M_MFLOW★, M_GEMMA}; `M_MFLOW` → {OUT_MUS★} |
| F-POSE-RESTYLE   | Image → posed restyle           | `IN_IMG` → {M_POSE★, T_CLIP}; `M_POSE` → {T_QPOSE★}; `T_QPOSE` → {T_FIRE, OUT_IMG★} |
| F-T2V            | Auto-prompt → T2V               | `IN_IMG` → {T_CLIP★}; `T_CLIP` → {T_LTX★, M_MFLOW}; `T_LTX` → {OUT_VID★} |
| F-VOICE-AB       | Text → A/B voice audition       | `IN_TXT` → {M_QTTS★(t1), M_QTTS★(t2), M_QTTS★(t3)}; each `M_QTTS` → {OUT_AUD★} |
| F-SUBJECT-CUT    | Image + box → subject-only      | `IN_IMG` → {IN_BOX★, M_SEG}; `IN_BOX` → {M_SEG★}; `M_SEG` → {T_FSWAP★, T_VBG}; `T_FSWAP` → {OUT_IMG★} |

`★` marks the **lead card** for that step (Deck shows it first, full-width).
Cards without ★ render in the secondary lane (half-width chips).

## 5. Default deck weights (used when a step doesn't override)

| Kind     | Weight | Notes |
|----------|--------|-------|
| output   | 0.95   | always offer the natural sink for the produced type |
| model    | 0.80   | prefer canonical model implementation over wrapper-tool |
| tool     | 0.70   | wrappers come second |
| bridge   | 0.60   | only surface when downstream needs a type-conversion |
| lora     | 0.30   | nudge, not a default |
| class    | 0.10   | rarely useful mid-flow |
| input    | 0.05   | re-adding an input mid-flow is almost always a mistake |

Within a kind, ties broken by ascending `vram_gb` then by `name`.

## 6. Bridge cards (type converters)

These are not new nodes — they wrap a tiny sub-chain that exists purely to bridge
a producer port-type to a consumer port-type the user keeps reaching for.

| Bridge id   | From → To | Sub-chain |
|-------------|-----------|-----------|
| BR-EMB-TXT  | EMB → TXT | `[M_GEMMA]` (treat embedding as system prompt context) |
| BR-MD-TXT   | MD  → TXT | identity (MD viewer also accepts TXT) |
| BR-TXT-MUS  | TXT → MUS | `[M_MFLOW]` |
| BR-TXT-AUD  | TXT → AUD | `[M_QTTS]` |
| BR-TXT-VID  | TXT → VID | `[T_LTX]` |
| BR-IMG-VID  | IMG → VID | `[T_LCV]`  (needs AUD; deck will also suggest IN_AUD) |
| BR-VID-TXT  | VID → TXT | `[M_MAR]`  (mode=caption) or `[M_STG]` |
| BR-AUD-TXT  | AUD → TXT | `[M_UV]` |
| BR-PDF-TXT  | PDF → TXT | `[T_MINE, M_GEMMA]` |

Bridges only surface when a *user-declared downstream consumer* exists whose
input-type doesn't match the upstream output-type.  If no downstream exists,
bridges are suppressed (don't litter the deck).

## 7. Determinism contract

For all `(anchor, graph)`:
- `deck(anchor, graph)` is pure, no IO, no clocks, no randomness.
- The set of card-ids returned is a subset of:
  `{ all node-ids } ∪ { bridge-ids in §6 }`.
- Order is stable across runs.

The Streamlit app calls `flows.predict_deck(anchor_uid, nodes, edges)` and
renders the result.  Tests in `test_pipelines.py` can pin this against fixtures.

## 8. Round-trip

- `flows.py` loads §4 and §6 from constants that mirror these tables.
- Adding a new flow = add a row in §4 **and** add an entry in `flows.py::FLOWS`.
- Tests assert: every flow's `lead_card` per step is a valid node-id and
  every step's anchor produces a type that the lead-card accepts.
