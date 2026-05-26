#!/usr/bin/env python3
"""mui_map.py — Maps MySpace++ widget vocabulary → Material UI components.

This is the canonical source for "what MUI component should the Phase-3
frontend render for each widget in a gui_card?" Lives separately so a
frontend builder can `import` it directly without pulling DB deps.

Each entry is `{component, props, wraps?, behavior?}`:
  - component:  MUI component name (e.g. "TextField", "Slider")
  - props:      default props as a dict (becomes JSX attrs)
  - wraps:      optional inner element template (e.g. "<input type=file>")
  - behavior:   optional notes for non-standard handlers (e.g. MediaRecorder)

The widget vocab covers all 10 input widgets the gui_cards use, plus the
state-machine nodes from the GUI interaction DAG (validate, submit,
running, done, error, hitl, download). MUI v5 names.
"""

from __future__ import annotations

from typing import Any

# Widget vocabulary → MUI component spec.
# Generators / frontends consume this dict directly. Don't add nesting
# beyond what's here without updating the consumers.
WIDGET_TO_MUI: dict[str, dict[str, Any]] = {
    # --- input widgets ---
    "text_input": {
        "component": "TextField",
        "props": {"variant": "outlined", "size": "small",
                  "fullWidth": True},
        "import": "@mui/material/TextField",
    },
    "text_input_multi": {
        "component": "TextField",
        "props": {"variant": "outlined", "multiline": True, "rows": 4,
                  "fullWidth": True},
        "import": "@mui/material/TextField",
    },
    "file_upload": {
        "component": "Button",
        "props": {"variant": "outlined", "component": "label",
                  "startIcon": "<CloudUploadIcon/>"},
        "import": "@mui/material/Button",
        "icon_import": "@mui/icons-material/CloudUpload",
        "wraps": "<input type='file' hidden accept='{{accept}}'/>",
        "behavior": "File picker; accept is set from gui_card props.accept",
    },
    "audio_recorder": {
        "component": "ToggleButton",
        "props": {"value": "record", "color": "error",
                  "startIcon": "<MicIcon/>"},
        "import": "@mui/material/ToggleButton",
        "icon_import": "@mui/icons-material/Mic",
        "behavior": "Wraps MediaRecorder API. Press to start, press again to stop. Falls back to file_upload if mic permission denied.",
    },
    "video_recorder": {
        "component": "ToggleButton",
        "props": {"value": "record", "color": "error",
                  "startIcon": "<VideocamIcon/>"},
        "import": "@mui/material/ToggleButton",
        "icon_import": "@mui/icons-material/Videocam",
        "behavior": "Wraps MediaRecorder API with video track. Falls back to file_upload if camera permission denied.",
    },
    "slider": {
        "component": "Slider",
        "props": {"valueLabelDisplay": "auto", "size": "small"},
        "import": "@mui/material/Slider",
    },
    "number_input": {
        "component": "TextField",
        "props": {"variant": "outlined", "type": "number",
                  "size": "small"},
        "import": "@mui/material/TextField",
    },
    "dropdown": {
        "component": "Select",
        "props": {"size": "small", "fullWidth": True},
        "import": "@mui/material/Select",
        "wraps": "{options.map(o => <MenuItem value={o}>{o}</MenuItem>)}",
        "extra_imports": ["@mui/material/MenuItem"],
    },
    "toggle": {
        "component": "Switch",
        "props": {"size": "small"},
        "import": "@mui/material/Switch",
    },

    # --- polymorphic output preview ---
    "output_preview": {
        "component": "Box",
        "props": {"sx": {"p": 2, "border": "1px solid",
                         "borderColor": "divider", "borderRadius": 1}},
        "import": "@mui/material/Box",
        "behavior": "Polymorphic by props.kind — see OUTPUT_KIND_TO_MUI",
    },
}


