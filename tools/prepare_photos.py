#!/usr/bin/env python3
"""
Resize photos for the web and strip ALL metadata (EXIF, GPS location, camera serials).
Optional helper; needs Pillow:  python3 -m pip install pillow

  (iPhone HEIC photos: export/convert to JPG first, see GUIDE.md)
  python3 tools/prepare_photos.py originals/bondi.jpg --slug bondi-beach

Writes docs/media/photos/<slug>.jpg (1600 px long edge) and <slug>-800.jpg (800 px),
then prints the JSON fields to paste into data/locations.json.
"""
import argparse, json, sys
from pathlib import Path
try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("Pillow is not installed. Run: python3 -m pip install pillow  (or use Squoosh/ImageOptim, see GUIDE.md)")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "media" / "photos"


def save(im, path, long_edge, quality):
    im = im.copy()
    im.thumbnail((long_edge, long_edge), Image.LANCZOS)
    # Re-encode from raw pixels with no exif/icc/xmp => metadata (incl. GPS) is gone
    clean = Image.new("RGB", im.size); clean.paste(im)
    clean.save(path, "JPEG", quality=quality, optimize=True, progressive=True)
    return clean.size, path.stat().st_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo"); ap.add_argument("--slug", required=True)
    ap.add_argument("--quality", type=int, default=80)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    im = ImageOps.exif_transpose(Image.open(a.photo)).convert("RGB")  # honour phone rotation first
    (w, h), size = save(im, OUT / f"{a.slug}.jpg", 1600, a.quality)
    (_, _), size_s = save(im, OUT / f"{a.slug}-800.jpg", 800, a.quality)
    print(f"docs/media/photos/{a.slug}.jpg  {w}x{h}  {size/1024:.0f} KB")
    print(f"docs/media/photos/{a.slug}-800.jpg  {size_s/1024:.0f} KB")
    if size > 450 * 1024:
        print("  tip: over ~400 KB; try --quality 72")
    print(json.dumps({"photo": f"media/photos/{a.slug}.jpg", "photo_small": f"media/photos/{a.slug}-800.jpg",
                      "photo_width": w, "photo_height": h}, indent=2)[1:-1])


if __name__ == "__main__":
    main()
