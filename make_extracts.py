"""Turn the raw downloads (data/raw, several GB) into small extracts (data/extracts, ~150 MB).

Each step reads one raw source, keeps only the covered area and the columns the site uses, and
writes Parquet (or copies small files). A step is skipped, keeping the existing extract, when its
raw input isn't on this computer, so an update only needs the new raw files.

  .venv/bin/python make_extracts.py                     # every step whose raw data is present
  .venv/bin/python make_extracts.py ppd --years 2026    # just refresh one Land Registry year
  .venv/bin/python make_extracts.py epc uprn            # re-match EPCs, refresh coordinates

Licence note: EPC address and postcode fields are NOT open data (Ordnance Survey / Royal Mail
terms). They are used here only to match certificates to sales; the extract keeps the matched
facts (floor area, rooms, rating, build period, UPRN), keyed by Land Registry transaction ID.
"""
import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_common import EXT, LADS, PPD_COLS, RATINGS, RAW, SALES_FROM, SCHOOL_PAD, age_band, norm  # noqa: E402

NUM = re.compile(r"\b\d+[A-Z]?\b")
to_bng = Transformer.from_crs(4326, 27700, always_xy=True)


def write(df, name):
    path = EXT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, compression="zstd", index=False)
    print(f"  {name}: {len(df):,} rows, {path.stat().st_size / 1e6:.1f} MB")


def covered_postcodes():
    return set(pd.read_parquet(EXT / "postcodes.parquet", columns=["pcds"]).pcds)


def area_bbox():
    """British National Grid box around the covered areas, padded for schools and stops."""
    geo = json.loads((EXT / "lsoa_2021.geojson").read_text())
    xs, ys = [], []
    for f in geo["features"]:
        g = f["geometry"]
        for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
            x, y = to_bng.transform(*np.array(poly[0]).T)
            xs.append(x)
            ys.append(y)
    xs, ys = np.concatenate(xs), np.concatenate(ys)
    return xs.min() - SCHOOL_PAD, xs.max() + SCHOOL_PAD, ys.min() - SCHOOL_PAD, ys.max() + SCHOOL_PAD


# ---------------------------------------------------------------- steps
def step_lookup():
    """ONS postcode -> LSOA/MSOA/LAD lookup, covered councils only."""
    zf = next((RAW / "ons").glob("pcd_lsoa_*.zip"), None)
    if not zf:
        return False
    lk = pd.read_csv(zf, usecols=["pcds", "lsoa21cd", "msoa21cd", "ladcd"], dtype=str, encoding="latin-1")
    write(lk[lk.ladcd.isin(LADS)], "postcodes.parquet")
    return True


def step_geo():
    """Small files copied as they are: LSOA boundaries and neighbourhood names."""
    done = False
    for src, dst in [(RAW / "boundaries" / "lsoa_2021.geojson", EXT / "lsoa_2021.geojson"),
                     (RAW / "names" / "msoa_names.csv", EXT / "msoa_names.csv")]:
        if src.exists():
            EXT.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            print(f"  {dst.name}: copied")
            done = True
    return done


def step_iod():
    """IoD 2025 domains, covered councils only."""
    f = next((RAW / "iod2025").glob("File_2_*.xlsx"), None)
    if not f:
        return False
    iod = pd.read_excel(f, sheet_name="IoD2025 Domains")
    iod = iod[iod["Local Authority District code (2024)"].isin(LADS)]
    write(iod, "iod2025_domains.parquet")
    return True


def step_ppd(years=None):
    """Land Registry Price Paid Data: one Parquet file per year, covered postcodes only.
    One file per year means an update only rewrites the years that changed."""
    files = {int(p.stem[3:]): p for p in (RAW / "land_registry").glob("pp-*.csv") if p.stem[3:].isdigit()}
    if years:
        files = {y: p for y, p in files.items() if y in years}
    if not files:
        return False
    pcs = covered_postcodes()
    for y, p in sorted(files.items()):
        parts = [c[c.postcode.isin(pcs)] for c in
                 pd.read_csv(p, header=None, names=PPD_COLS, dtype=str, chunksize=1_000_000)]
        write(pd.concat(parts, ignore_index=True), f"ppd/pp-{y}.parquet")
    return True


def analysed_sales():
    """Sales the site analyses (from SALES_FROM, category A), from the extracts."""
    years = sorted(int(p.stem[3:]) for p in (EXT / "ppd").glob("pp-*.parquet"))
    df = pd.concat([pd.read_parquet(EXT / "ppd" / f"pp-{y}.parquet") for y in years if y >= SALES_FROM])
    return df[df.category == "A"]


