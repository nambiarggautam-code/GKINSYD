#!/usr/bin/env python3
"""Actual-size back-of-print templates and the tag-writing checklist.

Reads output/a1/layout.json (dot positions) and data/locations.json (tags, clusters).
Tag centre = mean position of the dots it covers (front, mm from top-left).
Back = mirrored left-right (back_x = 841 - x), as seen when the print lies face down.

Outputs (output/a1/):
  back-template-A1-single.pdf   one 841 x 594 mm page
  back-template-A4-tiled.pdf    15 A4 portrait pages, 10 mm overlap, alignment marks
  tags-A1.csv                   tag centres (front and back)
  nfc-tag-checklist-A4.pdf      one A4 page
PRINT AT 100% / ACTUAL SIZE. Check the 100 mm calibration bar with a ruler.
"""
import csv, json, math, itertools
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Circle, Rectangle

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "output" / "a1"
MM = 1 / 25.4
PW, PH, MARGIN = 841.0, 594.0, 30.0
TAG_D = 25.0
A4W, A4H, A4M, OVL = 210.0, 297.0, 10.0, 10.0   # A4 portrait, 10 mm printer margin, 10 mm overlap
RED = "#B3261E"


def load():
    lay = json.load(open(OUT / "layout.json"))
    data = json.load(open(ROOT / "private" / "locations.json" if (ROOT / "private" / "locations.json").exists() else ROOT / "data" / "locations.json"))
    dots = {p["slug"]: (p["x_mm"], p["y_mm"]) for p in lay["points"]}
    cl = {c["slug"]: c for c in data["clusters"]}
    city = set(cl["sydney-city"]["members"])
    tags = []
    for t in sorted(data["tags"], key=lambda t: t["number"]):
        members = cl[t["target"]]["members"] if t["target"] in cl else [t["target"]]
        dslugs = []
        for m in members:  # city members share the single merged dot
            s = "sydney-city" if m in city else m
            if s not in dslugs:
                dslugs.append(s)
        xs, ys = zip(*[dots[s] for s in dslugs])
        x, y = sum(xs) / len(xs), sum(ys) / len(ys)
        tags.append(dict(number=t["number"], name=t["name"], target=t["target"], members=members, dots=dslugs,
                         x=x, y=y, bx=PW - x, url=data["site"]["base_url"] + f"memories/{t['target']}.html",
                         path=f"memories/{t['target']}.html"))
    return dots, tags, data


def draw_back(ax, dots, tags, title=True):
    """Everything in back-of-print mm coordinates (y down)."""
    ax.add_patch(Rectangle((0, 0), PW, PH, fill=False, lw=0.8, ec="k"))                 # paper edge
    ax.add_patch(Rectangle((MARGIN, MARGIN), PW - 2 * MARGIN, PH - 2 * MARGIN, fill=False, lw=0.5,
                           ec="0.45", ls=(0, (4, 2))))                                     # map frame
    for s, (x, y) in dots.items():
        ax.add_patch(Circle((PW - x, y), 1.75, fc="#e9b9b5", ec="none", zorder=2))          # faint dots
    for t in tags:
        x, y = t["bx"], t["y"]
        ax.add_patch(Circle((x, y), TAG_D / 2, fill=False, lw=0.7, ec=RED, zorder=4))
        ax.plot([x - 15, x + 15], [y, y], color="k", lw=0.35, zorder=5)
        ax.plot([x, x], [y - 15, y + 15], color="k", lw=0.35, zorder=5)
        ax.text(x + 2, y - 2, str(t["number"]), fontsize=11, fontweight="bold", color="k", zorder=6)
        ax.text(x, y + TAG_D / 2 + 4, t["name"], fontsize=6.5, ha="center", va="top", color="k", zorder=6)
        ax.text(x, y + TAG_D / 2 + 8, f"centre {x:.1f}, {y:.1f} mm from top-left (back)", fontsize=4.5,
                ha="center", va="top", color="0.35", zorder=6)
    # 100 mm calibration bars (one near each bottom corner of the frame area)
    for bx0 in (40, PW - 140):
        y0 = PH - 18
        ax.plot([bx0, bx0 + 100], [y0, y0], color="k", lw=1.0)
        for k in range(0, 101, 10):
            ax.plot([bx0 + k, bx0 + k], [y0 - (3 if k % 50 == 0 else 1.5), y0], color="k", lw=0.5)
        ax.text(bx0 + 50, y0 + 2, "100 mm calibration: measure this", fontsize=5.5, ha="center", va="top")
    if title:
        ax.text(PW / 2, 12, "BACK OF PRINT (mirrored: lay the print face down, top edge at the top). "
                "Tag centres = cross hairs; red circles = 25 mm tags; pink = map dots (reference).",
                fontsize=7, ha="center", va="center")
        ax.text(PW / 2, 19, "Print at 100% / Actual size. Do not 'fit to page'.", fontsize=6.5,
                ha="center", va="center", color="0.3")


