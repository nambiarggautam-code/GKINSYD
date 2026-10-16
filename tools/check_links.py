#!/usr/bin/env python3
"""
Link checker (standard library only).

  python3 tools/check_links.py                      # check files in docs/ on disk
  python3 tools/check_links.py http://localhost:8000/GKINSYD/   # crawl a running server

Checks every internal href/src/srcset/poster, and every page reached from the homepage.
External links (Google Fonts etc.) are listed but not fetched.
"""
import sys, re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

DOCS = Path(__file__).resolve().parent.parent / "docs"


class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        for k in ("href", "src", "poster"):
            if a.get(k):
                self.refs.append((tag, a[k]))
        if a.get("srcset"):
            for part in a["srcset"].split(","):
                self.refs.append((tag, part.strip().split(" ")[0]))


def is_external(u):
    return urlparse(u).scheme in ("http", "https", "mailto", "tel", "data") or u.startswith("//")


def check_disk():
    bad, ext, n = [], set(), 0
    for page in sorted(DOCS.rglob("*.html")):
        if page.name == "404.html":
            continue  # 404 uses absolute site paths by design; checked in server mode
        p = Refs(); p.feed(page.read_text(encoding="utf-8"))
        for tag, ref in p.refs:
            n += 1
            if is_external(ref):
                ext.add(ref); continue
            url, frag = urldefrag(ref)
            if not url:
                if frag and frag not in p.ids:
                    bad.append(f"{page.relative_to(DOCS)}: missing anchor #{frag}")
                continue
            if url.startswith("/"):
                bad.append(f"{page.relative_to(DOCS)}: root-absolute link breaks under a repo subpath: {ref}")
                continue
            target = (page.parent / url).resolve()
            if not target.is_file():
                bad.append(f"{page.relative_to(DOCS)}: broken -> {ref}")
    for css in DOCS.rglob("*.css"):
        for ref in re.findall(r"url\(['\"]?([^'\")]+)", css.read_text()):
            if not is_external(ref) and not (css.parent / ref).resolve().is_file():
                bad.append(f"{css.relative_to(DOCS)}: broken url({ref})")
    return n, bad, ext


def check_http(base):
    seen, queue, bad, ext, n = set(), [base], [], set(), 0
    # also include 404 page and a deliberately missing page
    queue.append(urljoin(base, "404.html"))
    while queue:
        url = queue.pop()
        if url in seen:
            continue
        seen.add(url); n += 1
        try:
            with urlopen(url, timeout=10) as r:
                body = r.read(); ctype = r.headers.get("Content-Type", "")
        except (HTTPError, URLError) as e:
            bad.append(f"{url}: {e}"); continue
        if "html" in ctype:
            p = Refs(); p.feed(body.decode("utf-8", "replace"))
            for tag, ref in p.refs:
                if is_external(ref):
                    ext.add(ref); continue
                target = urldefrag(urljoin(url, ref))[0]
                if not target.startswith(base):
                    bad.append(f"{url}: link escapes the site base: {ref} -> {target}")
                    continue
                queue.append(target)
    return n, bad, ext


if __name__ == "__main__":
    if len(sys.argv) > 1:
        base = sys.argv[1] if sys.argv[1].endswith("/") else sys.argv[1] + "/"
        n, bad, ext = check_http(base)
        print(f"HTTP crawl of {base}: {n} URLs fetched")
    else:
        n, bad, ext = check_disk()
        print(f"Disk check of docs/: {n} references")
    print("External (not fetched):", ", ".join(sorted(ext)) or "none")
    if bad:
        print(f"\n{len(bad)} problem(s):"); [print("  -", b) for b in bad]; sys.exit(1)
    print("All internal links and assets resolve.")
