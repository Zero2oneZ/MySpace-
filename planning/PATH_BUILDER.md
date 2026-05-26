# path_builder.py — quickref

A walker for the opcode DAG in `hf_task_evolution.jsonl`. Three modes:

```bash
python3 planning/path_builder.py                              # interactive REPL
python3 planning/path_builder.py rank DOC AUDIO --intent "spanish translation"
python3 planning/path_builder.py build "Document Question Answering" \
                                       "Translation" "Text-to-Speech" \
                                       --name pdf-spanish-podcast
```

## Scoring

Each candidate gets a base score of 10 with adjustments:

| Modifier | Δ |
|---|---|
| length penalty | −0.7 per hop after the first |
| same SRC/DST modality on length > 1 (loopback) | −0.3 |
| Layer-3 or Layer-5 compound task | +0.3 each |
| Era-5+ (modern multimodal LLM) | +0.2 each |
| `Fill-Mask` in chain interior | −2.0 |
| TEXT-only routing when neither endpoint is TEXT (and not intent-matched) | −1.5 |
| any task whose role/notes/category matches an intent word | +2.0 **once per path** |

The intent boost is capped per-path so it stays a tiebreaker, not a
dominant signal. The user's `--intent "translation spanish"` flips a tie
between `DocQA → Text-to-Speech` and `DocQA → Translation → Text-to-Speech`
toward the translation chain without distorting the ranking.

## REPL commands

```
--- search ---
  goal SRC DST [--intent TEXT]
  list [N]
  show I
  rerank --intent TEXT

--- walk current path ---
  path
  alts I              alternatives for step I (matching IO shape)
  swap I TASK
  insert I TASK
  append TASK
  remove I
  validate
  emit [NAME]         workflow JSON, shaped for cc workflow define
  save NAME

--- DAG walk ---
  node TASK
  in                  parents (tasks whose outputs feed this node)
  out                 children (tasks whose inputs accept this node's outputs)
  goto TASK

--- info ---
  info TASK
  modalities
  catalog [REGEX]
  saved
  help | ?
  quit | exit
```

Partial task names are accepted — `swap 1 trans` resolves to `Translation`.

## Worked example: PDF → Spanish podcast

```
> goal DOC AUDIO --intent translation spanish
[ 0] ★ score=11.1  Document Question Answering → Translation → Text-to-Audio
[ 1]   score=11.1  Document Question Answering → Translation → Text-to-Speech
[ 2]   score=10.9  Document Question Answering → Audio-Text-to-Text → Translation → Text-to-Audio
...

> show 1
  [0] Document Question Answering   DOC+TEXT → TEXT
  [1] Translation                       TEXT → TEXT
  [2] Text-to-Speech                    TEXT → AUDIO

> alts 1
  shape=6  era=2  L1  Fill-Mask              [TEXT → TEXT]
  shape=6  era=2  L3  Question Answering     [TEXT+TEXT → TEXT]
  shape=6  era=2  L1  Summarization          [TEXT → TEXT]
  shape=6  era=2  L1  Text Generation        [TEXT → TEXT]
  shape=2  era=7  L5  Any-to-Any             [* → *]

> emit pdf-spanish-podcast
{
  "name": "pdf-spanish-podcast",
  "steps": [
    {"tool": "Document Question Answering", "binds": {"DOC":"$input_doc","TEXT":"$input_text"}, "out": "step_0_out"},
    {"tool": "Translation",                  "binds": {"TEXT":"$step_0_out"},                   "out": "step_1_out"},
    {"tool": "Text-to-Speech",               "binds": {"TEXT":"$step_1_out"},                   "out": "step_2_out"}
  ]
}
```

`emit` output is shaped for `cc workflow define` — but the `tool` fields
are still opcode names. Concrete tool resolution (opcode → actual model
endpoint or local binary) is the next step.

## DAG-walk example: explore a node's neighborhood

```
> node Translation
  at: Translation  [['TEXT'] → ['TEXT']]

> out
  CHILDREN of Translation (26):
    via TEXT → Audio-Text-to-Text
    via TEXT → Image-Text-to-Image
    via TEXT → Text-to-Speech
    via TEXT → Text-to-Video
    ... (every task that accepts TEXT)

> in
  PARENTS of Translation (14):
    via TEXT ← Automatic Speech Recognition
    via TEXT ← Document Question Answering
    via TEXT ← Image-to-Text
    ... (every task that emits TEXT)
```

## Known limitations

1. **Single-input edge matching** — an edge from A to B is established if
   ONE of B's inputs matches one of A's outputs. Multi-input tasks (like
   `Image-Text-to-Text` needing both IMAGE and TEXT) get noted as "broken"
   by `validate` if a previous step doesn't satisfy all required inputs.
   A real planner would walk back to find a sub-chain for each unmet input.
2. **`alts` IO shape matching** is loose — it returns any task that overlaps
   on at least one input AND one output, ranked by overlap strength.
   Strict shape equality is shape=6 (3 for ins + 3 for outs); partial gets
   lower. Use the `shape=` column to prefer drop-in replacements.
3. **No concrete tool resolution** — the JSONL is opcodes only. Linking
   each opcode to a real HF model or local binary lives in a separate
   `tool_resolutions.jsonl` (not yet written).