def single(dots, tags):
    fig = plt.figure(figsize=(PW * MM, PH * MM))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, PW); ax.set_ylim(PH, 0); ax.axis("off")
    draw_back(ax, dots, tags)
    fig.savefig(OUT / "back-template-A1-single.pdf"); plt.close(fig)


def tiled(dots, tags):
    cw, ch = A4W - 2 * A4M, A4H - 2 * A4M          # printable window 190 x 277
    sx, sy = cw - OVL, ch - OVL                    # step 180 x 267
    cols = math.ceil((PW - cw) / sx) + 1
    rows = math.ceil((PH - ch) / sy) + 1
    n = rows * cols
    with PdfPages(OUT / "back-template-A4-tiled.pdf") as pdf:
        # cover / assembly page
        fig = plt.figure(figsize=(A4W * MM, A4H * MM))
        ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, A4W); ax.set_ylim(A4H, 0); ax.axis("off")
        lines = ["Back-of-print tag template, A1 (841 × 594 mm), tiled on A4",
                 "", f"{n} tile pages: {rows} rows × {cols} columns, each overlapping the next by {OVL:.0f} mm.",
                 "1. Print at 100% / Actual size (no scaling, no 'fit to page').",
                 "2. Measure the 100 mm bar on this page. If it is not 100 mm, fix the print settings.",
                 "3. Trim the white paper margin off the LEFT edge of every tile except column 1,",
                 "   and off the TOP edge of every tile except row 1, exactly at the printed edge.",
                 "4. Lay each trimmed edge over its neighbour's grey overlap band, with the edge on",
                 "   the dashed line and the + alignment marks meeting. Tape. (Marks every 90 mm.)",
                 "5. Lay the A1 print FACE DOWN, top edge at the top. Align the assembled sheet's",
                 "   paper edge with the print's edge. Tag centres are the numbered cross hairs.",
                 "", "Tile layout (row, column):"]
        y = 20
        for i, l in enumerate(lines):
            ax.text(15, y, l, fontsize=12 if i == 0 else 8.5, fontweight="bold" if i == 0 else "normal", va="top")
            y += 9 if i == 0 else 6.5
        # mini map of tiles
        s = 150 / PW; ox, oy = 30, y + 4
        ax.add_patch(Rectangle((ox, oy), PW * s, PH * s, fill=False, lw=0.8))
        for r in range(rows):
            for c in range(cols):
                x0, y0 = c * sx, r * sy
                ax.add_patch(Rectangle((ox + x0 * s, oy + y0 * s), cw * s, ch * s, fill=False, lw=0.3, ec="0.5"))
                ax.text(ox + (x0 + cw / 2) * s, oy + (y0 + ch / 2) * s, f"R{r+1}C{c+1}", fontsize=6, ha="center", va="center")
        for t in tags:
            ax.add_patch(Circle((ox + t["bx"] * s, oy + t["y"] * s), 1.2, color=RED))
        yb = oy + ((rows - 1) * sy + ch) * s + 16
        ax.plot([30, 130], [yb, yb], color="k", lw=1)
        for k in range(0, 101, 10):
            ax.plot([30 + k, 30 + k], [yb - (3 if k % 50 == 0 else 1.5), yb], color="k", lw=0.5)
        ax.text(80, yb + 3, "100 mm calibration bar", fontsize=7, ha="center", va="top")
        pdf.savefig(fig); plt.close(fig)
        for r in range(rows):
            for c in range(cols):
                x0, y0 = c * sx, r * sy
                fig = plt.figure(figsize=(A4W * MM, A4H * MM))
                ax = fig.add_axes([A4M / A4W, A4M / A4H, cw / A4W, ch / A4H])
                ax.set_xlim(x0, x0 + cw); ax.set_ylim(y0 + ch, y0); ax.axis("off")
                draw_back(ax, dots, tags, title=False)
                # overlap bands (right / bottom) and trim lines (left / top of the band belongs to next tile)
                if c < cols - 1:
                    ax.add_patch(Rectangle((x0 + sx, y0), OVL, ch, fc="0.92", ec="none", zorder=0))
                    ax.plot([x0 + sx, x0 + sx], [y0, y0 + ch], color="0.4", lw=0.4, ls=(0, (3, 2)))
                if r < rows - 1:
                    ax.add_patch(Rectangle((x0, y0 + sy), cw, OVL, fc="0.92", ec="none", zorder=0))
                    ax.plot([x0, x0 + cw], [y0 + sy, y0 + sy], color="0.4", lw=0.4, ls=(0, (3, 2)))
                # alignment + marks every 90 mm along a global grid (shared across tiles)
                for gx in range(0, int(PW) + 1, 90):
                    for gy in range(0, int(PH) + 1, 90):
                        if x0 <= gx <= x0 + cw and y0 <= gy <= y0 + ch:
                            ax.plot([gx - 4, gx + 4], [gy, gy], color="0.25", lw=0.4)
                            ax.plot([gx, gx], [gy - 4, gy + 4], color="0.25", lw=0.4)
                            ax.text(gx + 1, gy - 1, f"{gx},{gy}", fontsize=3.5, color="0.4")
                fig.text(0.5, 1 - 5 / A4H, f"Tile R{r+1}C{c+1} of {rows}×{cols}  ·  back of print, mirrored  ·  "
                         f"covers x {x0:.0f}–{min(x0 + cw, PW):.0f} mm, y {y0:.0f}–{min(y0 + ch, PH):.0f} mm  ·  100% scale",
                         fontsize=6, ha="center", va="center")
                pdf.savefig(fig); plt.close(fig)
    return rows, cols


