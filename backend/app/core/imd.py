"""Real IMD observational data.

Two published India Meteorological Department datasets back this system:

1. **Sub-division monthly rainfall, 1901-2017** (36 sub-divisions x 117 years).
   Supplies the real rainfall climatology and, just as usefully, the real
   *interannual variability* of each sub-division - a region whose September
   rainfall swings by +/-60% between years is genuinely harder to forecast than
   one that does not, and that is a legitimate predictor rather than an
   invented constant.

2. **District-wise daily rainfall** - daily actual against IMD's own daily
   normal, with the departure category (LD/D/N/E/LE), for 728 districts.
   Supplies the real observations that forecasts are verified against.

What these datasets do *not* contain is NWP ensemble output - no meteorological
agency publishes ensemble members as CSV - so the ensemble remains simulated.
The important consequence is that it is now simulated *around a real observed
value*: the truth in every verification statistic on the dashboard is a real
IMD measurement, not a number this system invented.

Real-world data hygiene handled here, because published data is never clean:
duplicate state spellings (CHHATISGARH / CHHATTISGARH, TAMIL NADU / TAMILNADU),
IMD's own long-standing 'Matathwada' typo in the sub-division series, 'NA'
sentinels, and blank measurements.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
SUBDIVISION_FILE = DATA_DIR / "imd_subdivision_rainfall_1901_2017.csv"
DISTRICT_DAILY_FILE = DATA_DIR / "imd_district_daily_rainfall.csv"

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

#: State spellings that appear more than one way in the published file.
STATE_ALIASES = {
    "CHHATISGARH": "CHHATTISGARH",
    "TAMILNADU": "TAMIL NADU",
    "NCT OF DELHI": "DELHI",
    "JAMMU AND KASHMIR": "JAMMU & KASHMIR",
}

#: IMD's sub-division series carries a long-standing spelling of Marathwada.
#: Mapping it here means the rest of the codebase can use the correct name.
SUBDIVISION_ALIASES = {
    "Marathwada": "Matathwada",
    "Odisha": "Orissa",
    "Rayalaseema": "Rayalseema",
}


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace("%", "")
    if not text or text.upper() in {"NA", "N/A", "-", "NULL"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalise_state(name: str) -> str:
    key = name.strip().upper()
    return STATE_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Dataset 1: sub-division monthly climatology, 1901-2017
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Climatology:
    """Real rainfall climatology for one IMD sub-division."""

    subdivision: str
    #: Mean rainfall for each calendar month, mm/month.
    monthly_mean: tuple[float, ...]
    #: Interannual standard deviation for each month, mm/month.
    monthly_sd: tuple[float, ...]
    annual_mean: float
    annual_sd: float
    years: int

    def month_mean(self, month: int) -> float:
        return self.monthly_mean[month - 1]

    def month_sd(self, month: int) -> float:
        return self.monthly_sd[month - 1]

    def daily_mean(self, month: int) -> float:
        """Mean rainfall per day for a calendar month, mm/day."""
        days = (31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]
        return self.monthly_mean[month - 1] / days

    @property
    def variability(self) -> float:
        """Coefficient of variation of annual rainfall.

        A real, measured index of how erratic a region's rainfall is. Regions
        with high interannual variability are harder to forecast, and this
        replaces what would otherwise be a hand-tuned difficulty constant.
        """
        return self.annual_sd / self.annual_mean if self.annual_mean > 0 else 0.0


@lru_cache(maxsize=1)
def climatologies() -> dict[str, Climatology]:
    """Per-sub-division climatology computed from the full 1901-2017 record."""
    monthly: dict[str, list[list[float]]] = {}
    annual: dict[str, list[float]] = {}

    with SUBDIVISION_FILE.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            name = row["SUBDIVISION"].strip()
            buckets = monthly.setdefault(name, [[] for _ in MONTHS])
            for i, month in enumerate(MONTHS):
                value = _float(row.get(month))
                if value is not None:
                    buckets[i].append(value)
            total = _float(row.get("ANNUAL"))
            if total is not None:
                annual.setdefault(name, []).append(total)

    out: dict[str, Climatology] = {}
    for name, buckets in monthly.items():
        totals = annual.get(name, [])
        if not totals:
            continue
        out[name] = Climatology(
            subdivision=name,
            monthly_mean=tuple(statistics.fmean(b) if b else 0.0 for b in buckets),
            monthly_sd=tuple(statistics.stdev(b) if len(b) > 1 else 0.0 for b in buckets),
            annual_mean=statistics.fmean(totals),
            annual_sd=statistics.stdev(totals) if len(totals) > 1 else 0.0,
            years=len(totals),
        )
    return out


def climatology(subdivision: str) -> Climatology | None:
    """Look up a sub-division, tolerating the published spelling variants."""
    table = climatologies()
    if subdivision in table:
        return table[subdivision]
    alias = SUBDIVISION_ALIASES.get(subdivision)
    return table.get(alias) if alias else None


# ---------------------------------------------------------------------------
# Dataset 2: district-wise daily observations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyObservation:
    """One district-day of real observed rainfall against IMD's normal."""

    state: str
    district: str
    day: date
    actual: float
    normal: float
    departure_pct: float | None
    category: str


