# Our Sydney Story

A minimalist Sydney memory map: a printed canvas with an NFC sticker behind each numbered dot, and a small static website with one page per place.

**Read `GUIDE.md` (or `GUIDE.html` / `GUIDE.pdf`) for the full step-by-step build.**

## Quick start

```bash
python3 build.py                          # validate data/locations.json, regenerate docs/
cd docs && python3 -m http.server 8000    # preview at http://localhost:8000
python3 tools/check_links.py              # check every internal link and image
```

- Edit only `data/locations.json` (and your photos in `docs/media/photos/`).
- Publish the `docs/` folder with GitHub Pages (Settings → Pages → main → /docs).
- Map poster: `pip install -r map/requirements.txt`, then `python map/make_map.py` (or `--pbf <extract>`).
- **Never rename a slug after writing NFC tags.** Run `python3 build.py --lock` once the tags are written.

Map data © OpenStreetMap contributors (ODbL). Fonts: SIL Open Font Licence.

## Deployment target

- Repository: `nambiarggautam-code/GKINSYD` (GitHub Pages: branch `main`, folder `/docs`)
- Site: https://nambiarggautam-code.github.io/GKINSYD/
- The 9 NFC tag URLs are in `nfc-urls.csv`; the printable checklist is `map/output/a1/nfc-tag-checklist-A4.pdf`.