# Output `kind` → MUI rendering. The GUI card's output widget always uses
# `output_preview` as the wrapper; the `kind` prop picks the inner render.
OUTPUT_KIND_TO_MUI: dict[str, dict[str, Any]] = {
    "text": {
        "inner": "Typography",
        "inner_props": {"variant": "body1",
                        "sx": {"whiteSpace": "pre-wrap"}},
        "import": "@mui/material/Typography",
    },
    "image": {
        "inner": "img",
        "inner_props": {"style": {"maxWidth": "100%", "borderRadius": "4px"}},
        "actions": ["Download", "CopyImage"],
    },
    "audio": {
        "inner": "audio",
        "inner_props": {"controls": True, "style": {"width": "100%"}},
        "actions": ["Download"],
    },
    "video": {
        "inner": "video",
        "inner_props": {"controls": True, "style": {"width": "100%",
                                                     "borderRadius": "4px"}},
        "actions": ["Download", "Share"],
    },
    "3d_viewer": {
        "inner": "ModelViewer",
        "inner_props": {"camera-controls": True, "auto-rotate": True},
        "behavior": "Wraps three.js / model-viewer custom element",
        "actions": ["Download"],
    },
    "doc": {
        "inner": "iframe",
        "inner_props": {"style": {"width": "100%", "height": "600px",
                                   "border": "none"}},
        "actions": ["Download"],
    },
    "mask": {
        "inner": "img",
        "inner_props": {"style": {"maxWidth": "100%",
                                   "imageRendering": "pixelated"}},
        "behavior": "Renders mask as overlay on source image when available",
    },
    "boxes_overlay": {
        "inner": "Canvas",
        "behavior": "Renders source image + bounding boxes via HTMLCanvasElement",
    },
    "keypoints_overlay": {
        "inner": "Canvas",
        "behavior": "Renders source image + skeleton keypoints via Canvas",
    },
    "heatmap": {
        "inner": "Canvas",
        "behavior": "Source image + color-mapped overlay (viridis/plasma)",
    },
    "label": {
        "inner": "Chip",
        "inner_props": {"color": "primary", "variant": "filled"},
        "import": "@mui/material/Chip",
        "behavior": "Single-label classification result + confidence",
    },
    "label_seq": {
        "inner": "Stack",
        "inner_props": {"direction": "row", "spacing": 0.5,
                        "flexWrap": "wrap"},
        "import": "@mui/material/Stack",
        "behavior": "Per-token Chip array (NER, POS)",
    },
    "scalar": {
        "inner": "Typography",
        "inner_props": {"variant": "h4"},
        "import": "@mui/material/Typography",
    },
    "chart": {
        "inner": "ResponsiveContainer",
        "behavior": "Recharts wrapper — LineChart for forecasts, BarChart for histograms",
        "extra_imports": ["recharts"],
    },
    "vector": {
        "inner": "Typography",
        "inner_props": {"variant": "body2",
                        "sx": {"fontFamily": "monospace"}},
        "behavior": "Embedding shown as JSON array (truncated to 16 dims)",
    },
    "graph": {
        "inner": "div",
        "behavior": "Cytoscape.js or react-flow wrapper for node-link diagrams",
        "extra_imports": ["reactflow"],
    },
    "action": {
        "inner": "Card",
        "inner_props": {"variant": "outlined"},
        "import": "@mui/material/Card",
        "behavior": "Renders RL/robotics action as structured card",
    },
    "table": {
        "inner": "DataGrid",
        "import": "@mui/x-data-grid",
        "behavior": "Paginated table view for tabular outputs",
    },
}


