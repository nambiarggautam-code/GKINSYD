#!/usr/bin/env python3
"""
Our Sydney Story: static site generator. Python 3.8+ standard library only.

  python3 build.py            # validate data/locations.json and regenerate docs/
  python3 build.py --lock     # freeze current slugs (run the day you write NFC tags)
  python3 build.py --strict   # also fail if any [REPLACE: ...] placeholders remain
  SITE_PASSWORD=... python3 build.py --encrypt   # build from private/ data, inline photos,
                                                 # encrypt every page with StatiCrypt into docs/

Data: private/locations.json (gitignored, real content) is used when it exists;
otherwise data/locations.json (public sample) is used.
Privacy: with private data, plain pages are NEVER written to docs/. Without
--encrypt they go to private/_preview/ for local viewing only.
Photos/audio/video are inlined as data: URIs (photos resized to 1600 px, EXIF
stripped) so no raw media files are published.

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
PRIVATE = ROOT / "private"
DATA = PRIVATE / "locations.json" if (PRIVATE / "locations.json").is_file() else ROOT / "data" / "locations.json"
USING_PRIVATE = DATA.parent == PRIVATE
LOCK = ROOT / "data" / "slugs.lock.json"
TPL = ROOT / "templates"
DOCS = ROOT / "docs"          # published folder (GitHub Pages)
OUT = DOCS                    # where plain pages are written (changed in main() for private data)
ASSET_DIRS = [PRIVATE, DOCS]  # where photo/audio/video paths are looked up
PHOTO_MAX, PHOTO_Q, THUMB_MAX = 1600, 80, 160
MEDIA_MAX_BYTES = 8 * 1024 * 1024
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
        for f in ("number", "slug", "name", "lat", "lon", "photo", "alt", "story"):
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
            if v and not re.match(r"^https?://", v) and not find_asset(v):
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


def find_asset(rel):
    for d in ASSET_DIRS:
        f = d / rel
        if f.is_file():
            return f
    return None


_URI_CACHE = {}
MIME = {".svg": "image/svg+xml", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg",
        ".wav": "audio/wav", ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}


def data_uri(rel, max_edge=None):
    """Inline a local file as a data: URI. Raster images are resized, EXIF/GPS stripped, saved as JPEG.
    Returns (uri, width, height) for images, (uri, None, None) otherwise."""
    import base64
    key = (rel, max_edge)
    if key in _URI_CACHE:
        return _URI_CACHE[key]
    f = find_asset(rel)
    ext = f.suffix.lower()
    w = h = None
    if ext == ".svg":
        raw, mime = f.read_bytes(), MIME[ext]
        m = re.search(rb'width="(\d+)"[^>]*height="(\d+)"', raw)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
    elif ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".tif", ".tiff"):
        try:
            from PIL import Image, ImageOps
        except ImportError:
            sys.exit("Pillow is needed to inline photos: pip install pillow")
        import io
        im = ImageOps.exif_transpose(Image.open(f))
        im = im.convert("RGB")
        im.thumbnail((max_edge or PHOTO_MAX, max_edge or PHOTO_MAX), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=PHOTO_Q, optimize=True, progressive=True)  # no exif= -> metadata dropped
        raw, mime, (w, h) = buf.getvalue(), "image/jpeg", im.size
    else:
        raw = f.read_bytes()
        if len(raw) > MEDIA_MAX_BYTES:
            errors.append(f"{rel}: {len(raw)/1e6:.1f} MB is too large to inline (limit {MEDIA_MAX_BYTES/1e6:.0f} MB); "
                          "shorten/compress it or host it elsewhere")
        mime = MIME.get(ext, "application/octet-stream")
    out = (f"data:{mime};base64," + base64.b64encode(raw).decode("ascii"), w, h)
    _URI_CACHE[key] = out
    return out


def media_src(rel):
    if re.match(r"^https?://", rel):
        return rel
    return data_uri(rel)[0]


def photo_tag(loc, prefix, cls="", eager=False, thumb=False):
    w, h = loc.get("photo_width") or 1600, loc.get("photo_height") or 1200
    if re.match(r"^https?://", loc["photo"]):
        src = loc["photo"]
    else:
        src, iw, ih = data_uri(loc["photo"], THUMB_MAX if thumb else PHOTO_MAX)
        if iw and ih:
            w, h = iw, ih
    attrs = [f'src="{esc(src)}"', f'alt="{esc(loc["alt"])}"', f'width="{int(w)}"', f'height="{int(h)}"', 'decoding="async"']
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
            media.append(f'    <figure class="media"><audio controls preload="none" src="{esc(media_src(loc["audio"]))}"></audio>'
                         f'<figcaption>A voice note</figcaption></figure>')
        if loc.get("video"):
            poster = f' poster="{esc(media_src(loc["video_poster"]))}"' if loc.get("video_poster") else ""
            media.append(f'    <figure class="media"><video controls playsinline preload="none"{poster} src="{esc(media_src(loc["video"]))}"></video>'
                         f'<figcaption>A little video</figcaption></figure>')
        prev_link = f'<a href="{prev_l["slug"]}.html" rel="prev">&larr; {esc(prev_l.get("short_name") or prev_l["name"])}</a>' if prev_l else "<span></span>"
        next_link = f'<a href="{next_l["slug"]}.html" rel="next">{esc(next_l.get("short_name") or next_l["name"])} &rarr;</a>' if next_l else "<span></span>"
        content = tpl("memory.html").substitute(
            number=int(loc["number"]), name=esc(loc["name"]), date_block=date_block,
            photo_tag=photo_tag(loc, "../", eager=True), story=paras(loc["story"]),
            love_block=(f'    <section class="section love" aria-labelledby="love-h">\n      <h2 id="love-h">What I love about you</h2>\n'
                        f'{paras(loc["love"])}\n    </section>') if (loc.get("love") or "").strip() else "",
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


STATICRYPT_CMD = ["npx", "--yes", "staticrypt@3.5.4"]   # override with env STATICRYPT_BIN=/path/to/staticrypt
PROMPT = {
    "--template-title": "Our Sydney Story",
    "--template-instructions": "A little secret, just for you.",
    "--template-button": "Open",
    "--template-placeholder": "Password",
    "--template-remember": "Remember me on this device",
    "--template-error": "Not quite. Try again?",
    "--template-toggle-show": "Show password",
    "--template-toggle-hide": "Hide password",
    "--template-color-primary": "#783D46",
    "--template-color-secondary": "#F6F1E8",
}


def encrypt(staging):
    """Encrypt every generated page except 404.html into docs/ with StatiCrypt (AES-256-GCM, PBKDF2-SHA256).
    One shared salt (.staticrypt.json) so 'Remember me' unlocks the whole site on that device."""
    import os, shutil, subprocess, secrets
    pw = os.environ.get("SITE_PASSWORD", "")
    if not pw:
        sys.exit("--encrypt needs the SITE_PASSWORD environment variable (the value is never printed).")
    cfg = ROOT / ".staticrypt.json"
    if not cfg.exists():
        cfg.write_text(json.dumps({"salt": secrets.token_hex(16)}, indent=4) + "\n")
    enc = PRIVATE / "_encrypted"
    shutil.rmtree(enc, ignore_errors=True)
    pages = sorted(str(f.relative_to(staging)) for f in staging.rglob("*.html") if f.name != "404.html")
    cmd = (os.environ["STATICRYPT_BIN"].split() if os.environ.get("STATICRYPT_BIN") else STATICRYPT_CMD)
    inputs = sorted(f.name for f in staging.glob("*.html") if f.name != "404.html") + \
        sorted(d.name for d in staging.iterdir() if d.is_dir())
    rel = lambda x: os.path.relpath(x, staging)   # StatiCrypt resolves the config path relative to cwd
    args = cmd + inputs + ["-r", "-d", rel(enc), "-c", rel(cfg), "--short", "--remember", "365",
                           "-t", rel(TPL / "password_template.html")]
    for k, v in PROMPT.items():
        args += [k, v]
    env = dict(os.environ, STATICRYPT_PASSWORD=pw)
    r = subprocess.run(args, cwd=staging, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("StatiCrypt failed (exit %d). Output withheld in case it echoes input; rerun manually if needed."
                 % r.returncode)
    made = sorted(str(f.relative_to(enc)) for f in enc.rglob("*.html"))
    if made != pages:
        sys.exit(f"StatiCrypt output mismatch: expected {len(pages)} pages, got {len(made)}")
    # sanity: no plaintext marker in any encrypted page
    for rel in made:
        t = (enc / rel).read_text(encoding="utf-8")
        if 'data-generated="our-sydney-story"' in t or "staticrypt" not in t:
            sys.exit(f"Encrypted page looks wrong: {rel}")
    # replace published pages
    for f in list(DOCS.glob("*.html")) + list((DOCS / "memories").glob("*.html")):
        f.unlink()
    shutil.rmtree(DOCS / "clusters", ignore_errors=True)
    (DOCS / "memories").mkdir(exist_ok=True)
    for rel in made:
        shutil.copyfile(enc / rel, DOCS / rel)
    shutil.copyfile(staging / "404.html", DOCS / "404.html")  # stays plain; contains no personal content
    shutil.rmtree(enc, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)
    return made


def main():
    global OUT
    import shutil
    data = json.loads(DATA.read_text(encoding="utf-8"))
    validate(data)
    if "--strict" in sys.argv and any("[REPLACE" in w for w in warnings):
        errors.append("--strict: placeholders remain")
    for w in warnings:
        print("WARNING:", w)
    if errors:
        for e in errors:
            print("ERROR:", e)
        print(f"\nBuild stopped. Fix the errors above in {DATA.relative_to(ROOT)}.")
        sys.exit(1)
    encrypt_mode = "--encrypt" in sys.argv
    print(f"Data: {DATA.relative_to(ROOT)}" + ("  (private)" if USING_PRIVATE else "  (public sample)"))
    if encrypt_mode:
        OUT = PRIVATE / "_plain"
    elif USING_PRIVATE:
        OUT = PRIVATE / "_preview"    # plain preview, never published
    if OUT != DOCS:
        shutil.rmtree(OUT, ignore_errors=True)
        OUT.mkdir(parents=True)
    written = build(data)
    if errors:
        for e in errors:
            print("ERROR:", e)
        sys.exit(1)
    big = [(p, (OUT / p).stat().st_size) for p in written if (OUT / p).stat().st_size > 1_000_000]
    for p, b in big:
        print(f"WARNING: {p} is {b/1e6:.2f} MB before encryption")
    if encrypt_mode:
        made = encrypt(OUT)
        sizes = sorted(((DOCS / p).stat().st_size, p) for p in made)
        print(f"Encrypted {len(made)} pages into docs/ (404.html left plain). "
              f"Largest: {sizes[-1][1]} {sizes[-1][0]/1e6:.2f} MB")
    elif USING_PRIVATE:
        shutil.copytree(DOCS / "assets", OUT / "assets")
        print(f"Built {len(written)} PLAIN preview pages into {OUT.relative_to(ROOT)}/ (not published). "
              "Use --encrypt to update docs/.")
    else:
        print(f"Built {len(written)} sample pages into docs/:")
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
