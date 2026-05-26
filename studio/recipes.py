"""Prebuilt recipes C01–C17 (DAG-GUI.md §1.2) as ordered chains of node-ids.

A chain is a list of dicts; each step instantiates a single node plus wiring
hints. The Streamlit app drops these straight into the canvas.
"""

RECIPES = {
    "C01": {
        "name": "Photo → talking avatar",
        "chain": ["IN_IMG", "IN_AUD", "T_LCV", "OUT_VID"],
        "note": "LongCat wants both portrait IMG and voice AUD.",
    },
    "C02": {
        "name": "Photo → 3D asset",
        "chain": ["IN_IMG", "M_DEPTH", "M_PX3D", "OUT_3D"],
        "note": "DepthPro feeds Pixal3D; image is reused as colour source.",
    },
    "C03": {
        "name": "Pose-controlled edit",
        "chain": ["IN_IMG", "M_POSE", "T_QPOSE", "OUT_IMG"],
        "note": "MediaPipe → KPTS → AnyPose.",
    },
    "C04": {
        "name": "Auto-prompt → T2V",
        "chain": ["IN_IMG", "T_CLIP", "T_LTX", "OUT_VID"],
        "note": "CLIP-Interrogator caption drives LTX2.3.",
    },
    "C05": {
        "name": "Song splitter → remix",
        "chain": ["IN_AUD", "T_VOX", "M_MFLOW", "OUT_MUS"],
        "note": "Vocal-Isolator stems → melodyflow remix (needs text bridge in app).",
    },
    "C06": {
        "name": "Doc ingest → LLM",
        "chain": ["IN_PDF", "T_MINE", "M_GEMMA", "OUT_TXT"],
        "note": "MinerU → MD → gemma.",
    },
    "C07": {
        "name": "Green-screen comp",
        "chain": ["IN_VID", "T_CKEY", "T_VBG", "OUT_VID"],
        "note": "CorridorKey then video-bg-removal.",
    },
    "C08": {
        "name": "Image → mood music",
        "chain": ["IN_IMG", "T_CLIP", "M_MFLOW", "OUT_MUS"],
        "note": "Caption → melodyflow.",
    },
    "C09": {
        "name": "Image → described 3D",
        "chain": ["IN_IMG", "T_CLIP", "M_GEMMA", "M_DEPTH", "M_PX3D", "OUT_3D"],
        "note": "Branchy: caption + 3D in parallel; final node is 3D.",
    },
    "C10": {
        "name": "Voice memo → markdown brief",
        "chain": ["IN_AUD", "M_UV", "M_GEMMA", "OUT_MD"],
        "note": "ultravox transcript → gemma summary.",
    },
    "C11": {
        "name": "PDF → narrated explainer",
        "chain": ["IN_PDF", "T_MINE", "M_GEMMA", "IN_IMG", "T_LCV", "OUT_VID"],
        "note": "Long pipeline; needs a TTS step in practice — placeholder.",
    },
    "C12": {
        "name": "Pose+style restyle",
        "chain": ["IN_IMG", "M_POSE", "T_QPOSE", "T_FIRE", "OUT_IMG"],
        "note": "AnyPose then FireRed restyle.",
    },
    "C13": {
        "name": "Subject-only image",
        "chain": ["IN_IMG", "IN_BOX", "M_SEG", "T_FSWAP", "OUT_IMG"],
        "note": "Box → mask → swap with background lora.",
    },
    "C14": {
        "name": "Try-on then animate",
        "chain": ["IN_IMG", "T_KOLOR", "IN_AUD", "T_LCV", "OUT_VID"],
        "note": "Virtual try-on then talking avatar.",
    },
    "C15": {
        "name": "Camera-controlled scene",
        "chain": ["IN_IMG", "IN_CAM", "T_QCAM", "T_LTX", "OUT_VID"],
        "note": "qwen-3d-camera then LTX2.3.",
    },
    "C16": {
        "name": "Video → music score",
        "chain": ["IN_VID", "M_PEAV", "M_GEMMA", "M_MFLOW", "OUT_MUS"],
        "note": "Video embedding → text bridge via gemma → melodyflow.",
    },
    "C17": {
        "name": "Video clean + bg remove combo",
        "chain": ["IN_VID", "T_CKEY", "T_VBG", "T_LCV", "OUT_VID"],
        "note": "Two cleanup passes then re-compose with LongCat.",
    },
    "C18": {
        "name": "Video → spoken summary",
        "chain": ["IN_VID", "M_MAR", "M_GEMMA", "M_QTTS", "OUT_AUD"],
        "note": "Marlin dense caption → gemma summarise → Qwen3-TTS speaks.",
    },
    "C19": {
        "name": "Video → narrated avatar recap",
        "chain": ["IN_VID", "M_MAR", "M_GEMMA", "M_QTTS", "IN_IMG", "T_LCV", "OUT_VID"],
        "note": "End-to-end: video → text → speech → talking avatar.",
    },
    "C20": {
        "name": "Image → captioned voice-over",
        "chain": ["IN_IMG", "T_CLIP", "M_GEMMA", "M_QTTS", "OUT_AUD"],
        "note": "Caption → rewrite → TTS audio.",
    },
    "C21": {
        "name": "Video → short caption (cheap)",
        "chain": ["IN_VID", "M_STG", "OUT_TXT"],
        "note": "SpaceTimeGPT one-line caption.",
    },
    "C22": {
        "name": "Find-a-moment then cut",
        "chain": ["IN_VID", "IN_TXT", "M_MAR", "OUT_TXT"],
        "note": "Marlin in 'find' mode returns (start,end) span over the input query.",
    },
    "C23": {
        "name": "PDF → audiobook",
        "chain": ["IN_PDF", "T_MINE", "M_GEMMA", "M_QTTS", "OUT_AUD"],
        "note": "MinerU → script clean-up → custom-voice TTS.",
    },
    "C24": {
        "name": "Voice memo → spoken reply",
        "chain": ["IN_AUD", "M_UV", "M_GEMMA", "M_QTTS", "OUT_AUD"],
        "note": "ultravox transcribe → gemma reply → Qwen3-TTS.",
    },
    "C25": {
        "name": "Music + narration mix",
        "chain": ["IN_TXT", "M_MFLOW", "M_QTTS", "OUT_AUD"],
        "note": "Parallel: melodyflow MUS + Qwen3-TTS speech (mix in inspector).",
    },
}


