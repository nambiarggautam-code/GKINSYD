#!/usr/bin/env python3
"""
make_map.py: geographically accurate, print-ready "Our Sydney Story" poster
from OpenStreetMap data, driven by ../data/locations.json (same file as the website).

Output (map/output/):
  our-sydney-story-map.pdf      vector PDF, 600 x 800 mm (+ bleed if requested)
  our-sydney-story-map.png      300 dpi raster (7087 x 9449 px with no bleed)
  tag-template-back.pdf         1:1 MIRRORED back-side template with 25 mm tag circles
  marker-positions.csv          every marker in mm from the top-left of the FRONT face,
                                plus the mirrored position for the BACK
  map-report.txt                extent, real-world scale, spacing warnings

Data sources (choose one):
  default         Overpass API via osmnx (needs internet; public servers can be busy)
  --pbf FILE      a local OSM extract (.osm.pbf), e.g. BBBike "Sydney" or Geofabrik
                  "australia" cut down with:  osmium extract -b 150.2,-34.1,151.4,-33.6 in.pbf -o sydney.osm.pbf

Map data © OpenStreetMap contributors, available under the Open Database Licence (ODbL).
The attribution line printed on the poster is REQUIRED. Do not remove it.

Usage:
  python make_map.py                         # Overpass
  python make_map.py --pbf ~/osm/sydney.osm.pbf
  python make_map.py --pbf sydney.osm.pbf --bleed-mm 40 --min-sep-mm 11
Run `python make_map.py -h` for every option.
"""
import argparse, csv, json, math, sys, warnings
from pathlib import Path

import numpy as np
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.patches import Rectangle, Circle, PathPatch
from matplotlib.path import Path as MPath
from pyproj import Transformer
from shapely.geometry import box, LineString, MultiLineString, Polygon, MultiPolygon, Point
from shapely.ops import polygonize, unary_union, linemerge

warnings.filterwarnings("ignore", category=UserWarning)
import logging
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data" / "locations.json"
OUTDIR = HERE / "output"

# Palette (matches the website)
CREAM, INK, BURGUNDY = "#F6F1E8", "#242424", "#783D46"
WATER, PARK, INK_SOFT = "#E6DED0", "#EFE9DC", "#4A4744"

# Canvas (mm). Portrait 60 x 80 cm.
W_MM, H_MM = 600.0, 800.0
MM = 1 / 25.4  # inches per mm
CRS = "EPSG:7856"  # GDA2020 / MGA zone 56: metres, true-shape for Sydney + Blue Mountains

# Road styling: (min metres-per-mm at which the class is dropped, base width in pt)
ROADS = {
    "motorway": (999, 1.7), "motorway_link": (60, 0.8), "trunk": (999, 1.45), "trunk_link": (60, 0.7),
    "primary": (999, 1.15), "primary_link": (45, 0.6), "secondary": (120, 0.85), "secondary_link": (45, 0.5),
    "tertiary": (70, 0.62), "tertiary_link": (35, 0.4), "residential": (38, 0.36), "unclassified": (38, 0.36),
    "living_street": (25, 0.3), "pedestrian": (25, 0.3), "service": (8, 0.18),
}
RAIL_W = 0.5


# ----------------------------------------------------------------------------- fonts
def load_fonts():
    fonts = {}
    for key, pattern, fallback in (("serif", "CormorantGaramond[[]wght[]].ttf", "DejaVu Serif"),
                                   ("serif_it", "CormorantGaramond-Italic*.ttf", "DejaVu Serif"),
                                   ("sans", "Inter*.ttf", "DejaVu Sans")):
        found = sorted((HERE / "fonts").glob(pattern))
        if found:
            font_manager.fontManager.addfont(str(found[0]))
            fonts[key] = font_manager.FontProperties(fname=str(found[0])).get_name()
        else:
            print(f"  note: font for {key} not found in map/fonts/, falling back to {fallback}")
            fonts[key] = fallback
    return fonts


# ----------------------------------------------------------------------------- data
def load_points(args):
    d = json.loads(Path(args.data).read_text(encoding="utf-8"))
    pts = []
    for l in sorted(d["locations"], key=lambda l: l["number"]):
        pts.append(dict(number=int(l["number"]), slug=l["slug"], name=l.get("short_name") or l["name"],
                        lat=float(l["lat"]), lon=float(l["lon"]), group=l.get("map_group", "auto")))
    to_m = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    for p in pts:
        p["X"], p["Y"] = to_m.transform(p["lon"], p["lat"])
    return d["site"], pts