def step_epc():
    """Match each analysed sale to its EPC and keep only the matched facts.

    A sale matches a certificate with the same postcode whose address has the same house/flat
    numbers (or, for a named house, contains the name). Of several matches, the latest lodged on
    or before the sale wins, else the first after. Input: data/raw/epc/epc_covered.* (from
    extract_epc.py); EPC addresses stay in data/raw and are never written to the extracts."""
    src = next((p for p in [RAW / "epc" / "epc_covered.parquet", RAW / "epc" / "epc_covered.csv"] if p.exists()), None)
    if not src:
        return False
    sales = analysed_sales()
    epc = pd.read_parquet(src) if src.suffix == ".parquet" else pd.read_csv(src, dtype=str)
    epc = epc[epc.postcode.isin(set(sales.postcode))].copy()
    epc["full"] = (epc.address1.fillna("") + " " + epc.address2.fillna("") + " " + epc.address3.fillna("")).map(norm)
    epc["nums"] = epc.full.map(lambda t: frozenset(NUM.findall(t)))
    epc["area"] = pd.to_numeric(epc.total_floor_area, errors="coerce")
    epc["rooms"] = pd.to_numeric(epc.number_habitable_rooms, errors="coerce")
    # stable, fully specified order so ties (same lodgement date) always resolve the same way
    epc = epc.sort_values(["lodgement_date", "full", "uprn", "total_floor_area"], kind="mergesort", na_position="first")
    by_pc = {pc: g[["full", "nums", "lodgement_date", "area", "rooms", "current_energy_rating",
                    "construction_age_band", "uprn"]].to_numpy() for pc, g in epc.groupby("postcode")}
    rows = []
    for r in sales.itertuples():
        cands = by_pc.get(r.postcode)
        if cands is None:
            continue
        label = norm(f"{r.saon if isinstance(r.saon, str) else ''} {r.paon if isinstance(r.paon, str) else ''}")
        nums = frozenset(NUM.findall(label))
        sale_day = r.date[:10]
        best = None
        for c in cands:
            ok = c[1] == nums if nums else (label and label in c[0] and not c[1])
            if not ok or not (c[3] > 0):
                continue
            if c[2] <= sale_day or best is None or best[2] > sale_day:
                best = c  # sorted by date: keeps the latest before the sale, else the first after
                if c[2] > sale_day:
                    break
        if best is not None:
            rows.append((r.id, int(round(best[3])), int(best[4]) if best[4] == best[4] else 0,
                         RATINGS.index(best[5]) if best[5] in RATINGS else -1, age_band(best[6]),
                         str(best[7]).split(".")[0] if isinstance(best[7], str) else ""))
    out = pd.DataFrame(rows, columns=["id", "floor_m2", "rooms", "rating", "age_band", "uprn"])
    print(f"  EPC matched: {len(out) / len(sales):.0%} of {len(sales):,} sales")
    write(out, "epc_matches.parquet")
    return True


def step_uprn():
    """Coordinates (OS Open UPRN) for the UPRNs of matched sales; new UPRNs are added to the extract."""
    zf = next((RAW / "uprn").glob("osopenuprn*.zip"), None)
    if not zf or not (EXT / "epc_matches.parquet").exists():
        return False
    need = set(pd.read_parquet(EXT / "epc_matches.parquet", columns=["uprn"]).uprn) - {""}
    old = pd.read_parquet(EXT / "uprn_coords.parquet") if (EXT / "uprn_coords.parquet").exists() else None
    if old is not None and need <= set(old.UPRN):
        print("  uprn_coords.parquet: already complete")
        return True
    with zipfile.ZipFile(zf) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(name) as fh:
            parts = [c[c.UPRN.isin(need)] for c in pd.read_csv(
                fh, usecols=["UPRN", "LATITUDE", "LONGITUDE"], dtype={"UPRN": str}, chunksize=2_000_000,
                encoding="utf-8-sig")]
    write(pd.concat(parts, ignore_index=True), "uprn_coords.parquet")
    return True


