# Data sources

Every dataset AtmosGuard uses or could use, with where it comes from and how to
get it.

## Read this first

Two of these are in the repository and wired in. The rest are **documented
routes, not live connections** - the `status` column says which is which, and
the System page in the running app shows the same thing. Nothing in this project
claims to be fed by a source it is not actually reading.

Portal addresses are stable and are given verbatim. Deep links to individual
files are not: agencies reorganise them, and several portals issue a download
link only after you log in or accept terms. Confirm the exact path at the
source rather than assuming a URL here still resolves.

```bash
python -m app.ingest.download --list            # the catalogue
python -m app.ingest.download --source <id>     # fetch, or print how to
```

## Open access

_Direct download, no account needed._

### Sub-divisional monthly rainfall, 1901-2017 **[in use]**

**India Meteorological Department** - India

| | |
|---|---|
| Portal | <https://data.gov.in/> |
| Variables | rainfall |
| Resolution | Sub-division, monthly |
| Coverage | 1901-2017, 36 sub-divisions, 4,188 rows |
| Format | CSV |
| Licence | Government Open Data Licence - India (GODL). Attribute IMD. |
| Feeds | `app/core/imd.py -> climatology; app/core/climate.py -> trend analytics` |

Rainfall climatology and measured interannual variability for all 36 IMD sub-divisions. Every site constant in AtmosGuard is derived from it.

**How to get it.** Search the OGD catalogue for 'sub divisional monthly rainfall'. Published by IMD under the Ministry of Earth Sciences.

### District-wise daily rainfall, actual against normal **[in use]**

**India Meteorological Department (Hydromet Division)** - India

| | |
|---|---|
| Portal | <https://data.gov.in/> |
| Variables | rainfall |
| Resolution | District, daily |
| Coverage | 728 districts, 16,001 district-days in the copy held here |
| Format | CSV |
| Licence | Government Open Data Licence - India (GODL). Attribute IMD. |
| Feeds | `app/core/imd.py -> observations; app/core/verification.py -> bust labels` |

The observations forecasts are verified against, and the source of the bust labels the risk model is fitted on.

**How to get it.** OGD catalogue, 'district wise rainfall'. The same statistics are published daily by IMD's Hydromet Division at https://hydro.imd.gov.in/.

**Note.** Carries real-world untidiness the loader handles: duplicate state spellings (CHHATISGARH / CHHATTISGARH, TAMIL NADU / TAMILNADU) and blank measurements.

### India state and union territory boundaries **[in use]**

**DataMeet India community** - India

| | |
|---|---|
| Portal | <https://github.com/datameet/maps> |
| Variables | geometry |
| Resolution | State / union territory, WGS84 |
| Coverage | Current administrative boundaries |
| Format | Shapefile (converted to GeoJSON at build time) |
| Licence | CC BY 4.0. Attribution required wherever the geometry is shown, which the map's attribution control carries. |
| Feeds | `frontend/src/components/RiskMap.tsx -> the vector base layer` |

The map itself. 36 states and union territories, simplified and bundled with the app so the country renders without any tile CDN.

**How to get it.** States/Admin2 in the repository. `scripts/build_basemap.py` downloads it, simplifies 1.07 M vertices to about 8,100, and writes frontend/src/lib/india-basemap.json.

**Note.** Chosen over the several unlicensed India GeoJSON repositories in circulation: those carry no rights grant at all, and some explicitly disclaim accuracy. A cartographic aid, not an authoritative boundary - official boundaries of India are published by the Survey of India.

### Global Historical Climatology Network - Daily **[in use]**

**NOAA National Centers for Environmental Information** - United States (global archive; Indian stations via WMO exchange)

| | |
|---|---|
| Portal | <https://registry.opendata.aws/noaa-ghcn/> |
| Variables | tmax, tmin, precipitation |
| Resolution | Station, daily |
| Coverage | 28 Indian stations passing a fixed coverage rule, 1995-2021 |
| Format | CSV per station (by_station), converted to one gzipped CSV |
| Licence | Public domain (U.S. Government work). Cite Menne et al. (2012), J. Atmos. Oceanic Technol. 29, 897-910. |
| Feeds | `7-day station replay: forecast, bust probability and verification.` |

Real daily observations for the 7-day station replay: maximum and minimum temperature and rainfall at 28 Indian synoptic stations, 1995-2021. The model trains on 1995-2009 and every day of 2010-2021 is held out for verification.

**How to get it.** `python -m scripts.import_ghcn_daily` reads the station list, inventory and by_station files from the AWS Open Data mirror, drops every value carrying a NOAA quality flag, and writes data/ghcn/india_daily_1995_2021.csv.gz. Unreported days stay empty.

**Note.** Indian stations often do not report rainfall on dry days; such days are treated as unreported, never as 0 mm.

- <https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily>

### Mausam - current forecasts, warnings and nowcasts

**India Meteorological Department** - India

