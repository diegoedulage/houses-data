"""Bring the data up to date by downloading only what changes, then rebuild the site.

  .venv/bin/python -I update_data.py                 # Land Registry (this + last year), schools, stops
  .venv/bin/python -I update_data.py --epc ~/Downloads/domestic-csv.zip   # also new EPCs
  .venv/bin/python -I update_data.py --uprn          # also refresh house coordinates (620 MB)
  .venv/bin/python -I update_data.py --no-download   # just rebuild from what's on disk

What changes over time, and what this does about it:
  Land Registry  new sales appear monthly; late registrations can land in last year's file
                 -> re-download this year and last year only (older years never change)
  EPC            new certificates every day, bulk zip needs a GOV.UK One Login (manual download)
                 -> with --epc, read only this year and last year from the zip, re-match sales
  OS Open UPRN   new addresses every ~6 weeks; only needed for newly matched sales -> --uprn
  Schools        register changes daily, Ofsted/census publish a few times a year -> register
                 re-downloaded; Ofsted and census URLs in download_data.sh when a new release is out
  Transport      NaPTAN changes slowly -> re-downloaded (small)
Deprivation (IoD 2025), boundaries, names and road noise only change with new national releases.
"""
import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PY = [sys.executable, "-I"]
RAW = ROOT / "data" / "raw"
LR = "http://prod.publicdata.landregistry.gov.uk.s3-website-eu-west-1.amazonaws.com/pp-{y}.csv"
NAPTAN = "https://naptan.api.dft.gov.uk/v1/access-nodes?dataFormat=csv&atcoAreaCodes={a}"
GIAS = "https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public/edubasealldata{d}.csv"
UPRN = "https://api.os.uk/downloads/v1/products/OpenUPRN/downloads?area=GB&format=CSV&redirect"


def run(cmd):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def fetch(url, dest):
    """curl uses the system certificate store (python.org builds often have none)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    run(["curl", "-sSfL", "-o", tmp, url])
    tmp.replace(dest)


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--epc", type=Path, help="a new EPC domestic bulk zip to take recent certificates from")
ap.add_argument("--uprn", action="store_true", help="re-download OS Open UPRN for new house coordinates")
ap.add_argument("--no-download", action="store_true", help="skip downloads, just re-extract and rebuild")
a = ap.parse_args()

year = dt.date.today().year
years = [year - 1, year]
steps = []

if not a.no_download:
    for y in years:
        fetch(LR.format(y=y), RAW / "land_registry" / f"pp-{y}.csv")
    for code in ["180", "060", "061", "068", "069", "910", "940"]:
        fetch(NAPTAN.format(a=code), RAW / "naptan" / f"naptan_{code}.csv")
    for back in range(7):  # the schools register is published daily; take the newest available
        d = (dt.date.today() - dt.timedelta(days=back)).strftime("%Y%m%d")
        try:
            fetch(GIAS.format(d=d), RAW / "schools" / f"gias_{d}.csv")
            for old in (RAW / "schools").glob("gias_*.csv"):
                if old.name != f"gias_{d}.csv":
                    old.unlink()
            break
        except subprocess.CalledProcessError:
            continue
    if a.uprn:
        fetch(UPRN, RAW / "uprn" / "osopenuprn_csv.zip")
    steps += ["schools", "census", "naptan"]

steps = ["ppd"] + steps
run(PY + ["make_extracts.py", "ppd", "--years", *map(str, years)])
if a.epc:
    run(PY + ["extract_epc.py", "--zip", a.epc, "--years", *map(str, years)])
# new sales need EPC matches and coordinates; both steps skip themselves if their raw data is absent
run(PY + ["make_extracts.py", "epc", "uprn", *[s for s in steps if s != "ppd"]])
run(PY + ["build_data.py"])
print("\nUpdated. Check the site, then commit data/extracts (and site/ if you publish it from git).")
