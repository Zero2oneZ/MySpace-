"""Node catalog: inputs, models, tools, loras, classes, outputs.

Schema (DAG-GUI.md §4):
  id, name, kind, dir?, entry?, inputs[], outputs[], params[], vram_gb, cpu_only
"""
from __future__ import annotations
from pathlib import Path

MODELS_ROOT = Path("/home/tom/models")


def port(name, t):
    return {"name": name, "type": t}


def p_int(name, lo, hi, default):
    return {"name": name, "type": "int", "min": lo, "max": hi, "default": default}


def p_float(name, lo, hi, default, step=0.1):
    return {"name": name, "type": "float", "min": lo, "max": hi, "default": default, "step": step}


def p_text(name, default=""):
    return {"name": name, "type": "text", "default": default}


def p_bool(name, default=False):
    return {"name": name, "type": "bool", "default": default}


def p_seed():
    return {"name": "seed", "type": "int", "min": 0, "max": 2**31 - 1, "default": 0}


# ─── INPUTS (sources) ────────────────────────────────────────────────────────
INPUT_NODES = [
    {"id": "IN_IMG", "name": "Image input",  "kind": "input",
     "inputs": [], "outputs": [port("out", "IMG")],
     "params": [{"name": "file", "type": "file"}]},
    {"id": "IN_VID", "name": "Video input",  "kind": "input",
     "inputs": [], "outputs": [port("out", "VID")],
     "params": [{"name": "file", "type": "file"}, p_float("trim_start", 0, 600, 0), p_float("trim_end", 0, 600, 0)]},
    {"id": "IN_AUD", "name": "Audio input",  "kind": "input",
     "inputs": [], "outputs": [port("out", "AUD")],
     "params": [{"name": "file", "type": "file"}]},
    {"id": "IN_TXT", "name": "Text input",   "kind": "input",
     "inputs": [], "outputs": [port("out", "TXT")],
     "params": [p_text("text", "a portrait, cinematic light")]},
    {"id": "IN_PDF", "name": "PDF input",    "kind": "input",
     "inputs": [], "outputs": [port("out", "PDF")],
     "params": [{"name": "file", "type": "file"}]},
    {"id": "IN_POSE", "name": "Pose kpts in", "kind": "input",
     "inputs": [], "outputs": [port("out", "POSE")],
     "params": [{"name": "file", "type": "file"}]},
    {"id": "IN_CAM", "name": "Camera/3D in", "kind": "input",
     "inputs": [], "outputs": [port("out", "CAM")],
     "params": [{"name": "file", "type": "file"}]},
    {"id": "IN_BOX", "name": "BBox hint",    "kind": "input",
     "inputs": [], "outputs": [port("out", "BOX")],
     "params": [p_int("x", 0, 4096, 0), p_int("y", 0, 4096, 0),
                p_int("w", 1, 4096, 256), p_int("h", 1, 4096, 256)]},
]


