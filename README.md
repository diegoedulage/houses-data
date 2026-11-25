# houses-data

Greater Manchester sold house prices joined to the English Indices of Deprivation 2025,
shown on an interactive web page: a map of every neighbourhood (LSOA), median price by
deprivation decile, a price vs deprivation scatter, and the list of sales in each area.

## View the page

```bash
python3 -m http.server 8765 --directory site
```

Then open http://localhost:8765.

## Data

| Folder | What | Source |
|---|---|---|
| `data/raw/iod2025/` | IoD 2025 Excel files (LSOA 2021) | MHCLG, gov.uk |
| `data/raw/land_registry/` | Price Paid Data, yearly CSVs (not in git, too large) | HM Land Registry |
| `data/raw/ons/` | Postcode → LSOA 2021 lookup, May 2026 (not in git) | ONS Open Geography Portal |
| `data/raw/boundaries/` | Greater Manchester LSOA 2021 boundaries | ONS Open Geography Portal |
| `site/*.js` | Joined output used by the page | `build_data.py` |

Only standard residential sales (Price Paid category A) are used. Sales are matched to
an LSOA through their postcode.

## Rebuild

```bash
python3 -m venv .venv && .venv/bin/pip install pandas openpyxl
./download_data.sh          # fetches Land Registry, ONS lookup and boundaries
.venv/bin/python build_data.py
```

To add a newer year, add it to the loop in `download_data.sh`. Land Registry updates
monthly; re-download the current year's file to refresh.

## Licences

Contains HM Land Registry data © Crown copyright and database right, licensed under the
Open Government Licence v3.0. Contains ONS and OS data © Crown copyright and database right.
