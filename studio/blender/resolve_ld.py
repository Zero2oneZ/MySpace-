#!/usr/bin/env python3
# Resolve a coherent set of 64-bit nix-store lib dirs Blender's loader needs,
# for NIX_LD_LIBRARY_PATH. Cached to .cc/blender_ld.txt (recompute if missing).
import glob, os, sys
from pathlib import Path
SONAMES = ["libX11.so.6","libXext.so.6","libXrender.so.1","libXi.so.6","libXfixes.so.3",
 "libXxf86vm.so.1","libXrandr.so.2","libXcursor.so.1","libXinerama.so.1","libSM.so.6",
 "libICE.so.6","libxkbcommon.so.0","libGL.so.1","libEGL.so.1","libgomp.so.1",
 "libstdc++.so.6","libz.so.1","libtinfo.so.6","libffi.so.8"]
def is64(p):
    try:
        with open(p,"rb") as f: h=f.read(5)
        return len(h)==5 and h[:4]==b"\x7fELF" and h[4]==2
    except Exception: return False
cache = Path(os.environ.get("CC_HOME", str(Path.home()/".cc")))/"blender_ld.txt"
if cache.exists() and cache.read_text().strip() and "--refresh" not in sys.argv:
    sys.stdout.write(cache.read_text().strip()); sys.exit(0)
dirs=[]
for so in SONAMES:
    for p in glob.glob(f"/nix/store/*/lib/{so}"):
        if is64(p): dirs.append(os.path.dirname(p)); break
out=":".join(sorted(set(dirs)))
cache.parent.mkdir(parents=True, exist_ok=True); cache.write_text(out)
sys.stdout.write(out)
