"""Climate analytics over the IMD sub-division record, 1901-2017.

Everything here is computed from the published India Meteorological Department
sub-divisional rainfall series - 36 sub-divisions x 117 years of monthly totals.
It answers the question a forecaster asks before trusting any medium-range
guidance: *what is normal here, how much does it vary, and is it changing?*

Two deliberate method choices:

* **Mann-Kendall with Sen's slope**, not ordinary least squares. Rainfall series
  are skewed, heteroscedastic and occasionally have a monster year; a least
  squares slope is dragged around by those years, while the rank-based test and
  the median-of-pairwise-slopes estimator are not. This is the standard pairing
  in hydroclimatology for exactly that reason.
* **IMD's own rainfall categories**, not invented thresholds. Excess, Normal,
  Deficient and Scanty are defined by IMD as departures of >= +20%, -19% to +19%,
  -20% to -59% and -60% to -99% from the long-period average. Using anything
  else would produce numbers a meteorologist could not check against their own
  published statistics.
"""

from __future__ import annotations

import csv
import math
import statistics
from dataclasses import dataclass
from functools import lru_cache

from .imd import MONTHS, SUBDIVISION_FILE, SUBDIVISION_ALIASES, _float

#: The south-west monsoon season - June to September - which delivers the bulk
#: of the annual total across most of India.
MONSOON_MONTHS = (6, 7, 8, 9)

#: IMD's published rainfall departure categories, as (label, lower %, upper %).
#: Open-ended bounds use +/- infinity.
IMD_CATEGORIES: tuple[tuple[str, float, float], ...] = (
    ("Large Excess", 60.0, math.inf),
    ("Excess", 20.0, 60.0),
    ("Normal", -19.0, 20.0),
    ("Deficient", -60.0, -19.0),
    ("Scanty", -99.0, -60.0),
    ("No Rain", -math.inf, -99.0),
)


def categorise(departure_pct: float) -> str:
    """Map a percentage departure from normal onto IMD's category scale."""
    for label, lower, upper in IMD_CATEGORIES:
        if lower <= departure_pct < upper:
            return label
    return "No Rain"


@dataclass(frozen=True)
class YearRecord:
    year: int
    annual: float
    monsoon: float
    monthly: tuple[float, ...]


@lru_cache(maxsize=1)
def _series() -> dict[str, tuple[YearRecord, ...]]:
    table: dict[str, list[YearRecord]] = {}
    with SUBDIVISION_FILE.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            annual = _float(row.get("ANNUAL"))
            if annual is None:
                continue
            monthly = [_float(row.get(m)) for m in MONTHS]
            if any(v is None for v in monthly):
                continue
            values = [float(v) for v in monthly]
            table.setdefault(row["SUBDIVISION"].strip(), []).append(
                YearRecord(
                    year=int(row["YEAR"]),
                    annual=annual,
                    monsoon=sum(values[m - 1] for m in MONSOON_MONTHS),
                    monthly=tuple(values),
                )
            )
    return {name: tuple(sorted(rows, key=lambda r: r.year)) for name, rows in table.items()}


def series(subdivision: str) -> tuple[YearRecord, ...]:
    """The year-by-year record for a sub-division, oldest first."""
    table = _series()
    if subdivision in table:
        return table[subdivision]
    alias = SUBDIVISION_ALIASES.get(subdivision)
    return table.get(alias, ()) if alias else ()


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


