# houses-data

Greater Manchester and Cheshire sold house prices joined to the English Indices of Deprivation 2025,
shown on an interactive web page: a map of every neighbourhood (LSOA), median price by
deprivation decile, a price vs deprivation scatter, the list of sales in each area, and
nearby schools with their Ofsted grades.

## View the page

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -I build_data.py          # ~15 s: builds site/*.js from data/extracts
python3 -m http.server 8765 --directory site
```

Then open http://localhost:8765. A fresh clone only needs these three commands: the raw
downloads are not required.

## Data: three layers

| Layer | Folder | Size | In git? | Made by |
|---|---|---|---|---|
| 1. Raw downloads | `data/raw/` | ~15 GB | No | `download_data.sh`, `fetch_noise.py`, EPC by hand |
| 2. Extracts for the covered area | `data/extracts/` | ~80 MB | Yes | `make_extracts.py` (+ `extract_epc.py`) |
| 3. Website | `site/` (`index.html` + generated `*.js`) | ~40 MB | `index.html` only | `build_data.py` |

`build_data.py` reads only layer 2, so the site can be rebuilt from git alone. Layer 2 is Parquet
(compressed, columns trimmed) with one file per Land Registry year, so an update only rewrites the
years that changed.

| Extract | What | Source |
|---|---|---|
| `ppd/pp-YYYY.parquet` | Every sale 1995–2026 in the covered postcodes | HM Land Registry Price Paid Data |
| `postcodes.parquet` | Postcode → LSOA / MSOA / council | ONS postcode lookup (May 2026) |
| `iod2025_domains.parquet` | Deprivation ranks and deciles per LSOA | MHCLG IoD 2025 |
| `lsoa_2021.geojson`, `msoa_names.csv` | Boundaries, neighbourhood names | ONS, House of Commons Library |
| `epc_matches.parquet` | Floor area, rooms, rating, build period, UPRN per sale (no EPC addresses) | MHCLG EPC, matched locally |
| `uprn_coords.parquet` | House coordinates for matched UPRNs | OS Open UPRN |
| `schools/*.parquet` | Schools register, Ofsted outcomes, school census | DfE GIAS, Ofsted, DfE |
| `naptan.parquet` | Bus, tram and rail stops | DfT NaPTAN |
| `noise/*.png` | Road noise map tiles (Lden, 10 m) | Defra Round 4 |

## Updating

```bash
.venv/bin/python -I update_data.py                                  # sales, schools, stops
.venv/bin/python -I update_data.py --epc ~/Downloads/domestic-csv.zip   # + new EPCs
.venv/bin/python -I update_data.py --uprn                           # + new house coordinates
```

Only what changes is downloaded: this year's and last year's Land Registry files (older years
never change), the newest schools register and NaPTAN. With `--epc`, only this year's and last
year's certificates are read from the zip. Then the extracts are refreshed and the site rebuilt.
Commit `data/extracts/` afterwards. New Ofsted or school census releases: update their URLs in
`download_data.sh` and run `make_extracts.py schools census` after downloading.

To rebuild layer 2 from scratch: `./download_data.sh` (≈7 GB), download the EPC bulk zip by
hand (GOV.UK One Login, https://get-energy-performance-data.communities.gov.uk/) into
`data/raw/epc/`, then `.venv/bin/python -I extract_epc.py` (~20 min) and
`.venv/bin/python -I make_extracts.py epc uprn`.

## Publishing

`.github/workflows/publish-site.yml` builds the site from `data/extracts` and deploys it to GitHub
Pages. It runs only when started by hand. Read `LICENCES.md` first.

Covered: the 10 Greater Manchester boroughs and ceremonial Cheshire (Cheshire East, Cheshire West
and Chester, Warrington, Halton). To add an authority, add its code to `REGIONS` in `pipeline_common.py`,
its name to `LADS` in `download_data.sh` and its NaPTAN area code to the NaPTAN loops, then
rebuild layer 2.

Schools: each area lists its 3 nearest state primary, 3 nearest state secondary and 2 nearest
private (independent) schools by straight-line distance from the area's centre (not official
catchments). Grades come from the latest Ofsted inspection: report-card grades (from Nov 2025) or
the older 1–4 grades. Most well-known private schools are inspected by the Independent Schools
Inspectorate (ISI), which publishes no grades; those show as "Inspected by ISI".

Floor area, rooms, EPC rating and build period come from Energy Performance Certificates. A
sale is matched to a certificate with the same postcode and the same house/flat numbers (or
house name); about 98% of sales match. "Rooms" are habitable rooms, not bedrooms. Price per m²
uses the certificate's total floor area.

Sale history: the page analyses sales from 2023 (`SALES_FROM` in `pipeline_common.py`). Older years
(1995–2022) are only used for each home's price history, shown when a house is clicked: every
Land Registry sale of the same postcode + flat/house + street, with % change between sales.

Road noise: Defra's modelled road-traffic noise (Round 4, 2021, Lden) read from map tiles at each
home's 10 m square (`fetch_noise.py`). Areas show the share of homes sold at 55 dB or more; the
map can also overlay Defra's noise map live.

Schools also show pupil numbers, capacity, free school meals, first language and pupils' ethnic
groups from the January 2026 school census (state schools; private schools report totals only).

Transport: each area shows its nearest rail station and Metrolink stop and the number of bus
stops within 400 m of its centre (straight-line). The map can be coloured by distance to the
nearest train or tram stop. Stop locations only: no timetable or service frequency.

Only standard residential sales (Price Paid category A) are used. Sales are matched to
an LSOA through their postcode.

## Licences

See `LICENCES.md`.
