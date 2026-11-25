#!/usr/bin/env python3
"""chain_builder.py — deterministic workspace-coordinate chains.

Each chain entry is a WORK COORDINATE, not a keyword triple:
  {
    "file":      "src/vm_navigator.gd",
    "folder":    "studio/godot/project/src",
    "action":    "edit",
    "instruction": "add crystal_hash method",
    "step":      3,
    "depends_on": [1, 2],
    "scope":     "narrow",
    "weight":    0.85,
    "tokens":    450
  }

Chain assembly produces a NESTED structure:
  {                                # root = whole workspace
    [step_1] { file, folder, action, instruction }
    [step_2] { file, folder, action, instruction, sub_chain {
      [step_2a] { ... }
      [step_2b] { ... }
    }}
    [step_3] { ... }
  }

The FULL chain is assembled into ONE prompt (the "master chain").
Then SLICES are cut by deterministic scope rules:
  - tiny   → single {file,folder,action,instruction} with exact line numbers
  - medium → [step_N .. step_M] within one folder
  - large  → whole chain with annotations, dispatches downward
  - epic   → master chain + all sub_chains + meta-analysis

Determinism: same input → same coordinates → same slices, byte for byte.
"""
import json
import os
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple, Any

CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
CHAIN_INDEX_PATH = CC_HOME / "chat_chain_index.json"


@dataclass
class ChainEntry:
    """A single deterministic work coordinate."""
    file: str = ""
    folder: str = ""
    action: str = ""          # read | write | edit | build | run | test | verify
    instruction: str = ""
    step: int = 0
    depends_on: List[int] = field(default_factory=list)
    scope: str = "narrow"     # narrow | medium | broad | epic
    weight: float = 1.0
    tokens: int = 0           # estimated token cost for this step
    crystal: str = ""         # blake3 hash of this entry (deterministic id)


@dataclass
class ChainNode:
    """A node in the nested chain tree. Can hold entries + child nodes."""
    name: str = ""
    entries: List[ChainEntry] = field(default_factory=list)
    children: List["ChainNode"] = field(default_factory=list)
    scope: str = "narrow"
    weight: float = 1.0

    def total_tokens(self) -> int:
        t = sum(e.tokens for e in self.entries)
        t += sum(c.total_tokens() for c in self.children)
        return t

    def total_steps(self) -> int:
        return len(self.entries) + sum(c.total_steps() for c in self.children)


# ---------------------------------------------------------------------------
# Default chain index — populated from DESIGN-PRINCIPLES.md + project structure
# ---------------------------------------------------------------------------
DEFAULT_ENTRIES: List[ChainEntry] = [
    # Godot C++ build pipeline
    ChainEntry("spatial_bridge.cpp",   "studio/godot/project/cpp/src",  "build",    "compile C++ SpatialBridge with scons",                  1, [],  "narrow",  1.0,  800),
    ChainEntry("ik_solver.cpp",        "studio/godot/project/cpp/src",  "build",    "compile C++ IKSolver with scons",                       2, [1], "narrow",  1.0,  800),
    ChainEntry("mspc.gdextension",     "studio/godot/project/cpp",        "verify",   "verify GDExtension manifest loads in Godot",            3, [1,2], "medium", 0.9,  200),
    ChainEntry("main_controller.gd",   "studio/godot/project/src",      "edit",     "wire CCBridge signals into _ready",                    4, [3], "narrow",  0.95, 350),
    ChainEntry("cc_bridge.gd",         "studio/godot/project/src",      "edit",     "add downward slice dispatch logic",                    5, [4], "narrow",  0.95, 400),

    # cc chat subsystem
    ChainEntry("token_router.py",      "core/lib",                      "edit",     "add tier-downward dispatch with blind_to filtering",   6, [],  "medium", 0.85, 500),
    ChainEntry("prompt_enhancer.py",   "core/lib",                      "edit",     "inject file/folder/action markers into prompts",       7, [6], "medium", 0.85, 450),
    ChainEntry("chain_builder.py",     "core/lib",                      "edit",     "rebuild with ChainEntry/ChainNode nesting",            8, [7], "broad",  0.9,  600),
    ChainEntry("chat.py",              "core/lib",                      "edit",     "orchestrate master-chain assembly + slicing",          9, [8], "broad",  0.9,  550),
    ChainEntry("cc.sh",                "core",                          "edit",     "add cmd_chat with --slice and --master flags",        10, [9], "medium", 0.85, 400),

    # Determinism infrastructure
    ChainEntry("cc.db",                "~/.cc",                         "verify",   "check WAL mode + foreign_keys + busy_timeout",        11, [],  "narrow", 0.8,  200),
    ChainEntry("local.db",             "<project>/.cc",                 "verify",   "check agent_claim/release semantics",                  12, [11], "narrow", 0.8,  200),
    ChainEntry("keys.sqlite",          "studio/auth",                   "verify",   "check mode 600 + salt rotation",                       13, [],  "narrow", 0.8,  150),

    # Tesseract / DAG
    ChainEntry("TESSERACT.md",         "studio/docs",                   "read",     "verify 253 nodes, 729 edges, 8 source DAGs",          14, [],  "medium", 0.7,  300),
    ChainEntry("tesseract_build.py",   "studio/tesseract",              "run",      "rebuild master SVG if schema changed",                 15, [14], "medium", 0.75, 400),

    # WEAVE compute fabric
    ChainEntry("weave.sqlite",         "studio/cache/dag",              "verify",   "check devices + webgpu_adapters + plans tables",       16, [],  "medium", 0.7,  250),
    ChainEntry("webgpu_worker.html",   "studio/weave",                  "read",     "verify no eval, no Function constructor",               17, [16], "narrow", 0.75, 200),

    # Inference pipeline
    ChainEntry("DepthPro",             "_inference/models",             "run",      "generate depth map from camera feed",                  18, [],  "medium", 0.85, 1500),
    ChainEntry("MediaPipe_Pose",       "_inference/models",             "run",      "extract 33 landmark skeleton",                         19, [18], "medium", 0.85, 1200),
    ChainEntry("SpaceTimeGPT",         "_inference/models",             "run",      "predict next frame physics state",                    20, [19], "heavy",  0.9,  2000),
]


