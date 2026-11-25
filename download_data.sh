#!/usr/bin/env bash
# Re-download the open datasets into data/raw/. The IoD 2025 Excel files in
# data/raw/iod2025 are kept in the repo (from gov.uk, English Indices of Deprivation 2025).
set -euo pipefail
cd "$(dirname "$0")"

# HM Land Registry Price Paid Data, one file per year (~150 MB each). Add years as needed.
mkdir -p data/raw/land_registry
for y in 2023 2024 2025 2026; do
  echo "Price paid $y"
  curl -sSfL -o "data/raw/land_registry/pp-$y.csv" \
    "http://prod.publicdata.landregistry.gov.uk.s3-website-eu-west-1.amazonaws.com/pp-$y.csv"
done

# ONS Postcode to OA (2021) to LSOA to MSOA to LAD (May 2026) Best Fit Lookup in the UK
mkdir -p data/raw/ons
curl -sSfL -o data/raw/ons/pcd_lsoa_may2026.zip \
  "https://www.arcgis.com/sharing/rest/content/items/2713c3a627454ff88add814226264d77/data"

# ONS LSOA 2021 boundaries (super generalised), Greater Manchester only
mkdir -p data/raw/boundaries
U="https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/LSOA_2021_EW_BSC_V4_RUC/FeatureServer/0/query"
W="LSOA21NM LIKE 'Bolton %' OR LSOA21NM LIKE 'Bury %' OR LSOA21NM LIKE 'Manchester %' OR LSOA21NM LIKE 'Oldham %' OR LSOA21NM LIKE 'Rochdale %' OR LSOA21NM LIKE 'Salford %' OR LSOA21NM LIKE 'Stockport %' OR LSOA21NM LIKE 'Tameside %' OR LSOA21NM LIKE 'Trafford %' OR LSOA21NM LIKE 'Wigan %'"
tmp=$(mktemp -d)
for o in 0 1000; do
  curl -sSf -G "$U" --data-urlencode "where=$W" --data-urlencode "outFields=LSOA21CD,LSOA21NM,RUC21NM" \
    -d outSR=4326 -d geometryPrecision=5 -d f=geojson -d resultRecordCount=1000 -d resultOffset=$o \
    -o "$tmp/part_$o.geojson"
done
python3 -I - "$tmp" <<'PY'
import json, sys
d = sys.argv[1]
fs = []
for o in (0, 1000):
    fs += json.load(open(f"{d}/part_{o}.geojson"))["features"]
json.dump({"type": "FeatureCollection", "features": fs}, open("data/raw/boundaries/gm_lsoa_2021.geojson", "w"))
print(f"Boundaries: {len(fs)} LSOAs")
PY
rm -rf "$tmp"
echo "Done. Now run: .venv/bin/python build_data.py"