# ─── MODELS (9) ──────────────────────────────────────────────────────────────
MODEL_NODES = [
    {"id": "M_DEPTH", "name": "apple_DepthPro", "kind": "model",
     "dir": "apple_DepthPro", "entry": "infer.py",
     "inputs": [port("image", "IMG")], "outputs": [port("depth", "DEPTH")],
     "params": [p_bool("invert", False)], "vram_gb": 6, "cpu_only": False},

    {"id": "M_SEG", "name": "finegrain_box_segmenter", "kind": "model",
     "dir": "finegrain_box_segmenter", "entry": "infer.py",
     "inputs": [port("image", "IMG"), port("box", "BOX")],
     "outputs": [port("mask", "MASK")],
     "params": [p_float("threshold", 0.0, 1.0, 0.5, 0.01)], "vram_gb": 4, "cpu_only": False},

    {"id": "M_MFLOW", "name": "melodyflow-t24-30secs", "kind": "model",
     "dir": "melodyflow-t24-30secs", "entry": "infer.py",
     "inputs": [port("prompt", "TXT")], "outputs": [port("music", "MUS")],
     "params": [p_float("duration", 1, 30, 12), p_seed()],
     "vram_gb": 8, "cpu_only": False},

    {"id": "M_MCLIP", "name": "metaclip-2-mt5", "kind": "model",
     "dir": "metaclip-2-mt5-worldwide-m16", "entry": "infer.py",
     "inputs": [port("image", "IMG")], "outputs": [port("emb", "EMB")],
     "params": [], "vram_gb": 3, "cpu_only": False},

    {"id": "M_PEAV", "name": "pe-av-small", "kind": "model",
     "dir": "pe-av-small", "entry": "infer.py",
     "inputs": [port("video", "VID")], "outputs": [port("emb", "EMB")],
     "params": [], "vram_gb": 4, "cpu_only": False},

    {"id": "M_POSE", "name": "qualcomm_MediaPipe_Pose", "kind": "model",
     "dir": "qualcomm_MediaPipe_Pose_Estimation", "entry": "infer.py",
     "inputs": [port("image", "IMG")], "outputs": [port("kpts", "KPTS")],
     "params": [p_bool("draw_overlay", True)], "vram_gb": 1, "cpu_only": True},

    {"id": "M_QIE", "name": "Qwen_Image_Edit_2511", "kind": "model",
     "dir": "Qwen_Image_Edit_2511", "entry": "infer.py",
     "inputs": [port("image", "IMG"), port("prompt", "TXT")],
     "outputs": [port("image", "IMG")],
     "params": [p_text("prompt", ""), p_float("strength", 0.0, 1.0, 0.7, 0.01), p_seed()],
     "vram_gb": 14, "cpu_only": False},

    {"id": "M_PX3D", "name": "TencentARC_Pixal3D", "kind": "model",
     "dir": "TencentARC_Pixal3D", "entry": "infer.py",
     "inputs": [port("image", "IMG"), port("depth", "DEPTH")],
     "outputs": [port("mesh", "3D")],
     "params": [p_int("resolution", 64, 512, 256)],
     "vram_gb": 10, "cpu_only": False},

    {"id": "M_UV", "name": "ultravox-v0_7-glm-4_6", "kind": "model",
     "dir": "ultravox-v0_7-glm-4_6", "entry": "infer.py",
     "inputs": [port("audio", "AUD"), port("prompt", "TXT")],
     "outputs": [port("text", "TXT")],
     "params": [p_text("system_prompt", "Transcribe and respond.")],
     "vram_gb": 12, "cpu_only": False},

    {"id": "M_GEMMA", "name": "gemma-4-E4B-it", "kind": "model",
     "dir": "gemma-4-E4B-it", "entry": "infer.py",
     "inputs": [port("text", "TXT")], "outputs": [port("text", "TXT")],
     "params": [p_text("system", "You are a helpful assistant."),
                p_float("temperature", 0.0, 2.0, 0.7, 0.05),
                p_int("max_tokens", 16, 4096, 512)],
     "vram_gb": 6, "cpu_only": False},

    {"id": "M_STG", "name": "SpaceTimeGPT", "kind": "model",
     "dir": "SpaceTimeGPT", "entry": "infer.py",
     "inputs": [port("video", "VID")], "outputs": [port("caption", "TXT")],
     "params": [p_int("num_frames", 4, 16, 8),
                p_int("max_new_tokens", 16, 128, 64)],
     "vram_gb": 3, "cpu_only": False},

    {"id": "M_MAR", "name": "Marlin-2B-ungated", "kind": "model",
     "dir": "Marlin-2B-ungated", "entry": "infer.py",
     "inputs": [port("video", "VID"), port("query", "TXT")],
     "outputs": [port("result", "TXT")],
     "params": [{"name": "mode", "type": "enum",
                 "options": ["caption", "find"], "default": "caption"},
                p_int("fps_sample", 1, 8, 2),
                p_int("max_new_tokens", 64, 1024, 384),
                p_float("temperature", 0.0, 1.0, 0.2, 0.05)],
     "vram_gb": 8, "cpu_only": False},

    {"id": "M_QTTS", "name": "Qwen3-TTS-12Hz-1.7B-CustomVoice", "kind": "model",
     "dir": "Qwen3-TTS-12Hz-1.7B-CustomVoice", "entry": "infer.py",
     "inputs": [port("text", "TXT"), port("instruction", "TXT")],
     "outputs": [port("audio", "AUD")],
     "params": [{"name": "timbre", "type": "enum",
                 "options": ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9"],
                 "default": "t1"},
                {"name": "language", "type": "enum",
                 "options": ["zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"],
                 "default": "en"},
                p_float("speaking_rate", 0.5, 2.0, 1.0, 0.05),
                p_bool("streaming", False),
                p_seed()],
     "vram_gb": 6, "cpu_only": False},
]


