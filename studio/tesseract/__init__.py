"""tesseract/ — the Tesseract Renderer.

A meta-DAG over every other DAG in the studio. The master SVG that this
module emits is BOTH:

  (1) a *document* — carries the full inventory of systems, DAGs, nodes,
      project types, and plan steps in a single self-describing file, and

  (2) an *executable plan* — an agent reads the SVG, follows the
      contract embedded inside it, and walks node-by-node until every
      DAG has been traversed and every connection identified.

To advance through one node, an agent must satisfy three requirements:

  1. IDENTIFY the node itself (set data-walk-id + data-walk-by).
  2. IDENTIFY every adjacent node (list neighbor IDs).
  3. MAP the subject matter at each layer (which DAG, subsystem, project
     types this node participates in).

Only then may the walker mark the node as processed and advance. This
is enforced by `tesseract.walker`.

Public API:
    build_master(out=None)        → emit/refresh the SVG
    inventory.build_inventory()   → live state from every DAG source
    walker.next_node()            → next pending node
    walker.identify(...)          → satisfy contract + advance
    projects.activate(name)       → enable/disable subsystems by project type
    plan.add_step / mark / query  → step tracker
"""

from .projects  import activate, PROJECT_TYPES      # noqa: F401
from .inventory import build_inventory              # noqa: F401

# Lazy re-exports for the modules built later in the wave — wrap in try
# so the package imports cleanly while still under construction.
try:
    from .svg     import build_master              # noqa: F401
except ImportError:
    pass
try:
    from .walker  import next_node, identify, status  # noqa: F401
except ImportError:
    pass
try:
    from . import plan                              # noqa: F401
except ImportError:
    pass