def assign_groups(pts, far_km):
    """main map vs. 'far' inset (e.g. Blue Mountains). Override per point in locations.json with
    "map_group": "main" | "inset" (far-away inset) | "zoom" (enlarged city-detail inset for crowded CBD points)."""
    xs = np.array([p["X"] for p in pts]); ys = np.array([p["Y"] for p in pts])
    cx, cy = np.median(xs), np.median(ys)
    for p in pts:
        if p["group"] in ("main", "inset", "zoom"):
            continue
        p["group"] = "inset" if math.hypot(p["X"] - cx, p["Y"] - cy) > far_km * 1000 else "main"
    if not any(p["group"] == "main" for p in pts):
        for p in pts:
            p["group"] = "main"


def fit_extent(pts, frame_w, frame_h, pad_frac, min_width_m):
    xs = [p["X"] for p in pts]; ys = [p["Y"] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = max(x1 - x0, 1), max(y1 - y0, 1)
    pad = max(w, h) * pad_frac
    x0 -= pad; x1 += pad; y0 -= pad; y1 += pad
    w, h = x1 - x0, y1 - y0
    w = max(w, min_width_m)
    aspect = frame_w / frame_h
    if w / h > aspect:
        h = w / aspect
    else:
        w = h * aspect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def extent_lonlat(ext, margin=0.03):
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    x0, y0, x1, y1 = ext
    lons, lats = zip(*[to_ll.transform(x, y) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))])
    dl = (max(lons) - min(lons)) * margin; dt = (max(lats) - min(lats)) * margin
    return min(lons) - dl, min(lats) - dt, max(lons) + dl, max(lats) + dt  # W S E N


# ---- loaders return dict of GeoDataFrames in EPSG:4326: roads(highway), rail, coast, water, parks
def fetch_overpass(bbox_wsen, args):
    import osmnx as ox
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(HERE / "cache")
    ox.settings.requests_timeout = 600
    if args.overpass_url:
        ox.settings.overpass_url = args.overpass_url
    out = {}

    def get(tags):
        try:
            return ox.features_from_bbox(bbox=bbox_wsen, tags=tags)
        except Exception as e:  # osmnx raises InsufficientResponseError when nothing matches
            if "InsufficientResponse" in type(e).__name__ or "No matching features" in str(e):
                return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
            raise
    hw = get({"highway": list(ROADS)})
    out["roads"] = hw[hw.geometry.type.isin(["LineString", "MultiLineString"])][["highway", "geometry"]] if len(hw) else hw
    rl = get({"railway": ["rail"]})
    out["rail"] = rl[rl.geometry.type.isin(["LineString", "MultiLineString"])] if len(rl) else rl
    co = get({"natural": "coastline"})
    out["coast"] = co[co.geometry.type == "LineString"] if len(co) else co
    wa = get({"natural": "water", "waterway": "riverbank", "landuse": "reservoir"})
    out["water"] = wa[wa.geometry.type.isin(["Polygon", "MultiPolygon"])] if len(wa) else wa
    pk = get({"leisure": ["park", "garden"]}) if args.parks else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    out["parks"] = pk[pk.geometry.type.isin(["Polygon", "MultiPolygon"])] if len(pk) else pk
    return out


_PBF_CACHE = {}


def fetch_pbf(bbox_wsen, args):
    """Read a local .osm.pbf once (pyosmium), then clip to the requested bbox."""
    import osmium
    from shapely import wkb
    if args.pbf not in _PBF_CACHE:
        print(f"  reading {args.pbf} (one-off, may take a few minutes for a big file)…")
        wkbf = osmium.geom.WKBFactory()
        rows = {k: [] for k in ("roads", "rail", "coast", "water", "parks")}
        fp = (osmium.FileProcessor(args.pbf).with_locations().with_areas()
              .with_filter(osmium.filter.KeyFilter("highway", "railway", "natural", "waterway", "landuse", "leisure", "water")))
        for o in fp:
            try:
                t = o.tags
                if o.is_area():
                    if t.get("natural") == "water" or t.get("waterway") == "riverbank" or t.get("landuse") == "reservoir":
                        rows["water"].append({"geometry": wkb.loads(wkbf.create_multipolygon(o), hex=True)})
                    elif args.parks and t.get("leisure") in ("park", "garden"):
                        rows["parks"].append({"geometry": wkb.loads(wkbf.create_multipolygon(o), hex=True)})
                elif o.is_way():
                    hw = t.get("highway")
                    if hw in ROADS:
                        rows["roads"].append({"highway": hw, "geometry": wkb.loads(wkbf.create_linestring(o), hex=True)})
                    elif t.get("railway") == "rail" and t.get("service") is None:
                        rows["rail"].append({"geometry": wkb.loads(wkbf.create_linestring(o), hex=True)})
                    elif t.get("natural") == "coastline":
                        rows["coast"].append({"geometry": wkb.loads(wkbf.create_linestring(o), hex=True)})
            except Exception:
                continue  # broken geometry at the extract edge
        _PBF_CACHE[args.pbf] = {k: gpd.GeoDataFrame(v if v else None, geometry=[r["geometry"] for r in v] if v else [],
                                                     crs="EPSG:4326") for k, v in rows.items()}
        for k, g in _PBF_CACHE[args.pbf].items():
            print(f"    {k}: {len(g)} features")
    clip = box(*bbox_wsen)
    out = {}
    for k, g in _PBF_CACHE[args.pbf].items():
        if len(g):
            g = g[g.intersects(clip)]
        out[k] = g
    return out


