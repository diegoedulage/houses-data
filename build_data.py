"""Join Land Registry sold prices with IoD 2025 deprivation for Greater Manchester and Cheshire.

Inputs (data/raw/):
  land_registry/pp-YYYY.csv   HM Land Registry Price Paid Data (yearly files)
  ons/pcd_lsoa_*.zip          ONS postcode -> LSOA 2021 lookup
  iod2025/File_2_*.xlsx       IoD 2025 domains (LSOA 2021)
  boundaries/lsoa_2021.geojson
  names/msoa_names.csv        House of Commons Library neighbourhood (MSOA) names

Outputs (site/):
  data.js        areas + sales (columnar) used by index.html
  addresses.js   address of every sale, loaded when an area is opened
  boundaries.js  LSOA polygons

Run:  .venv/bin/python build_data.py
"""
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "site"
OUT.mkdir(exist_ok=True)

# Local authority code -> region. Cheshire = ceremonial county (incl. Warrington and Halton).
REGIONS = {**{f"E080000{i:02d}": "Greater Manchester" for i in range(1, 11)},
           "E06000049": "Cheshire", "E06000050": "Cheshire", "E06000007": "Cheshire", "E06000006": "Cheshire"}
LADS = list(REGIONS)

PPD_COLS = ["id", "price", "date", "postcode", "type", "new", "tenure", "paon", "saon",
            "street", "locality", "town", "district", "county", "category", "status"]

# ---------------------------------------------------------------- sales
sales = []
for f in sorted(glob.glob(str(RAW / "land_registry" / "pp-*.csv"))):
    df = pd.read_csv(f, header=None, names=PPD_COLS, dtype=str)
    df = df[df.category == "A"]  # standard residential sales; area filter happens via the postcode lookup
    sales.append(df)
    print(f"{Path(f).name}: {len(df):,} standard sales in England & Wales")
sales = pd.concat(sales, ignore_index=True)
sales["price"] = sales.price.astype(int)
sales["date"] = pd.to_datetime(sales.date)

# ---------------------------------------------------------------- postcode -> LSOA
zf = next((RAW / "ons").glob("pcd_lsoa_*.zip"))
lookup = pd.read_csv(zf, usecols=["pcds", "lsoa21cd", "msoa21cd", "ladcd"], dtype=str, encoding="latin-1")
lookup = lookup[lookup.ladcd.isin(LADS)]
lsoa_msoa = dict(zip(lookup.lsoa21cd, lookup.msoa21cd))
sales = sales.merge(lookup[["pcds", "lsoa21cd"]], left_on="postcode", right_on="pcds", how="inner")
print(f"Sales in covered areas: {len(sales):,}")

# ---------------------------------------------------------------- deprivation
iod_file = next((RAW / "iod2025").glob("File_2_*.xlsx"))
iod = pd.read_excel(iod_file, sheet_name="IoD2025 Domains")
iod = iod[iod["Local Authority District code (2024)"].isin(LADS)]


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

geo = json.loads((RAW / "boundaries" / "lsoa_2021.geojson").read_text())

names = pd.read_csv(RAW / "names" / "msoa_names.csv", encoding="utf-8-sig")
msoa_name = dict(zip(names.msoa21cd, names.msoa21hclnm))
geo_codes = {f["properties"]["LSOA21CD"] for f in geo["features"]}

