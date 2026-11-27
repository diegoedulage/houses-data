#!/usr/bin/env bash
# Layer 1: download every open dataset into data/raw/ (~7 GB; not in git), then turn them into the
# small extracts in data/extracts/ (in git). Only needed to rebuild the extracts from scratch;
# for regular updates use update_data.py, which downloads only what changes.
# EPC needs a GOV.UK One Login: download it by hand (see README), then run extract_epc.py.
set -euo pipefail
cd "$(dirname "$0")"

# Local authorities covered (names as they start LSOA names). Keep in sync with REGIONS in build_data.py.
LADS=("Bolton" "Bury" "Manchester" "Oldham" "Rochdale" "Salford" "Stockport" "Tameside" "Trafford" "Wigan"
      "Cheshire East" "Cheshire West and Chester" "Warrington" "Halton")

# MHCLG English Indices of Deprivation 2025 (File 2 = domains, used by the site)
mkdir -p data/raw/iod2025
curl -sSfL -o "data/raw/iod2025/File_2_IoD2025_Domains_of_Deprivation.xlsx" \
  "https://assets.publishing.service.gov.uk/media/691decfae39a085bda43efcd/File_2_IoD2025_Domains_of_Deprivation.xlsx"

# OS Open UPRN: coordinates of every address (620 MB), for house positions and Street View
mkdir -p data/raw/uprn
curl -sSfL -o data/raw/uprn/osopenuprn_csv.zip \
  "https://api.os.uk/downloads/v1/products/OpenUPRN/downloads?area=GB&format=CSV&redirect"

# HM Land Registry Price Paid Data, one file per year (~100-200 MB each, ~5 GB in all).
# 2023 onwards is the analysed period (SALES_FROM in build_data.py); 1995-2022 only feed each
# home's price history. Re-download the current year monthly to pick up new sales.
mkdir -p data/raw/land_registry
for y in $(seq 1995 2026); do
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
curl -sSfL -o data/raw/schools/ofsted_state_2026-08-31.csv \
  "https://assets.publishing.service.gov.uk/media/6aec9e0a05bab4df5458aee2/State-funded_schools_inspections_and_outcomes_as_at_31_August_2026.csv"
# Private (non-association independent) schools inspected by Ofsted. Updated yearly:
# https://www.gov.uk/government/collections/independent-schools-inspections-and-outcomes
curl -sSfL -o data/raw/schools/ofsted_independent_2026-08-31.csv \
  "https://assets.publishing.service.gov.uk/media/6aff04d8b42780af16207872/Non-association_independent_schools_inspections_and_outcomes_at_31_August_2026.csv"

# DfE school census, January 2026 ("Schools, pupils and their characteristics", school level):
# pupils by ethnicity, free school meals, first language. ~46 MB compressed, 2.8 GB unpacked.
curl -sSf -o data/raw/schools/census_school_level_2025_26.csv.gz \
  "https://api.education.gov.uk/statistics/v1/data-sets/019e7403-4523-7749-b530-159f451dd83c/csv?dataSetVersion=1.0"

# DfT NaPTAN public transport stops: Greater Manchester (180), Cheshire East (060),
# Cheshire West and Chester (061), Halton (068), Warrington (069), National Rail (910), trams (940)
mkdir -p data/raw/naptan
for a in 180 060 061 068 069 910 940; do
  curl -sSf -o "data/raw/naptan/naptan_$a.csv" "https://naptan.api.dft.gov.uk/v1/access-nodes?dataFormat=csv&atcoAreaCodes=$a"
done

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
# Defra road noise map (Round 4, Lden), 42 map tiles (~14 MB); needs the boundaries above
.venv/bin/python -I fetch_noise.py

# Layer 2: small extracts for the covered area (steps without raw data, e.g. EPC, keep their extract)
.venv/bin/python -I make_extracts.py
# Layer 3: the site
.venv/bin/python -I build_data.py