# Single-hop chains (S01–S21) for quick experimentation
SINGLE_HOPS = {
    "S01": ["IN_IMG", "T_CLIP", "OUT_TXT"],
    "S02": ["IN_IMG", "M_DEPTH", "OUT_DEPTH"],
    "S03": ["IN_IMG", "IN_BOX", "M_SEG", "OUT_MASK"],
    "S04": ["IN_IMG", "M_MCLIP", "OUT_EMB"],
    "S05": ["IN_IMG", "M_POSE", "OUT_KPTS"],
    "S06": ["IN_IMG", "IN_TXT", "T_FIRE", "OUT_IMG"],
    "S07": ["IN_IMG", "T_PX3D", "OUT_3D"],
    "S08": ["IN_IMG", "T_FSWAP", "OUT_IMG"],
    "S09": ["IN_IMG", "T_KOLOR", "OUT_IMG"],
    "S10": ["IN_IMG", "IN_AUD", "T_LCV", "OUT_VID"],
    "S11": ["IN_VID", "T_CKEY", "OUT_VID"],
    "S12": ["IN_VID", "T_VBG", "OUT_VID"],
    "S13": ["IN_VID", "M_PEAV", "OUT_EMB"],
    "S14": ["IN_AUD", "T_VOX", "OUT_AUD"],
    "S15": ["IN_AUD", "M_UV", "OUT_TXT"],
    "S16": ["IN_TXT", "M_MFLOW", "OUT_MUS"],
    "S17": ["IN_TXT", "M_GEMMA", "OUT_TXT"],
    "S18": ["IN_TXT", "T_LTX", "OUT_VID"],
    "S19": ["IN_PDF", "T_MINE", "OUT_MD"],
    "S20": ["IN_POSE", "IN_IMG", "T_QPOSE", "OUT_IMG"],
    "S21": ["IN_CAM", "IN_IMG", "T_QCAM", "OUT_IMG"],
    "S22": ["IN_VID", "M_STG", "OUT_TXT"],
    "S23": ["IN_VID", "IN_TXT", "M_MAR", "OUT_TXT"],
    "S24": ["IN_TXT", "M_QTTS", "OUT_AUD"],
}
