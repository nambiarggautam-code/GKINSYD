#!/usr/bin/env python3
"""
Our Sydney Story: static site generator. Python 3.8+ standard library only.

  python3 build.py            # validate data/locations.json and regenerate docs/
  python3 build.py --lock     # freeze current slugs (run the day you write NFC tags)
  python3 build.py --strict   # also fail if any [REPLACE: ...] placeholders remain

Outputs:
  docs/index.html, docs/our-story.html, docs/404.html,
  docs/memories/<slug>.html (memory pages AND cluster pages, so every tag URL
  has the same memories/<slug>.html pattern),
  nfc-urls.csv  (the exact URL to write to each tag; not published)

SLUGS ARE PERMANENT. Once a URL is written to an NFC tag, never rename or remove
its slug. After --lock, the build refuses to drop a locked slug.
"""
import csv, html, json, re, sys
from pathlib import Path
from string import Template
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "locations.json"
LOCK = ROOT / "data" / "slugs.lock.json"
TPL = ROOT / "templates"
OUT = ROOT / "docs"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# NTAG213 has 144 bytes of user memory; leave margin for the NDEF wrapper.
NDEF_PREFIXES = ["https://www.", "http://www.", "https://", "http://"]

errors, warnings = [], []


def tpl(name):
    return Template((TPL / name).read_text(encoding="utf-8"))


def esc(s):
    return html.escape(str(s or ""), quote=True)


def paras(text, indent="      "):
    """Plain text -> <p> paragraphs. Blank line = new paragraph; single newline = <br>."""
    text = str(text or "").strip()
    if not text:
        return ""
    out = []
    for block in re.split(r"\n\s*\n", text):
        out.append(f"{indent}<p>{esc(block.strip()).replace(chr(10), '<br>')}</p>")
    return "\n".join(out)


def page(title, content, root, description="A small collection of memories.", slug=None):
    attrs = f' data-slug="{esc(slug)}"' if slug else ""
    return tpl("layout.html").substitute(title=esc(title), description=esc(description), root=root,
                                         body_attrs=attrs, content=content)


def ndef_bytes(url):
    rest = url
    for p in NDEF_PREFIXES:
        if url.startswith(p):
            rest = url[len(p):]
            break
    payload = 1 + len(rest.encode("utf-8"))
    record = 3 + 1 + payload          # short-record header + type 'U' + payload
    return 2 + record + 1             # TLV (03 len) + record + terminator FE