# ----------------------------------------------------------------------------- geometry
def ocean_polygons(coast_m, ext):
    """Turn coastline lines (land on the LEFT, OSM convention) into sea polygons inside ext."""
    bb = box(*ext)
    lines = [g for g in coast_m.geometry if g is not None and not g.is_empty]
    if not lines:
        return []
    merged = linemerge(unary_union(lines))
    clipped = merged.intersection(bb)
    faces = list(polygonize(unary_union([bb.boundary, clipped])))
    oriented = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    sea = []
    for f in faces:
        rp = f.representative_point()
        line = min(oriented, key=lambda ln: ln.distance(rp))
        s = line.project(line.interpolate(line.project(rp)))
        a = line.interpolate(max(s - 1.0, 0)); b = line.interpolate(min(s + 1.0, line.length))
        near = line.interpolate(s)
        cross = (b.x - a.x) * (rp.y - near.y) - (b.y - a.y) * (rp.x - near.x)
        if cross < 0:  # right of the coastline = water
            sea.append(f)
    return sea


def iter_lines(geom):
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, LineString):
        yield geom
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from iter_lines(g)


def iter_polys(geom):
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from iter_polys(g)


class Frame:
    """A rectangle on the page (mm, y down) showing a projected extent (metres)."""

    def __init__(self, rect_mm, ext):
        self.x, self.y, self.w, self.h = rect_mm
        self.ext = ext
        self.mpm = (ext[2] - ext[0]) / self.w  # metres per mm

    def to_mm(self, X, Y):
        return self.x + (np.asarray(X) - self.ext[0]) / self.mpm, self.y + (self.ext[3] - np.asarray(Y)) / self.mpm

    def contains_mm(self, x, y, inset=0):
        return self.x + inset <= x <= self.x + self.w - inset and self.y + inset <= y <= self.y + self.h - inset


def poly_patch(poly, fr, **kw):
    verts, codes = [], []
    for ring in [poly.exterior, *poly.interiors]:
        xs, ys = fr.to_mm(*ring.xy)
        pts = list(zip(xs, ys))
        verts += pts + [pts[0]]
        codes += [MPath.MOVETO] + [MPath.LINETO] * (len(pts) - 1) + [MPath.CLOSEPOLY]
    return PathPatch(MPath(verts, codes), **kw)


def draw_frame(ax, fr, layers, args, label_scale=True):
    clip = Rectangle((fr.x, fr.y), fr.w, fr.h, transform=ax.transData)
    ext = fr.ext
    bb = box(*ext).buffer((ext[2] - ext[0]) * 0.01)
    L = {k: (v.to_crs(CRS) if len(v) else v) for k, v in layers.items()}
    ax.add_patch(Rectangle((fr.x, fr.y), fr.w, fr.h, facecolor=CREAM, edgecolor="none", zorder=1))
    width_k = float(np.clip((22 / fr.mpm) ** 0.45, 0.55, 1.25)) * args.line_scale

    def add_polys(gdf_or_list, color, z):
        geoms = gdf_or_list if isinstance(gdf_or_list, list) else list(gdf_or_list.geometry)
        patches = [poly_patch(p, fr) for g in geoms for p in iter_polys(g.intersection(bb) if g is not None else None)]
        if patches:
            pc = PatchCollection(patches, facecolor=color, edgecolor="none", zorder=z)
            ax.add_collection(pc); pc.set_clip_path(clip)  # clip AFTER adding, or matplotlib resets it

    if len(L.get("parks", [])):
        add_polys(L["parks"], PARK, 2)
    sea = ocean_polygons(L["coast"], ext) if len(L.get("coast", [])) else []
    add_polys(sea, WATER, 3)
    if len(L.get("water", [])):
        add_polys(L["water"], WATER, 3)
    # coastline outline
    if len(L.get("coast", [])):
        segs = [np.column_stack(fr.to_mm(*ln.xy)) for g in L["coast"].geometry for ln in iter_lines(g.intersection(bb))]
        lc = LineCollection(segs, colors=INK, linewidths=0.45 * width_k, zorder=4, capstyle="round")
        ax.add_collection(lc); lc.set_clip_path(clip)
    # rail
    if len(L.get("rail", [])) and fr.mpm < 150:
        segs = [np.column_stack(fr.to_mm(*ln.xy)) for g in L["rail"].geometry for ln in iter_lines(g.intersection(bb))]
        lc = LineCollection(segs, colors=INK, linewidths=RAIL_W * width_k * 0.6, linestyles=(0, (3, 2)), zorder=5, alpha=.55)
        ax.add_collection(lc); lc.set_clip_path(clip)
    # roads, minor first so major roads sit on top
    if len(L.get("roads", [])):
        order = sorted(ROADS, key=lambda k: ROADS[k][1])
        for z, cls in enumerate(order):
            drop_at, base_w = ROADS[cls]
            if fr.mpm > drop_at:
                continue
            sub = L["roads"][L["roads"]["highway"] == cls]
            if not len(sub):
                continue
            segs = [np.column_stack(fr.to_mm(*ln.xy)) for g in sub.geometry for ln in iter_lines(g.intersection(bb))]
            lc = LineCollection(segs, colors=INK, linewidths=base_w * width_k, zorder=6 + z * 0.01,
                                capstyle="round", joinstyle="round")
            ax.add_collection(lc); lc.set_clip_path(clip)
    ax.add_patch(Rectangle((fr.x, fr.y), fr.w, fr.h, facecolor="none", edgecolor=INK, linewidth=0.6, zorder=20))


