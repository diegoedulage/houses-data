# Licences and conditions

Checked 27 November 2026 against each publisher's licence page. This is a summary to help
decide what can be shared, not legal advice.

## Summary

| Data | Licence | What it means here |
|---|---|---|
| HM Land Registry Price Paid Data | Open Government Licence v3.0 (OGL) | Commercial and non-commercial use allowed. The **address fields** are processed against Ordnance Survey AddressBase and Royal Mail PAF; Royal Mail and OS allow them to be displayed "for the purpose of providing residential property price information services", which is what this site does. Other uses of the addresses need a Royal Mail licence. |
| EPC (MHCLG Energy Performance of Buildings data) | OGL for all fields **except** address 1–3 and postcode (UPRN is OGL) | The address and postcode fields are under Ordnance Survey / Royal Mail terms limited to energy-performance purposes. **They are used only locally to match certificates to sales and are never written to `data/extracts/` or the site**, which carry only floor area, rooms, rating, build period and UPRN, keyed by Land Registry transaction ID. Raw EPC files stay in `data/raw/` (not in git). |
| ONS postcode lookup, LSOA boundaries | OGL, with ONS, OS and Royal Mail attribution | Re-use in any format allowed with the attribution below. (Northern Ireland BT postcodes need a separate licence for commercial use; this project has none.) |
| OS Open UPRN | OGL (OS OpenData) | Free use with OS attribution. |
| IoD 2025, DfE schools register and census, Ofsted outcomes, DfT NaPTAN, Defra noise maps, House of Commons Library MSOA names | OGL | Free use with attribution. |
| Basemap tiles (Esri World Gray Canvas, loaded live) | Esri terms of use | Attribution shown on the map. For heavy or commercial public use, check Esri's terms or switch to another tile provider. |

## Required attribution (shown in the site footer)

- Contains HM Land Registry data © Crown copyright and database right 2026. This data is licensed under the Open Government Licence v3.0.
- Contains OS data © Crown copyright and database right 2026.
- Contains Royal Mail data © Royal Mail copyright and database right 2026.
- Source: Office for National Statistics licensed under the Open Government Licence v.3.0.
- Other public sector information licensed under the Open Government Licence v3.0.

## Personal data: decide before publishing publicly

The EPC guidance states that address-level energy performance data is **personal data** under
UK GDPR and the Data Protection Act 2018, and that whoever processes it becomes a **data
controller**. This site attaches EPC facts (size, rooms, rating, build period) and modelled road
noise to individual sold addresses. Keeping the repository private and the site on your own
computer is personal use. Publishing it to the internet is not, and would bring data-protection
obligations (a lawful basis such as legitimate interests, a privacy notice, a way for people to
ask for removal).

Options:
1. Keep the site private (local, or a password-protected host).
2. Publish it, taking on the controller obligations above.
3. Publish a version that shows EPC facts only as area averages, not per house (a code change).

Sources: GOV.UK "Get energy performance of buildings data", licensing restrictions and data
protection requirements pages; gov.uk Price Paid Data downloads page; ONS geography licences page;
Ordnance Survey OS Open UPRN product page.
