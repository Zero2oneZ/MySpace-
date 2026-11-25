"""passes/ — declarative inference-pass registry + per-filetype DAG.

Concept:
    An "asset" (image / video / audio / 3D file) has many possible passes
    that can be run against it (mask, depth, caption, keypoints, embedding,
    waveform, vocal-separation, …). Each pass:
      - declares its input + output kinds (filetype DAG edges)
      - has a default inference function (`passes.inference`)
      - has a cost class (LIGHT / MEDIUM / HEAVY) that decides whether
        it runs at IMPORT time (user is fine waiting) or LAZY (on render)
      - records its measured duration into `passes.timing` so cost
        classes evolve over time per machine

The output of an import-time run is bundled into a single SVG via
`passes.svg_layers` — one `<g id="pass:<id>">` per pass, with
`data-instruction` + `data-duration-ms` attributes so the file is
self-describing.

Each piece (mask, depth-png, caption-text, etc.) is also indexed by
`passes.pieces_index` so the studio can search existing pre-computed
pieces before generating new ones ("we already have a mask for a red
dress, use that").

Public API (top of the module):
    REGISTRY                — list[Pass]
    by_id(pass_id) -> Pass
    for_filetype(ext)       — passes applicable to a filetype
    run_pass(pass_id, …)    — invoke the inference, with timing
"""

from .registry import (  # noqa: F401
    Pass, REGISTRY, by_id, for_filetype, for_kind,
    COST_LIGHT, COST_MEDIUM, COST_HEAVY,
)