def nice_scale_len(mpm, target_mm=40):
    raw = mpm * target_mm
    for v in [100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000]:
        if v >= raw * 0.6:
            return v
    return 50000


def draw_scalebar(ax, fr, fonts, x, y):
    L = nice_scale_len(fr.mpm)
    lmm = L / fr.mpm
    ax.plot([x, x + lmm], [y, y], color=INK, lw=0.8, zorder=30, solid_capstyle="butt")
    for xx in (x, x + lmm):
        ax.plot([xx, xx], [y - 1.2, y + 1.2], color=INK, lw=0.6, zorder=30)
    lab = f"{L/1000:g} km" if L >= 1000 else f"{L} m"
    ax.text(x + lmm / 2, y - 2.5, lab, ha="center", va="bottom", fontsize=7, family=fonts["sans"], color=INK_SOFT, zorder=30)


# ----------------------------------------------------------------------------- markers
def place_markers(markers, min_sep, frames):
    """Repel overlapping dots; each dot keeps a leader line back to its true position."""
    for m in markers:
        m["mx"], m["my"] = m["tx"], m["ty"]
    for _ in range(400):
        moved = False
        for i, a in enumerate(markers):
            for b in markers[i + 1:]:
                if a["frame"] is not b["frame"]:
                    continue
                dx, dy = b["mx"] - a["mx"], b["my"] - a["my"]
                d = math.hypot(dx, dy)
                if d < min_sep:
                    if d < 1e-6:
                        dx, dy, d = 1.0, 0.3, 1.04
                    push = (min_sep - d) / 2 + 0.05
                    ux, uy = dx / d, dy / d
                    a["mx"] -= ux * push; a["my"] -= uy * push
                    b["mx"] += ux * push; b["my"] += uy * push
                    moved = True
        for m in markers:  # keep dots inside their frame
            f = m["frame"]; r = min_sep / 2
            m["mx"] = min(max(m["mx"], f.x + r), f.x + f.w - r)
            m["my"] = min(max(m["my"], f.y + r), f.y + f.h - r)
        if not moved:
            break