# ─── TOOLS (13) ──────────────────────────────────────────────────────────────
TOOL_NODES = [
    {"id": "T_CLIP", "name": "CLIP-Interrogator", "kind": "tool",
     "dir": "CLIP-Interrogator", "entry": "run.py",
     "inputs": [port("image", "IMG")], "outputs": [port("caption", "TXT")],
     "params": [{"name": "mode", "type": "enum", "options": ["fast", "best", "classic"], "default": "best"}],
     "vram_gb": 4, "cpu_only": True},

    {"id": "T_CKEY", "name": "CorridorKey", "kind": "tool",
     "dir": "CorridorKey", "entry": "run.py",
     "inputs": [port("video", "VID")], "outputs": [port("video", "VID")],
     "params": [{"name": "key_color", "type": "enum", "options": ["green", "blue", "auto"], "default": "auto"},
                p_float("tolerance", 0.0, 1.0, 0.3, 0.01)],
     "vram_gb": 4, "cpu_only": False},

    {"id": "T_FIRE", "name": "FireRed-Image-Edit", "kind": "tool",
     "dir": "FireRed-Image-Edit-1.0-Fast", "entry": "run.py",
     "inputs": [port("image", "IMG"), port("prompt", "TXT"), port("mask", "MASK")],
     "outputs": [port("image", "IMG")],
     "params": [p_text("prompt", ""), p_seed()],
     "vram_gb": 14, "cpu_only": False, "uses": "M_QIE"},

    {"id": "T_FSWAP", "name": "Flux2-Klein-Face-Swap", "kind": "tool",
     "dir": "Flux2-Klein-Face-Swap", "entry": "run.py",
     "inputs": [port("source", "IMG"), port("target", "IMG"), port("mask", "MASK")],
     "outputs": [port("image", "IMG")],
     "params": [p_bool("use_bg_lora", True), p_seed()],
     "vram_gb": 16, "cpu_only": False, "uses": "L_BG"},

    {"id": "T_KOLOR", "name": "Kolors-Virtual-Try-On", "kind": "tool",
     "dir": "Kolors-Virtual-Try-On", "entry": "run.py",
     "inputs": [port("person", "IMG"), port("garment", "IMG")],
     "outputs": [port("image", "IMG")],
     "params": [p_seed()], "vram_gb": 12, "cpu_only": False},

    {"id": "T_LCV", "name": "LongCat-Video-Avatar-1.5", "kind": "tool",
     "dir": "LongCat-Video-Avatar-1.5", "entry": "run.py",
     "inputs": [port("portrait", "IMG"), port("voice", "AUD")],
     "outputs": [port("video", "VID")],
     "params": [p_int("fps", 12, 60, 25), p_float("duration", 1, 30, 8)],
     "vram_gb": 12, "cpu_only": False},

    {"id": "T_LTX", "name": "LTX2.3-Studio", "kind": "tool",
     "dir": "LTX2.3-Studio", "entry": "run.py",
     "inputs": [port("prompt", "TXT")], "outputs": [port("video", "VID")],
     "params": [p_int("frames", 24, 240, 96), p_int("fps", 12, 60, 24), p_seed()],
     "vram_gb": 18, "cpu_only": False},

    {"id": "T_MINE", "name": "MinerU", "kind": "tool",
     "dir": "MinerU", "entry": "run.py",
     "inputs": [port("pdf", "PDF")], "outputs": [port("markdown", "MD")],
     "params": [p_bool("extract_tables", True), p_bool("extract_images", True)],
     "vram_gb": 0, "cpu_only": True},

    {"id": "T_PX3D", "name": "Pixal3D", "kind": "tool",
     "dir": "Pixal3D", "entry": "run.py",
     "inputs": [port("image", "IMG")], "outputs": [port("mesh", "3D")],
     "params": [p_int("resolution", 64, 512, 256)],
     "vram_gb": 10, "cpu_only": False, "uses": "M_PX3D"},

    {"id": "T_QPOSE", "name": "Qwen-AnyPose", "kind": "tool",
     "dir": "Qwen-Image-Edit-2511-AnyPose", "entry": "run.py",
     "inputs": [port("image", "IMG"), port("kpts", "KPTS"), port("prompt", "TXT")],
     "outputs": [port("image", "IMG")],
     "params": [p_text("prompt", ""), p_seed()],
     "vram_gb": 14, "cpu_only": False, "uses": "M_QIE"},

    {"id": "T_QCAM", "name": "qwen-3d-camera", "kind": "tool",
     "dir": "qwen-image-multiple-angles-3d-camera", "entry": "run.py",
     "inputs": [port("image", "IMG"), port("camera", "CAM"), port("prompt", "TXT")],
     "outputs": [port("image", "IMG")],
     "params": [p_text("prompt", ""), p_seed()],
     "vram_gb": 14, "cpu_only": False, "uses": "M_QIE"},

    {"id": "T_VBG", "name": "video-background-removal", "kind": "tool",
     "dir": "video-background-removal", "entry": "run.py",
     "inputs": [port("video", "VID"), port("mask", "MASK")],
     "outputs": [port("video", "VID")],
     "params": [p_bool("transparent", True)],
     "vram_gb": 6, "cpu_only": False},

    {"id": "T_VOX", "name": "Vocal-Isolator", "kind": "tool",
     "dir": "Vocal-Isolator", "entry": "run.py",
     "inputs": [port("audio", "AUD")], "outputs": [port("stems", "AUD")],
     "params": [{"name": "model", "type": "enum",
                 "options": ["uvr-vocals", "uvr-drums", "uvr-bass", "uvr-other"],
                 "default": "uvr-vocals"}],
     "vram_gb": 4, "cpu_only": False},
]


