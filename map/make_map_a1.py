#!/usr/bin/env python3
"""Our Sydney Story: A1 landscape, text-free memory map.

841 x 594 mm page, equal 30 mm cream margin, map frame 781 x 534 mm.
Projection: GDA2020 / MGA zone 56 (EPSG:7856), true shape, uniform scale.
No text of any kind is drawn on the artwork. OSM attribution goes on the
separate back-of-canvas label (back_label.pdf).

Data: Geofabrik extract -> osmium -> load_a1_data.py cache.
Usage: python make_map_a1.py [--preview-only]
"""
import argparse, csv, json, math, pickle
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.patches import Circle, Rectangle
from PIL import Image
from pyproj import Transformer
from shapely.geometry import box
from make_map import ocean_polygons, iter_lines, iter_polys, Frame, poly_patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "output" / "a1"
CACHE = "/workspace/osmdata/cache/a1_layers.pkl"
CRS = "EPSG:7856"
MM = 1 / 25.4
PT = 25.4 / 72  # mm per point

CREAM, INK, WATER = "#F6F1E8", "#242424", "#E6DED0"
RIVER = "#BFB4A2"
RED = "#B3261E"
PAGE_W, PAGE_H, MARGIN = 841.0, 594.0, 30.0
FRAME = (MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN)
DOT_MM = 3.5
TAG_MM = 35.0

# Extent (v2, "Just want this area"): Gautam's crop of the v1 preview, matched to
# the v1 layout using 4 dots (fit error < 0.2 mm). Crop in MGA56 metres:
CROP = (226026.6, 6204652.6, 366737.7, 6298366.8)   # aspect 1.501
# v3 (final): EXACTLY Gautam's crop. Keep its full width; the crop is slightly
# wider (1.501) than the frame (1.4625), so add the minimum height, split equally
# top and bottom (+1.2 km each), to fit 781:534 without stretching or cutting
# anything from his crop. Wollongong Central is outside and is not drawn.

# (width pt, alpha, colour) for each road class, drawn minor -> major.
# v2 (1:224k): slightly lighter mid classes for a clearer hierarchy; residential
# a touch more present because it is less dense at this scale.
ROADS = [("minor", 0.10, 0.34), ("tertiary", 0.18, 0.50), ("secondary", 0.28, 0.70),
         ("primary", 0.42, 0.88), ("trunk", 0.62, 1.0), ("motorway", 0.80, 1.0)]

to_m = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)


def extent():
    x0, y0, x1, y1 = CROP
    w = x1 - x0
    h = w * FRAME[3] / FRAME[2]
    yc = (y0 + y1) / 2
    return (x0, yc - h / 2, x1, yc + h / 2)


def load_points():
    d = json.load(open(ROOT / "data" / "locations.json"))
    mem = {m["slug"]: m for m in d["locations"]}
    pts = []
    clustered = set()
    for c in d.get("clusters", []):
        ms = [mem[s] for s in c["members"]]
        X, Y = zip(*[to_m.transform(m["lon"], m["lat"]) for m in ms])
        pts.append({"slug": c["slug"], "name": c["name"], "kind": "cluster",
                    "members": c["members"], "X": float(np.mean(X)), "Y": float(np.mean(Y))})
        clustered |= set(c["members"])
    for m in d["locations"]:
        if m["slug"] in clustered or m.get("on_map") is False:
            continue
        X, Y = to_m.transform(m["lon"], m["lat"])
        pts.append({"slug": m["slug"], "name": m["name"], "kind": "memory", "members": [], "X": X, "Y": Y})
    for p in pts:
        p["lon"], p["lat"] = to_ll.transform(p["X"], p["Y"])
    return pts


def segs_for(geoms, fr, bb):
    return [np.column_stack(fr.to_mm(*ln.xy)) for g in geoms for ln in iter_lines(g.intersection(bb) if not bb.contains(g) else g)]