def mann_kendall(values: list[float]) -> tuple[float, float]:
    """Mann-Kendall trend test. Returns (Z statistic, two-sided p-value).

    Non-parametric: it tests whether later values tend to exceed earlier ones,
    using only the sign of each pairwise comparison. That makes it insensitive
    to the skew and the outlier years that make rainfall series awkward for a
    parametric test. Ties are handled by the standard variance correction.
    """
    n = len(values)
    if n < 10:
        return 0.0, 1.0

    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            s += (values[j] > values[i]) - (values[j] < values[i])

    # Variance, corrected for tied groups.
    counts: dict[float, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    tie_term = sum(t * (t - 1) * (2 * t + 5) for t in counts.values() if t > 1)
    variance = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if variance <= 0:
        return 0.0, 1.0

    if s > 0:
        z = (s - 1) / math.sqrt(variance)
    elif s < 0:
        z = (s + 1) / math.sqrt(variance)
    else:
        z = 0.0

    p = 2.0 * (1.0 - _standard_normal_cdf(abs(z)))
    return z, min(max(p, 0.0), 1.0)


def _standard_normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def sens_slope(years: list[int], values: list[float]) -> float:
    """Sen's slope: the median of all pairwise slopes, in units per year.

    A least-squares slope on a rainfall series is pulled around by the handful
    of extreme years that define the distribution's tail. The median pairwise
    slope is not.
    """
    slopes: list[float] = []
    n = len(values)
    for i in range(n - 1):
        for j in range(i + 1, n):
            span = years[j] - years[i]
            if span:
                slopes.append((values[j] - values[i]) / span)
    return statistics.median(slopes) if slopes else 0.0


@dataclass(frozen=True)
class Trend:
    slope_per_decade: float
    percent_per_decade: float
    z: float
    p_value: float
    significant: bool
    direction: str


def trend(subdivision: str, season: str = "monsoon") -> Trend | None:
    """Rainfall trend over the full record for a sub-division."""
    rows = series(subdivision)
    if len(rows) < 30:
        return None

    years = [r.year for r in rows]
    values = [r.monsoon if season == "monsoon" else r.annual for r in rows]
    mean = statistics.fmean(values)

    z, p = mann_kendall(values)
    slope = sens_slope(years, values) * 10.0
    significant = p < 0.05

    if not significant:
        direction = "no significant trend"
    elif slope > 0:
        direction = "increasing"
    else:
        direction = "decreasing"

    return Trend(
        slope_per_decade=round(slope, 2),
        percent_per_decade=round(slope / mean * 100.0, 2) if mean else 0.0,
        z=round(z, 3),
        p_value=round(p, 4),
        significant=significant,
        direction=direction,
    )


# ---------------------------------------------------------------------------
# Distribution of outcomes
# ---------------------------------------------------------------------------


def category_frequency(subdivision: str) -> list[dict[str, object]]:
    """How often each IMD rainfall category occurred, over the full record."""
    rows = series(subdivision)
    if not rows:
        return []

    normal = statistics.fmean(r.monsoon for r in rows)
    counts: dict[str, int] = {label: 0 for label, _, _ in IMD_CATEGORIES}
    for row in rows:
        departure = (row.monsoon - normal) / normal * 100.0 if normal else 0.0
        counts[categorise(departure)] += 1

    total = len(rows)
    return [
        {
            "category": label,
            "years": counts[label],
            "frequency": round(counts[label] / total, 4),
            "range": _range_label(lower, upper),
        }
        for label, lower, upper in IMD_CATEGORIES
    ]


def _range_label(lower: float, upper: float) -> str:
    if lower == -math.inf:
        return f"below {upper:+.0f}%"
    if upper == math.inf:
        return f"{lower:+.0f}% and above"
    return f"{lower:+.0f}% to {upper:+.0f}%"


def decadal_means(subdivision: str) -> list[dict[str, object]]:
    """Monsoon rainfall averaged by decade - the long view, smoothed."""
    rows = series(subdivision)
    if not rows:
        return []

    buckets: dict[int, list[float]] = {}
    for row in rows:
        buckets.setdefault(row.year // 10 * 10, []).append(row.monsoon)

    overall = statistics.fmean(r.monsoon for r in rows)
    return [
        {
            "decade": decade,
            "label": f"{decade}s",
            "mean": round(statistics.fmean(values), 1),
            "departure_pct": round((statistics.fmean(values) - overall) / overall * 100.0, 1)
            if overall
            else 0.0,
            "years": len(values),
        }
        for decade, values in sorted(buckets.items())
        if len(values) >= 5  # ignore part-decades at either end
    ]


def extremes(subdivision: str, count: int = 3) -> dict[str, list[dict[str, object]]]:
    """The wettest and driest monsoons on record."""
    rows = series(subdivision)
    if not rows:
        return {"wettest": [], "driest": []}

    normal = statistics.fmean(r.monsoon for r in rows)

    def describe(row: YearRecord) -> dict[str, object]:
        departure = (row.monsoon - normal) / normal * 100.0 if normal else 0.0
        return {
            "year": row.year,
            "monsoon": round(row.monsoon, 1),
            "departure_pct": round(departure, 1),
            "category": categorise(departure),
        }

    ordered = sorted(rows, key=lambda r: r.monsoon)
    return {
        "wettest": [describe(r) for r in reversed(ordered[-count:])],
        "driest": [describe(r) for r in ordered[:count]],
    }


def baseline_shift(subdivision: str, window: int = 30) -> dict[str, object] | None:
    """Compare the most recent 30 years against the earliest 30.

    Thirty years is the standard climate normal period, so this is the
    comparison a climatologist would reach for first.
    """
    rows = series(subdivision)
    if len(rows) < window * 2:
        return None

    early = [r.monsoon for r in rows[:window]]
    late = [r.monsoon for r in rows[-window:]]
    early_mean, late_mean = statistics.fmean(early), statistics.fmean(late)

    return {
        "early_period": f"{rows[0].year}-{rows[window - 1].year}",
        "late_period": f"{rows[-window].year}-{rows[-1].year}",
        "early_mean": round(early_mean, 1),
        "late_mean": round(late_mean, 1),
        "change_pct": round((late_mean - early_mean) / early_mean * 100.0, 1) if early_mean else 0.0,
        "early_variability": round(statistics.stdev(early) / early_mean, 3) if early_mean else 0.0,
        "late_variability": round(statistics.stdev(late) / late_mean, 3) if late_mean else 0.0,
    }


def profile(subdivision: str) -> dict[str, object] | None:
    """Everything the climate panel needs for one sub-division."""
    rows = series(subdivision)
    if not rows:
        return None

    annual_mean = statistics.fmean(r.annual for r in rows)
    monsoon_mean = statistics.fmean(r.monsoon for r in rows)
    monsoon_trend = trend(subdivision, "monsoon")
    shift = baseline_shift(subdivision)

    return {
        "subdivision": subdivision,
        "record": {"start": rows[0].year, "end": rows[-1].year, "years": len(rows)},
        "annual_mean": round(annual_mean, 1),
        "monsoon_mean": round(monsoon_mean, 1),
        "monsoon_share": round(monsoon_mean / annual_mean * 100.0, 1) if annual_mean else 0.0,
        "variability": round(statistics.stdev([r.annual for r in rows]) / annual_mean, 3)
        if annual_mean
        else 0.0,
        "trend": monsoon_trend.__dict__ if monsoon_trend else None,
        "categories": category_frequency(subdivision),
        "decades": decadal_means(subdivision),
        "extremes": extremes(subdivision),
        "baseline_shift": shift,
        "series": [
            {"year": r.year, "monsoon": round(r.monsoon, 1), "annual": round(r.annual, 1)}
            for r in rows
        ],
        "source": {
            "name": "IMD sub-divisional monthly rainfall, 1901-2017",
            "publisher": "India Meteorological Department",
            "method": "Mann-Kendall test with Sen's slope; IMD rainfall departure categories",
        },
    }