# State-machine nodes from the GUI interaction DAG.
STATE_NODE_TO_MUI: dict[str, dict[str, Any]] = {
    "validate": {
        "component": "Alert",
        "props": {"severity": "info"},
        "import": "@mui/material/Alert",
        "behavior": "severity flips to 'success' when all required inputs filled",
    },
    "submit": {
        "component": "Button",
        "props": {"variant": "contained", "size": "large",
                  "startIcon": "<PlayArrowIcon/>", "color": "primary"},
        "import": "@mui/material/Button",
        "icon_import": "@mui/icons-material/PlayArrow",
        "behavior": "disabled while validate fails; spinner+disabled during running",
    },
    "running": {
        "component": "Box",
        "props": {"sx": {"display": "flex", "flexDirection": "column",
                          "gap": 1, "alignItems": "center"}},
        "wraps": "<LinearProgress sx={{width:'100%'}}/><Typography variant='caption'>Running... ~{{rt}}s</Typography>",
        "import": "@mui/material/Box",
        "extra_imports": ["@mui/material/LinearProgress",
                          "@mui/material/Typography"],
    },
    "done": {
        "component": "Alert",
        "props": {"severity": "success",
                  "icon": "<CheckCircleIcon/>"},
        "import": "@mui/material/Alert",
        "icon_import": "@mui/icons-material/CheckCircle",
    },
    "error": {
        "component": "Alert",
        "props": {"severity": "error",
                  "action": "<Button onClick={onRetry}>Retry</Button>"},
        "import": "@mui/material/Alert",
        "extra_imports": ["@mui/material/Button"],
        "behavior": "Action button kicks off submit again with same inputs",
    },
    "hitl": {
        "component": "Dialog",
        "props": {"maxWidth": "sm", "fullWidth": True},
        "import": "@mui/material/Dialog",
        "wraps": "<DialogTitle/><DialogContent/><DialogActions>"
                 "<Button onClick={onReject}>Reject</Button>"
                 "<Button onClick={onApprove} variant='contained'>Approve</Button>"
                 "</DialogActions>",
        "extra_imports": [
            "@mui/material/DialogTitle",
            "@mui/material/DialogContent",
            "@mui/material/DialogActions",
            "@mui/material/Button",
        ],
    },
    "download": {
        "component": "Button",
        "props": {"variant": "outlined",
                  "startIcon": "<DownloadIcon/>",
                  "size": "small"},
        "import": "@mui/material/Button",
        "icon_import": "@mui/icons-material/Download",
    },
}


def lookup(widget_or_state: str, kind: str = "") -> dict[str, Any]:
    """Return the MUI spec for a widget name. For `output_preview`,
    pass the `kind` to get the inner render mapping merged in."""
    if widget_or_state in WIDGET_TO_MUI:
        spec = dict(WIDGET_TO_MUI[widget_or_state])
        if widget_or_state == "output_preview" and kind:
            inner = OUTPUT_KIND_TO_MUI.get(kind)
            if inner:
                spec["inner_render"] = inner
        return spec
    if widget_or_state in STATE_NODE_TO_MUI:
        return dict(STATE_NODE_TO_MUI[widget_or_state])
    return {"component": "Box", "props": {},
            "behavior": f"unknown widget '{widget_or_state}'"}


def all_components() -> set[str]:
    """All distinct MUI components referenced across the map. Useful
    for generating a single import header in a frontend bundle."""
    comps: set[str] = set()
    for spec in list(WIDGET_TO_MUI.values()) + list(STATE_NODE_TO_MUI.values()):
        c = spec.get("component")
        if c:
            comps.add(c)
    for spec in OUTPUT_KIND_TO_MUI.values():
        inner = spec.get("inner")
        if inner and inner[0].isupper():
            comps.add(inner)
    return comps


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        for k, v in WIDGET_TO_MUI.items():
            print(f"{k:<18} → {v['component']}")
        print()
        for k, v in OUTPUT_KIND_TO_MUI.items():
            print(f"output:{k:<10} → {v.get('inner', '-')}")
        print()
        for k, v in STATE_NODE_TO_MUI.items():
            print(f"state:{k:<12} → {v['component']}")
    elif len(sys.argv) > 1 and sys.argv[1] == "--components":
        for c in sorted(all_components()):
            print(c)
    elif len(sys.argv) > 1:
        widget = sys.argv[1]
        kind = sys.argv[2] if len(sys.argv) > 2 else ""
        print(json.dumps(lookup(widget, kind), indent=2))
    else:
        print(__doc__)