def step_schools():
    """Schools register (GIAS) near the covered areas, plus their Ofsted records."""
    g = next((RAW / "schools").glob("gias_*.csv"), None)
    if not g:
        return False
    x0, x1, y0, y1 = area_bbox()
    gias = pd.read_csv(g, encoding="latin-1", dtype=str,
                       usecols=["URN", "EstablishmentName", "EstablishmentStatus (name)", "EstablishmentTypeGroup (name)",
                                "Easting", "Northing", "NumberOfPupils", "TypeOfEstablishment (name)", "Gender (name)",
                                "ReligiousCharacter (name)", "StatutoryLowAge", "StatutoryHighAge", "SchoolWebsite",
                                "InspectorateName (name)", "LA (name)", "LA (code)", "EstablishmentNumber",
                                "SchoolCapacity"])
    gias = gias[(gias["EstablishmentStatus (name)"] == "Open") & gias.Easting.notna()]
    e, n = gias.Easting.astype(float), gias.Northing.astype(float)
    gias = gias[e.between(x0, x1) & n.between(y0, y1)]
    write(gias, "schools/gias.parquet")
    urns = set(gias.URN)
    for pattern, name in [("ofsted_state_*.csv", "ofsted_state"), ("ofsted_independent_*.csv", "ofsted_independent")]:
        f = next((RAW / "schools").glob(pattern), None)
        if f:
            o = pd.read_csv(f, encoding="utf-8-sig", dtype=str)
            write(o[o.URN.isin(urns)], f"schools/{name}.parquet")
    return True


def step_census():
    """DfE school census: ethnicity, free school meals, first language and totals per school."""
    f = next((RAW / "schools").glob("census_school_level_*.csv*"), None)
    if not f or not (EXT / "schools" / "gias.parquet").exists():
        return False
    gias = pd.read_parquet(EXT / "schools" / "gias.parquet")
    want = set(gias["LA (code)"].fillna("") + gias["EstablishmentNumber"].fillna("").str.zfill(4))
    keep = {"Ethnicity minor", "First language", "Free school meal status", "Total"}
    parts = []
    for c in pd.read_csv(f, dtype=str, chunksize=2_000_000,
                         usecols=["school_laestab", "attendance_pattern", "sex", "breakdown_topic", "breakdown",
                                  "pupil_count", "pupil_percent"]):
        parts.append(c[c.school_laestab.isin(want) & c.breakdown_topic.isin(keep)
                       & (c.attendance_pattern == "Total") & (c.sex == "Total")])
    write(pd.concat(parts, ignore_index=True), "schools/census.parquet")
    return True


def step_naptan():
    """NaPTAN stops near the covered areas (all stop types; build_data.py picks bus, tram and rail)."""
    files = sorted((RAW / "naptan").glob("naptan_*.csv"))
    if not files:
        return False
    x0, x1, y0, y1 = area_bbox()
    nap = pd.concat([pd.read_csv(f, dtype=str, usecols=["ATCOCode", "CommonName", "Indicator", "LocalityName",
                                                        "Easting", "Northing", "Latitude", "Longitude",
                                                        "StopType", "Status"]) for f in files]).drop_duplicates("ATCOCode")
    nap = nap[nap.Easting.notna()]
    e, n = nap.Easting.astype(float), nap.Northing.astype(float)
    write(nap[e.between(x0, x1) & n.between(y0, y1)], "naptan.parquet")
    return True


def step_noise():
    """Defra road-noise map tiles (palette PNGs from fetch_noise.py), copied as they are."""
    tiles = sorted((RAW / "noise").glob("lden_*_*.png"))
    if not tiles:
        return False
    (EXT / "noise").mkdir(parents=True, exist_ok=True)
    for t in tiles:
        shutil.copyfile(t, EXT / "noise" / t.name)
    print(f"  noise/: {len(tiles)} tiles copied")
    return True


STEPS = {"lookup": step_lookup, "geo": step_geo, "iod": step_iod, "ppd": step_ppd, "epc": step_epc,
         "uprn": step_uprn, "schools": step_schools, "census": step_census, "naptan": step_naptan,
         "noise": step_noise}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("steps", nargs="*", help=f"steps to run (default: all): {', '.join(STEPS)}")
    ap.add_argument("--years", type=int, nargs="+", help="Land Registry years for the ppd step")
    a = ap.parse_args()
    unknown = [s for s in a.steps if s not in STEPS]
    if unknown:
        ap.error(f"unknown step(s): {', '.join(unknown)}")
    for name in a.steps or STEPS:
        print(f"[{name}]")
        ok = STEPS[name](a.years) if name == "ppd" else STEPS[name]()
        if not ok:
            print("  skipped: raw input not found, existing extract kept")
