"""node_map.py — the missing glue.

The canvas/runtime speaks node-ids (nodes.py: M_DEPTH, T_CLIP, …).
The real engine speaks two other vocabularies:
  - passes (passes/registry.py: depth, mask, caption, …)  — media inference, runs on the GPU box
  - roles  (models/role_map.json: chat/code/reason/…)       — LLM/text generation via ai_orchestrator

This module maps node-id → one of those routes. A node not in either map is
"unrouted" and the dispatcher falls back to a synth placeholder so the UI still
works. Add a row here (no other code change) to light a node up for real.
"""
from __future__ import annotations

# node_id -> pass_id  (media inference, executed on the z21 GPU server :8525)
NODE_PASS: dict[str, str] = {
    "M_DEPTH":  "depth",
    "M_SEG":    "mask",
    "M_POSE":   "keypoints",
    "M_MCLIP":  "embedding",
    "M_PEAV":   "embedding",
    "T_CLIP":   "caption",
    "M_STG":    "video_caption",
    "M_MAR":    "video_caption",
    "T_VOX":    "stems",
    "M_UV":     "speech_to_text",
    # texture/3d passes (used by 3D nodes / marigold-normals if added as nodes):
    # "M_NORMALS": "normal_map",
}

# node_id -> {backend, role}  (text/LLM generation via ai_orchestrator :8524)
# backend ∈ {auto, ollama, claude, cc}; role is advisory (role_map.json).
NODE_ROLE: dict[str, dict] = {
    "M_GEMMA": {"backend": "auto", "role": "reason"},
}

# Generative/diffusion nodes that need a comfyui/blender connector that is NOT
# implemented yet — listed so the UI can show "connector pending" instead of a
# silent synth. (role_map.json: image/video/3d/speech → connector comfyui/blender)
NODE_CONNECTOR: dict[str, str] = {
    "M_QIE": "comfyui", "T_FIRE": "comfyui", "T_QPOSE": "comfyui",
    "T_QCAM": "comfyui", "T_FSWAP": "comfyui", "T_KOLOR": "comfyui",
    "M_QTTS": "comfyui", "M_MFLOW": "comfyui", "T_LTX": "comfyui",
    "T_LCV": "comfyui", "M_PX3D": "blender", "T_PX3D": "blender",
}


def route_for(node_id: str) -> tuple[str, object]:
    """Return (route_kind, target). route_kind ∈ pass|role|connector|input|output|none."""
    if node_id.startswith("IN_"):
        return "input", None
    if node_id.startswith("OUT_"):
        return "output", None
    if node_id in NODE_PASS:
        return "pass", NODE_PASS[node_id]
    if node_id in NODE_ROLE:
        return "role", NODE_ROLE[node_id]
    if node_id in NODE_CONNECTOR:
        return "connector", NODE_CONNECTOR[node_id]
    return "none", None
