"""svg_layers.py — pack pass outputs into one self-describing SVG.

Output structure (simplified):

    <svg xmlns="http://www.w3.org/2000/svg" width="W" height="H">
      <metadata id="passes-manifest">
        <passes:dag>
          <passes:pass id="thumb" cost="LIGHT" ms="3"/>
          <passes:pass id="mask"  cost="HEAVY" ms="412"/>
          ...
        </passes:dag>
      </metadata>

      <!-- base: source image (always layer 0) -->
      <g id="pass:source" data-pass-id="source"
         data-instruction="original imported image">
        <image href="data:image/jpeg;base64,..." width="W" height="H"/>
      </g>

      <!-- one <g> per pass that produced a renderable artifact -->
      <g id="pass:mask"  data-pass-id="mask"  data-cost-class="HEAVY"
         data-duration-ms="412" data-instruction="alpha matte ..."
         display="none">
        <image href="data:image/png;base64,..."/>
      </g>

      ...

      <!-- text-only passes go under <text> in a stash group -->
      <g id="pass:caption" data-pass-id="caption" display="none">
        <text>red dress, satin, evening wear</text>
      </g>
    </svg>

The SVG is both a *bundle* (everything in one file) and a *plan* (the
data-instruction strings tell future code what each layer means / how
it was produced). Viewers can show/hide individual layers; downstream
tools can read the manifest to skip already-computed passes.
"""
from __future__ import annotations

import base64
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths   # noqa: E402

from . import registry as reg   # noqa: E402

SVG_NS    = "http://www.w3.org/2000/svg"
XLINK_NS  = "http://www.w3.org/1999/xlink"
PASS_NS   = "https://myspace.local/passes"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)
ET.register_namespace("passes", PASS_NS)


def _b64(path: Path) -> str:
    """data: URL for an image path."""
    suffix = path.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png",  "webp": "image/webp",
            "gif": "image/gif",  "bmp": "image/bmp"}.get(suffix, "image/png")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return 1024, 1024