# ---------------------------------------------------------------------------
# Chain Assembler
# ---------------------------------------------------------------------------
class ChainAssembler:
    """Assembles entries into nested ChainNodes by folder + dependency order."""

    def __init__(self, entries: Optional[List[ChainEntry]] = None):
        self.entries = entries or self._load_or_default()

    @staticmethod
    def _load_or_default() -> List[ChainEntry]:
        if CHAIN_INDEX_PATH.exists():
            try:
                data = json.loads(CHAIN_INDEX_PATH.read_text())
                return [ChainEntry(**e) for e in data.get("entries", [])]
            except Exception:
                pass
        return DEFAULT_ENTRIES

    def save(self) -> None:
        CC_HOME.mkdir(parents=True, exist_ok=True)
        CHAIN_INDEX_PATH.write_text(
            json.dumps({"entries": [asdict(e) for e in self.entries]}, indent=2),
            encoding="utf-8",
        )

    def assemble(self, scope_hint: str = "") -> ChainNode:
        """Build a nested tree grouping entries by folder, sorted by step."""
        # Sort by step number deterministically
        sorted_entries = sorted(self.entries, key=lambda e: e.step)

        # Group by folder
        by_folder: Dict[str, List[ChainEntry]] = {}
        for e in sorted_entries:
            folder = e.folder or "(root)"
            by_folder.setdefault(folder, []).append(e)

        # Build root
        root = ChainNode(name="master_chain", scope="epic", weight=1.0)

        for folder, folder_entries in sorted(by_folder.items()):
            # Check if this folder has sub-entries that form a sub-chain
            child = ChainNode(name=folder, scope=self._folder_scope(folder_entries), weight=1.0)

            for e in folder_entries:
                child.entries.append(e)

            # Compute child weight as average of entry weights
            if child.entries:
                child.weight = sum(e.weight for e in child.entries) / len(child.entries)

            root.children.append(child)

        # Compute root weight as weighted average by token count
        total_tokens = root.total_tokens()
        if total_tokens > 0:
            root.weight = sum(
                c.weight * c.total_tokens() for c in root.children
            ) / total_tokens

        return root

    @staticmethod
    def _folder_scope(entries: List[ChainEntry]) -> str:
        scopes = {e.scope for e in entries}
        if "epic" in scopes:
            return "epic"
        if "broad" in scopes:
            return "broad"
        if "medium" in scopes:
            return "medium"
        return "narrow"

    def resolve_dependencies(self, root: ChainNode) -> List[Tuple[int, int]]:
        """Return list of (from_step, to_step) edges."""
        edges = []
        for child in root.children:
            for e in child.entries:
                for dep in e.depends_on:
                    edges.append((dep, e.step))
        return edges


