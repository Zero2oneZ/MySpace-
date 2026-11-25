#!/usr/bin/env python3
"""scan_report.py — walk a project scan chain JSONL and emit a preliminary report.

Uses ParserCursor (XMLParser-shaped) to traverse the chain deterministically.
Groups findings by project, extracts README/CLAUDE.md/AGENT_CARD.md snippets,
counts languages, identifies subsystems.

Usage: python3 scan_report.py <chain.jsonl>
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))

from parser_cursor import ParserCursor, OK, ERR_FILE_EOF, NODE_ELEMENT, NODE_TEXT


KEY_DOCS = ("README.md", "CLAUDE.md", "AGENT_CARD.md", "REGISTRY.md", "BB.md",
            "NORTHSTAR_AGENT.md", "Cargo.toml", "package.json", "pyproject.toml",
            "Move.toml", "project.godot")


def main(chain_path: str) -> None:
    cur = ParserCursor()
    if cur.open(chain_path) != OK:
        print(f"could not open {chain_path}", file=sys.stderr)
        sys.exit(1)

    projects: dict[str, dict] = {}
    current_project = None
    current_file_rel = None

    while cur.read() != ERR_FILE_EOF:
        node_type = cur.get_node_type()
        node_name = cur.get_node_name()
        attrs = cur._current.attributes
        data = cur.get_node_data()

        if node_type == NODE_ELEMENT and node_name == "project":
            current_project = attrs.get("name") or attrs.get("path") or "?"
            projects[current_project] = {
                "path": attrs.get("path", ""),
                "total_files": attrs.get("total_files", 0),
                "total_dirs": attrs.get("total_dirs", 0),
                "total_size_kb": attrs.get("total_size_kb", 0),
                "langs": attrs.get("langs", ""),
                "has_rust": attrs.get("has_rust", False),
                "has_python": attrs.get("has_python", False),
                "has_move": attrs.get("has_move", False),
                "has_godot": attrs.get("has_godot", False),
                "has_node": attrs.get("has_node", False),
                "has_htmx": attrs.get("has_htmx", False),
                "has_3d_assets": attrs.get("has_3d_assets", False),
                "has_db": attrs.get("has_db", False),
                "dirs": [],
                "key_files": [],
                "manifests": [],
                "snippets": {},
            }
            continue

        if current_project is None:
            continue

        proj = projects[current_project]

        if node_type == NODE_ELEMENT and node_name == "dir":
            proj["dirs"].append((attrs.get("rel", ""), attrs.get("file_count", 0)))
            continue

        if node_type == NODE_ELEMENT and node_name == "file":
            rel = attrs.get("rel", "")
            bn = rel.rsplit("/", 1)[-1] if "/" in rel else rel
            if bn in KEY_DOCS or rel in KEY_DOCS:
                proj["key_files"].append({
                    "rel": rel,
                    "ext": attrs.get("ext", ""),
                    "lang": attrs.get("lang", ""),
                    "size": attrs.get("size", 0),
                })
                current_file_rel = rel
            else:
                current_file_rel = None
            continue

        if node_type == NODE_ELEMENT and node_name == "manifest":
            rel = attrs.get("rel", "")
            proj["manifests"].append({
                "rel": rel,
                "name": attrs.get("name", ""),
                "size": attrs.get("size", 0),
            })
            current_file_rel = rel
            continue

        if node_type == NODE_TEXT and node_name == "snippet" and current_file_rel:
            # Coerce — bash jline auto-parses JSON-looking content into dicts.
            if isinstance(data, (dict, list)):
                text = json.dumps(data, indent=2)[:600].strip()
            else:
                text = (str(data) if data is not None else "")[:600].strip()
            if text:
                proj["snippets"][current_file_rel] = text
            current_file_rel = None
            continue

    cur.close()

    # ---- emit report ------------------------------------------------------
    print("# PROJECT SCAN — PRELIMINARY REPORT\n")
    print(f"_Chain: `{chain_path}`_  |  Projects: {len(projects)}\n")

    # Quick summary table
    print("## Summary\n")
    print("| Project | Files | Size | Rust | Py | Move | Godot | Node | HTMX | 3D | DB | Langs |")
    print("|---|---:|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|")
    for name, p in sorted(projects.items()):
        size_mb = p["total_size_kb"] / 1024
        check = lambda b: "●" if b else "·"
        langs_short = (p["langs"][:48] + "…") if len(p["langs"]) > 48 else p["langs"]
        print(f"| **{name}** | {p['total_files']} | {size_mb:.1f}M | {check(p['has_rust'])} | {check(p['has_python'])} | {check(p['has_move'])} | {check(p['has_godot'])} | {check(p['has_node'])} | {check(p['has_htmx'])} | {check(p['has_3d_assets'])} | {check(p['has_db'])} | `{langs_short}` |")
    print()

    # Per-project detail
    for name, p in sorted(projects.items()):
        print(f"\n## {name}\n")
        print(f"**Path**: `{p['path']}`  ·  **Dirs**: {p['total_dirs']}  ·  **Files**: {p['total_files']}  ·  **Size**: {p['total_size_kb']/1024:.1f} MB")
        print(f"**Langs**: `{p['langs']}`")
        flags = [k for k in ("has_rust","has_python","has_move","has_godot","has_node","has_htmx","has_3d_assets","has_db") if p[k]]
        if flags:
            print(f"**Signals**: {', '.join(f.replace('has_','') for f in flags)}")

        if p["dirs"]:
            print("\n**Top-level dirs**:")
            for rel, n in p["dirs"][:12]:
                print(f"  - `{rel}/` ({n} files)")
            if len(p["dirs"]) > 12:
                print(f"  - … and {len(p['dirs']) - 12} more")

        # Identity doc first: README or CLAUDE.md
        for prefer in ("CLAUDE.md", "README.md", "NORTHSTAR_AGENT.md", "AGENT_CARD.md", "REGISTRY.md", "BB.md"):
            if prefer in p["snippets"]:
                print(f"\n**{prefer}** (first 600 chars):")
                print("```")
                print(p["snippets"][prefer])
                print("```")
                break

        # Notable manifests
        notable = [m for m in p["manifests"] if m["name"] in ("Cargo.toml","package.json","pyproject.toml","Move.toml","project.godot","CLAUDE.md","BB.md","REGISTRY.md","AGENT_CARD.md")]
        if notable:
            print("\n**Manifests** (nested):")
            for m in notable[:8]:
                print(f"  - `{m['rel']}` ({m['size']} bytes)")
            if len(notable) > 8:
                print(f"  - … and {len(notable) - 8} more")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: scan_report.py <chain.jsonl>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