areas = []
for _, r in iod.iterrows():
    a = {
        "code": r["LSOA code (2021)"],
        "name": r["LSOA name (2021)"],
        "lad": r["Local Authority District name (2024)"],
        "region": REGIONS[r["Local Authority District code (2024)"]],
        "hood": msoa_name.get(lsoa_msoa.get(r["LSOA code (2021)"]), ""),
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


# ---------------------------------------------------------------- schools
# Ofsted grades -> one shared colour category. The old 4-point scale (to 2024) and the
# report-card scale (from Nov 2025) are different, so this is only a rough common ground.
CAT = {"Exceptional": 1, "Strong standard": 2, "Expected standard": 3, "Needs attention": 4, "Urgent improvement": 5,
       "1": 1, "2": 2, "3": 4, "4": 5}
OLD = {"1": "Outstanding", "2": "Good", "3": "Requires improvement", "4": "Inadequate"}
RC_AREAS = ["Achievement", "Curriculum and teaching", "Inclusion", "Attendance and behaviour",
            "Personal development and wellbeing", "Leadership and governance",
            "Early years (where applicable)", "Post-16 provision (where applicable)"]
OLD_AREAS = {"Quality of education": "Latest OEIF quality of education",
             "Behaviour and attitudes": "Latest OEIF behaviour and attitudes",
             "Personal development": "Latest OEIF personal development",
             "Leadership and management": "Latest OEIF effectiveness of leadership and management",
             "Early years": "Latest OEIF early years provision (where applicable)",
             "Sixth form": "Latest OEIF sixth form provision (where applicable)"}

to_bng = Transformer.from_crs(4326, 27700, always_xy=True)
to_wgs = Transformer.from_crs(27700, 4326, always_xy=True)


def centroid(geom):
    """Area-weighted centroid (BNG metres) of the largest polygon."""
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    best = None
    for poly in polys:
        x, y = to_bng.transform(*np.array(poly[0]).T)
        cross = x[:-1] * y[1:] - x[1:] * y[:-1]
        a = cross.sum() / 2
        if best is None or abs(a) > abs(best[0]):
            cx = ((x[:-1] + x[1:]) * cross).sum() / (6 * a)
            cy = ((y[:-1] + y[1:]) * cross).sum() / (6 * a)
            best = (a, cx, cy)
    return best[1], best[2]


cent = {f["properties"]["LSOA21CD"]: centroid(f["geometry"]) for f in geo["features"]}
ax = np.array([cent[a["code"]] for a in areas])

gias = pd.read_csv(next((RAW / "schools").glob("gias_*.csv")), encoding="latin-1", dtype=str,
                   usecols=["URN", "EstablishmentStatus (name)", "Easting", "Northing", "NumberOfPupils",
                            "TypeOfEstablishment (name)", "Gender (name)", "ReligiousCharacter (name)"])
gias = gias[(gias["EstablishmentStatus (name)"] == "Open") & gias.Easting.notna()]
ofs = pd.read_csv(next((RAW / "schools").glob("ofsted_*.csv")), encoding="utf-8-sig", dtype=str)
ofs = ofs[ofs["Ofsted phase"].isin(["Primary", "Secondary"])]
sch = ofs.merge(gias, on="URN")
sch["e"], sch["n"] = sch.Easting.astype(float), sch.Northing.astype(float)
pad = 8000  # include schools just over the border
sch = sch[sch.e.between(ax[:, 0].min() - pad, ax[:, 0].max() + pad) &
          sch.n.between(ax[:, 1].min() - pad, ax[:, 1].max() + pad)].reset_index(drop=True)


def fmt_date(s):
    return pd.to_datetime(s, dayfirst=True).strftime("%Y-%m-%d") if isinstance(s, str) and s else ""


schools = []
for row in sch.to_dict("records"):
    s = {"name": row["School name"], "phase": row["Ofsted phase"][0], "urn": row["URN"],
         "la": row["Local authority"], "type": row["TypeOfEstablishment (name)"],
         "pupils": int(row["NumberOfPupils"]) if isinstance(row["NumberOfPupils"], str) else None,
         "faith": "" if row["ReligiousCharacter (name)"] in ("None", "Does not apply", None) or not isinstance(row["ReligiousCharacter (name)"], str) else row["ReligiousCharacter (name)"],
         "cat": 0, "scheme": "", "date": "", "head": "", "grades": []}
    if isinstance(row["Achievement"], str):  # report card (renewed framework, Nov 2025+)
        s.update(scheme="Report card", date=fmt_date(row["Inspection start date"]),
                 head="Achievement: " + row["Achievement"], cat=CAT[row["Achievement"]],
                 grades=[[k.replace(" (where applicable)", ""), row[k]] for k in RC_AREAS if isinstance(row[k], str)]
                 + ([["Safeguarding", row["Safeguarding standards"]]] if isinstance(row["Safeguarding standards"], str) else []))
    elif isinstance(row["Latest OEIF overall effectiveness"], str):
        oe = row["Latest OEIF overall effectiveness"]
        s.update(scheme="Graded inspection", date=fmt_date(row["Inspection start date of latest OEIF graded inspection"]),
                 grades=[[k, OLD[row[c]]] for k, c in OLD_AREAS.items() if row[c] in OLD])
        if oe in OLD:
            s.update(head=OLD[oe], cat=CAT[oe])
        elif row["Latest OEIF quality of education"] in OLD:  # Sept 2024+ inspections have no overall grade
            q = row["Latest OEIF quality of education"]
            s.update(head="Quality of education: " + OLD[q], cat=CAT[q])
        ug = row["Ungraded inspection overall outcome"]
        if isinstance(ug, str) and fmt_date(row["Date of latest ungraded inspection"]) > s["date"]:
            s["later"] = [fmt_date(row["Date of latest ungraded inspection"]), ug]
    ug = row["Ungraded inspection overall outcome"]
    if not s["scheme"] and isinstance(ug, str):  # only a short (ungraded) inspection on record
        s.update(scheme="Ungraded inspection", date=fmt_date(row["Date of latest ungraded inspection"]), head=ug,
                 cat=1 if ug.startswith("School remains Outstanding") else 2 if ug.startswith("School remains Good") else 0)
    lat_lon = to_wgs.transform(row["e"], row["n"])
    s["lon"], s["lat"] = round(lat_lon[0], 5), round(lat_lon[1], 5)
    schools.append(s)

sx = sch[["e", "n"]].to_numpy()
for i, a in enumerate(areas):
    d = np.hypot(sx[:, 0] - ax[i, 0], sx[:, 1] - ax[i, 1])
    near = []
    for ph in ("P", "S"):
        cand = [j for j in np.argsort(d) if schools[j]["phase"] == ph][:3]
        near += [[int(j), int(round(d[j], -1))] for j in cand]
    a["sch"] = near
print(f"Schools: {len(schools):,} primary/secondary in or near the covered areas")
(OUT / "schools.js").write_text("window.GM_SCHOOLS=" + json.dumps(schools, separators=(",", ":")) + ";")

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