# ---------------------------------------------------------------------------
# Chain Slicer — deterministic distribution by tier
# ---------------------------------------------------------------------------
class ChainSlicer:
    """Slice a master chain into tier-scoped pieces.

    Rules:
      - tiny:   single entry with exact file/folder coordinates. Max 4k tokens.
      - medium: all entries in one folder, or a contiguous step range. Max 32k.
      - large:  whole chain with annotations + downward dispatch plan. Max 128k.
      - epic:   master + all sub_chains + dependency graph + meta-analysis.
    """

    TIER_LIMITS = {
        "tiny":   4096,
        "medium": 32768,
        "large":  131072,
        "epic":   999999,
    }

    TIER_BLIND = {
        "tiny":   {"medium", "large", "epic"},
        "medium": {"large", "epic"},
        "large":  {"epic"},
        "epic":   set(),
    }

    def slice_by_tier(self, root: ChainNode, tier: str) -> List[ChainNode]:
        """Return slices appropriate for the given tier."""
        limit = self.TIER_LIMITS.get(tier, 4096)

        if tier == "tiny":
            # One slice per entry, exact coordinates
            slices = []
            for child in root.children:
                for e in child.entries:
                    if e.tokens <= limit:
                        node = ChainNode(
                            name=f"step_{e.step}",
                            scope="narrow",
                            weight=e.weight,
                            entries=[e]
                        )
                        slices.append(node)
            return slices

        if tier == "medium":
            # One slice per folder, if under limit
            slices = []
            for child in root.children:
                if child.total_tokens() <= limit:
                    slices.append(child)
                else:
                    # Split folder into smaller chunks by step ranges
                    slices.extend(self._chunk_node(child, limit))
            return slices

        if tier == "large":
            # Whole chain with annotations, but truncate if over limit
            if root.total_tokens() <= limit:
                return [root]
            # Create annotated root with dispatch plan
            annotated = self._annotate_for_large(root)
            return [annotated]

        # epic: full everything
        return [root]

    def _chunk_node(self, node: ChainNode, limit: int) -> List[ChainNode]:
        """Split a node into token-sized chunks."""
        chunks = []
        current = ChainNode(name=node.name, scope="medium", weight=node.weight, entries=[])
        current_tokens = 0

        for e in node.entries:
            if current_tokens + e.tokens > limit and current.entries:
                chunks.append(current)
                current = ChainNode(name=node.name, scope="medium", weight=node.weight, entries=[])
                current_tokens = 0
            current.entries.append(e)
            current_tokens += e.tokens

        if current.entries:
            chunks.append(current)
        return chunks

    def _annotate_for_large(self, root: ChainNode) -> ChainNode:
        """Add downward-dispatch annotations to the root for large-tier consumption."""
        annotated = ChainNode(
            name=root.name + "_annotated",
            scope="broad",
            weight=root.weight,
            children=root.children,
        )
        # The annotation is implicit: large tier sees whole chain and generates slices
        return annotated

    def downward_slice(self, root: ChainNode, from_tier: str, to_tier: str) -> List[ChainNode]:
        """Create slices for a lower tier from a higher tier's perspective."""
        if to_tier in self.TIER_BLIND.get(from_tier, set()):
            # Cannot dispatch to a tier that is blind to origin
            return []
        return self.slice_by_tier(root, to_tier)