# ─── LORAS + CLASSES ────────────────────────────────────────────────────────
LORA_NODES = [
    {"id": "L_BG", "name": "flux2_klein_bg_remove_lora", "kind": "lora",
     "dir": "flux_2_klein_4B_background_remove_lora", "entry": None,
     "inputs": [], "outputs": [port("weights", "EMB")],
     "params": [p_float("strength", 0.0, 1.5, 1.0, 0.05)],
     "vram_gb": 0, "cpu_only": True},
]

CLASS_NODES = [
    {"id": "C_RSN", "name": "claude-opus-reasoning-8.7k", "kind": "class",
     "dir": "claude-opus-4.6-4.7-reasoning-8.7k", "entry": None,
     "inputs": [], "outputs": [port("corpus", "MD")],
     "params": [], "vram_gb": 0, "cpu_only": True},
]


# ─── OUTPUTS (sinks) ─────────────────────────────────────────────────────────
OUTPUT_NODES = [
    {"id": "OUT_IMG", "name": "Image output",  "kind": "output",
     "inputs": [port("in", "IMG")],  "outputs": [], "params": []},
    {"id": "OUT_VID", "name": "Video output",  "kind": "output",
     "inputs": [port("in", "VID")],  "outputs": [], "params": []},
    {"id": "OUT_AUD", "name": "Audio output",  "kind": "output",
     "inputs": [port("in", "AUD")],  "outputs": [], "params": []},
    {"id": "OUT_TXT", "name": "Text output",   "kind": "output",
     "inputs": [port("in", "TXT")],  "outputs": [], "params": []},
    {"id": "OUT_MD",  "name": "Markdown output","kind": "output",
     "inputs": [port("in", "MD")],   "outputs": [], "params": []},
    {"id": "OUT_3D",  "name": "3D mesh output","kind": "output",
     "inputs": [port("in", "3D")],   "outputs": [], "params": []},
    {"id": "OUT_DEPTH","name": "Depth viewer", "kind": "output",
     "inputs": [port("in", "DEPTH")],"outputs": [], "params": []},
    {"id": "OUT_MASK","name": "Mask viewer",  "kind": "output",
     "inputs": [port("in", "MASK")], "outputs": [], "params": []},
    {"id": "OUT_KPTS","name": "Kpts viewer",  "kind": "output",
     "inputs": [port("in", "KPTS")], "outputs": [], "params": []},
    {"id": "OUT_EMB", "name": "Embedding sink","kind": "output",
     "inputs": [port("in", "EMB")],  "outputs": [], "params": []},
    {"id": "OUT_MUS", "name": "Music output", "kind": "output",
     "inputs": [port("in", "MUS")],  "outputs": [], "params": []},
]


NODES = INPUT_NODES + MODEL_NODES + TOOL_NODES + LORA_NODES + CLASS_NODES + OUTPUT_NODES
NODES_BY_ID = {n["id"]: n for n in NODES}


def nodes_by_kind(kind: str):
    return [n for n in NODES if n["kind"] == kind]


def nodes_accepting(producer_type: str):
    """All nodes that have at least one input port accepting producer_type
    (honouring types_meta.TYPE_COERCIONS, e.g. MD → TXT)."""
    from types_meta import types_compatible
    out = []
    for n in NODES:
        for inp in n["inputs"]:
            if types_compatible(producer_type, inp["type"]):
                out.append(n)
                break
    return out


def nodes_producing(consumer_type: str):
    """All nodes that have at least one output port producing consumer_type
    (honouring types_meta.TYPE_COERCIONS)."""
    from types_meta import types_compatible
    out = []
    for n in NODES:
        for o in n["outputs"]:
            if types_compatible(o["type"], consumer_type):
                out.append(n)
                break
    return out
