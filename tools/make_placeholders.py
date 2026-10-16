#!/usr/bin/env python3
"""Create simple cream SVG placeholder photos (no stock images). Standard library only."""
from pathlib import Path
OUT = Path(__file__).resolve().parent.parent / "docs" / "assets" / "img" / "placeholders"
OUT.mkdir(parents=True, exist_ok=True)
SPECS = [("photo-placeholder", 1600, 1200, "")]
for name, w, h, label in SPECS:
    cx, cy = w / 2, h / 2
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<rect width="{w}" height="{h}" fill="#EDE5D7"/>
<rect x="40" y="40" width="{w-80}" height="{h-80}" fill="none" stroke="#242424" stroke-opacity=".25" stroke-width="2"/>
<path d="M{w*0.2:.0f} {h*0.62:.0f} C {w*0.35:.0f} {h*0.52:.0f}, {w*0.5:.0f} {h*0.7:.0f}, {w*0.8:.0f} {h*0.58:.0f}" fill="none" stroke="#783D46" stroke-opacity=".5" stroke-width="3"/>
<circle cx="{cx:.0f}" cy="{h*0.38:.0f}" r="10" fill="#783D46"/>
<text x="{cx:.0f}" y="{h*0.47:.0f}" text-anchor="middle" font-family="Georgia, serif" font-size="{w/22:.0f}" fill="#242424">Photo coming soon</text>
<text x="{cx:.0f}" y="{h*0.47 + w/16:.0f}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="{w/40:.0f}" fill="#4A4744">{label}</text>
</svg>'''
    (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
    print("wrote", OUT / f"{name}.svg")
