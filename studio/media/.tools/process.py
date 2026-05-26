#!/usr/bin/env python3
"""
process.py — classify a downloaded media file and optionally remove background.

Usage:
  process.py classify <file>           -> prints relative dest dir
  process.py bgremove <file> <outpng>  -> writes rgba png with bg removed (if rembg present)
  process.py mask     <file> <outpng>  -> writes binary mask png (if rembg present)

Classification is heuristic-first (extension + filename keywords). When the
local `cc tiny` helper is available we fall back to it for ambiguous cases.
Background removal uses `rembg` if installed; otherwise it no-ops and returns 2.
"""
from __future__ import annotations
import os, sys, re, subprocess, shutil

VIDEO_EXT = {".mp4",".mov",".mkv",".webm",".avi",".m4v",".flv",".wmv"}
MESH_EXT  = {".obj",".stl",".gltf",".glb",".fbx",".ply",".dae",".usdz"}
IMG_EXT   = {".jpg",".jpeg",".png",".webp",".bmp",".gif",".tif",".tiff",".avif"}

# Keyword -> destination relative path (under the media root — historically
# Images/, now studio/media/).
# Patterns are checked top→bottom; first match wins. Trailing 's' is allowed via
# the (?:s)? suffix instead of \b so we don't accidentally over-match.
def _kw(*words):
    return r"\b(?:" + "|".join(words) + r")(?:s|es|ing)?\b"

KEYWORDS = [
    # NSFW first — should win over softer signals like "group"/"solo"
    (_kw("nude","nsfw","erotic","porn","sex","lewd","hentai","topless","xxx"),
        "Models/Females/Sex"),

    # Cloths
    (_kw("dress","gown","frock"),                                       "Cloths/Female/Dresses"),
    (_kw("shirt","tee","tshirt","t-shirt","blouse","top","tank","hoodie","sweater","jumper"),
        "Cloths/__GENDER__/Tops"),
    (_kw("pant","jean","trouser","legging","short","skirt","cargo","slack"),
        "Cloths/__GENDER__/Bottoms"),
    (_kw("jacket","coat","parka","blazer","outerwear","cardigan","windbreaker"),
        "Cloths/__GENDER__/Outerwear"),
    (_kw("shoe","sneaker","boot","heel","sandal","loafer","footwear"),
        "Cloths/__GENDER__/Footwear"),
    (_kw("hat","cap","belt","scarf","glove","tie","sunglass","accessor","accessory"),
        "Cloths/__GENDER__/Accessories"),
    (_kw("bikini","swimsuit","swimwear","trunk"),
        "Cloths/__GENDER__/Swimwear"),
    (_kw("bra","panty","pantie","lingerie","underwear","brief","boxer"),
        "Cloths/__GENDER__/Underwear"),
    (_kw("pajama","pyjama","sleepwear","robe","nightgown"),
        "Cloths/__GENDER__/Sleepwear"),

    # Furniture / rooms
    (_kw("bedroom"),                                "Furniture/RoomsType/Bedroom"),
    (_kw("livingroom","living","lounge"),           "Furniture/RoomsType/LivingRoom"),
    (_kw("kitchen"),                                "Furniture/RoomsType/Kitchen"),
    (_kw("bathroom","bathtub","shower"),            "Furniture/RoomsType/Bathroom"),
    (_kw("diningroom","dining","dinette"),          "Furniture/RoomsType/DiningRoom"),
    (_kw("office","study","workspace"),             "Furniture/RoomsType/Office"),
    (_kw("outdoor","patio","garden","porch","backyard"), "Furniture/RoomsType/Outdoor"),
    (_kw("hallway","corridor","foyer","entry"),     "Furniture/RoomsType/Hallway"),
    (_kw("loft","studioapt","studioflat"),          "Furniture/RoomsType/Studio"),
    (_kw("sofa","couch","chair","table","dresser","lamp","nightstand",
         "wardrobe","bookshelf","desk","stool","ottoman","furniture"),
        "Furniture/RoomsType/LivingRoom"),

    # Models / Females
    (_kw("headshot","portrait","face","bust"),                 "Models/Females/HeadShots"),
    (_kw("group","trio","duo","couple","threesome"),           "Models/Females/Group"),
    (_kw("solo","alone","single"),                             "Models/Females/Solo"),
    (_kw("woman","female","girl","lady","model"),              "Models/Females/Solo"),
]

