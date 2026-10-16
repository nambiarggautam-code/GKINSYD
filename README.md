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

## Password protection (private build)

The real memories, letter and photos live in `private/` (gitignored, never committed):
`private/locations.json` and `private/photos/`. `data/locations.json` in git is a
placeholder sample only.

Rebuild and encrypt the published site (needs Node.js for `npx`, and Pillow for photos):

```bash
SITE_PASSWORD='the-password' python3 build.py --encrypt
```

- Every page except `404.html` is encrypted with StatiCrypt v3 (AES-256-GCM, PBKDF2-SHA256)
  using the shared salt in `.staticrypt.json`, so one unlock with "Remember me" (365 days)
  works across the whole site on that device. Keep the salt and password unchanged when
  rebuilding so her phone stays unlocked.
- Photos (and any audio/video) are resized, stripped of EXIF/GPS and embedded inside the
  encrypted pages, so no image files are published.
- Without `--encrypt`, a build from private data goes to `private/_preview/` (plain, local only).
- Tip: type the command with a leading space or use `read -s SITE_PASSWORD; export SITE_PASSWORD`
  so the password is not saved in your shell history.
