"""Port-type metadata: colors + legal connections (DAG-GUI.md §1.4)."""

PORT_COLORS = {
    "IMG":   "#22d3ee",
    "VID":   "#6366f1",
    "AUD":   "#f59e0b",
    "TXT":   "#e5e7eb",
    "PDF":   "#ef4444",
    "DEPTH": "#8b5cf6",
    "MASK":  "#84cc16",
    "KPTS":  "#ec4899",
    "EMB":   "#9ca3af",
    "MD":    "#d6b48a",
    "BOX":   "#fb923c",
    "CAM":   "#14b8a6",
    "MUS":   "#eab308",
    "3D":    "#10b981",
    "POSE":  "#ec4899",
}

ALL_TYPES = list(PORT_COLORS.keys())

TYPE_GLYPH = {
    "IMG": "image", "VID": "video", "AUD": "audio", "TXT": "text", "PDF": "pdf",
    "DEPTH": "depth", "MASK": "mask", "KPTS": "kpts", "EMB": "embedding",
    "MD": "markdown", "BOX": "bbox", "CAM": "camera", "MUS": "music", "3D": "3D mesh",
    "POSE": "pose-kpts",
}


def chip(type_code: str) -> str:
    color = PORT_COLORS.get(type_code, "#888")
    return (
        f"<span style='display:inline-block;padding:1px 8px;margin:0 4px 0 0;"
        f"border-radius:10px;background:{color};color:#0b0d10;font-size:11px;"
        f"font-weight:600'>{type_code}</span>"
    )


def edge_legal(producer_type: str, consumer_types: list) -> bool:
    return producer_type in consumer_types


# Cross-type coercions explicitly documented as legal in DAG-GUI.md §1.4.
# Example: MD feeds gemma + viewer where TXT is expected.
TYPE_COERCIONS: dict[str, set[str]] = {
    "MD": {"TXT"},
}


def types_compatible(producer_type: str, consumer_type: str) -> bool:
    if producer_type == consumer_type:
        return True
    return consumer_type in TYPE_COERCIONS.get(producer_type, set())
