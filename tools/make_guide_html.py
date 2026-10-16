#!/usr/bin/env python3
"""Render GUIDE.md -> GUIDE.html (needs: pip install markdown). PDF: print GUIDE.html from Chrome."""
from pathlib import Path
import markdown
ROOT = Path(__file__).resolve().parent.parent
md = (ROOT / "GUIDE.md").read_text(encoding="utf-8")
body = markdown.markdown(md, extensions=["tables", "fenced_code", "toc", "sane_lists"])
css = """
body{margin:0;background:#F6F1E8;color:#242424;font:16px/1.65 Inter,system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif}
main{max-width:58rem;margin:0 auto;padding:2.5rem 1.5rem 4rem}
h1,h2,h3{font-family:'Cormorant Garamond',Garamond,Georgia,serif;font-weight:500;line-height:1.2}
h1{font-size:2.6rem;letter-spacing:.04em;text-align:center;margin:.5rem 0 .25rem}
h2{font-size:1.9rem;border-top:1px solid #D9CFBF;padding-top:1.5rem;margin-top:2.5rem;color:#242424}
h3{font-size:1.35rem;color:#783D46;margin-top:1.8rem}
a{color:#783D46}
table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.88rem;background:#fbf8f2}
th,td{border:1px solid #D9CFBF;padding:.45rem .6rem;vertical-align:top;text-align:left}
th{background:#EDE5D7}
code{background:#EDE5D7;padding:.1em .3em;border-radius:3px;font-size:.88em}
pre{background:#242424;color:#F6F1E8;padding:1rem;overflow:auto;border-radius:4px;font-size:.82rem;line-height:1.45}
pre code{background:none;padding:0;color:inherit}
blockquote{border-left:3px solid #783D46;margin:1.2rem 0;padding:.4rem 1rem;background:#fbf8f2}
img{max-width:100%;height:auto;border:1px solid #D9CFBF}
td img{max-width:240px}
@media print{body{background:#fff;font-size:10.5pt}main{max-width:none;padding:0}
 h2{break-before:page;border-top:0} h2:first-of-type{break-before:avoid} table,pre,blockquote,img{break-inside:avoid} a{color:#242424}}
@page{size:A4;margin:16mm 14mm}
"""
html = f"""<!doctype html><html lang="en-AU"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Our Sydney Story: Build Guide</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500&family=Inter:wght@400;500&display=swap">
<style>{css}</style></head><body><main>{body}</main></body></html>"""
(ROOT / "GUIDE.html").write_text(html, encoding="utf-8")
print("wrote GUIDE.html")
