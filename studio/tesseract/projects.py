"""projects.py — project-type ↔ subsystem activation matrix.

A "project type" is the user's high-level intent (3D scene, texture
work, makeup design, app build, etc.). Each type activates / deactivates
a specific subset of the studio's subsystems so the UI + DAG don't
overwhelm the user with irrelevant tools.

The matrix below is the source of truth — Tesseract reads it to decide
which subsystem nodes light up in the master SVG when a project is
opened.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ── Subsystem catalog ───────────────────────────────────────────────────────
# Status:
#   "impl"        — fully implemented
#   "partial"     — usable for the primary path but missing features
#   "stub"        — defined + addressable but not yet wired up
#   "placeholder" — earmarked, no code yet
#
# `files` is a list of repo-relative paths where the implementation lives
# (or would live). `helps` is a list of other subsystems this one assists.

SUBSYSTEMS: dict[str, dict] = {
    "scene_3d": {
        "name":   "3D Scene engine",
        "status": "partial",
        "files":  ["studio/media/Media/3d/", "studio/projects/*/scene.json"],
        "helps":  ["furniture", "render", "texture"],
    },
    "texture": {
        "name":   "Texture system",
        "status": "partial",
        "files":  ["studio/media/Media/3d/textures/", "studio/passes/inference.py::pass_normal_map"],
        "helps":  ["scene_3d", "render"],
    },
    "inference": {
        "name":   "Inference system",
        "status": "impl",
        "files":  ["studio/passes/", "studio/nodes.py", "studio/runtime.py"],
        "helps":  ["makeup", "furniture", "search", "render", "scene_3d"],
    },
    "makeup": {
        "name":   "Makeup design system",
        "status": "placeholder",
        "files":  ["studio/projects/*/makeup/"],
        "helps":  ["render"],
    },
    "furniture": {
        "name":   "Furniture design system",
        "status": "stub",
        "files":  ["studio/media/Furniture/", "studio/projects/*/scene.json"],
        "helps":  ["scene_3d", "render"],
    },
    "search": {
        "name":   "Search system (pieces + Pinterest)",
        "status": "impl",
        "files":  ["studio/passes/pieces_index.py", "studio/pinterest/"],
        "helps":  ["inference", "scene_3d", "furniture", "makeup", "texture"],
    },
    "render": {
        "name":   "Inference + render system",
        "status": "partial",
        "files":  ["studio/runtime.py", "studio/passes/svg_layers.py"],
        "helps":  ["scene_3d", "makeup", "furniture", "app_builder"],
    },
    "business": {
        "name":   "Business system (CRM / records / billing)",
        "status": "placeholder",
        "files":  ["TODO: studio/business/"],
        "helps":  ["app_builder", "comms"],
    },
    "app_builder": {
        "name":   "App + website builder",
        "status": "placeholder",
        "files":  ["TODO: studio/app_builder/"],
        "helps":  ["business", "comms"],
    },
    "comms": {
        "name":   "Communications system",
        "status": "placeholder",
        "files":  ["TODO: studio/comms/", "studio/proxy/claude_proxy.py"],
        "helps":  ["business", "app_builder", "inference"],
    },
}


# ── Project types ──────────────────────────────────────────────────────────
@dataclass
class ProjectType:
    id: str
    label: str
    required: list[str] = field(default_factory=list)   # must be active
    optional: list[str] = field(default_factory=list)   # nice to have
    default_passes: list[str] = field(default_factory=list)
    description: str = ""


PROJECT_TYPES: dict[str, ProjectType] = {
    "3d-scene": ProjectType(
        id="3d-scene", label="3D scene composition",
        required=["scene_3d", "render"],
        optional=["texture", "furniture", "inference", "search"],
        default_passes=["thumb", "content_hash", "bbox_volume", "mesh_thumb"],
        description="Build / edit a 3D scene from imported meshes.",
    ),
    "texture": ProjectType(
        id="texture", label="Texture / material design",
        required=["texture"],
        optional=["scene_3d", "inference", "search"],
        default_passes=["thumb", "normal_map", "depth", "mask", "albedo"],
        description="Convert images into PBR texture stacks (albedo + normal + depth).",
    ),
    "makeup-designer": ProjectType(
        id="makeup-designer", label="Makeup designer",
        required=["makeup", "render"],
        optional=["inference", "search"],
        default_passes=["thumb", "mask", "keypoints", "depth"],
        description="JSONL-stacked makeup layers on a head template.",
    ),
    "furniture-designer": ProjectType(
        id="furniture-designer", label="Furniture / room designer",
        required=["furniture", "scene_3d", "render"],
        optional=["texture", "search", "inference"],
        default_passes=["thumb", "mesh_thumb", "bbox_volume", "depth"],
        description="Compose furnished rooms from the Furniture/ library.",
    ),
    "image-search": ProjectType(
        id="image-search", label="Image / asset search",
        required=["search", "inference"],
        optional=["render"],
        default_passes=["thumb", "content_hash", "embedding", "caption", "tags"],
        description="Browse the media library by content + tags.",
    ),
    "render": ProjectType(
        id="render", label="Render-only pipeline",
        required=["render", "inference"],
        optional=["scene_3d", "texture"],
        default_passes=["thumb"],
        description="Headless render service mode — minimal UI.",
    ),
    "business-record": ProjectType(
        id="business-record", label="Business record / CRM",
        required=["business"],
        optional=["comms", "app_builder"],
        default_passes=[],
        description="Customer / project / billing records (placeholder).",
    ),
    "app-builder": ProjectType(
        id="app-builder", label="App or website builder",
        required=["app_builder"],
        optional=["render", "comms", "business", "search"],
        default_passes=["thumb"],
        description="Generate an app / website from declarative configs (placeholder).",
    ),
    "comms": ProjectType(
        id="comms", label="Communications hub",
        required=["comms"],
        optional=["business", "app_builder", "inference"],
        default_passes=[],
        description="Inbox / messaging / Claude proxy front-end (placeholder).",
    ),
}


def activate(project_type: str) -> dict:
    """Return the activation map for a project type:
        {subsystem_id: {active: bool, role: 'required'|'optional', status: ...}}
    """
    pt = PROJECT_TYPES.get(project_type)
    if pt is None:
        raise KeyError(f"unknown project type: {project_type!r}")
    out: dict[str, dict] = {}
    for sid, meta in SUBSYSTEMS.items():
        role: Optional[str] = None
        if sid in pt.required: role = "required"
        elif sid in pt.optional: role = "optional"
        out[sid] = {
            "active": role is not None,
            "role":   role,
            "status": meta["status"],
            "name":   meta["name"],
            "files":  meta["files"],
            "helps":  meta["helps"],
        }
    return {
        "project_type":   pt.id,
        "label":          pt.label,
        "description":    pt.description,
        "default_passes": pt.default_passes,
        "subsystems":     out,
    }


if __name__ == "__main__":
    import json, sys
    if len(sys.argv) >= 2:
        print(json.dumps(activate(sys.argv[1]), indent=2))
    else:
        print(f"{'project type':<22} required subsystems")
        print("-" * 76)
        for pt in PROJECT_TYPES.values():
            req = ", ".join(pt.required)
            print(f"  {pt.id:<22} {req}")
