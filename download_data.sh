#!/usr/bin/env bash
# Re-download the open datasets into data/raw/. The IoD 2025 Excel files in
# data/raw/iod2025 are kept in the repo (from gov.uk, English Indices of Deprivation 2025).
set -euo pipefail
cd "$(dirname "$0")"

# Local authorities covered (names as they start LSOA names). Keep in sync with REGIONS in build_data.py.
LADS=("Bolton" "Bury" "Manchester" "Oldham" "Rochdale" "Salford" "Stockport" "Tameside" "Trafford" "Wigan"
      "Cheshire East" "Cheshire West and Chester" "Warrington" "Halton")

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

# House of Commons Library MSOA (neighbourhood) names
mkdir -p data/raw/names
curl -sSfL -o data/raw/names/msoa_names.csv "https://houseofcommonslibrary.github.io/msoanames/MSOA-Names-Latest2.csv"

# Schools: DfE Get Information about Schools (daily extract; try the last week) and Ofsted outcomes.
# Ofsted publishes a new file twice a year: update the URL from
# https://www.gov.uk/government/collections/maintained-schools-and-academies-inspections-and-outcomes-official-statistics
mkdir -p data/raw/schools
for i in 0 1 2 3 4 5 6; do
  d=$(date -v-"$i"d +%Y%m%d 2>/dev/null || date -d "-$i day" +%Y%m%d)
  if curl -sSfL -o "data/raw/schools/gias_$d.csv" \
      "https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public/edubasealldata$d.csv"; then
    echo "Schools register $d"; find data/raw/schools -name 'gias_*.csv' ! -name "gias_$d.csv" -delete; break
  fi
  rm -f "data/raw/schools/gias_$d.csv"
done
curl -sSfL -o data/raw/schools/ofsted_2026-08-31.csv \
  "https://assets.publishing.service.gov.uk/media/6aec9e0a05bab4df5458aee2/State-funded_schools_inspections_and_outcomes_as_at_31_August_2026.csv"

# ONS LSOA 2021 boundaries (super generalised), covered authorities only
mkdir -p data/raw/boundaries
U="https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/LSOA_2021_EW_BSC_V4_RUC/FeatureServer/0/query"
tmp=$(mktemp -d)
for lad in "${LADS[@]}"; do
  echo "Boundaries: $lad"
  # "<name> 0" so "Manchester" doesn't also match other names; LSOA names are "<LAD> 001A".
  curl -sSf -G "$U" --data-urlencode "where=LSOA21NM LIKE '$lad 0%' OR LSOA21NM LIKE '$lad 1%' OR LSOA21NM LIKE '$lad 2%' OR LSOA21NM LIKE '$lad 3%'" \
    --data-urlencode "outFields=LSOA21CD,LSOA21NM" \
    -d outSR=4326 -d geometryPrecision=5 -d f=geojson -d resultRecordCount=2000 \
    -o "$tmp/${lad// /_}.geojson"
done
python3 -I - "$tmp" <<'PY'
import json, sys, glob
fs = []
for f in sorted(glob.glob(sys.argv[1] + "/*.geojson")):
    fs += json.load(open(f))["features"]
json.dump({"type": "FeatureCollection", "features": fs}, open("data/raw/boundaries/lsoa_2021.geojson", "w"))
print(f"Boundaries: {len(fs)} LSOAs")
PY
rm -rf "$tmp"
echo "Done. Now run: .venv/bin/python build_data.py"
