"""Read the filtered regional OSM extract once, project to MGA56, simplify, cache as pickles."""
import sys, pickle, time
import osmium, geopandas as gpd
from shapely import wkb
from shapely.geometry import box
PBF = sys.argv[1] if len(sys.argv) > 1 else "/workspace/osmdata/region-filtered.osm.pbf"
OUT = "/workspace/osmdata/cache/a1_layers.pkl"
CRS = "EPSG:7856"
ROAD = {"motorway":"motorway","motorway_link":"motorway","trunk":"trunk","trunk_link":"trunk",
        "primary":"primary","primary_link":"primary","secondary":"secondary","secondary_link":"secondary",
        "tertiary":"tertiary","tertiary_link":"tertiary","residential":"minor","unclassified":"minor","living_street":"minor"}
t0 = time.time()
f = osmium.geom.WKBFactory()
rows = {"roads": [], "coast": [], "water": [], "rivers": [], "rail": []}
cls = []
fp = osmium.FileProcessor(PBF).with_locations().with_areas()
for o in fp:
    try:
        t = o.tags
        if o.is_area():
            if t.get("natural") == "water" or t.get("waterway") == "riverbank" or t.get("landuse") == "reservoir":
                rows["water"].append(wkb.loads(f.create_multipolygon(o), hex=True))
        elif o.is_way():
            hw = t.get("highway")
            if hw in ROAD:
                rows["roads"].append(wkb.loads(f.create_linestring(o), hex=True)); cls.append(ROAD[hw])
            elif t.get("natural") == "coastline":
                rows["coast"].append(wkb.loads(f.create_linestring(o), hex=True))
            elif t.get("waterway") == "river":
                rows["rivers"].append(wkb.loads(f.create_linestring(o), hex=True))
            elif t.get("railway") == "rail" and t.get("service") is None:
                rows["rail"].append(wkb.loads(f.create_linestring(o), hex=True))
    except Exception:
        continue
print({k: len(v) for k, v in rows.items()}, f"{time.time()-t0:.0f}s")
out = {}
for k, v in rows.items():
    g = gpd.GeoDataFrame({"cls": cls} if k == "roads" else None, geometry=v, crs="EPSG:4326").to_crs(CRS)
    if k == "water":
        g = g[g.geometry.area > 20000]  # drop ponds < 2 ha (invisible at 1:354k)
        g["geometry"] = g.geometry.simplify(15)
    elif k != "coast":
        g["geometry"] = g.geometry.simplify(8)
    out[k] = g
    print(k, len(g))
pickle.dump(out, open(OUT, "wb"))
print("saved", OUT, f"{time.time()-t0:.0f}s")
