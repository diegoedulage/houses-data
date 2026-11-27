"""Settings and helpers shared by make_extracts.py, build_data.py and update_data.py.

Data is kept in three layers:
  data/raw/       original downloads, several GB, NOT in git (re-creatable with download_data.sh)
  data/extracts/  small Parquet/PNG files filtered to the covered area, in git: everything the
                  site needs, so the site can be rebuilt without the raw downloads
  site/           the website, generated from data/extracts by build_data.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
EXT = ROOT / "data" / "extracts"
SITE = ROOT / "site"

# Local authority code -> region. Cheshire = ceremonial county (incl. Warrington and Halton).
REGIONS = {**{f"E080000{i:02d}": "Greater Manchester" for i in range(1, 11)},
           "E06000049": "Cheshire", "E06000050": "Cheshire", "E06000007": "Cheshire", "E06000006": "Cheshire"}
LADS = list(REGIONS)

# The site analyses sales from this year on; older Land Registry years only feed price histories.
SALES_FROM = 2023

# Land Registry Price Paid Data columns (the CSVs have no header row).
PPD_COLS = ["id", "price", "date", "postcode", "type", "new", "tenure", "paon", "saon",
            "street", "locality", "town", "district", "county", "category", "status"]

RATINGS = "ABCDEFG"
# EPC build-period bands; newer certificates give an exact year, which is mapped into these.
AGE_BANDS = ["before 1900", "1900-1929", "1930-1949", "1950-1966", "1967-1975", "1976-1982", "1983-1990",
             "1991-1995", "1996-2002", "2003-2006", "2007-2011", "2012-2019", "2020 onwards"]
BAND_STARTS = [0, 1900, 1930, 1950, 1967, 1976, 1983, 1991, 1996, 2003, 2007, 2012, 2020]

SCHOOL_PAD = 8000  # metres: schools and stops this far outside the covered areas are included


def norm(t):
    """Normalise an address part for matching: upper case, '&' -> AND, no punctuation."""
    t = re.sub(r"[^A-Z0-9 ]", " ", str(t).upper().replace("&", " AND "))
    return " ".join(t.split())


def age_band(t):
    """Index into AGE_BANDS, or -1 when the certificate has no usable build period."""
    if not isinstance(t, str):
        return -1
    tl = t.lower()
    if "before 1900" in tl or "pre-1900" in tl:
        return 0
    yrs = re.findall(r"\d{4}", t)
    if not yrs:
        return -1
    y = int(yrs[0])
    if re.fullmatch(r"\s*\d{4}\s*", t):  # exact year (newer certificates)
        return 12 if y >= 2020 else 11 if y >= 2012 else max(k for k, lo in enumerate(BAND_STARTS) if y >= lo)
    # a band such as "England and Wales: 1930-1949"; "2012 onwards" / "2012-2021" go to 2012-2019
    return max(k for k, lo in enumerate(BAND_STARTS[:12]) if y >= lo)


def norm_series(s):
    """norm() for a whole pandas column at once (much faster than mapping row by row)."""
    s = s.fillna("").astype(str).str.upper().str.replace("&", " AND ", regex=False)
    return s.str.replace(r"[^A-Z0-9 ]", " ", regex=True).str.split().str.join(" ")


def home_key(df):
    """One string per home: postcode + flat (SAON) + house (PAON) + street, normalised."""
    return (df.postcode.fillna("") + "|" + norm_series(df.saon) + "|" + norm_series(df.paon)
            + "|" + norm_series(df.street))
