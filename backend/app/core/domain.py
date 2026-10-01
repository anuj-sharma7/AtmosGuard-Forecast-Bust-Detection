"""Domain reference data: monitoring sites, variables, NWP models, regimes.

Each site carries only what cannot be measured - its name, its coordinates, and
which IMD sub-division and reporting district it belongs to. Everything that
*can* be measured is derived from the real IMD record at import time rather
than hand-tuned:

* ``rain_climatology`` - the sub-division's real mean rainfall for the season.
* ``historical_skill`` - derived from real interannual variability. A region
  whose annual rainfall swings by a third between years genuinely resists
  medium-range prediction; one that repeats itself does not.
* ``convective_index`` - derived from the real month-to-month variability of
  rainfall within the sub-division.

Replacing invented constants with measured ones matters beyond tidiness: the
risk model weights these quantities, so if they were arbitrary the ranking they
produce would be arbitrary too.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from . import imd


@dataclass(frozen=True)
class Location:
    """A monitoring site: a city or an IMD sub-divisional cell."""

    id: str
    name: str
    state: str
    lat: float
    lon: float
    #: IMD sub-division supplying the 1901-2017 rainfall climatology.
    subdivision: str
    #: State whose district observations represent this site.
    obs_state: str
    #: Reporting district, for city sites. Region sites use the state area-mean.
    obs_district: str | None = None
    featured: bool = False
    #: Mean 2 m temperature (degC). Supplied, not measured: the IMD datasets in
    #: use are rainfall-only, and inventing a temperature record would be worse
    #: than declaring this one constant.
    temp_climatology: float = 30.0

    @cached_property
    def _climatology(self) -> imd.Climatology | None:
        return imd.climatology(self.subdivision)

    @cached_property
    def rain_climatology(self) -> float:
        """Real peak-monsoon rainfall for this sub-division, mm/day."""
        clim = self._climatology
        if clim is None:
            return 30.0
        # July-August is the climatological peak across the Indian domain.
        return max((clim.daily_mean(7) + clim.daily_mean(8)) / 2.0, 1.5)

    def rain_climatology_for(self, month: int) -> float:
        """Real mean rainfall for a given calendar month, mm/day."""
        clim = self._climatology
        return max(clim.daily_mean(month), 0.2) if clim else 5.0

    @cached_property
    def annual_variability(self) -> float:
        """Measured coefficient of variation of annual rainfall."""
        clim = self._climatology
        return clim.variability if clim else 0.25

    @cached_property
    def historical_skill(self) -> float:
        """Long-run medium-range skill, 0-1, from real interannual variability.

        Anchored so a typical sub-division (CV ~0.22) scores about 0.62, the
        most stable (Kerala, CV 0.15) about 0.75, and the most erratic
        (West Rajasthan, CV 0.37) about 0.40.
        """
        return float(min(0.85, max(0.30, 0.78 - 1.55 * (self.annual_variability - 0.15))))

    @cached_property
    def convective_index(self) -> float:
        """How erratic rainfall is month to month, 0-1, from the real record.

        Sub-divisions whose monthly totals vary wildly relative to their mean
        are dominated by short-lived convective events rather than steady
        large-scale forcing, and their forecasts fail more often at Day 5+.
        """
        clim = self._climatology
        if clim is None:
            return 0.65
        monsoon = range(6, 10)  # June-September
        ratios = [
            clim.month_sd(m) / clim.month_mean(m)
            for m in monsoon
            if clim.month_mean(m) > 1.0
        ]
        if not ratios:
            return 0.65
        mean_ratio = sum(ratios) / len(ratios)
        return float(min(0.95, max(0.25, mean_ratio * 1.45)))


#: The ten featured forecast points, each tied to its IMD sub-division for
#: climatology and to a real reporting district for observations.
LOCATIONS: tuple[Location, ...] = (
    Location("jaipur", "Jaipur", "Rajasthan", 26.9124, 75.7873,
             "East Rajasthan", "RAJASTHAN", "JAIPUR", True, 33.5),
    Location("delhi", "Delhi", "Delhi NCR", 28.6139, 77.2090,
             "Haryana Delhi & Chandigarh", "DELHI", "NEW DELHI", True, 34.2),
    Location("mumbai", "Mumbai", "Maharashtra", 19.0760, 72.8777,
             "Konkan & Goa", "MAHARASHTRA", "MUMBAI CITY", True, 29.4),
    Location("chennai", "Chennai", "Tamil Nadu", 13.0827, 80.2707,
             "Tamil Nadu", "TAMIL NADU", "CHENNAI", True, 32.1),
    Location("kolkata", "Kolkata", "West Bengal", 22.5726, 88.3639,
             "Gangetic West Bengal", "WEST BENGAL", "KOLKATA", True, 31.0),
    Location("guwahati", "Guwahati", "Assam", 26.1445, 91.7362,
             "Assam & Meghalaya", "ASSAM", "KAMRUP METRO", True, 29.8),
    Location("bengaluru", "Bengaluru", "Karnataka", 12.9716, 77.5946,
             "South Interior Karnataka", "KARNATAKA", "BANGLORE URBAN", True, 27.6),
    Location("hyderabad", "Hyderabad", "Telangana", 17.3850, 78.4867,
             "Telangana", "TELANGANA", "HYDERABAD", True, 31.4),
    Location("patna", "Patna", "Bihar", 25.5941, 85.1376,
             "Bihar", "BIHAR", "PATNA", True, 32.0),
    Location("srinagar", "Srinagar", "Jammu & Kashmir", 34.0837, 74.7973,
             "Jammu & Kashmir", "JAMMU & KASHMIR", "SRINAGAR", True, 24.5),
)

LOCATIONS_BY_ID = {loc.id: loc for loc in LOCATIONS}


@dataclass(frozen=True)
class Variable:
    id: str
    label: str
    unit: str
    # Axis label used by the ensemble chart.
    axis_label: str
    # Relative difficulty of medium-range prediction (1.0 = hardest).
    predictability_penalty: float


VARIABLES: tuple[Variable, ...] = (
    Variable("rainfall", "Rainfall", "mm", "Rainfall (mm/day)", 1.00),
    Variable("temperature", "Temperature", "degC", "2 m Temperature (degC)", 0.52),
    Variable("wind", "Wind", "m/s", "10 m Wind Speed (m/s)", 0.71),
    Variable("pressure", "Pressure", "hPa", "MSLP (hPa)", 0.44),
)

VARIABLES_BY_ID = {v.id: v for v in VARIABLES}


@dataclass(frozen=True)
class NWPModel:
    id: str
    label: str
    centre: str
    # Long-run relative skill of the model in the Indian domain, 0-1.
    skill: float
    # Systematic bias multiplier applied to the deterministic run.
    bias: float
    has_ensemble: bool


MODELS: tuple[NWPModel, ...] = (
    NWPModel("ecmwf", "ECMWF", "ECMWF IFS / ENS", 0.86, 1.00, True),
    NWPModel("ncmrwf", "NCMRWF-NCUM", "NCMRWF NCUM-G / NEPS", 0.78, 0.93, True),
    NWPModel("gfs", "GFS", "NOAA NCEP GFS / GEFS", 0.74, 1.12, True),
    NWPModel("ensemble", "Multi-Model Ensemble", "ECMWF + NCUM + GFS", 0.88, 1.01, True),
)

MODELS_BY_ID = {m.id: m for m in MODELS}

DETERMINISTIC_MODEL_IDS = ("ecmwf", "ncmrwf", "gfs")

# Synoptic regimes used by the synthetic provider and the analogue engine.
REGIMES: tuple[str, ...] = (
    "Active monsoon trough",
    "Break monsoon",
    "Low-pressure area / depression",
    "Western disturbance interaction",
    "Bay of Bengal cyclonic circulation",
    "Arabian Sea moisture surge",
    "Post-monsoon anticyclonic ridge",
)

# Display bands (inclusive integer ranges, as shown in the UI legend) paired
# with the exact upper bound used for classification. Using an explicit upper
# bound avoids the classic gap bug where a score of 60.6 falls between the
# "31-60" and "61-80" buckets and silently defaults to LOW.
RISK_BANDS: tuple[tuple[str, int, int, float], ...] = (
    ("LOW", 0, 30, 30.0),
    ("MODERATE", 31, 60, 60.0),
    ("HIGH", 61, 80, 80.0),
    ("SEVERE", 81, 100, float("inf")),
)


def risk_category(score_0_100: float) -> str:
    """Map a 0-100 bust-risk score onto the AtmosGuard risk bands."""
    for name, _lo, _hi, upper in RISK_BANDS:
        if score_0_100 <= upper:
            return name
    return "SEVERE"


# ---------------------------------------------------------------------------
# Extended monitoring network
# ---------------------------------------------------------------------------
# The ten cities above are the featured forecast points. The map and the alert
# engine additionally monitor these regional cells so that the national picture
# is more than ten dots - this is what the "Active High-Risk Areas" KPI counts.
# In production these are the grid cells of the NWP domain.

REGIONS: tuple[Location, ...] = (
    Location("west-rajasthan", "West Rajasthan", "Rajasthan", 26.30, 72.00,
             "West Rajasthan", "RAJASTHAN", None, False, 35.8),
    Location("east-rajasthan", "East Rajasthan", "Rajasthan", 25.60, 76.20,
             "East Rajasthan", "RAJASTHAN", None, False, 33.0),
    Location("west-mp", "West Madhya Pradesh", "Madhya Pradesh", 23.20, 76.00,
             "West Madhya Pradesh", "MADHYA PRADESH", None, False, 31.6),
    Location("east-mp", "East Madhya Pradesh", "Madhya Pradesh", 23.40, 81.00,
             "East Madhya Pradesh", "MADHYA PRADESH", None, False, 31.2),
    Location("saurashtra", "Saurashtra & Kutch", "Gujarat", 22.30, 70.20,
             "Saurashtra & Kutch", "GUJARAT", None, False, 32.4),
    Location("gujarat-region", "Gujarat Region", "Gujarat", 22.60, 72.90,
             "Gujarat Region", "GUJARAT", None, False, 32.0),
    Location("konkan", "Konkan & Goa", "Maharashtra", 17.40, 73.40,
             "Konkan & Goa", "GOA", None, False, 29.0),
    Location("madhya-maha", "Madhya Maharashtra", "Maharashtra", 18.60, 74.60,
             "Madhya Maharashtra", "MAHARASHTRA", None, False, 30.6),
    Location("vidarbha", "Vidarbha", "Maharashtra", 20.90, 78.60,
             "Vidarbha", "MAHARASHTRA", None, False, 32.6),
    Location("marathwada", "Marathwada", "Maharashtra", 18.90, 76.60,
             "Marathwada", "MAHARASHTRA", None, False, 32.2),
    Location("telangana-region", "Telangana", "Telangana", 18.10, 79.20,
             "Telangana", "TELANGANA", None, False, 31.8),
    Location("coastal-ap", "Coastal Andhra Pradesh", "Andhra Pradesh", 16.30, 81.20,
             "Coastal Andhra Pradesh", "ANDHRA PRADESH", None, False, 31.4),
    Location("rayalaseema", "Rayalaseema", "Andhra Pradesh", 14.40, 78.40,
             "Rayalaseema", "ANDHRA PRADESH", None, False, 32.8),
    Location("north-karnataka", "North Interior Karnataka", "Karnataka", 15.80, 76.20,
             "North Interior Karnataka", "KARNATAKA", None, False, 31.0),
    Location("coastal-karnataka", "Coastal Karnataka", "Karnataka", 13.90, 74.70,
             "Coastal Karnataka", "KARNATAKA", None, False, 28.4),
    Location("kerala", "Kerala & Mahe", "Kerala", 10.20, 76.40,
             "Kerala", "KERALA", None, False, 28.8),
    Location("south-tn", "South Tamil Nadu", "Tamil Nadu", 9.60, 78.20,
             "Tamil Nadu", "TAMIL NADU", None, False, 32.4),
    Location("odisha", "Odisha", "Odisha", 20.60, 84.40,
             "Odisha", "ODISHA", None, False, 30.8),
    Location("jharkhand", "Jharkhand", "Jharkhand", 23.60, 85.40,
             "Jharkhand", "JHARKHAND", None, False, 30.4),
    Location("east-up", "East Uttar Pradesh", "Uttar Pradesh", 26.40, 82.60,
             "East Uttar Pradesh", "UTTAR PRADESH", None, False, 32.4),
    Location("west-up", "West Uttar Pradesh", "Uttar Pradesh", 27.80, 78.80,
             "West Uttar Pradesh", "UTTAR PRADESH", None, False, 33.2),
    Location("uttarakhand", "Uttarakhand", "Uttarakhand", 30.10, 79.20,
             "Uttarakhand", "UTTARAKHAND", None, False, 24.8),
    Location("himachal", "Himachal Pradesh", "Himachal Pradesh", 31.80, 77.20,
             "Himachal Pradesh", "HIMACHAL PRADESH", None, False, 22.6),
    Location("punjab-haryana", "Punjab", "Punjab", 30.40, 75.80,
             "Punjab", "PUNJAB", None, False, 33.6),
    Location("sub-himalayan-wb", "Sub-Himalayan West Bengal & Sikkim", "West Bengal", 26.60, 88.60,
             "Sub Himalayan West Bengal & Sikkim", "SIKKIM", None, False, 29.2),
    Location("arunachal", "Arunachal Pradesh", "Arunachal Pradesh", 28.00, 94.20,
             "Arunachal Pradesh", "ARUNACHAL PRADESH", None, False, 24.0),
    Location("chhattisgarh", "Chhattisgarh", "Chhattisgarh", 21.20, 82.00,
             "Chhattisgarh", "CHHATTISGARH", None, False, 31.4),
    Location("naga-mani-mizo", "Naga Mani Mizo Tripura", "North East", 24.20, 93.40,
             "Naga Mani Mizo Tripura", "MANIPUR", None, False, 26.4),
)

#: Every point the system monitors: featured cities first, then regional cells.
ALL_SITES: tuple[Location, ...] = LOCATIONS + REGIONS
ALL_SITES_BY_ID = {site.id: site for site in ALL_SITES}
