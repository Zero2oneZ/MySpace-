"""material.py — assemble a Godot-ready PBR material set from one base image.

The deterministic asset-landing law (ground truth = Godot's res:// + the
godot_ssot_proxy): renders live at ~/.cc/chain_renders/<crystal_short>/ as
  manifest.json  +  <name>_albedo.png / _normal.png / _depth.png / _alpha.png
keyed by a CRYSTAL hash (symbolic, self-organizing — no manual foldering).
chain_render_bridge.gd already pulls /chain/render/<crystal>/manifest and the
assets; this just emits the material flavour of that manifest so a
StandardMaterial3D can be built from it (Godot Y-up, sRGB albedo, linear normal).

Maps today (use-what-is-built):
  albedo  = the base image itself (diffuse/base color)         [real]
  depth   = passes.pass_depth (PIL pseudo-depth)               [rough; TODO DepthPro/Marigold in /home/tom/models]
  normal  = passes.pass_normal_map (PIL gradient normal)       [rough; TODO marigold-normals]
  alpha   = passes.pass_nobg (rembg)                           [PENDING: onnxruntime import blocked]

Upgrade path is wired into the manifest (instruction fields) so swapping the
rough passes for the real models is a drop-in, not a rewrite.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from passes import inference as pinf  # noqa: E402

CHAIN_RENDERS_ROOT = Path.home() / ".cc" / "chain_renders"

# global asset standards — synced by default (the chain READS them; change once,
# propagates everywhere). Meta-SDK-aligned (units/normals/texture sizes/PBR).
def _standards() -> dict:
    for p in (os.environ.get("GENTLY_STANDARDS"),
              "/home/tom/Projects/gently/docs/standards.json",
              "/data/Projects/gently/docs/standards.json"):
        if p and Path(p).exists():
            try:
                return json.loads(Path(p).read_text())
            except Exception:
                pass
    return {}


def _crystal_short(albedo_bytes: bytes, name: str) -> str:
    h = hashlib.blake2b(albedo_bytes + name.encode(), digest_size=16)
    return h.hexdigest()[:16]


def _run_map(fn, src: Path) -> str | None:
    """Run a pass; return its output path or None (unavailable)."""
    try:
        res = fn(src)
        return res.get("path") if res.get("ok") else None
    except Exception:
        return None


def build_material(src: Path, name: str = "material") -> dict:
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(src)
    albedo_bytes = src.read_bytes()
    crystal = _crystal_short(albedo_bytes, name)
    out_dir = CHAIN_RENDERS_ROOT / crystal
    out_dir.mkdir(parents=True, exist_ok=True)

    maps: dict[str, str] = {}
    pending: dict[str, str] = {}

    # albedo = the base image (diffuse/base color)
    albedo_p = out_dir / f"{name}_albedo.png"
    shutil.copy(src, albedo_p)
    maps["albedo"] = albedo_p.name

    # depth (PIL pseudo-depth — rough; upgrade: apple_DepthPro / Depth-Anything)
    dp = _run_map(pinf.pass_depth, src)
    if dp and Path(dp).exists():
        shutil.copy(dp, out_dir / f"{name}_depth.png"); maps["depth"] = f"{name}_depth.png"
    else:
        pending["depth"] = "pass_depth unavailable"

    # normal (PIL gradient — rough; upgrade: prs-eth marigold-normals)
    nm = _run_map(pinf.pass_normal_map, src)
    if nm and Path(nm).exists():
        shutil.copy(nm, out_dir / f"{name}_normal.png"); maps["normal"] = f"{name}_normal.png"
    else:
        pending["normal"] = "pass_normal_map unavailable"

    # alpha (rembg background removal → transparent texture)
    al = _run_map(pinf.pass_nobg, src)
    if al and Path(al).exists():
        shutil.copy(al, out_dir / f"{name}_alpha.png"); maps["alpha"] = f"{name}_alpha.png"
    else:
        pending["alpha"] = "pass_nobg unavailable (rembg/onnxruntime import blocked)"

    # the Godot StandardMaterial3D recipe — bridge builds the material from this.
    material = {
        "type": "StandardMaterial3D",
        "albedo_texture": maps.get("albedo"),
        "albedo_color_space": "sRGB",
        "normal_enabled": "normal" in maps,
        "normal_texture": maps.get("normal"),
        "heightmap_enabled": "depth" in maps,
        "heightmap_texture": maps.get("depth"),
        "transparency": "alpha" if "alpha" in maps else "disabled",
        "up_axis": "Y",
    }
    manifest = {
        "kind": "material",
        "crystal_short": crystal,
        "name": name,
        "target": "godot",
        "created": int(time.time()),
        "maps": maps,
        "pending": pending,
        "material": material,
        "standards_version": _standards().get("version"),
        "conventions": _standards().get("units", {"up": "Y"}),
        "normals": _standards().get("normals"),
        "texture_spec": _standards().get("textures"),
        "export_targets": _standards().get("export_targets"),
        "upgrade": {"depth": "apple_DepthPro / Depth-Anything-v2",
                    "normal": "prs-eth marigold-normals",
                    "alpha": "fix onnxruntime sys.version parse → rembg"},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return {"crystal_short": crystal, "dir": str(out_dir),
            "manifest_url": f"/chain/render/{crystal}/manifest", **manifest}


if __name__ == "__main__":
    src = Path(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else src.stem
    r = build_material(src, name)
    print(json.dumps({"crystal_short": r["crystal_short"], "dir": r["dir"],
                      "maps": r["maps"], "pending": r["pending"]}, indent=2))