def checklist(tags, data):
    fig = plt.figure(figsize=(A4W * MM, A4H * MM))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, A4W); ax.set_ylim(A4H, 0); ax.axis("off")
    ax.text(15, 18, "Our Sydney Story: NFC tag-writing checklist", fontsize=14, fontweight="bold", va="top")
    ax.text(15, 27, "Write each tag with one NDEF URL record (NFC Tools: Write > Add a record > URL), test it with "
            "two phones,\nthen tick. Lock tags only after the site is live and all 9 work. Then run: python3 build.py --lock",
            fontsize=7, va="top", linespacing=1.5)
    if "REPLACE" in data["site"]["base_url"]:
        ax.text(15, 38, "NOTE: base_url is still a placeholder. Set site.base_url, run build.py and reprint this page "
                "before writing tags.", fontsize=7, color=RED, va="top")
    y = 48
    ax.text(15, y, "#", fontsize=8, fontweight="bold"); ax.text(23, y, "Tag / URL to write", fontsize=8, fontweight="bold")
    ax.text(166, y, "Written", fontsize=8, fontweight="bold", ha="center"); ax.text(186, y, "Tested", fontsize=8, fontweight="bold", ha="center")
    y += 4
    for t in tags:
        ax.plot([15, 195], [y, y], color="0.75", lw=0.4)
        ax.text(15, y + 7, str(t["number"]), fontsize=13, fontweight="bold", va="center")
        ax.text(23, y + 5, f"{t['name']}  ({len(t['members'])} place{'s' if len(t['members']) > 1 else ''})", fontsize=9, va="center")
        ax.text(23, y + 11, t["url"], fontsize=6.3, va="center", family="monospace")
        ax.text(23, y + 16, f"back position: x {t['bx']:.1f} mm, y {t['y']:.1f} mm from top-left (face down)",
                fontsize=5.5, va="center", color="0.4")
        for bx in (166, 186):
            ax.add_patch(Rectangle((bx - 3.5, y + 4), 7, 7, fill=False, lw=0.7))
        y += 22
    ax.plot([15, 195], [y, y], color="0.75", lw=0.4)
    ax.text(15, y + 8, "Spare tag: homepage " + data["site"]["base_url"], fontsize=6.5, family="monospace", va="top")
    fig.savefig(OUT / "nfc-tag-checklist-A4.pdf"); plt.close(fig)


def main():
    dots, tags, data = load()
    single(dots, tags)
    rows, cols = tiled(dots, tags)
    checklist(tags, data)
    with open(OUT / "tags-A1.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag_number", "tag_name", "path", "front_x_mm", "front_y_mm", "back_x_mm", "back_y_mm", "places"])
        for t in tags:
            w.writerow([t["number"], t["name"], t["path"], f"{t['x']:.1f}", f"{t['y']:.1f}", f"{t['bx']:.1f}", f"{t['y']:.1f}", ";".join(t["members"])])
    md = min(math.hypot(a["x"] - b["x"], a["y"] - b["y"]) for a, b in itertools.combinations(tags, 2))
    print(f"{len(tags)} tags; min centre distance {md:.1f} mm; tiles {rows}x{cols}; places {sum(len(t['members']) for t in tags)}")
    for t in tags:
        print(t["number"], t["name"], round(t["x"], 1), round(t["y"], 1), "back", round(t["bx"], 1))


if __name__ == "__main__":
    main()