def validate(data):
    site, locs = data.get("site", {}), data.get("locations", [])
    if not locs:
        errors.append("No locations in data/locations.json")
    seen_slugs, seen_nums = set(), set()
    for i, loc in enumerate(locs):
        label = loc.get("slug") or f"location #{i+1}"
        for f in ("number", "slug", "name", "lat", "lon", "photo", "alt", "story", "love"):
            if loc.get(f) in (None, ""):
                errors.append(f"{label}: missing required field '{f}'")
        s = loc.get("slug", "")
        if s and not SLUG_RE.match(s):
            errors.append(f"{label}: slug must be lowercase letters, digits and single hyphens (e.g. 'manly-ferry')")
        if s in seen_slugs:
            errors.append(f"duplicate slug '{s}'")
        seen_slugs.add(s)
        n = loc.get("number")
        if n in seen_nums:
            errors.append(f"duplicate number {n}")
        seen_nums.add(n)
        try:
            lat, lon = float(loc.get("lat")), float(loc.get("lon"))
            if not (-35.5 <= lat <= -32.5 and 149.5 <= lon <= 152.5):
                warnings.append(f"{label}: coordinates ({lat}, {lon}) are outside the greater Sydney region; check lat/lon order and sign")
        except (TypeError, ValueError):
            errors.append(f"{label}: lat/lon must be numbers (decimal degrees, lat negative for Sydney)")
        for f in ("photo", "photo_small", "audio", "video", "video_poster"):
            v = loc.get(f)
            if v and not re.match(r"^https?://", v) and not (OUT / v).is_file():
                errors.append(f"{label}: {f} file not found: docs/{v}")
        if "placeholders/" in str(loc.get("photo", "")):
            warnings.append(f"{label}: still using a placeholder photo")
    for c in data.get("clusters", []) or []:
        if not SLUG_RE.match(c.get("slug", "")):
            errors.append(f"cluster '{c.get('slug')}': bad slug")
        if c.get("slug") in seen_slugs:
            errors.append(f"cluster slug '{c.get('slug')}' clashes with a location slug")
        for m in c.get("members", []):
            if m not in seen_slugs:
                errors.append(f"cluster '{c.get('slug')}': unknown member slug '{m}'")
    targets = seen_slugs | {c.get("slug") for c in data.get("clusters", []) or []}
    nums = [t.get("number") for t in data.get("tags", []) or []]
    if len(nums) != len(set(nums)):
        errors.append("tags: duplicate tag numbers")
    for t in data.get("tags", []) or []:
        if t.get("target") not in targets:
            errors.append(f"tag {t.get('number')}: unknown target '{t.get('target')}'")
    bu = site.get("base_url", "")
    if not bu.endswith("/"):
        errors.append("site.base_url must end with '/'")
    if "REPLACE" in bu:
        warnings.append("site.base_url is still a placeholder; nfc-urls.csv will not contain real URLs yet")
    # Slug lock
    if LOCK.exists():
        locked = set(json.loads(LOCK.read_text())["slugs"])
        all_slugs = seen_slugs | {c.get("slug") for c in data.get("clusters", []) or []}
        missing = sorted(locked - all_slugs)
        if missing:
            errors.append("These slugs are LOCKED (already written to NFC tags) but are missing from the data file: "
                          + ", ".join(missing) + ". Restore them. Never rename a slug after writing tags.")
    else:
        warnings.append("No slug lock yet. Run 'python3 build.py --lock' right after you write the NFC tags.")
    raw = DATA.read_text(encoding="utf-8")
    n_rep = raw.count("[REPLACE")
    if n_rep:
        warnings.append(f"{n_rep} [REPLACE: ...] placeholders remain in data/locations.json")


def photo_tag(loc, prefix, cls="", eager=False, thumb=False):
    src = loc["photo"] if re.match(r"^https?://", loc["photo"]) else prefix + loc["photo"]
    w, h = loc.get("photo_width") or 1600, loc.get("photo_height") or 1200
    attrs = [f'src="{esc(src)}"', f'alt="{esc(loc["alt"])}"', f'width="{int(w)}"', f'height="{int(h)}"', 'decoding="async"']
    if loc.get("photo_small"):
        small = prefix + loc["photo_small"]
        attrs.append(f'srcset="{esc(small)} 800w, {esc(src)} 1600w"')
        attrs.append('sizes="(min-width: 40rem) 72px, 72px"' if thumb else 'sizes="(min-width: 56rem) 54rem, 100vw"')
    if eager:
        attrs.append('fetchpriority="high"')
    else:
        attrs.append('loading="lazy"')
    if thumb:
        attrs[1] = 'alt=""'  # decorative in list; the link text names the place
    if cls:
        attrs.append(f'class="{cls}"')
    return "<img " + " ".join(attrs) + ">"


def place_item(loc, href, prefix):
    date = loc.get("date") or ""
    date_html = f'<span class="place-date">{esc(date)}</span>' if date else ""
    return (f'    <li><a href="{href}" data-place="{esc(loc["slug"])}">'
            f'<span class="place-num" aria-hidden="true">{int(loc["number"])}</span>'
            f'{photo_tag(loc, prefix, "place-thumb", thumb=True)}'
            f'<span><span class="place-name"><span class="visually-hidden">{int(loc["number"])}. </span>{esc(loc["name"])}</span>{date_html}</span>'
            f'<span class="place-mark" aria-hidden="true">&#9825;</span></a></li>')