def render(fr, L, pts, png_path=None, pdf_path=None, dpi=300, show_dots=True):
    if png_path and not pdf_path:  # exact pixel count (e.g. 9933 x 7016 at 300 dpi)
        size = (round(PAGE_W * MM * dpi) / dpi, round(PAGE_H * MM * dpi) / dpi)
    else:
        size = (PAGE_W * MM, PAGE_H * MM)
    fig = plt.figure(figsize=size)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, PAGE_W); ax.set_ylim(PAGE_H, 0); ax.axis("off")
    fig.patch.set_facecolor(CREAM)
    ax.add_patch(Rectangle((0, 0), PAGE_W, PAGE_H, facecolor=CREAM, edgecolor="none", zorder=0))
    clip = Rectangle(FRAME[:2], FRAME[2], FRAME[3], transform=ax.transData)
    bb = box(*fr.ext).buffer(2000)

    def polys(geoms, z, **kw):
        patches = [poly_patch(p, fr) for g in geoms for p in iter_polys(g.intersection(bb))]
        pc = PatchCollection(patches, zorder=z, **kw)
        ax.add_collection(pc); pc.set_clip_path(clip)

    sea = ocean_polygons(L["coast"], fr.ext)
    polys(sea, 2, facecolor=WATER, edgecolor="none")
    water = [g for g in L["water"].geometry if g.intersects(bb)]
    polys(water, 2, facecolor=WATER, edgecolor=RIVER, linewidth=0.12)
    riv = segs_for([g for g in L["rivers"].geometry if g.intersects(bb)], fr, bb)
    lc = LineCollection(riv, colors=RIVER, linewidths=0.35, zorder=3, capstyle="round", joinstyle="round")
    ax.add_collection(lc); lc.set_clip_path(clip)
    co = segs_for(list(L["coast"].geometry), fr, bb)
    lc = LineCollection(co, colors=INK, linewidths=0.32, alpha=0.85, zorder=4, capstyle="round", joinstyle="round")
    ax.add_collection(lc); lc.set_clip_path(clip)
    R = L["roads"]
    for i, (cls, w, a) in enumerate(ROADS):
        sub = R[R["cls"] == cls]
        sub = sub[sub.intersects(bb)]
        lc = LineCollection(segs_for(sub.geometry, fr, bb), colors=INK, linewidths=w, alpha=a,
                            zorder=5 + i * 0.1, capstyle="round", joinstyle="round",
                            rasterized=(cls == "minor"))
        ax.add_collection(lc); lc.set_clip_path(clip)
    ax.add_patch(Rectangle(FRAME[:2], FRAME[2], FRAME[3], facecolor="none", edgecolor=INK, linewidth=0.5, zorder=8))
    if show_dots:
        for p in pts:
            ax.add_patch(Circle((p["x_mm"], p["y_mm"]), DOT_MM / 2, facecolor=RED,
                                edgecolor=CREAM, linewidth=0.35, zorder=10))
    if pdf_path:
        fig.savefig(pdf_path, facecolor=CREAM, dpi=dpi)
    if png_path:
        fig.savefig(png_path, dpi=dpi, facecolor=CREAM)
        im = Image.open(png_path).convert("RGB")
        im.save(png_path, dpi=(dpi, dpi))
    plt.close(fig)


def mirrored_back(pts, path):
    """Back-of-canvas template: positions mirrored left-right, page outline, cross hairs only.
    (This template is for the back, so small guide numbers are OK here, but the artwork stays text-free.)"""
    fig = plt.figure(figsize=(PAGE_W * MM, PAGE_H * MM))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, PAGE_W); ax.set_ylim(PAGE_H, 0); ax.axis("off")
    ax.add_patch(Rectangle((0.5, 0.5), PAGE_W - 1, PAGE_H - 1, fill=False, lw=0.6, ec="k"))
    ax.add_patch(Rectangle((PAGE_W - FRAME[0] - FRAME[2], FRAME[1]), FRAME[2], FRAME[3], fill=False, lw=0.3, ec="0.6", ls="--"))
    for i, p in enumerate(pts, 1):
        x, y = p["back_x_mm"], p["y_mm"]
        ax.add_patch(Circle((x, y), TAG_MM / 2 - 5, fill=False, lw=0.4, ec="0.5"))  # ~25 mm tag outline
        ax.plot([x - 4, x + 4], [y, y], color="k", lw=0.5); ax.plot([x, x], [y - 4, y + 4], color="k", lw=0.5)
        ax.text(x + 2, y - 2, f"{i}", fontsize=7, color="k")
        ax.text(x + 2, y + 4.5, p["slug"], fontsize=4.5, color="0.35")
    ax.text(10, PAGE_H - 8, "BACK OF CANVAS (mirrored). Tag centres = cross hairs. Circles = 25 mm tag. "
            "Not part of the artwork.", fontsize=7)
    fig.savefig(path); plt.close(fig)