def draw_markers(ax, markers, fonts, dot_mm):
    for m in markers:
        moved = math.hypot(m["mx"] - m["tx"], m["my"] - m["ty"]) > 0.8
        if moved:
            ax.plot([m["tx"], m["mx"]], [m["ty"], m["my"]], color=BURGUNDY, lw=0.5, zorder=39)
            ax.add_patch(Circle((m["tx"], m["ty"]), 0.9, color=BURGUNDY, zorder=40, lw=0))
        ax.add_patch(Circle((m["mx"], m["my"]), dot_mm / 2, facecolor=BURGUNDY, edgecolor=CREAM, lw=0.8, zorder=41))
        ax.text(m["mx"], m["my"] + 0.15, str(m["number"]), ha="center", va="center", fontsize=dot_mm * 1.25,
                family=fonts["sans"], color=CREAM, zorder=42, fontweight="medium")


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--pbf", help="local .osm.pbf extract instead of Overpass")
    ap.add_argument("--overpass-url", help="alternative Overpass endpoint")
    ap.add_argument("--bbox", help="force main extent W,S,E,N (decimal degrees)")
    ap.add_argument("--pad", type=float, default=0.18, help="padding around points, fraction of extent")
    ap.add_argument("--min-width-km", type=float, default=9.0, help="minimum main-map width")
    ap.add_argument("--far-km", type=float, default=30.0, help="points further than this from the median go to an inset")
    ap.add_argument("--dot-mm", type=float, default=8.0, help="marker dot diameter")
    ap.add_argument("--min-sep-mm", type=float, default=10.0, help="minimum distance between dots on the FRONT")
    ap.add_argument("--tag-mm", type=float, default=25.0, help="NFC sticker diameter (for the back template)")
    ap.add_argument("--tag-gap-mm", type=float, default=35.0, help="recommended centre-to-centre tag spacing")
    ap.add_argument("--bleed-mm", type=float, default=0.0, help="extra artwork on every side (canvas wrap / bleed)")
    ap.add_argument("--line-scale", type=float, default=1.0, help="multiply all road widths")
    ap.add_argument("--no-parks", dest="parks", action="store_false")
    ap.add_argument("--width-mm", type=float, default=600.0, help="finished face width (e.g. 610 for a 61 x 81 cm canvas)")
    ap.add_argument("--height-mm", type=float, default=800.0, help="finished face height")
    ap.add_argument("--no-proof", dest="proof", action="store_false", help="skip the A1 1:1 paper proof PDF")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--out", default=str(OUTDIR))
    args = ap.parse_args()
    global W_MM, H_MM
    W_MM, H_MM = args.width_mm, args.height_mm

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    fonts = load_fonts()
    site, pts = load_points(args)
    assign_groups(pts, args.far_km)
    main_pts = [p for p in pts if p["group"] == "main"]
    far_pts = [p for p in pts if p["group"] == "inset"]
    fetch = (lambda bb: fetch_pbf(bb, args)) if args.pbf else (lambda bb: fetch_overpass(bb, args))

    # Page layout (mm from top-left of the finished face)
    MAP = (40.0, 112.0, W_MM - 80.0, H_MM - 252.0)  # x, y, w, h (520 x 548 mm on a 600 x 800 canvas)
    if args.bbox:
        w, s, e, n = map(float, args.bbox.split(","))
        to_m = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
        corners = [dict(X=a, Y=b) for a, b in [to_m.transform(w, s), to_m.transform(e, n)]]
        ext = fit_extent(corners, MAP[2], MAP[3], 0.0, 0)
    else:
        ext = fit_extent(main_pts + [p for p in pts if p["group"] == "zoom"], MAP[2], MAP[3], args.pad, args.min_width_km * 1000)
    main_fr = Frame(MAP, ext)

    # Insets: "inset" = far away (e.g. Blue Mountains), "zoom" = enlarged detail of crowded points (e.g. CBD).
    zoom_pts = [p for p in pts if p["group"] == "zoom"]
    insets, used = [], set()
    size = 150.0
    corners = {"bottom-left": (MAP[0] + 8, MAP[1] + MAP[3] - size - 8), "top-left": (MAP[0] + 8, MAP[1] + 8),
               "bottom-right": (MAP[0] + MAP[2] - size - 8, MAP[1] + MAP[3] - size - 8),
               "top-right": (MAP[0] + MAP[2] - size - 8, MAP[1] + 8)}

    def covered(c):
        x, y = c
        n = 0
        for p in main_pts + zoom_pts:  # zoom points weigh more: their dashed box must stay visible
            px, py = main_fr.to_mm(p["X"], p["Y"])
            n += (x - 6 <= px <= x + size + 6 and y - 6 <= py <= y + size + 6) * (3 if p in zoom_pts else 1)
        return n
    for kind, group_pts, min_w in (("far", far_pts, 7000), ("zoom", zoom_pts, 1200)):
        if not group_pts:
            continue
        free = {k: v for k, v in corners.items() if k not in used}
        name, (ix, iy) = min(free.items(), key=lambda kv: covered(kv[1]))
        used.add(name)
        iext = fit_extent(group_pts, size, size, 0.35, min_w)
        insets.append(dict(fr=Frame((ix, iy, size, size), iext), pts=group_pts, corner=name, kind=kind))

    print("Fetching OpenStreetMap data…")
    try:
        main_layers = fetch(extent_lonlat(ext))
        inset_layers = [fetch(extent_lonlat(i["fr"].ext)) for i in insets]
    except Exception as e:
        print(f"\nCould not download map data: {type(e).__name__}: {str(e)[:300]}")
        if not args.pbf:
            print("Public Overpass servers are often busy. Options:\n"
                  "  1. wait a few minutes and run again (results are cached in map/cache/)\n"
                  "  2. try another server: --overpass-url https://overpass.private.coffee/api/interpreter\n"
                  "  3. most reliable: download an extract and use --pbf (see GUIDE.md, 'Map data offline')")
        sys.exit(2)

    render(args, fonts, site, pts, main_fr, main_layers, insets, inset_layers, out)