def gender_hint(name: str) -> str:
    n = name.lower()
    if re.search(r"\b(men|man|male|guy|boy|gentleman|mens)\b", n):
        return "Male"
    return "Female"

def cc_tiny_classify(name: str) -> str | None:
    """Ask the local tiny model for a single-bucket answer; return None on fail."""
    if not shutil.which("cc"):
        return None
    buckets = (
        "Media/Video, Media/Image, Media/Mask, Media/3d, "
        "Furniture/RoomsType/Bedroom, Furniture/RoomsType/LivingRoom, "
        "Furniture/RoomsType/Kitchen, Furniture/RoomsType/Bathroom, "
        "Furniture/RoomsType/DiningRoom, Furniture/RoomsType/Office, "
        "Furniture/RoomsType/Outdoor, Furniture/RoomsType/Hallway, "
        "Furniture/RoomsType/Studio, "
        "Models/Females/Solo, Models/Females/Group, "
        "Models/Females/HeadShots, Models/Females/Sex, "
        "Cloths/Female/Tops, Cloths/Female/Bottoms, Cloths/Female/Dresses, "
        "Cloths/Female/Outerwear, Cloths/Female/Footwear, Cloths/Female/Accessories, "
        "Cloths/Female/Swimwear, Cloths/Female/Underwear, Cloths/Female/Sleepwear, "
        "Cloths/Male/Tops, Cloths/Male/Bottoms, Cloths/Male/Outerwear, "
        "Cloths/Male/Footwear, Cloths/Male/Accessories, Cloths/Male/Swimwear, "
        "Cloths/Male/Underwear, Cloths/Male/Sleepwear"
    )
    prompt = (
        f"Pick exactly ONE bucket from this list for the filename '{name}'. "
        f"Reply ONLY with the bucket path, no explanation.\n"
        f"Buckets: {buckets}"
    )
    try:
        out = subprocess.run(
            ["cc", "tiny", prompt],
            capture_output=True, text=True, timeout=20,
        )
        txt = out.stdout.strip().splitlines()[-1].strip() if out.stdout else ""
        # crude validation: must look like one of the buckets
        if "/" in txt and len(txt) < 80:
            return txt
    except Exception:
        return None
    return None

def classify(path: str) -> str:
    name = os.path.basename(path)
    low  = name.lower()
    ext  = os.path.splitext(low)[1]
    # Normalize separators so \b in keyword regex catches "_foo_" patterns too
    norm = re.sub(r"[_\-./]+", " ", os.path.splitext(low)[0]) + " " + ext.lstrip(".")

    if ext in VIDEO_EXT:
        return "Media/Video"
    if ext in MESH_EXT:
        return "Media/3d"
    if ext not in IMG_EXT and ext not in {""}:
        return "Media/Image"  # unknown → generic image bucket

    gender = gender_hint(norm)
    for pat, dest in KEYWORDS:
        if re.search(pat, norm):
            return dest.replace("__GENDER__", gender)

    # Fall back to cc tiny if we still don't know
    guess = cc_tiny_classify(name)
    if guess:
        return guess

    return "Media/Image"

def bgremove(src: str, dst: str) -> int:
    try:
        from rembg import remove
        from PIL import Image
    except Exception as e:
        sys.stderr.write(f"[bgremove] rembg/PIL not installed ({e}); skipped\n")
        return 2
    with open(src, "rb") as f:
        data = f.read()
    out = remove(data)
    with open(dst, "wb") as f:
        f.write(out)
    return 0

def mask(src: str, dst: str) -> int:
    try:
        from rembg import remove
        from PIL import Image
        import io
    except Exception as e:
        sys.stderr.write(f"[mask] rembg/PIL not installed ({e}); skipped\n")
        return 2
    with open(src, "rb") as f:
        data = f.read()
    out = remove(data)
    img = Image.open(io.BytesIO(out)).convert("RGBA")
    alpha = img.split()[-1]
    bw = alpha.point(lambda p: 255 if p > 16 else 0).convert("L")
    bw.save(dst, "PNG")
    return 0

def main(argv):
    if len(argv) < 2:
        print(__doc__); return 1
    cmd = argv[1]
    if cmd == "classify" and len(argv) == 3:
        print(classify(argv[2])); return 0
    if cmd == "bgremove" and len(argv) == 4:
        return bgremove(argv[2], argv[3])
    if cmd == "mask" and len(argv) == 4:
        return mask(argv[2], argv[3])
    print(__doc__); return 1

if __name__ == "__main__":
    sys.exit(main(sys.argv))
