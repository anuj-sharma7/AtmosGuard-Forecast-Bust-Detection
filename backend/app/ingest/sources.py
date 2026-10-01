"""Catalogue of official data sources for AtmosGuard.

Every entry is a real, publicly documented portal. The catalogue is data rather
than prose so it can drive three things at once: the download CLI, the System
page in the UI, and `docs/DATA_SOURCES.md`.

**Read this before trusting a URL.** Portal-level addresses are stable and are
given here verbatim. Deep links to individual files are *not* stable - agencies
reorganise them, and several of these portals require you to accept terms or
log in before a download link is issued. So each entry gives the portal, the
dataset name as the agency publishes it, and what to look for once you are
there. Confirm the exact path at the source rather than assuming a link in this
file still resolves.

Access levels:
  open        - direct download, no account
  key         - free API key from a self-service registration
  account     - free account plus, usually, accepting a data-use agreement
  restricted  - request form, institutional affiliation, or paid licence
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    agency: str
    country: str
    portal: str
    #: What this gives AtmosGuard specifically.
    role: str
    variables: tuple[str, ...]
    resolution: str
    coverage: str
    fmt: str
    access: str
    #: How to find the dataset once you are on the portal.
    how_to_get: str
    licence: str
    #: Which part of the system this would replace or feed.
    feeds: str
    notes: str = ""
    status: str = "planned"
    docs: tuple[str, ...] = field(default_factory=tuple)


SOURCES: tuple[Source, ...] = (
    # ---------------------------------------------------------------- in use
    Source(
        id="imd-subdivision-rainfall",
        name="Sub-divisional monthly rainfall, 1901-2017",
        agency="India Meteorological Department",
        country="India",
        portal="https://data.gov.in/",
        role="Rainfall climatology and measured interannual variability for all "
        "36 IMD sub-divisions. Every site constant in AtmosGuard is derived from it.",
        variables=("rainfall",),
        resolution="Sub-division, monthly",
        coverage="1901-2017, 36 sub-divisions, 4,188 rows",
        fmt="CSV",
        access="open",
        how_to_get="Search the OGD catalogue for 'sub divisional monthly rainfall'. "
        "Published by IMD under the Ministry of Earth Sciences.",
        licence="Government Open Data Licence - India (GODL). Attribute IMD.",
        feeds="app/core/imd.py -> climatology; app/core/climate.py -> trend analytics",
        status="in use",
    ),
    Source(
        id="imd-district-daily-rainfall",
        name="District-wise daily rainfall, actual against normal",
        agency="India Meteorological Department (Hydromet Division)",
        country="India",
        portal="https://data.gov.in/",
        role="The observations forecasts are verified against, and the source of "
        "the bust labels the risk model is fitted on.",
        variables=("rainfall",),
        resolution="District, daily",
        coverage="728 districts, 16,001 district-days in the copy held here",
        fmt="CSV",
        access="open",
        how_to_get="OGD catalogue, 'district wise rainfall'. The same statistics are "
        "published daily by IMD's Hydromet Division at https://hydro.imd.gov.in/.",
        licence="Government Open Data Licence - India (GODL). Attribute IMD.",
        feeds="app/core/imd.py -> observations; app/core/verification.py -> bust labels",
        notes="Carries real-world untidiness the loader handles: duplicate state "
        "spellings (CHHATISGARH / CHHATTISGARH, TAMIL NADU / TAMILNADU) and blank "
        "measurements.",
        status="in use",
    ),
    Source(
        id="datameet-boundaries",
        name="India state and union territory boundaries",
        agency="DataMeet India community",
        country="India",
        portal="https://github.com/datameet/maps",
        role="The map itself. 36 states and union territories, simplified and "
        "bundled with the app so the country renders without any tile CDN.",
        variables=("geometry",),
        resolution="State / union territory, WGS84",
        coverage="Current administrative boundaries",
        fmt="Shapefile (converted to GeoJSON at build time)",
        access="open",
        how_to_get="States/Admin2 in the repository. `scripts/build_basemap.py` "
        "downloads it, simplifies 1.07 M vertices to about 8,100, and writes "
        "frontend/src/lib/india-basemap.json.",
        licence="CC BY 4.0. Attribution required wherever the geometry is shown, "
        "which the map's attribution control carries.",
        feeds="frontend/src/components/RiskMap.tsx -> the vector base layer",
        notes="Chosen over the several unlicensed India GeoJSON repositories in "
        "circulation: those carry no rights grant at all, and some explicitly "
        "disclaim accuracy. A cartographic aid, not an authoritative boundary - "
        "official boundaries of India are published by the Survey of India.",
        status="in use",
    ),
    Source(
        id="noaa-ghcn-daily",
        name="Global Historical Climatology Network - Daily",
        agency="NOAA National Centers for Environmental Information",
        country="United States (global archive; Indian stations via WMO exchange)",
        portal="https://registry.opendata.aws/noaa-ghcn/",
        role="Real daily observations for the 7-day station replay: maximum and "
        "minimum temperature and rainfall at 28 Indian synoptic stations, "
        "1995-2021. The model trains on 1995-2009 and every day of 2010-2021 "
        "is held out for verification.",
        variables=("tmax", "tmin", "precipitation"),
        resolution="Station, daily",
        coverage="28 Indian stations passing a fixed coverage rule, 1995-2021",
        fmt="CSV per station (by_station), converted to one gzipped CSV",
        access="open",
        how_to_get="`python -m scripts.import_ghcn_daily` reads the station list, "
        "inventory and by_station files from the AWS Open Data mirror, drops "
        "every value carrying a NOAA quality flag, and writes "
        "data/ghcn/india_daily_1995_2021.csv.gz. Unreported days stay empty.",
        licence="Public domain (U.S. Government work). Cite Menne et al. (2012), "
        "J. Atmos. Oceanic Technol. 29, 897-910.",
        feeds="7-day station replay: forecast, bust probability and verification.",
        notes="Indian stations often do not report rainfall on dry days; such days "
        "are treated as unreported, never as 0 mm.",
        status="in use",
        docs=(
            "https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily",
        ),
    ),
    # ------------------------------------------------------------- live operational feeds
    Source(
        id="imd-cityforecast-api",
        name="IMD Official 7-Day City Forecast & Warning Bulletin",
        agency="India Meteorological Department (National Weather Forecasting Centre)",
        country="India",
        portal="https://api.imd.gov.in/api/v1/cityforecastwarning",
        role="Live 113+ station daily weather observations, 7-day outlooks, and multi-tier "
        "color warnings (Red/Orange/Yellow/Green). Powers real-time early warning alerts "
        "and station-level convective bust probability scoring.",
        variables=("rainfall", "tmax", "tmin", "humidity", "warnings", "forecast_text"),
        resolution="Station / City, daily observations & 7-day horizon",
        coverage="113 operational weather observatories covering all Indian states and UTs",
        fmt="REST JSON / Geo-referenced",
        access="key",
        how_to_get="Registered API key access via api.imd.gov.in test console and operational endpoints.",
        licence="Government of India / IMD Official Weather Service Terms. Attribute IMD.",
        feeds="app/ingest/imd_live.py -> /api/imd/cityforecast, /api/imd/bust, /api/imd/alerts",
        notes="High-frequency operational feed with 24-hr observed rainfall, warning categories, and detailed meteorologist bulletins.",
        status="live feed",
        docs=("https://api.imd.gov.in/",),
    ),
    Source(
        id="imd-geoserver-wfs",
        name="IMD Operational GeoServer Sub-divisional Warnings",
        agency="India Meteorological Department",
        country="India",
        portal="https://reactjs.imd.gov.in/geoserver/wfs",
        role="Live sub-divisional color-coded weather warnings across all 36 meteorological "
        "subdivisions of India with Day 1 to Day 5 forecast codes.",
        variables=("warnings", "geometry", "hazard_codes"),
        resolution="Meteorological sub-division, live WFS vector layers",
        coverage="All 36 IMD sub-divisions nationwide",
        fmt="WFS GeoJSON",
        access="open",
        how_to_get="WFS endpoint queried with feature type `imd:subdiv_warnings_now`.",
        licence="Government of India / IMD Open Geospatial Service.",
        feeds="app/ingest/imd_live.py -> /api/imd/live, /api/warnings",
        status="live feed",
        docs=("https://mausam.imd.gov.in/",),
    ),
    Source(
        id="imd-mausam",
        name="Mausam - current forecasts, warnings and nowcasts",
        agency="India Meteorological Department",
        country="India",
        portal="https://mausam.imd.gov.in/",
        role="IMD's operational warning picture: district colour-coded "
        "warnings, nowcasts and city forecasts. The reference AtmosGuard's warning "
        "map is styled after, and the natural source for real hazard types.",
        variables=("rainfall", "temperature", "wind", "warnings"),
        resolution="District and city, daily with nowcast updates",
        coverage="Current, rolling",
        fmt="HTML / JSON endpoints",
        access="open",
        how_to_get="The site exposes JSON behind its dashboards; there is also "
        "https://api.imd.gov.in/api/v1/cityforecastwarning.",
        licence="IMD terms of use; attribute IMD.",
        feeds="Supplies hazard types and color-coded boundaries for the warning map.",
        notes="Official national weather service portal of India.",
        status="live feed",
    ),
    Source(
        id="ecmwf-open-data",
        name="ECMWF open forecast data (HRES and ENS)",
        agency="European Centre for Medium-Range Weather Forecasts",
        country="International",
        portal="https://data.ecmwf.int/forecasts/",
        role="Real ensemble members. This is the single dataset that would remove "
        "the last modelled component from AtmosGuard - the reconstruction exists "
        "only because no ensemble archive was to hand.",
        variables=("rainfall", "temperature", "wind", "pressure"),
        resolution="0.25 degree, 51 ensemble members, 3-hourly to T+144",
        coverage="Real time, roughly the last four days retained",
        fmt="GRIB2",
        access="open",
        how_to_get="No registration. Use the official client: `pip install ecmwf-opendata`, "
        "then request stream='enfo' (ensemble) or 'oper' (deterministic). See "
        "app/ingest/ecmwf_open.py.",
        licence="Creative Commons CC BY 4.0. Attribute ECMWF.",
        feeds="Would replace app/core/synthetic.py entirely",
        notes="Only a few days of history are kept, so building a training archive "
        "means collecting it daily. That is the real cost of moving off the "
        "reconstruction, and it is why this is a roadmap item rather than a quick fix.",
        docs=("https://github.com/ecmwf/ecmwf-opendata",),
    ),
    Source(
        id="tigge",
        name="TIGGE multi-model ensemble archive",
        agency="ECMWF / WMO THORPEX",
        country="International",
        portal="https://apps.ecmwf.int/datasets/data/tigge/",
        role="The canonical archive for exactly this problem: ensemble forecasts "
        "from ten centres, back to 2006, which is what a bust-risk model should "
        "really be trained on.",
        variables=("rainfall", "temperature", "wind", "pressure"),
        resolution="0.5 degree, up to 51 members per centre, to T+360",
        coverage="2006 to present",
        fmt="GRIB",
        access="account",
        how_to_get="Free ECMWF account, then the web interface or the `ecmwfapi` "
        "Python client. Research use; check the terms for each contributing centre.",
        licence="Research and education use; per-centre conditions apply.",
        feeds="Training archive for a properly fitted risk model",
        notes="The right long-term answer for training data. Retrieval is slow - "
        "requests queue - so it is a batch job, not a live feed.",
    ),
    Source(
        id="ncmrwf-ncum",
        name="NCUM deterministic and NEPS ensemble output",
        agency="National Centre for Medium Range Weather Forecasting",
        country="India",
        portal="https://www.ncmrwf.gov.in/",
        role="India's own operational medium-range model and its ensemble - the "
        "regional counterpart the dashboard compares against ECMWF and GFS.",
        variables=("rainfall", "temperature", "wind", "pressure"),
        resolution="NCUM-G 12 km global; NEPS 12 km, 22 members",
        coverage="Operational, real time",
        fmt="GRIB2 / NetCDF",
        access="restricted",
        how_to_get="Products are shown publicly on the site; bulk data access needs "
        "a request to NCMRWF, normally with institutional affiliation.",
        licence="By agreement with NCMRWF.",
        feeds="app/core/domain.py -> the NCMRWF-NCUM model entry",
    ),
    Source(
        id="imdaa",
        name="IMDAA regional reanalysis",
        agency="NCMRWF",
        country="India",
        portal="https://rds.ncmrwf.gov.in/",
        role="12 km reanalysis over India from 1979 - the gridded truth for "
        "verification, and the archive an analogue search should run over.",
        variables=("rainfall", "temperature", "wind", "pressure", "geopotential"),
        resolution="12 km, hourly",
        coverage="1979 to present",
        fmt="GRIB2 / NetCDF",
        access="account",
        how_to_get="Register on the NCMRWF Reanalysis Data Store and accept the "
        "data policy; datasets are then downloadable by variable and period.",
        licence="Free for research with attribution; registration required.",
        feeds="Would replace the demonstration analogue catalogue in app/core/analogues.py",
    ),
    Source(
        id="imd-gridded-rainfall",
        name="Gridded daily rainfall, 0.25 degree",
        agency="IMD Pune",
        country="India",
        portal="https://www.imdpune.gov.in/",
        role="Gauge-based gridded rainfall from 1901 - spatially complete, which "
        "district means are not, and the right basis for verifying on a grid.",
        variables=("rainfall",),
        resolution="0.25 x 0.25 degree, daily",
        coverage="1901 to present",
        fmt="Binary (GRD) with documented layout, plus NetCDF for some years",
        access="account",
        how_to_get="IMD Pune's data supply portal at https://dsp.imdpune.gov.in/. "
        "Some products are free for research; others are charged.",
        licence="IMD data supply policy; charges may apply for commercial use.",
        feeds="Would replace district-mean observations with grid-cell verification",
    ),
    Source(
        id="era5",
        name="ERA5 global reanalysis",
        agency="Copernicus Climate Change Service / ECMWF",
        country="International",
        portal="https://cds.climate.copernicus.eu/",
        role="The global reanalysis used everywhere for verification and for the "
        "pattern fields an analogue search needs.",
        variables=("rainfall", "temperature", "wind", "pressure", "geopotential"),
        resolution="0.25 degree, hourly",
        coverage="1940 to present",
        fmt="NetCDF / GRIB",
        access="key",
        how_to_get="Free CDS account, accept the licence, then use the `cdsapi` "
        "Python client with the key from your CDS profile page.",
        licence="Copernicus licence - free reuse with attribution.",
        feeds="Verification truth and analogue pattern fields",
        docs=("https://cds.climate.copernicus.eu/how-to-api",),
    ),
    Source(
        id="noaa-gfs",
        name="GFS and GEFS operational output",
        agency="NOAA / NCEP",
        country="United States",
        portal="https://nomads.ncep.noaa.gov/",
        role="The third model in the comparison, and a genuinely independent one - "
        "which is what makes model disagreement informative rather than circular.",
        variables=("rainfall", "temperature", "wind", "pressure"),
        resolution="GFS 0.25 degree; GEFS 0.5 degree, 31 members",
        coverage="Real time; archives at https://www.ncei.noaa.gov/",
        fmt="GRIB2",
        access="open",
        how_to_get="NOMADS serves current cycles directly over HTTP, including "
        "GRIB subsetting. Older cycles come from the NCEI archive.",
        licence="US Government work - public domain.",
        feeds="app/core/domain.py -> the GFS model entry",
    ),
    # ----------------------------------------------------------- supporting
    Source(
        id="india-wris",
        name="India Water Resources Information System",
        agency="Ministry of Jal Shakti / Central Water Commission",
        country="India",
        portal="https://indiawris.gov.in/",
        role="Rainfall, reservoir levels and river basin data - the impact context "
        "a disaster-management user needs alongside a forecast-reliability flag.",
        variables=("rainfall", "reservoir", "river"),
        resolution="Station, district and basin",
        coverage="Varies by product; many series from 2000",
        fmt="JSON API / CSV",
        access="open",
        how_to_get="The portal exposes REST endpoints behind its dashboards; no key "
        "for most public products.",
        licence="GODL-India.",
        feeds="Impact context for alerts (not yet implemented)",
    ),
    Source(
        id="mosdac",
        name="INSAT-3D / 3DR satellite products",
        agency="Space Applications Centre, ISRO",
        country="India",
        portal="https://mosdac.gov.in/",
        role="Satellite-derived rainfall and cloud imagery - an independent check "
        "on whether a system is developing the way the models say.",
        variables=("rainfall", "cloud", "humidity"),
        resolution="4 km, half-hourly",
        coverage="2013 to present",
        fmt="HDF5 / NetCDF / GeoTIFF",
        access="account",
        how_to_get="Free MOSDAC registration, then order products by date and type.",
        licence="Free for research with attribution to ISRO/SAC.",
        feeds="Nowcast cross-check (not yet implemented)",
    ),
    Source(
        id="datagov-api",
        name="Open Government Data platform API",
        agency="NIC, Ministry of Electronics and IT",
        country="India",
        portal="https://data.gov.in/",
        role="The programmatic route to most Indian government datasets, including "
        "the two IMD rainfall files this project already uses.",
        variables=("various",),
        resolution="Per resource",
        coverage="Per resource",
        fmt="JSON / CSV / XML",
        access="key",
        how_to_get="Register at https://data.gov.in/ for a free API key, then call "
        "https://api.data.gov.in/resource/<resource-id>?api-key=<key>&format=json. "
        "See app/ingest/datagov.py.",
        licence="GODL-India, per dataset.",
        feeds="Automated refresh of the IMD rainfall files",
    ),
    Source(
        id="soi-boundaries",
        name="Administrative boundaries",
        agency="Survey of India / NRSC Bhuvan",
        country="India",
        portal="https://bhuvan.nrsc.gov.in/",
        role="Authoritative district and sub-division polygons, which would replace "
        "the schematic outline the map currently falls back to.",
        variables=("geometry",),
        resolution="District and sub-district",
        coverage="Current",
        fmt="Shapefile / GeoJSON / WMS",
        access="account",
        how_to_get="Bhuvan's Thematic Services, or the boundary datasets published "
        "on data.gov.in. Survey of India is the authority for official boundaries.",
        licence="Check per product; official boundaries carry usage conditions.",
        feeds="Authoritative replacement for the bundled community boundaries",
    ),
)

SOURCES_BY_ID = {s.id: s for s in SOURCES}

ACCESS_ORDER = ("open", "key", "account", "restricted")


def by_access(level: str) -> list[Source]:
    return [s for s in SOURCES if s.access == level]


def in_use() -> list[Source]:
    return [s for s in SOURCES if s.status == "in use"]