| | |
|---|---|
| Portal | <https://mausam.imd.gov.in/> |
| Variables | rainfall, temperature, wind, warnings |
| Resolution | District and city, daily with nowcast updates |
| Coverage | Current, rolling |
| Format | HTML / JSON endpoints |
| Licence | IMD terms of use; attribute IMD. |
| Feeds | `Would supply real hazard types for the warning map, replacing the types derived from the forecast here` |

IMD's own operational warning picture: district colour-coded warnings, nowcasts and city forecasts. The reference AtmosGuard's warning map is styled after, and the natural source for real hazard types.

**How to get it.** The site exposes JSON behind its dashboards; there is also https://api.imd.gov.in/api/v1/cityforecast. See app/ingest/imd_api.py, which ships an --inspect mode because the response schema is undocumented.

**Note.** Often reachable only from Indian networks, and blocks some cloud ranges - the client could not be verified against it from this project's build environment.

### ECMWF open forecast data (HRES and ENS)

**European Centre for Medium-Range Weather Forecasts** - International

| | |
|---|---|
| Portal | <https://data.ecmwf.int/forecasts/> |
| Variables | rainfall, temperature, wind, pressure |
| Resolution | 0.25 degree, 51 ensemble members, 3-hourly to T+144 |
| Coverage | Real time, roughly the last four days retained |
| Format | GRIB2 |
| Licence | Creative Commons CC BY 4.0. Attribute ECMWF. |
| Feeds | `Would replace app/core/synthetic.py entirely` |

Real ensemble members. This is the single dataset that would remove the last modelled component from AtmosGuard - the reconstruction exists only because no ensemble archive was to hand.

**How to get it.** No registration. Use the official client: `pip install ecmwf-opendata`, then request stream='enfo' (ensemble) or 'oper' (deterministic). See app/ingest/ecmwf_open.py.

**Note.** Only a few days of history are kept, so building a training archive means collecting it daily. That is the real cost of moving off the reconstruction, and it is why this is a roadmap item rather than a quick fix.

- <https://github.com/ecmwf/ecmwf-opendata>

### GFS and GEFS operational output

**NOAA / NCEP** - United States

| | |
|---|---|
| Portal | <https://nomads.ncep.noaa.gov/> |
| Variables | rainfall, temperature, wind, pressure |
| Resolution | GFS 0.25 degree; GEFS 0.5 degree, 31 members |
| Coverage | Real time; archives at https://www.ncei.noaa.gov/ |
| Format | GRIB2 |
| Licence | US Government work - public domain. |
| Feeds | `app/core/domain.py -> the GFS model entry` |

The third model in the comparison, and a genuinely independent one - which is what makes model disagreement informative rather than circular.

**How to get it.** NOMADS serves current cycles directly over HTTP, including GRIB subsetting. Older cycles come from the NCEI archive.

### India Water Resources Information System

**Ministry of Jal Shakti / Central Water Commission** - India

| | |
|---|---|
| Portal | <https://indiawris.gov.in/> |
| Variables | rainfall, reservoir, river |
| Resolution | Station, district and basin |
| Coverage | Varies by product; many series from 2000 |
| Format | JSON API / CSV |
| Licence | GODL-India. |
| Feeds | `Impact context for alerts (not yet implemented)` |

Rainfall, reservoir levels and river basin data - the impact context a disaster-management user needs alongside a forecast-reliability flag.

**How to get it.** The portal exposes REST endpoints behind its dashboards; no key for most public products.

## Key access

_Free API key from a self-service registration._

### ERA5 global reanalysis

**Copernicus Climate Change Service / ECMWF** - International

| | |
|---|---|
| Portal | <https://cds.climate.copernicus.eu/> |
| Variables | rainfall, temperature, wind, pressure, geopotential |
| Resolution | 0.25 degree, hourly |
| Coverage | 1940 to present |
| Format | NetCDF / GRIB |
| Licence | Copernicus licence - free reuse with attribution. |
| Feeds | `Verification truth and analogue pattern fields` |

The global reanalysis used everywhere for verification and for the pattern fields an analogue search needs.

**How to get it.** Free CDS account, accept the licence, then use the `cdsapi` Python client with the key from your CDS profile page.

- <https://cds.climate.copernicus.eu/how-to-api>

### Open Government Data platform API

**NIC, Ministry of Electronics and IT** - India

| | |
|---|---|
| Portal | <https://data.gov.in/> |
| Variables | various |
| Resolution | Per resource |
| Coverage | Per resource |
| Format | JSON / CSV / XML |
| Licence | GODL-India, per dataset. |
| Feeds | `Automated refresh of the IMD rainfall files` |

The programmatic route to most Indian government datasets, including the two IMD rainfall files this project already uses.

**How to get it.** Register at https://data.gov.in/ for a free API key, then call https://api.data.gov.in/resource/<resource-id>?api-key=<key>&format=json. See app/ingest/datagov.py.

## Account access

_Free account, usually with a data-use agreement to accept._

### TIGGE multi-model ensemble archive

**ECMWF / WMO THORPEX** - International

