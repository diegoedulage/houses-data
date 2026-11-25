"""Join Land Registry sold prices with IoD 2025 deprivation for Greater Manchester.

Inputs (data/raw/):
  land_registry/pp-YYYY.csv   HM Land Registry Price Paid Data (yearly files)
  ons/pcd_lsoa_*.zip          ONS postcode -> LSOA 2021 lookup
  iod2025/File_2_*.xlsx       IoD 2025 domains (LSOA 2021)
  boundaries/gm_lsoa_2021.geojson

Outputs (site/):
  data.js        areas + sales (columnar) used by index.html
  addresses.js   address of every sale, loaded when an area is opened
  boundaries.js  LSOA polygons

Run:  .venv/bin/python build_data.py
"""
import glob
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "site"
OUT.mkdir(exist_ok=True)

GM_LADS = [f"E0800000{i}" for i in range(1, 10)] + ["E08000010"]

PPD_COLS = ["id", "price", "date", "postcode", "type", "new", "tenure", "paon", "saon",
            "street", "locality", "town", "district", "county", "category", "status"]

# ---------------------------------------------------------------- sales
sales = []
for f in sorted(glob.glob(str(RAW / "land_registry" / "pp-*.csv"))):
    df = pd.read_csv(f, header=None, names=PPD_COLS, dtype=str)
    df = df[(df.county == "GREATER MANCHESTER") & (df.category == "A")]
    sales.append(df)
    print(f"{Path(f).name}: {len(df):,} GM standard sales")
sales = pd.concat(sales, ignore_index=True)
sales["price"] = sales.price.astype(int)
sales["date"] = pd.to_datetime(sales.date)

# ---------------------------------------------------------------- postcode -> LSOA
zf = next((RAW / "ons").glob("pcd_lsoa_*.zip"))
lookup = pd.read_csv(zf, usecols=["pcds", "lsoa21cd", "ladcd"], dtype=str, encoding="latin-1")
lookup = lookup[lookup.ladcd.isin(GM_LADS)][["pcds", "lsoa21cd"]]
sales = sales.merge(lookup, left_on="postcode", right_on="pcds", how="left")
missing = sales.lsoa21cd.isna().sum()
print(f"Sales without an LSOA match: {missing:,} of {len(sales):,} (dropped)")
sales = sales.dropna(subset=["lsoa21cd"])

# ---------------------------------------------------------------- deprivation
iod_file = next((RAW / "iod2025").glob("File_2_*.xlsx"))
iod = pd.read_excel(iod_file, sheet_name="IoD2025 Domains")
iod = iod[iod["Local Authority District code (2024)"].isin(GM_LADS)]


def col(prefix, kind):
    return next(c for c in iod.columns if c.startswith(prefix) and kind in c)


DOMAINS = {
    "imd": "Index of Multiple Deprivation",
    "income": "Income",
    "employment": "Employment",
    "education": "Education, Skills and Training",
    "health": "Health Deprivation and Disability",
    "crime": "Crime",
    "housing": "Barriers to Housing and Services",
    "environment": "Living Environment",
}

geo = json.loads((RAW / "boundaries" / "gm_lsoa_2021.geojson").read_text())
geo_codes = {f["properties"]["LSOA21CD"] for f in geo["features"]}

areas = []
for _, r in iod.iterrows():
    a = {
        "code": r["LSOA code (2021)"],
        "name": r["LSOA name (2021)"],
        "lad": r["Local Authority District name (2024)"],
        "rank": int(r[col(DOMAINS["imd"], "Rank")]),
    }
    for key, label in DOMAINS.items():
        a[key] = int(r[col(label, "Decile")])
    areas.append(a)
areas.sort(key=lambda a: a["code"])
idx = {a["code"]: i for i, a in enumerate(areas)}
print(f"Areas: {len(areas)} (with boundary: {len(geo_codes & set(idx))})")

sales = sales[sales.lsoa21cd.isin(idx)].sort_values("date").reset_index(drop=True)
epoch = pd.Timestamp("2023-01-01")
TYPES = "DSTFO"


def address(r):
    parts = [r.saon, r.paon, r.street]
    return " ".join(p for p in parts if isinstance(p, str) and p).title() + ", " + r.postcode


data = {
    "updated": sales.date.max().strftime("%Y-%m-%d"),
    "first": sales.date.min().strftime("%Y-%m-%d"),
    "areas": areas,
    "sales": {
        "a": [idx[c] for c in sales.lsoa21cd],
        "p": sales.price.tolist(),
        "d": ((sales.date - epoch).dt.days).tolist(),
        "t": [TYPES.index(t) for t in sales.type],
        "n": [1 if n == "Y" else 0 for n in sales.new],
    },
}
(OUT / "data.js").write_text("window.GM_DATA=" + json.dumps(data, separators=(",", ":")) + ";")
(OUT / "addresses.js").write_text(
    "window.GM_ADDR=" + json.dumps([address(r) for r in sales.itertuples()], separators=(",", ":")) + ";")

for f in geo["features"]:
    f["properties"] = {"code": f["properties"]["LSOA21CD"]}
(OUT / "boundaries.js").write_text("window.GM_GEO=" + json.dumps(geo, separators=(",", ":")) + ";")

print(f"Sales written: {len(sales):,}  ({data['first']} to {data['updated']})")
for p in ("data.js", "addresses.js", "boundaries.js"):
    print(f"  site/{p}: {(OUT / p).stat().st_size / 1e6:.1f} MB")