def render(args, fonts, site, pts, main_fr, main_layers, insets, inset_layers, out):
    b = args.bleed_mm
    px_w, px_h = round((W_MM + 2 * b) * MM * args.dpi), round((H_MM + 2 * b) * MM * args.dpi)
    fig = plt.figure(figsize=(px_w / args.dpi, px_h / args.dpi), facecolor=CREAM)  # exact pixel size, e.g. 7087 x 9449
    page = fig.add_axes([0, 0, 1, 1]); page.set_xlim(-b, W_MM + b); page.set_ylim(H_MM + b, -b); page.axis("off")
    draw_frame(page, main_fr, main_layers, args)

    # Inset axes, each a separate axes in the same mm coordinate system, stacked above the page
    inset_axes = []
    for ins, lay in zip(insets, inset_layers):
        iax = fig.add_axes([0, 0, 1, 1], zorder=5); iax.set_xlim(-b, W_MM + b); iax.set_ylim(H_MM + b, -b)
        iax.axis("off"); iax.patch.set_alpha(0)
        f = ins["fr"]
        iax.add_patch(Rectangle((f.x - 2.5, f.y - 2.5), f.w + 5, f.h + 5, facecolor=CREAM, edgecolor="none", zorder=0.5))
        draw_frame(iax, f, lay, args)
        far_p = ins["pts"]
        cx = np.mean([p["X"] for p in far_p]); cy = np.mean([p["Y"] for p in far_p])
        mx = (main_fr.ext[0] + main_fr.ext[2]) / 2; my = (main_fr.ext[1] + main_fr.ext[3]) / 2
        dist = math.hypot(cx - mx, cy - my) / 1000
        brg = (math.degrees(math.atan2(cx - mx, cy - my)) + 360) % 360
        compass = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][int((brg + 22.5) // 45) % 8]
        if ins["kind"] == "zoom":
            label = "City detail (enlarged)"
            x0, y0 = main_fr.to_mm(f.ext[0], f.ext[3]); x1, y1 = main_fr.to_mm(f.ext[2], f.ext[1])
            zb = page.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec=BURGUNDY, lw=0.6, ls=(0, (2, 1.5)), zorder=35))
            zb.set_clip_path(Rectangle((main_fr.x, main_fr.y), main_fr.w, main_fr.h, transform=page.transData))
        else:
            label = f"{far_p[0]['name'] if len(far_p) == 1 else 'Further afield'} · about {dist:.0f} km {compass} of the city"
        ins["label"] = label
        iax.text(f.x + 5, f.y + 5, label, ha="left", va="top", fontsize=8.5, family=fonts["serif_it"], color=INK, zorder=30,
                 bbox=dict(facecolor=CREAM, edgecolor="none", pad=2.5))
        draw_scalebar(iax, f, fonts, f.x + 6, f.y + f.h - 6)
        inset_axes.append(iax)

    # Markers
    markers = []
    for p in pts:
        if p["group"] == "main":
            fr, axm = main_fr, page
        else:
            k = next(i for i, ins in enumerate(insets) if p in ins["pts"])
            fr, axm = insets[k]["fr"], inset_axes[k]
        tx, ty = fr.to_mm(p["X"], p["Y"])
        markers.append(dict(p, tx=float(tx), ty=float(ty), frame=fr, ax=axm))
    place_markers(markers, args.min_sep_mm, None)
    for axm in {id(m["ax"]): m["ax"] for m in markers}.values():
        draw_markers(axm, [m for m in markers if m["ax"] is axm], fonts, args.dot_mm)
    # markers on the main map hidden under an inset?
    hidden = [m for m in markers if m["frame"] is main_fr and any(i["fr"].contains_mm(m["mx"], m["my"], -4) for i in insets)]

    # Typography
    page.text(W_MM / 2, 62, site.get("title", "Our Sydney Story").upper(), ha="center", va="baseline", fontsize=64,
              family=fonts["serif"], color=INK, zorder=50)
    page.text(W_MM / 2, 84, site.get("subtitle", ""), ha="center", va="baseline", fontsize=22,
              family=fonts["serif_it"], color=INK_SOFT, zorder=50)
    page.plot([W_MM / 2 - 15, W_MM / 2 + 15], [96, 96], color=INK, lw=0.5, alpha=.6)
    draw_scalebar(page, main_fr, fonts, main_fr.x + 10, main_fr.y + main_fr.h - 8)
    # north mark
    nx, ny = main_fr.x + main_fr.w - 12, main_fr.y + 16
    page.annotate("", xy=(nx, ny - 7), xytext=(nx, ny + 3), arrowprops=dict(arrowstyle="-|>", color=INK, lw=0.6), zorder=30)
    page.text(nx, ny - 9, "N", ha="center", va="bottom", fontsize=8, family=fonts["sans"], color=INK, zorder=30)

    # Legend: numbered entries in up to 3 columns
    leg_y0, cols = main_fr.y + main_fr.h + 18, 3 if len(pts) > 8 else 2
    rows = math.ceil(len(pts) / cols)
    col_w = main_fr.w / cols
    row_h = min(8.5, 52 / max(rows, 1))
    for i, p in enumerate(pts):
        c, r = divmod(i, rows)
        x = main_fr.x + c * col_w; y = leg_y0 + r * row_h
        page.add_patch(Circle((x + 3, y), 2.6, color=BURGUNDY, lw=0))
        page.text(x + 3, y + 0.1, str(p["number"]), ha="center", va="center", fontsize=6.5, family=fonts["sans"], color=CREAM)
        page.text(x + 9, y, p["name"], ha="left", va="center", fontsize=10.5, family=fonts["serif"], color=INK)
    page.text(W_MM / 2, H_MM - 32, site.get("footer", ""), ha="center", va="baseline", fontsize=20,
              family=fonts["serif_it"], color=INK_SOFT)
    scale_n = round(main_fr.mpm * 1000, -2)
    page.text(main_fr.x + main_fr.w, H_MM - 14, f"Map data © OpenStreetMap contributors (ODbL) · openstreetmap.org/copyright · Scale ≈ 1:{scale_n:,.0f} at {W_MM/10:g} × {H_MM/10:g} cm",
              ha="right", va="baseline", fontsize=6.5, family=fonts["sans"], color=INK_SOFT)

    base = out / "our-sydney-story-map"
    print("Rendering PDF…"); fig.savefig(f"{base}.pdf", facecolor=CREAM)
    print("Rendering PNG…"); fig.savefig(f"{base}.png", dpi=args.dpi, facecolor=CREAM)
    try:  # flatten to RGB (printers dislike alpha) and stamp the dpi
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        im = Image.open(f"{base}.png").convert("RGB"); im.save(f"{base}.png", dpi=(args.dpi, args.dpi), optimize=True)
        print(f"  PNG {im.size[0]} x {im.size[1]} px RGB at {args.dpi} dpi")
    except ImportError:
        pass
    plt.close(fig)

    write_csv_and_report(args, pts, markers, main_fr, insets, hidden, out, scale_n)
    tag_template(args, markers, fonts, out)
    if args.proof:
        a1_proof(args, f"{base}.png", out)
    print(f"Done. Files in {out}")