def back_label(path):
    w, h = 100, 50
    fig = plt.figure(figsize=(w * MM, h * MM))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, w); ax.set_ylim(h, 0); ax.axis("off")
    ax.add_patch(Rectangle((1, 1), w - 2, h - 2, fill=False, lw=0.5, ec=INK))
    lines = [("Our Sydney Story", 11, "bold"),
             ("Map data © OpenStreetMap contributors", 7.5, "normal"),
             ("Available under the Open Database Licence (ODbL)", 6.5, "normal"),
             ("openstreetmap.org/copyright", 6.5, "normal"),
             ("Projection: GDA2020 / MGA zone 56", 5.5, "normal")]
    y = 11
    for t, s, wgt in lines:
        ax.text(w / 2, y, t, ha="center", va="center", fontsize=s, fontweight=wgt, color=INK, family="serif")
        y += 8.5 if s > 8 else 7
    fig.savefig(path); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview-only", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ext = extent()
    fr = Frame(FRAME, ext)
    pts = load_points()
    for p in pts:
        x, y = fr.to_mm(p["X"], p["Y"])
        p["x_mm"], p["y_mm"] = float(x), float(y)
        p["back_x_mm"] = PAGE_W - p["x_mm"]
        assert fr.contains_mm(p["x_mm"], p["y_mm"], inset=3), p["slug"]
    pts.sort(key=lambda p: (round(p["y_mm"]), p["x_mm"]))
    L = pickle.load(open(CACHE, "rb"))
    print("extent m", [round(v) for v in ext], "m/mm", round(fr.mpm, 1), "scale 1:", round(fr.mpm * 1000))
    ll = [to_ll.transform(ext[0], ext[1]), to_ll.transform(ext[2], ext[3])]
    print("extent lonlat SW", ll[0], "NE", ll[1])
    render(fr, L, pts, png_path=OUT / "preview_150dpi.png", dpi=150)
    im = Image.open(OUT / "preview_150dpi.png"); im.thumbnail((2000, 2000))
    im.save(OUT / "our-sydney-story-A1-preview.png"); (OUT / "preview_150dpi.png").unlink()
    if a.preview_only:
        return
    render(fr, L, pts, png_path=OUT / "our-sydney-story-A1-300dpi.png", dpi=300)
    render(fr, L, pts, pdf_path=OUT / "our-sydney-story-A1-print.pdf", dpi=300)
    render(fr, L, pts, png_path=OUT / "our-sydney-story-A1-no-dots-preview.png", dpi=72, show_dots=False)
    # Tag back templates now come from make_tag_templates.py (run it after this script).
    # mirrored_back(pts, OUT / "our-sydney-story-A1-back-template.pdf")
    back_label(OUT / "back-of-canvas-label.pdf")
    with open(OUT / "marker-positions-A1.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["n", "slug", "name", "kind", "members", "lat", "lon", "front_x_mm", "front_y_mm",
                     "back_x_mm", "back_y_mm", "nfc_url_path"])
        for i, p in enumerate(pts, 1):
            path = f"memories/{p['slug']}.html"
            wr.writerow([i, p["slug"], p["name"], p["kind"], ";".join(p["members"]), f"{p['lat']:.6f}", f"{p['lon']:.6f}",
                         f"{p['x_mm']:.1f}", f"{p['y_mm']:.1f}", f"{p['back_x_mm']:.1f}", f"{p['y_mm']:.1f}", path])
    # spacing report
    import itertools
    rows = []
    for p, q in itertools.combinations(pts, 2):
        d = math.hypot(p["x_mm"] - q["x_mm"], p["y_mm"] - q["y_mm"])
        if d < TAG_MM:
            rows.append((d, p["slug"], q["slug"]))
    rows.sort()
    json.dump({"extent_mga56": ext, "extent_lonlat": ll, "m_per_mm": fr.mpm, "scale": fr.mpm * 1000,
               "points": pts, "pairs_under_35mm": rows}, open(OUT / "layout.json", "w"), indent=1, default=float)
    print(len(pts), "dots;", len(rows), "pairs under 35 mm")


if __name__ == "__main__":
    main()