| | |
|---|---|
| Portal | <https://apps.ecmwf.int/datasets/data/tigge/> |
| Variables | rainfall, temperature, wind, pressure |
| Resolution | 0.5 degree, up to 51 members per centre, to T+360 |
| Coverage | 2006 to present |
| Format | GRIB |
| Licence | Research and education use; per-centre conditions apply. |
| Feeds | `Training archive for a properly fitted risk model` |

The canonical archive for exactly this problem: ensemble forecasts from ten centres, back to 2006, which is what a bust-risk model should really be trained on.

**How to get it.** Free ECMWF account, then the web interface or the `ecmwfapi` Python client. Research use; check the terms for each contributing centre.

**Note.** The right long-term answer for training data. Retrieval is slow - requests queue - so it is a batch job, not a live feed.

### IMDAA regional reanalysis

**NCMRWF** - India

| | |
|---|---|
| Portal | <https://rds.ncmrwf.gov.in/> |
| Variables | rainfall, temperature, wind, pressure, geopotential |
| Resolution | 12 km, hourly |
| Coverage | 1979 to present |
| Format | GRIB2 / NetCDF |
| Licence | Free for research with attribution; registration required. |
| Feeds | `Would replace the demonstration analogue catalogue in app/core/analogues.py` |

12 km reanalysis over India from 1979 - the gridded truth for verification, and the archive an analogue search should run over.

**How to get it.** Register on the NCMRWF Reanalysis Data Store and accept the data policy; datasets are then downloadable by variable and period.

### Gridded daily rainfall, 0.25 degree

**IMD Pune** - India

| | |
|---|---|
| Portal | <https://www.imdpune.gov.in/> |
| Variables | rainfall |
| Resolution | 0.25 x 0.25 degree, daily |
| Coverage | 1901 to present |
| Format | Binary (GRD) with documented layout, plus NetCDF for some years |
| Licence | IMD data supply policy; charges may apply for commercial use. |
| Feeds | `Would replace district-mean observations with grid-cell verification` |

Gauge-based gridded rainfall from 1901 - spatially complete, which district means are not, and the right basis for verifying on a grid.

**How to get it.** IMD Pune's data supply portal at https://dsp.imdpune.gov.in/. Some products are free for research; others are charged.

### INSAT-3D / 3DR satellite products

**Space Applications Centre, ISRO** - India

| | |
|---|---|
| Portal | <https://mosdac.gov.in/> |
| Variables | rainfall, cloud, humidity |
| Resolution | 4 km, half-hourly |
| Coverage | 2013 to present |
| Format | HDF5 / NetCDF / GeoTIFF |
| Licence | Free for research with attribution to ISRO/SAC. |
| Feeds | `Nowcast cross-check (not yet implemented)` |

Satellite-derived rainfall and cloud imagery - an independent check on whether a system is developing the way the models say.

**How to get it.** Free MOSDAC registration, then order products by date and type.

### Administrative boundaries

**Survey of India / NRSC Bhuvan** - India

| | |
|---|---|
| Portal | <https://bhuvan.nrsc.gov.in/> |
| Variables | geometry |
| Resolution | District and sub-district |
| Coverage | Current |
| Format | Shapefile / GeoJSON / WMS |
| Licence | Check per product; official boundaries carry usage conditions. |
| Feeds | `Authoritative replacement for the bundled community boundaries` |

Authoritative district and sub-division polygons, which would replace the schematic outline the map currently falls back to.

**How to get it.** Bhuvan's Thematic Services, or the boundary datasets published on data.gov.in. Survey of India is the authority for official boundaries.

## Restricted access

_Request form, institutional affiliation, or a paid licence._

### NCUM deterministic and NEPS ensemble output

**National Centre for Medium Range Weather Forecasting** - India

| | |
|---|---|
| Portal | <https://www.ncmrwf.gov.in/> |
| Variables | rainfall, temperature, wind, pressure |
| Resolution | NCUM-G 12 km global; NEPS 12 km, 22 members |
| Coverage | Operational, real time |
| Format | GRIB2 / NetCDF |
| Licence | By agreement with NCMRWF. |
| Feeds | `app/core/domain.py -> the NCMRWF-NCUM model entry` |

India's own operational medium-range model and its ensemble - the regional counterpart the dashboard compares against ECMWF and GFS.

**How to get it.** Products are shown publicly on the site; bulk data access needs a request to NCMRWF, normally with institutional affiliation.

## Attribution

The two IMD datasets in this repository are published by the **India
Meteorological Department**, Ministry of Earth Sciences, Government of India,
under the Government Open Data Licence - India (GODL). Any work built on them
should say so.

## What is still missing

The one component of AtmosGuard that is not measured is the **ensemble**. No
agency publishes an archive of historical ensemble members as a convenient
download, so the system reconstructs them around the real observed outcome and
labels that plainly throughout.

Two sources would close that gap, in order of effort:

1. **ECMWF open data** - real 51-member ensembles, free, no registration, but
   only a few days are retained. Collect daily to build an archive.
2. **TIGGE** - the proper answer: ten centres' ensembles back to 2006, which is
   what a bust-risk model should really be trained on. Needs a free ECMWF
   account and patience with the retrieval queue.
