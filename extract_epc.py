"""Pull the covered councils' domestic EPCs out of the national bulk download.

Input:  a domestic bulk zip from GOV.UK "Get energy performance of buildings data" (needs a
        GOV.UK One Login): all certificates for England & Wales, one CSV per lodgement year,
        ~98 GB unzipped. Default: data/raw/epc/domestic-csv*.zip
Output: data/raw/epc/epc_covered.parquet  (only the columns and councils this project uses)

The zip is streamed, never unpacked. A full run reads every year (~20 min). For an update, pass
--years with only the newest years: those years are replaced and the rest of the file is kept.

  .venv/bin/python -I extract_epc.py                      # everything
  .venv/bin/python -I extract_epc.py --years 2026         # refresh just 2026's certificates
  .venv/bin/python -I extract_epc.py --zip ~/Downloads/domestic-csv.zip --years 2026

This file contains EPC address fields, which are NOT open data (Ordnance Survey / Royal Mail
terms), so it stays in data/raw (not in git). make_extracts.py keeps only the matched facts.
"""
import argparse
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_common import LADS, RAW  # noqa: E402

EPC = RAW / "epc"
COLS = ["address1", "address2", "address3", "postcode", "local_authority", "uprn", "lodgement_date",
        "current_energy_rating", "current_energy_efficiency", "total_floor_area", "number_habitable_rooms",
        "construction_age_band", "built_form", "property_type", "tenure", "main_fuel"]
OUT = EPC / "epc_covered.parquet"

ap = argparse.ArgumentParser()
ap.add_argument("--zip", type=Path, help="bulk zip (default: newest data/raw/epc/domestic-csv*.zip)")
ap.add_argument("--years", type=int, nargs="+", help="only these lodgement years (update mode)")
a = ap.parse_args()
zpath = a.zip or max(EPC.glob("domestic-csv*.zip"), key=lambda p: p.stat().st_mtime)

parts = []
with zipfile.ZipFile(zpath) as z:
    names = sorted(n for n in z.namelist() if re.fullmatch(r"certificates-\d{4}\.csv", n))
    if a.years:
        names = [n for n in names if int(n[13:17]) in a.years]
    for name in names:
        kept = 0
        with z.open(name) as fh:
            for chunk in pd.read_csv(fh, usecols=COLS, dtype=str, chunksize=500_000, low_memory=False):
                chunk = chunk[chunk.local_authority.isin(LADS)]
                parts.append(chunk)
                kept += len(chunk)
        print(f"{name}: {kept:,} certificates kept", flush=True)
new = pd.concat(parts, ignore_index=True)

if a.years:
    # replace those years in the existing file, keep the rest
    old = pd.read_parquet(OUT) if OUT.exists() else (
        pd.read_csv(EPC / "epc_covered.csv", dtype=str) if (EPC / "epc_covered.csv").exists() else new.iloc[:0])
    old = old[~old.lodgement_date.str[:4].astype(int).isin(a.years)]
    new = pd.concat([old, new], ignore_index=True)
new.to_parquet(OUT, compression="zstd", index=False)
print(f"Done: {len(new):,} certificates -> {OUT.relative_to(RAW.parent.parent)} ({OUT.stat().st_size / 1e6:.0f} MB)")
