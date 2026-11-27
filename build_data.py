"""Build the website data (site/*.js) from the small extracts in data/extracts.

Needs only data/extracts (in git), not the multi-GB raw downloads: those are turned into extracts
by make_extracts.py. See pipeline_common.py for the three data layers.

Outputs (site/):
  data.js        areas + sales (columnar) used by index.html
  addresses.js   address and coordinates of every sale, loaded when an area is opened
  history.js     every Land Registry sale since 1995 of the same homes (price histories)
  boundaries.js  LSOA polygons
  schools.js     schools, Ofsted grades, pupil census
  stops.js       bus, tram and rail stops

Run:  .venv/bin/python -I build_data.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_common import (AGE_BANDS, EXT, LADS, RATINGS, REGIONS, SALES_FROM, SCHOOL_PAD, SITE,  # noqa: E402
                             home_key)

OUT = SITE
OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------- sales
# The analysis covers standard (category A) sales from SALES_FROM on; older years only feed each
# home's price history (see "sale history" below).
PPD_YEARS = sorted(int(p.stem[3:]) for p in (EXT / "ppd").glob("pp-*.parquet"))
sales = pd.concat([pd.read_parquet(EXT / "ppd" / f"pp-{y}.parquet") for y in PPD_YEARS if y >= SALES_FROM],
                  ignore_index=True)
sales = sales[sales.category == "A"].reset_index(drop=True)
print(f"Land Registry: {len(sales):,} standard sales from {SALES_FROM} in the covered postcodes")
sales["price"] = sales.price.astype(int)
sales["date"] = pd.to_datetime(sales.date)

# ---------------------------------------------------------------- postcode -> LSOA
lookup = pd.read_parquet(EXT / "postcodes.parquet")
lsoa_msoa = dict(zip(lookup.lsoa21cd, lookup.msoa21cd))
sales = sales.merge(lookup[["pcds", "lsoa21cd"]], left_on="postcode", right_on="pcds", how="inner")
print(f"Sales in covered areas: {len(sales):,}")

# ---------------------------------------------------------------- deprivation
iod = pd.read_parquet(EXT / "iod2025_domains.parquet")


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

geo = json.loads((EXT / "lsoa_2021.geojson").read_text())

names = pd.read_csv(EXT / "msoa_names.csv", encoding="utf-8-sig")
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

# ---------------------------------------------------------------- EPC facts and coordinates
# Matched by make_extracts.py (step "epc"): floor area, rooms, rating, build period and UPRN per
# Land Registry transaction. Coordinates come from OS Open UPRN via the UPRN.
m = EXT / "epc_matches.parquet"
if m.exists():
    em = pd.read_parquet(m).set_index("id")
    sales["f"] = sales.id.map(em.floor_m2).fillna(0).astype(int)
    sales["r"] = sales.id.map(em.rooms).fillna(0).astype(int)
    sales["e"] = sales.id.map(em.rating).fillna(-1).astype(int)
    sales["g"] = sales.id.map(em.age_band).fillna(-1).astype(int)
    sales["uprn"] = sales.id.map(em.uprn).fillna("")
    print(f"EPC matched: {(sales.f > 0).mean():.0%} of sales")
else:
    sales[["f", "r", "e", "g"]] = [0, 0, -1, -1]
    sales["uprn"] = ""
    print("No EPC matches (data/extracts/epc_matches.parquet): sizes and ratings left empty")

sale_lat = sale_lon = [0] * len(sales)
c = EXT / "uprn_coords.parquet"
if c.exists():
    coords = pd.read_parquet(c)
    ll = dict(zip(coords.UPRN, zip(coords.LATITUDE, coords.LONGITUDE)))
    got = [ll.get(u) for u in sales.uprn]
    sale_lat = [int(round(g[0] * 1e5)) if g else 0 for g in got]
    sale_lon = [int(round(g[1] * 1e5)) if g else 0 for g in got]
    print(f"Coordinates: {sum(1 for g in got if g) / len(sales):.0%} of sales")


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

gias = pd.read_parquet(EXT / "schools" / "gias.parquet")
gias = gias[(gias["EstablishmentStatus (name)"] == "Open") & gias.Easting.notna()]
gias["e"], gias["n"] = gias.Easting.astype(float), gias.Northing.astype(float)
gias["laestab"] = gias["LA (code)"].fillna("") + gias["EstablishmentNumber"].fillna("").str.zfill(4)
pad = SCHOOL_PAD  # include schools just over the border
gias = gias[gias.e.between(ax[:, 0].min() - pad, ax[:, 0].max() + pad) &
            gias.n.between(ax[:, 1].min() - pad, ax[:, 1].max() + pad)]

# State schools: Ofsted's state-funded file decides phase.
ofs = pd.read_parquet(EXT / "schools" / "ofsted_state.parquet")
ofs = ofs[ofs["Ofsted phase"].isin(["Primary", "Secondary"])].rename(columns={"Web Link": "link"})
state = ofs.merge(gias, on="URN")
state["phase"] = state["Ofsted phase"].str[0]
state["sector"] = "State"

# Private (independent) mainstream schools: every one is in the DfE register; Ofsted grades
# only the "non-association" ones, the rest are inspected by ISI (no published grades file).
ind = gias[gias["EstablishmentTypeGroup (name)"] == "Independent schools"].copy()
ind_ofs = pd.read_parquet(EXT / "schools" / "ofsted_independent.parquet")
ind_ofs = ind_ofs.rename(columns={"Web link to Ofsted provider page (opens in new window)": "link",
                                  "Inspection start date of latest OEIF standard inspection":
                                      "Inspection start date of latest OEIF graded inspection"})
ind = ind.merge(ind_ofs.drop(columns=["School name"]), on="URN", how="left")
ind["School name"] = ind["EstablishmentName"]
lo, hi = ind.StatutoryLowAge.astype(float), ind.StatutoryHighAge.astype(float)
# Prep schools (to 13) count as primary; senior schools (from 11) as secondary; 3-18 as both.
ind["phase"] = np.where(lo >= 11, "S", np.where(hi <= 13, "P", "PS"))
ind["sector"] = "Private"
sch = pd.concat([state, ind], ignore_index=True)
for c in ["Achievement", "Latest OEIF overall effectiveness", "Ungraded inspection overall outcome",
          "Date of latest ungraded inspection", "Inspection start date", "Safeguarding standards",
          "Latest OEIF quality of education", "link"]:
    if c not in sch:
        sch[c] = np.nan


# School census (DfE "Schools, pupils and their characteristics", Jan 2026): pupils, ethnicity,
# free school meals, first language. Matched on LA+establishment number: the file's URN column is
# mangled (e.g. "1e+05").
census = {}
if (EXT / "schools" / "census.parquet").exists():
    cz = pd.read_parquet(EXT / "schools" / "census.parquet")

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None  # suppressed ("c", "x", "z") or missing

    for le, g in cz.groupby("school_laestab"):
        row = {r.breakdown: (num(r.pupil_count), num(r.pupil_percent)) for r in g.itertuples() if r.breakdown_topic != "Ethnicity minor"}
        eth = [[r.breakdown, num(r.pupil_percent)] for r in g.itertuples()
               if r.breakdown_topic == "Ethnicity minor" and (num(r.pupil_percent) or 0) > 0]
        census[le] = {"pupils": int(row.get("Total", (0,))[0] or 0) or None,
                      "fsm": row.get("FSM eligible", (None, None))[1],
                      "eal": row.get("First language other than English", (None, None))[1],
                      "eth": sorted(eth, key=lambda x: -x[1])}
    print(f"School census: {len(census):,} schools matched")


def fmt_date(s):
    return pd.to_datetime(s, dayfirst=True).strftime("%Y-%m-%d") if isinstance(s, str) and s else ""


def txt(v):
    return v if isinstance(v, str) else ""


schools = []
for row in sch.to_dict("records"):
    faith = txt(row["ReligiousCharacter (name)"])
    s = {"name": row["School name"], "phase": row["phase"], "sector": row["sector"], "urn": row["URN"],
         "la": txt(row["LA (name)"]), "type": txt(row["TypeOfEstablishment (name)"]),
         "pupils": int(row["NumberOfPupils"]) if isinstance(row["NumberOfPupils"], str) else None,
         "ages": f'{row["StatutoryLowAge"]}-{row["StatutoryHighAge"]}' if isinstance(row["StatutoryLowAge"], str) else "",
         "gender": txt(row["Gender (name)"]) if txt(row["Gender (name)"]) in ("Boys", "Girls") else "",
         "faith": "" if faith in ("", "None", "Does not apply", "Unknown") else faith,
         "web": txt(row["SchoolWebsite"]), "link": txt(row["link"]),
         "capacity": int(row["SchoolCapacity"]) if isinstance(row["SchoolCapacity"], str) and row["SchoolCapacity"].isdigit() else None,
         **({"census": census[row["laestab"]]} if row["laestab"] in census else {}),
         "cat": 0, "scheme": "", "date": "", "head": "", "grades": []}
    if isinstance(row["Achievement"], str):  # report card (renewed framework, Nov 2025+)
        s.update(scheme="Report card", date=fmt_date(row["Inspection start date"]),
                 head="Achievement: " + row["Achievement"], cat=CAT.get(row["Achievement"], 0),
                 grades=[[k.replace(" (where applicable)", ""), row[k]] for k in RC_AREAS if isinstance(row[k], str)]
                 + ([["Safeguarding", row["Safeguarding standards"]]] if isinstance(row["Safeguarding standards"], str) else []))
    elif isinstance(row["Latest OEIF overall effectiveness"], str):
        oe = row["Latest OEIF overall effectiveness"]
        s.update(scheme="Graded inspection", date=fmt_date(row["Inspection start date of latest OEIF graded inspection"]),
                 grades=[[k, OLD[row[c]]] for k, c in OLD_AREAS.items() if row.get(c) in OLD])
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
    if not s["scheme"] and s["sector"] == "Private":
        insp = txt(row["InspectorateName (name)"])
        s["head"] = "Inspected by ISI (no grades)" if insp == "ISI" else "No Ofsted grade on record"
        s["insp"] = insp
    lon, lat = to_wgs.transform(row["e"], row["n"])
    s["lon"], s["lat"] = round(lon, 5), round(lat, 5)
    schools.append(s)

sx = sch[["e", "n"]].to_numpy()
for i, a in enumerate(areas):
    d = np.hypot(sx[:, 0] - ax[i, 0], sx[:, 1] - ax[i, 1])
    order = np.argsort(d)
    near = []
    for ph in ("P", "S"):  # 3 nearest state primaries and secondaries
        near += [[int(j), int(round(d[j], -1))] for j in
                 [j for j in order[:400] if schools[j]["sector"] == "State" and schools[j]["phase"] == ph][:3]]
    near += [[int(j), int(round(d[j], -1))] for j in  # 2 nearest private schools of any phase
             [j for j in order[:400] if schools[j]["sector"] == "Private"][:2]]
    a["sch"] = near
n_priv = sum(s["sector"] == "Private" for s in schools)
print(f"Schools: {len(schools) - n_priv:,} state and {n_priv:,} private in or near the covered areas")
(OUT / "schools.js").write_text("window.GM_SCHOOLS=" + json.dumps(schools, separators=(",", ":")) + ";")

# ---------------------------------------------------------------- public transport
# DfT NaPTAN stops: active bus stops, Metrolink tram stops and National Rail stations.
# Heritage railways (listed with trams in NaPTAN) are left out.
nap = pd.read_parquet(EXT / "naptan.parquet")
nap = nap[(nap.Status == "active") & nap.Easting.notna()]
nap["mode"] = np.select([nap.StopType.isin(["BCT", "BCS", "BCQ"]),
                         (nap.StopType == "MET") & nap.CommonName.str.contains("Metrolink", na=False),
                         nap.StopType == "RLY"], ["b", "t", "r"], "")
nap = nap[nap["mode"] != ""].copy()
nap["e"], nap["n"] = nap.Easting.astype(float), nap.Northing.astype(float)
nap = nap[nap.e.between(ax[:, 0].min() - pad, ax[:, 0].max() + pad) &
          nap.n.between(ax[:, 1].min() - pad, ax[:, 1].max() + pad)].reset_index(drop=True)


def stop_name(r):
    n = re.sub(r"\s*\((Manchester Metrolink)\)$", "", r.CommonName)
    n = re.sub(r"\s+Rail Station$", "", n)
    if r.mode == "b":
        ind = r.Indicator if isinstance(r.Indicator, str) else ""
        n = f"{n} ({ind})" if ind else n
        if isinstance(r.LocalityName, str) and r.LocalityName not in n:
            n += f", {r.LocalityName}"
    return n


stops = {"m": nap["mode"].tolist(), "name": [stop_name(r) for r in nap.itertuples()],
         "lat": [round(float(v), 5) for v in nap.Latitude], "lon": [round(float(v), 5) for v in nap.Longitude]}
(OUT / "stops.js").write_text("window.GM_STOPS=" + json.dumps(stops, separators=(",", ":")) + ";")

px = nap[["e", "n"]].to_numpy()
mode = nap["mode"].to_numpy()
for i, a in enumerate(areas):
    d = np.hypot(px[:, 0] - ax[i, 0], px[:, 1] - ax[i, 1])
    tr = {}
    for m in ("r", "t"):
        of_mode = np.where(mode == m)[0]
        j = of_mode[np.argmin(d[of_mode])]
        tr[m] = [int(j), int(round(d[j], -1))]
    tr["b400"] = int(((mode == "b") & (d <= 400)).sum())  # bus stops within ~5 minutes' walk
    tr["rt"] = min(tr["r"][1], tr["t"][1])                 # nearest train or tram stop, metres
    a["tr"] = tr
counts = nap["mode"].value_counts().to_dict()
print(f"Transport: {counts.get('b', 0):,} bus stops, {counts.get('t', 0)} tram stops, {counts.get('r', 0)} rail stations")

# ---------------------------------------------------------------- road noise
# Defra strategic noise map, Round 4 (2021 modelling), road traffic Lden (day-evening-night average),
# fetched as palette PNG tiles by fetch_noise.py. Each palette colour is one 5 dB band. Each home
# takes the band of the 10 m cell it sits in; if that cell has no value, the median of the 5 x 5
# cells around it. (Taking the loudest nearby cell instead overstates exposure: 91% vs 38% at 55 dB+.)
NOISE_BANDS = ["under 40", "40-45", "45-50", "50-55", "55-60", "60-65", "65-70", "70-75", "75-80", "80+"]
NOISE_COLORS = ["#ffffff", "#b8d6d1", "#cee4cc", "#e2f2bf", "#f3c683", "#e87e4d", "#cd463e", "#a11a4d", "#75085c", "#430a4a"]
NOISE_TILE = 20_000
noise = np.full(len(sales), -1, dtype=int)
noise_tiles = {}
for f in (EXT / "noise").glob("lden_*_*.png"):
    from PIL import Image
    _, e0, n0 = f.stem.split("_")
    img = Image.open(f)
    pal = img.getpalette() or []
    trans = img.info.get("transparency")
    lut = np.full(256, -1, dtype=np.int8)
    for k in range(len(pal) // 3):
        hexc = "#%02x%02x%02x" % tuple(pal[3 * k:3 * k + 3])
        alpha = trans[k] if isinstance(trans, (bytes, list, tuple)) and k < len(trans) else (0 if trans == k else 255)
        if alpha and hexc in NOISE_COLORS:
            lut[k] = NOISE_COLORS.index(hexc)
    noise_tiles[(int(e0), int(n0))] = lut[np.asarray(img)]
if noise_tiles:
    sx_, sy_ = to_bng.transform(np.array(sale_lon) / 1e5, np.array(sale_lat) / 1e5)
    for k in np.where(np.array(sale_lat) != 0)[0]:
        e0, n0 = int(sx_[k] // NOISE_TILE * NOISE_TILE), int(sy_[k] // NOISE_TILE * NOISE_TILE)
        t = noise_tiles.get((e0, n0))
        if t is None:
            continue
        c, r = int((sx_[k] - e0) // 10), int((n0 + NOISE_TILE - sy_[k]) // 10)
        if 0 <= r < t.shape[0] and 0 <= c < t.shape[1] and t[r, c] >= 0:
            noise[k] = int(t[r, c])
        else:
            win = t[max(r - 2, 0):r + 3, max(c - 2, 0):c + 3]
            win = win[win >= 0]
            noise[k] = int(np.median(win)) if win.size else -1
    print(f"Road noise: {(noise >= 0).mean():.0%} of sales with a noise band, "
          f"{(noise >= 4).sum() / max((noise >= 0).sum(), 1):.0%} of those at 55 dB Lden or more")
else:
    print("No noise tiles (data/extracts/noise/): run fetch_noise.py, then make_extracts.py noise")
sales_idx_area = np.array([idx[c] for c in sales.lsoa21cd])
for i, a in enumerate(areas):
    z = noise[(sales_idx_area == i) & (noise >= 0)]
    a["noisy"] = round(float((z >= 4).mean()) * 100) if len(z) else None  # % of sold homes at 55 dB+

data = {
    "updated": sales.date.max().strftime("%Y-%m-%d"),
    "first": sales.date.min().strftime("%Y-%m-%d"),
    "areas": areas,
    "ratings": RATINGS,
    "ageBands": AGE_BANDS,
    "noiseBands": NOISE_BANDS,
    "noiseColors": NOISE_COLORS,
    "sales": {
        "a": [idx[c] for c in sales.lsoa21cd],
        "p": sales.price.tolist(),
        "d": ((sales.date - epoch).dt.days).tolist(),
        "t": [TYPES.index(t) for t in sales.type],
        "n": [1 if n == "Y" else 0 for n in sales.new],
        "l": [1 if t == "L" else 0 for t in sales.tenure],  # 1 = leasehold, 0 = freehold
        "f": sales.f.astype(int).tolist(),   # floor area m2 (0 = no EPC match)
        "r": sales.r.astype(int).tolist(),   # habitable rooms
        "e": sales.e.astype(int).tolist(),   # EPC rating index into RATINGS (-1 = none)
        "g": sales.g.astype(int).tolist(),
        "z": noise.tolist(),                 # road noise band index into NOISE_BANDS (-1 = unknown)   # construction age band index into AGE_BANDS
    },
}
(OUT / "data.js").write_text("window.GM_DATA=" + json.dumps(data, separators=(",", ":")) + ";")
# ---------------------------------------------------------------- sale history
# Every Land Registry sale since 1995 of the same home (same postcode + flat/house + street), for
# the price history shown when a house is clicked. Includes category B sales (e.g. repossessions,
# buy-to-let to companies), flagged.
pcs = set(sales.postcode)
allp = pd.concat([pd.read_parquet(EXT / "ppd" / f"pp-{y}.parquet") for y in PPD_YEARS], ignore_index=True)
allp = allp[allp.postcode.isin(pcs)].drop_duplicates("id")
old_years = [y for y in PPD_YEARS if y < SALES_FROM]


allp["key"] = home_key(allp)
sale_keys = home_key(sales)
allp = allp[allp.key.isin(set(sale_keys))]  # only homes sold in the analysed period
allp["d"] = allp.date.str[:10].str.replace("-", "").astype(int)  # yyyymmdd
allp = allp.sort_values(["key", "d", "id"], kind="mergesort")
# split the sorted rows into one block per home in a single pass (groupby per home is very slow)
kv = allp.key.to_numpy(dtype=object)
cols = allp[["d", "price", "type", "tenure", "new", "category"]].astype(object).to_numpy()
cuts = np.flatnonzero(kv[1:] != kv[:-1]) + 1
starts = np.r_[0, cuts]
ends = np.r_[cuts, len(kv)]
hist_lists = {kv[s0]: cols[s0:e0] for s0, e0 in zip(starts, ends)}
keys, key_idx = [], {}
hist_of_sale = []
for k in sale_keys:
    h = hist_lists.get(k)
    if h is None or len(h) < 2:      # only this sale on record: nothing extra to show
        hist_of_sale.append(-1)
        continue
    if k not in key_idx:
        key_idx[k] = len(keys)
        keys.append([[int(d), int(pr), t, ten, 1 if nw == "Y" else 0, 1 if cat == "B" else 0]
                     for d, pr, t, ten, nw, cat in h])
    hist_of_sale.append(key_idx[k])
with_hist = sum(1 for h in hist_of_sale if h >= 0)
print(f"Sale history: {with_hist:,} sales ({with_hist / len(sales):.0%}) have earlier or later sales of the same home"
      f" (records back to {min(old_years) if old_years else SALES_FROM})")
(OUT / "history.js").write_text("window.GM_HIST=" + json.dumps({"homes": keys, "sale": hist_of_sale}, separators=(",", ":")) + ";")

(OUT / "addresses.js").write_text(
    "window.GM_ADDR=" + json.dumps([address(r) for r in sales.itertuples()], separators=(",", ":")) + ";\n"
    # house coordinates x 1e5 (0 = unknown), for Street View links
    + "window.GM_LL=" + json.dumps({"lat": sale_lat, "lon": sale_lon}, separators=(",", ":")) + ";")

for f in geo["features"]:
    f["properties"] = {"code": f["properties"]["LSOA21CD"]}
(OUT / "boundaries.js").write_text("window.GM_GEO=" + json.dumps(geo, separators=(",", ":")) + ";")

print(f"Sales written: {len(sales):,}  ({data['first']} to {data['updated']})")
for p in ("data.js", "addresses.js", "boundaries.js"):
    print(f"  site/{p}: {(OUT / p).stat().st_size / 1e6:.1f} MB")