def areas_block(data):
    """Discreet homepage links to the area pages (the pages behind the NFC tags)."""
    cl = {c["slug"]: c for c in data.get("clusters", []) or []}
    links = []
    for t in sorted(data.get("tags", []) or [], key=lambda t: t["number"]):
        if t["target"] in cl and cl[t["target"]].get("show_on_home", True):
            links.append(f'      <li><a href="memories/{esc(t["target"])}.html">{esc(cl[t["target"]]["name"])}</a></li>')
    if not links:
        return ""
    return ('  <nav class="areas" aria-label="Areas on our map">\n    <p>On the map</p>\n    <ul>\n'
            + "\n".join(links) + "\n    </ul>\n  </nav>")


def build(data):
    site = data["site"]
    locs = sorted(data["locations"], key=lambda l: l["number"])
    footer = esc(site.get("footer", ""))
    (OUT / "memories").mkdir(parents=True, exist_ok=True)
    written = []

    # Remove stale generated memory/cluster pages (only files we generated: have the marker)
    keep = {f"{l['slug']}.html" for l in locs} | {f"{c['slug']}.html" for c in data.get("clusters", []) or []}
    for f in list((OUT / "memories").glob("*.html")) + list((OUT / "clusters").glob("*.html")):
        if f.parent.name == "clusters":
            keep_this = False
        else:
            keep_this = f.name in keep
        if keep_this:
            continue
        if "data-generated=\"our-sydney-story\"" in f.read_text(encoding="utf-8"):
            f.unlink()

    # Homepage
    items = "\n".join(place_item(l, f"memories/{l['slug']}.html", "") for l in locs)
    content = tpl("home.html").substitute(
        site_title=esc(site["title"]), subtitle=esc(site.get("subtitle", "")), intro=esc(site.get("intro", "")),
        home_hint=esc(site.get("home_hint", "")), place_items=items, areas_block=areas_block(data),
        letter_title=esc(site.get("letter", {}).get("title", "")), footer=footer)
    write(OUT / "index.html", page(site["title"], content, ""))
    written.append("index.html")

    # Memory pages
    for i, loc in enumerate(locs):
        prev_l = locs[i - 1] if i > 0 else None
        next_l = locs[i + 1] if i < len(locs) - 1 else None
        date = loc.get("date") or ""
        date_block = f'    <p class="memory-date">{esc(date)}</p>' if date else ""
        oneday = loc.get("oneday") or ""
        oneday_block = (f'    <section class="section" aria-labelledby="oneday-h">\n      <h2 id="oneday-h">One day, we&rsquo;ll&hellip;</h2>\n'
                        f'{paras(oneday)}\n    </section>') if oneday else ""
        media = []
        if loc.get("audio"):
            media.append(f'    <figure class="media"><audio controls preload="none" src="../{esc(loc["audio"])}"></audio>'
                         f'<figcaption>A voice note</figcaption></figure>')
        if loc.get("video"):
            poster = f' poster="../{esc(loc["video_poster"])}"' if loc.get("video_poster") else ""
            media.append(f'    <figure class="media"><video controls playsinline preload="none"{poster} src="../{esc(loc["video"])}"></video>'
                         f'<figcaption>A little video</figcaption></figure>')
        prev_link = f'<a href="{prev_l["slug"]}.html" rel="prev">&larr; {esc(prev_l.get("short_name") or prev_l["name"])}</a>' if prev_l else "<span></span>"
        next_link = f'<a href="{next_l["slug"]}.html" rel="next">{esc(next_l.get("short_name") or next_l["name"])} &rarr;</a>' if next_l else "<span></span>"
        content = tpl("memory.html").substitute(
            number=int(loc["number"]), name=esc(loc["name"]), date_block=date_block,
            photo_tag=photo_tag(loc, "../", eager=True), story=paras(loc["story"]), love=paras(loc["love"]),
            oneday_block=oneday_block, media_block="\n".join(media), prev_link=prev_link, next_link=next_link,
            footer=footer)
        write(OUT / "memories" / f"{loc['slug']}.html",
              page(f"{loc['name']} · {site['title']}", content, "../", slug=loc["slug"]))
        written.append(f"memories/{loc['slug']}.html")

    # Cluster pages (one NFC tag -> several nearby memories)
    by_slug = {l["slug"]: l for l in locs}
    for c in data.get("clusters", []) or []:
        sections = c.get("sections") or [{"members": c["members"]}]
        blocks = []
        for sec in sections:
            if sec.get("heading"):
                head = esc(sec["heading"])
                if sec.get("link"):
                    head = f'<a href="{esc(sec["link"])}.html">{head}</a>'
                blocks.append(f'  <h2 class="cluster-heading">{head}</h2>')
            items = "\n".join(place_item(by_slug[m], f"{m}.html", "../") for m in sec["members"])
            blocks.append(f'  <ol class="places cluster-list">\n{items}\n  </ol>')
        content = tpl("cluster.html").substitute(name=esc(c.get("name", "")), intro=paras(c.get("intro", ""), "  "),
                                                 lists="\n".join(blocks), footer=footer)
        write(OUT / "memories" / f"{c['slug']}.html", page(f"{c.get('name')} · {site['title']}", content, "../", slug=c["slug"]))
        written.append(f"memories/{c['slug']}.html")
    try:
        (OUT / "clusters").rmdir()  # remove the old, now-empty clusters/ folder if present
    except OSError:
        pass

    # Letter
    L = site.get("letter", {})
    content = tpl("letter.html").substitute(
        site_title=esc(site["title"]), letter_title=esc(L.get("title", "")), opening=esc(L.get("opening", "")),
        body=paras(L.get("body", ""), "    "), closing=esc(L.get("closing", "")), signature=esc(L.get("signature", "")),
        footer=footer)
    write(OUT / "our-story.html", page(f"{L.get('title')} · {site['title']}", content, ""))
    written.append("our-story.html")

    # 404: GitHub Pages serves it at any depth, so use the absolute site path.
    base_path = urlparse(site["base_url"]).path or "/"
    content = tpl("404.html").substitute(base_path=esc(base_path), footer=footer)
    write(OUT / "404.html", page(f"Not found · {site['title']}", content, base_path))
    written.append("404.html")

    # NFC URL list: exactly one row per physical tag (data["tags"])
    with open(ROOT / "nfc-urls.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tag_number", "tag_name", "path", "url", "ndef_bytes", "fits_ntag213_144B", "places_covered"])
        cl = {c["slug"]: c for c in data.get("clusters", []) or []}
        for t in sorted(data.get("tags", []) or [], key=lambda t: t["number"]):
            path = f"memories/{t['target']}.html"
            url = site["base_url"] + path
            b = ndef_bytes(url)
            n = len(cl[t["target"]]["members"]) if t["target"] in cl else 1
            w.writerow([t["number"], t["name"], path, url, b, "yes" if b <= 144 else "NO: use NTAG215 or a shorter URL", n])
    return written


def write(path, text):
    text = text.replace("<body", '<body data-generated="our-sydney-story"', 1) if "data-generated" not in text else text
    path.write_text(text, encoding="utf-8")


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    validate(data)
    if "--strict" in sys.argv and any("[REPLACE" in w for w in warnings):
        errors.append("--strict: placeholders remain")
    for w in warnings:
        print("WARNING:", w)
    if errors:
        for e in errors:
            print("ERROR:", e)
        print("\nBuild stopped. Fix the errors above in data/locations.json.")
        sys.exit(1)
    written = build(data)
    print(f"Built {len(written)} pages into docs/:")
    for p in written:
        print("  ", p)
    print("NFC URL list: nfc-urls.csv")
    if "--lock" in sys.argv:
        slugs = sorted({l["slug"] for l in data["locations"]} | {c["slug"] for c in data.get("clusters", []) or []})
        if LOCK.exists():
            slugs = sorted(set(slugs) | set(json.loads(LOCK.read_text())["slugs"]))
        LOCK.write_text(json.dumps({"note": "Slugs written to NFC tags. Never remove or rename.", "slugs": slugs}, indent=2))
        print(f"Locked {len(slugs)} slugs in data/slugs.lock.json")


if __name__ == "__main__":
    main()
