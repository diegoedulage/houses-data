"""Download Defra's road noise map (Round 4, 2021 modelling, Lden, all roads) for the covered area.

Defra's raster (WCS) service rejects area requests, so this uses the map-image (WMS) service:
PNG tiles at the map's native 10 m resolution in British National Grid. Each pixel's palette
colour is one 5 dB band, so build_data.py can read the band back exactly (see NOISE_BANDS there).

Output: data/raw/noise/lden_<east>_<north>.png  (20 km x 20 km tiles, 2000 x 2000 px)
Run:    .venv/bin/python -I fetch_noise.py
"""
import json
import subprocess
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "raw" / "noise"
OUT.mkdir(parents=True, exist_ok=True)
WMS = "https://environment.data.gov.uk/geoservices/datasets/562c9d56-7c2d-4d42-83bb-578d6e97a517/wms"
LAYER = "Road_Noise_Lden_England_Round_4_All"
TILE = 20_000  # metres; 2000 px at 10 m

# Extent of the covered areas in British National Grid, from the boundaries file (+1 km).
from pyproj import Transformer  # noqa: E402

to_bng = Transformer.from_crs(4326, 27700, always_xy=True)
geo = json.loads((ROOT / "data" / "raw" / "boundaries" / "lsoa_2021.geojson").read_text())
xs, ys = [], []
for f in geo["features"]:
    g = f["geometry"]
    for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
        x, y = to_bng.transform(*zip(*poly[0]))
        xs += x
        ys += y
x0, y0 = int(min(xs) // TILE * TILE) - TILE, int(min(ys) // TILE * TILE) - TILE
x1, y1 = int(max(xs)) + 1000, int(max(ys)) + 1000

n = 0
for e in range(x0, x1, TILE):
    for nn in range(y0, y1, TILE):
        f = OUT / f"lden_{e}_{nn}.png"
        if f.exists() and f.stat().st_size > 0:
            continue
        q = urllib.parse.urlencode({"service": "WMS", "version": "1.3.0", "request": "GetMap", "layers": LAYER,
                                    "styles": "", "crs": "EPSG:27700", "bbox": f"{e},{nn},{e + TILE},{nn + TILE}",
                                    "width": TILE // 10, "height": TILE // 10, "format": "image/png",
                                    "transparent": "true"})
        # curl uses the system's certificate store (python.org builds often have none installed)
        for attempt in range(3):
            r = subprocess.run(["curl", "-sSf", "--max-time", "300", f"{WMS}?{q}"], capture_output=True)
            if r.returncode == 0 and r.stdout[:4] == b"\x89PNG":
                f.write_bytes(r.stdout)
                break
            print("retry", f.name, r.stderr.decode()[:200] or r.stdout[:200], flush=True)
            time.sleep(5)
        else:
            raise SystemExit(f"Failed to download {f.name}")
        n += 1
        print(f"{f.name}: {f.stat().st_size // 1024} KB", flush=True)
print(f"Done: {n} tiles fetched")