#: IMD rainfall departure categories, as published.
CATEGORY_LABELS = {
    "LE": "Large Excess",
    "E": "Excess",
    "N": "Normal",
    "D": "Deficient",
    "LD": "Large Deficient",
    "NR": "No Rain",
    "ND": "No Data",
}


@lru_cache(maxsize=1)
def _daily_rows() -> tuple[DailyObservation, ...]:
    rows: list[DailyObservation] = []
    with DISTRICT_DAILY_FILE.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            actual = _float(row.get("Daily Actual"))
            normal = _float(row.get("Daily Normal"))
            if actual is None or normal is None:
                continue
            try:
                day = date.fromisoformat(row["Date"].strip())
            except (KeyError, ValueError):
                continue
            rows.append(
                DailyObservation(
                    state=normalise_state(row["State"]),
                    district=row["District"].strip().upper(),
                    day=day,
                    actual=actual,
                    normal=normal,
                    departure_pct=_float(row.get("Daily Departure Per")),
                    category=(row.get("Daily Category") or "").strip().upper(),
                )
            )
    return tuple(rows)


@lru_cache(maxsize=1)
def observation_window() -> tuple[date, date]:
    """First and last date covered by the district daily observations."""
    days = [row.day for row in _daily_rows()]
    return min(days), max(days)


@lru_cache(maxsize=1)
def _by_district() -> dict[tuple[str, str], dict[date, DailyObservation]]:
    index: dict[tuple[str, str], dict[date, DailyObservation]] = {}
    for row in _daily_rows():
        index.setdefault((row.state, row.district), {})[row.day] = row
    return index


@lru_cache(maxsize=1)
def _by_state() -> dict[str, dict[date, list[DailyObservation]]]:
    index: dict[str, dict[date, list[DailyObservation]]] = {}
    for row in _daily_rows():
        index.setdefault(row.state, {}).setdefault(row.day, []).append(row)
    return index


def district_observation(state: str, district: str, day: date) -> DailyObservation | None:
    return _by_district().get((normalise_state(state), district.upper()), {}).get(day)


def state_observation(state: str, day: date) -> tuple[float, float, int] | None:
    """Area-mean observed and normal rainfall across a state's districts.

    Region-level sites have no single reporting district, so their observation
    is the mean over every district reporting that day - which is how a
    sub-divisional rainfall figure is actually constructed.
    """
    rows = _by_state().get(normalise_state(state), {}).get(day)
    if not rows:
        return None
    actual = statistics.fmean(r.actual for r in rows)
    normal = statistics.fmean(r.normal for r in rows)
    return actual, normal, len(rows)


@lru_cache(maxsize=1)
def coverage() -> dict[str, object]:
    """Summary of what the real datasets contain, for the System Status page."""
    rows = _daily_rows()
    start, end = observation_window()
    clim = climatologies()
    return {
        "subdivision_records": sum(c.years for c in clim.values()),
        "subdivisions": len(clim),
        "climatology_start": 1901,
        "climatology_end": 2017,
        "district_observations": len(rows),
        "districts": len({(r.state, r.district) for r in rows}),
        "states": len({r.state for r in rows}),
        "observation_start": start.isoformat(),
        "observation_end": end.isoformat(),
    }