def pack(asset_path: Path, results: list[dict],
         out_path: Optional[Path] = None) -> Path:
    """Pack the source + every pass result into one SVG.
    `results` is a list of PassResult dicts (see inference.py)."""
    asset_path = Path(asset_path)
    w, h = _image_size(asset_path)

    # Build the SVG tree.
    svg = ET.Element(f"{{{SVG_NS}}}svg", attrib={
        "width":   str(w),
        "height":  str(h),
        "viewBox": f"0 0 {w} {h}",
        "version": "1.1",
    })

    # ── Manifest under <metadata> ────────────────────────────────────────
    meta = ET.SubElement(svg, f"{{{SVG_NS}}}metadata", attrib={"id": "passes-manifest"})
    dag  = ET.SubElement(meta, f"{{{PASS_NS}}}dag", attrib={"asset": asset_path.name})
    for r in results:
        if not r.get("ok"):
            continue
        try:
            p = reg.by_id(r["pass_id"])
        except KeyError:
            continue
        ET.SubElement(dag, f"{{{PASS_NS}}}pass", attrib={
            "id":            r["pass_id"],
            "kind":          r.get("kind", ""),
            "cost":          p.cost_class,
            "import-time":   "1" if p.import_time else "0",
            "duration-ms":   f"{r.get('duration_ms', 0.0):.2f}",
            "instruction":   r.get("instruction", "") or p.instruction,
        })

    # ── Base layer: the source image ─────────────────────────────────────
    g_src = ET.SubElement(svg, f"{{{SVG_NS}}}g", attrib={
        "id":               "pass:source",
        "data-pass-id":     "source",
        "data-instruction": "original imported image (read-only)",
    })
    img = ET.SubElement(g_src, f"{{{SVG_NS}}}image", attrib={
        "x": "0", "y": "0", "width": str(w), "height": str(h),
        "href": _b64(asset_path),
    })
    img.set(f"{{{XLINK_NS}}}href", img.get("href"))   # back-compat

    # ── One <g> per pass result ──────────────────────────────────────────
    for r in results:
        if not r.get("ok"):
            continue
        pid = r["pass_id"]
        if pid == "layered_svg":          # don't recursively embed self
            continue
        try:
            p = reg.by_id(pid)
        except KeyError:
            continue

        g = ET.SubElement(svg, f"{{{SVG_NS}}}g", attrib={
            "id":                f"pass:{pid}",
            "data-pass-id":      pid,
            "data-kind":         r.get("kind") or "",
            "data-cost-class":   p.cost_class,
            "data-duration-ms":  f"{r.get('duration_ms', 0.0):.2f}",
            "data-instruction":  r.get("instruction", "") or p.instruction,
            "display":           "none",   # layers off-by-default in viewers
        })

        path_str = r.get("path")
        if path_str and Path(path_str).exists() and Path(path_str).is_file():
            ext = Path(path_str).suffix.lower().lstrip(".")
            if ext in ("png", "jpg", "jpeg", "webp", "gif", "bmp"):
                # Renderable image layer.
                im_el = ET.SubElement(g, f"{{{SVG_NS}}}image", attrib={
                    "x": "0", "y": "0", "width": str(w), "height": str(h),
                    "href": _b64(Path(path_str)),
                })
                im_el.set(f"{{{XLINK_NS}}}href", im_el.get("href"))
            else:
                # Non-image piece — store a file pointer + size, not the bytes.
                ET.SubElement(g, f"{{{PASS_NS}}}piece", attrib={
                    "href":  str(Path(path_str).relative_to(paths.MEDIA_ROOT)
                                  if str(path_str).startswith(str(paths.MEDIA_ROOT))
                                  else path_str),
                    "bytes": str(Path(path_str).stat().st_size),
                    "kind":  r.get("kind") or "",
                })

        # Handle fused depth special case - it outputs a .npz file with multiple arrays
        if pid == "fused_depth" and path_str:
            npz_path = Path(path_str)
            if npz_path.exists():
                # Embed depth stats as text (not the raw array)
                import numpy as np
                with np.load(npz_path) as data:
                    depth = data.get("depth")
                    if depth is not None:
                        ET.SubElement(g, f"{{{SVG_NS}}}desc").text = json.dumps({
                            "depth_stats": {
                                "min_m": float(depth.min()),
                                "max_m": float(depth.max()),
                                "mean_m": float(depth.mean()),
                                "std_m": float(depth.std()),
                            },
                            "room_dims": r.get("room_dims", {}),
                        })
        elif r.get("value") is not None:
            # Text / list / dict result — embed inline.
            val = r["value"]
            if isinstance(val, (str, int, float)):
                txt = ET.SubElement(g, f"{{{SVG_NS}}}text", attrib={
                    "x": "8", "y": "20",
                    "font-family": "system-ui, sans-serif",
                    "font-size": "12",
                })
                txt.text = str(val)
            else:
                txt = ET.SubElement(g, f"{{{SVG_NS}}}desc")
                txt.text = json.dumps(val, ensure_ascii=False)

    # ── Write ────────────────────────────────────────────────────────────
    if out_path is None:
        # Default location: under paths.LAYER_STYLE_DIR/<asset-stem>.svg
        out_path = paths.LAYER_STYLE_DIR / f"{asset_path.stem}.layers.svg"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ET.ElementTree(svg).write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path


def pack_for_source(src: Path) -> dict:
    """Convenience entry — runs all import-time passes on `src`, then packs.
    Returns a PassResult-shaped dict for the `layered_svg` registry entry."""
    from . import inference, timing
    ext = src.suffix.lstrip(".").lower()
    plan_passes = [p for p in reg.import_time_passes(ext) if p.id != "layered_svg"]
    results: list[dict] = []
    for p in plan_passes:
        results.append(inference.run(p.id, src))
    with timing.Timer("layered_svg", src) as t:
        out = pack(src, results)
    return {
        "ok": True, "kind": "SVG", "value": None, "path": str(out),
        "duration_ms": t.duration_ms or 0.0,
        "instruction": "bundle source + pass outputs into one SVG",
        "pass_id": "layered_svg", "error": None,
        "sub_results": results,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: svg_layers.py <image>", file=sys.stderr); sys.exit(2)
    r = pack_for_source(Path(sys.argv[1]))
    print(json.dumps({k: v for k, v in r.items() if k != "sub_results"},
                     indent=2, default=str))