# ---------------------------------------------------------------------------
# Prompt Renderer — turn ChainNode into deterministic prompt text
# ---------------------------------------------------------------------------
class PromptRenderer:
    """Render a ChainNode (or list of them) into a deterministic prompt."""

    def render(self, node: ChainNode, mode: str = "full") -> str:
        """mode: full | coordinates_only | instructions_only"""
        lines = []
        lines.append("# Chain Prompt")
        lines.append(f"# scope: {node.scope}")
        lines.append(f"# total_steps: {node.total_steps()}")
        lines.append(f"# total_tokens: {node.total_tokens()}")
        lines.append(f"# weight: {node.weight:.4f}")
        lines.append("")

        self._render_node(lines, node, 0, mode)
        return "\n".join(lines)

    def _render_node(self, lines: List[str], node: ChainNode, depth: int, mode: str):
        indent = "  " * depth
        if node.name and node.name != "master_chain":
            lines.append(f"{indent}## folder: {node.name}")

        for e in node.entries:
            if mode == "coordinates_only":
                lines.append(f"{indent}[step {e.step}] {e.folder}/{e.file} :: {e.action}")
            elif mode == "instructions_only":
                lines.append(f"{indent}[step {e.step}] {e.instruction}")
            else:
                lines.append(f"{indent}[step {e.step}] {e.folder}/{e.file}")
                lines.append(f"{indent}  action: {e.action}")
                lines.append(f"{indent}  instruction: {e.instruction}")
                lines.append(f"{indent}  scope: {e.scope} | weight: {e.weight} | tokens: {e.tokens}")
                if e.depends_on:
                    lines.append(f"{indent}  depends_on: {e.depends_on}")
                if e.crystal:
                    lines.append(f"{indent}  crystal: {e.crystal}")
                lines.append("")

        for child in node.children:
            self._render_node(lines, child, depth + 1, mode)

    def render_slices(self, slices: List[ChainNode], tier: str) -> str:
        lines = [f"# Sliced Prompts for tier: {tier}", ""]
        for i, slc in enumerate(slices, 1):
            lines.append(f"## Slice {i}/{len(slices)} — {slc.name}")
            lines.append(f"# steps: {slc.total_steps()} | tokens: {slc.total_tokens()} | weight: {slc.weight:.4f}")
            lines.append("")
            lines.append(self.render(slc, mode="full"))
            lines.append("")
            lines.append("---")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Token Counter (lightweight, deterministic)
# ---------------------------------------------------------------------------
class TokenCounter:
    @staticmethod
    def count(text: str) -> int:
        return max(1, len(text) // 3)


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(description="chain_builder — workspace-coordinate chains")
    ap.add_argument("--assemble", action="store_true", help="assemble master chain")
    ap.add_argument("--slice", choices=["tiny", "medium", "large", "epic"], help="slice for tier")
    ap.add_argument("--downward", nargs=2, metavar=("FROM", "TO"), help="downward dispatch")
    ap.add_argument("--render", choices=["full", "coordinates_only", "instructions_only"], default="full")
    ap.add_argument("--scope", default="", help="scope hint")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--add-entry", nargs=6, metavar=("FILE", "FOLDER", "ACTION", "INSTRUCTION", "STEP", "TOKENS"), help="add entry")
    args = ap.parse_args()

    assembler = ChainAssembler()

    if args.add_entry:
        e = ChainEntry(
            file=args.add_entry[0],
            folder=args.add_entry[1],
            action=args.add_entry[2],
            instruction=args.add_entry[3],
            step=int(args.add_entry[4]),
            tokens=int(args.add_entry[5]),
        )
        assembler.entries.append(e)
        assembler.save()
        print(f"added step {e.step}: {e.folder}/{e.file} :: {e.action}")
        return

    root = assembler.assemble(args.scope)
    slicer = ChainSlicer()
    renderer = PromptRenderer()

    if args.slice:
        slices = slicer.slice_by_tier(root, args.slice)
        if args.json:
            out = []
            for slc in slices:
                out.append({
                    "name": slc.name,
                    "scope": slc.scope,
                    "weight": slc.weight,
                    "steps": slc.total_steps(),
                    "tokens": slc.total_tokens(),
                    "entries": [asdict(e) for e in slc.entries],
                    "children": [{"name": c.name, "steps": c.total_steps(), "tokens": c.total_tokens()} for c in slc.children],
                })
            print(json.dumps(out, indent=2))
        else:
            print(renderer.render_slices(slices, args.slice))
        return

    if args.downward:
        slices = slicer.downward_slice(root, args.downward[0], args.downward[1])
        if args.json:
            print(json.dumps([{
                "name": s.name, "steps": s.total_steps(), "tokens": s.total_tokens(),
                "entries": [asdict(e) for e in s.entries]
            } for s in slices], indent=2))
        else:
            for slc in slices:
                print(renderer.render(slc))
        return

    # Default: assemble + render
    if args.json:
        def node_to_dict(n: ChainNode) -> dict:
            return {
                "name": n.name,
                "scope": n.scope,
                "weight": n.weight,
                "steps": n.total_steps(),
                "tokens": n.total_tokens(),
                "entries": [asdict(e) for e in n.entries],
                "children": [node_to_dict(c) for c in n.children],
            }
        print(json.dumps(node_to_dict(root), indent=2))
    else:
        print(renderer.render(root, args.render))


if __name__ == "__main__":
    main()