def write_csv_and_report(args, pts, markers, main_fr, insets, hidden, out, scale_n):
    rows, warnings_ = [], []
    for m in markers:
        others = [o for o in markers if o is not m]
        nn = min((math.hypot(o["mx"] - m["mx"], o["my"] - m["my"]) for o in others), default=float("inf"))
        rows.append(dict(number=m["number"], slug=m["slug"], name=m["name"], lat=m["lat"], lon=m["lon"],
                         where="main map" if m["frame"] is main_fr else "inset",
                         true_x_mm=round(m["tx"], 1), true_y_mm=round(m["ty"], 1),
                         marker_x_mm=round(m["mx"], 1), marker_y_mm=round(m["my"], 1),
                         back_x_mm=round(W_MM - m["mx"], 1), back_y_mm=round(m["my"], 1),
                         nearest_marker_mm=round(nn, 1) if nn != float("inf") else "",
                         tag_spacing_ok="yes" if nn >= args.tag_gap_mm else f"NO (<{args.tag_gap_mm:.0f} mm)"))
        if nn < args.tag_gap_mm:
            warnings_.append(f"#{m['number']} {m['name']}: nearest marker {nn:.0f} mm away (< {args.tag_gap_mm:.0f} mm). "
                             "Tags this close can be read together. Use a cluster tag, a CBD inset, or nudge the marker.")
    with open(out / "marker-positions.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    ext = main_fr.ext
    rep = [
        "OUR SYDNEY STORY: map report",
        f"Canvas: {W_MM:.0f} x {H_MM:.0f} mm portrait, bleed {args.bleed_mm:.0f} mm each side",
        f"Raster: {round((W_MM + 2*args.bleed_mm)/25.4*args.dpi)} x {round((H_MM + 2*args.bleed_mm)/25.4*args.dpi)} px at {args.dpi} dpi",
        f"Projection: {CRS} (GDA2020 / MGA zone 56)",
        f"Main map frame: x={main_fr.x} y={main_fr.y} w={main_fr.w} h={main_fr.h} mm",
        f"Main map covers {(ext[2]-ext[0])/1000:.2f} km x {(ext[3]-ext[1])/1000:.2f} km on the ground",
        f"Real-world scale: 1 mm on canvas = {main_fr.mpm:.1f} m, so 1 cm = {main_fr.mpm*10/1000:.3f} km (about 1:{scale_n:,.0f})",
        "Converting lat/lon to canvas mm: project (lon, lat) to EPSG:7856 metres (X, Y), then",
        f"  x_mm = {main_fr.x} + (X - {ext[0]:.1f}) / {main_fr.mpm:.4f}",
        f"  y_mm = {main_fr.y} + ({ext[3]:.1f} - Y) / {main_fr.mpm:.4f}",
        f"  back_x_mm = {W_MM:.0f} - x_mm  (mirror for the BACK; y is unchanged)",
    ]
    for i in insets:
        f = i["fr"]
        rep.append(f"Inset ({i['kind']}, {i['corner']}): {i.get('label','')}; 1 mm = {f.mpm:.1f} m; frame x={f.x:.0f} y={f.y:.0f} {f.w:.0f}x{f.h:.0f} mm")
    if hidden:
        rep.append("WARNING: markers hidden under an inset: " + ", ".join(f"#{m['number']}" for m in hidden)
                   + ". Move the inset (pick a different extent) or set map_group.")
    rep += warnings_ or ["All markers are at least the recommended tag spacing apart."]
    (out / "map-report.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


def tag_template(args, markers, fonts, out):
    """Full-size BACK view (mirrored): where to stick each NFC tag."""
    fig = plt.figure(figsize=(W_MM * MM, H_MM * MM), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W_MM); ax.set_ylim(H_MM, 0); ax.axis("off")
    ax.add_patch(Rectangle((0.5, 0.5), W_MM - 1, H_MM - 1, fill=False, lw=0.6, ec="black"))
    for m in markers:
        x, y = W_MM - m["mx"], m["my"]
        ax.add_patch(Circle((x, y), args.tag_mm / 2, fill=False, lw=0.7, ec="black"))
        ax.plot([x - 3, x + 3], [y, y], color="black", lw=0.4); ax.plot([x, x], [y - 3, y + 3], color="black", lw=0.4)
        ax.text(x, y + args.tag_mm / 2 + 4, f"#{m['number']:02d}  x={x:.0f} y={y:.0f} mm", ha="center", va="top", fontsize=7,
                family=fonts["sans"])
    ax.text(W_MM / 2, 20, "BACK OF CANVAS (mirrored). Tag centres in mm from the top-left corner of the BACK.",
            ha="center", fontsize=12, family=fonts["sans"])
    ax.text(W_MM / 2, 30, f"Circles = {args.tag_mm:.0f} mm stickers. Print at 100% (no 'fit to page'). Check the 100 mm bar below.",
            ha="center", fontsize=9, family=fonts["sans"])
    ax.plot([50, 150], [45, 45], color="black", lw=1); ax.text(100, 50, "100 mm", ha="center", va="top", fontsize=8, family=fonts["sans"])
    fig.savefig(out / "tag-template-back.pdf", facecolor="white"); plt.close(fig)


def a1_proof(args, png_path, out):
    """1:1 paper proof on an A1 sheet (594 x 841 mm). The poster is placed at TRUE size, centred;
    A1 is 6 mm narrower than 600 mm, so ~3 mm of plain margin is trimmed on each side (no content lost).
    Upload this PDF to a print shop and choose A1, 'actual size' / 100%, never 'fit to page'."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    AW, AH = 594.0, 841.0
    im = Image.open(png_path)
    scale = 150 / args.dpi  # 150 dpi is plenty for a proof and keeps the file small
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    fig = plt.figure(figsize=(AW * MM, AH * MM), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, AW); ax.set_ylim(AH, 0); ax.axis("off")
    b = args.bleed_mm
    x0 = (AW - W_MM) / 2 - b; y0 = (AH - H_MM) / 2 - b
    ax.imshow(np.asarray(im), extent=(x0, x0 + W_MM + 2 * b, y0 + H_MM + 2 * b, y0), interpolation="antialiased")
    ax.plot([AW / 2 - 50, AW / 2 + 50], [AH - 6, AH - 6], color="black", lw=0.8)
    ax.text(AW / 2, AH - 7.5, "PROOF: this bar must measure exactly 100 mm", ha="center", va="bottom", fontsize=6)
    fig.savefig(out / "proof-A1-actual-size.pdf", facecolor="white"); plt.close(fig)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
