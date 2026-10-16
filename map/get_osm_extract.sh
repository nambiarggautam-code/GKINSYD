#!/usr/bin/env bash
# Download OpenStreetMap data once and cut it to your map area, so make_map.py
# does not depend on the (often busy) public Overpass servers.
#
#   bash map/get_osm_extract.sh                 # default area: Sydney + Blue Mountains
#   bash map/get_osm_extract.sh 150.2,-34.2,151.4,-33.5
#
# Needs: curl and osmium-tool  (macOS: brew install osmium-tool | Debian/Ubuntu/WSL: sudo apt install osmium-tool)
# Data © OpenStreetMap contributors, ODbL. Geofabrik: https://download.geofabrik.de/
set -euo pipefail
BBOX="${1:-150.25,-33.95,151.32,-33.66}"   # W,S,E,N in decimal degrees; widen it to include all your places
DIR="$(cd "$(dirname "$0")" && pwd)/osm"
mkdir -p "$DIR" && cd "$DIR"
if [ ! -f australia-latest.osm.pbf ]; then
  echo "Downloading Geofabrik Australia extract (about 1 GB, one-off)…"
  curl -L --fail -o australia-latest.osm.pbf https://download.geofabrik.de/australia-oceania/australia-latest.osm.pbf
fi
echo "Cutting to $BBOX…"
osmium extract -b "$BBOX" australia-latest.osm.pbf -o area.osm.pbf --overwrite
echo "Keeping only the layers the poster uses…"
osmium tags-filter area.osm.pbf w/highway w/railway=rail w/natural=coastline \
  wa/natural=water wa/waterway=riverbank wa/landuse=reservoir wa/leisure=park,garden \
  -o sydney-map.osm.pbf --overwrite
echo "Done: $DIR/sydney-map.osm.pbf"
echo "Now run:  python map/make_map.py --pbf $DIR/sydney-map.osm.pbf"
