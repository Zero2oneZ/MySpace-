# Models DAG Studio (Streamlit)

A pipeline-builder GUI for the model/tool catalogue under `/home/tom/models/`.
Implements the spec in `../DAG-GUI.md` adapted to Streamlit (card-based chain
editor instead of an infinite ComfyUI-style canvas).

## Layout

```
dag_studio/
├── app.py          ─ main Streamlit app
├── nodes.py        ─ node manifests (inputs, models, tools, loras, class, outputs)
├── recipes.py      ─ prebuilt chains C01–C17 + single-hops S01–S21
├── runtime.py      ─ topo-sort, type-validate, cache-key, mock executor
├── types_meta.py   ─ port colours + chips
├── recipes/        ─ user-extensible recipe drops
├── saved/          ─ persisted .dag.json pipelines
└── run.sh          ─ venv bootstrap + streamlit run
```

## Run

```bash
cd /home/tom/models/dag_studio
./run.sh
# → http://localhost:8501
```

## What works today

- Drag-equivalent palette (＋ button) for all 8 inputs, 9 models, 13 tools,
  1 lora, 1 class, 11 outputs from `../DAG.md`.
- Type-checked edges (DAG-GUI.md §1.4 matrix).
- Auto-wiring: each node's inputs link to the nearest upstream producer of
  a matching port type.
- Recipe loader: 17 multi-hop + 21 single-hop chains.
- Per-node Inspector — auto-generated param form, wiring view,
  content-addressed cache key, output JSON.
- Save / load `.dag.json` (mirrors `DAG.md` node ids for diffability).
- Run / Dry-run with mock executor (per-node status dots, progress bar,
  job log).

## What's stubbed

- `runtime.run_step()` returns deterministic mock outputs.
  Wire each node's real implementation by dispatching
  `python -m <entry>` inside `<MODELS_ROOT>/<dir>/.venv/` (per
  `nodes.py` manifests) and writing artifacts to
  `~/.cache/dag-studio/<cache_key>/`.
- File uploaders capture metadata only — pass real paths into `run_step`
  once subprocess dispatch is wired.
