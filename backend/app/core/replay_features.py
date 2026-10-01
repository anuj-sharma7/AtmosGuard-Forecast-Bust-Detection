"""Origin-only predictors for the historical replay.

Every feature here is built from an `Archive`, which physically cannot read
past the origin date. That is the whole point: the existing operational
predictor set (`core/predictors.py`) is derived from the reconstructed
ensemble, and that reconstruction is anchored to the observation it will later
be verified against - legitimate for a live demonstration, fatal for a
backtest. These predictors touch none of it.

What they use instead, all dated <= T:

* the site's own recent observed rainfall, and how it departs from normal
* the state's field on the origin day - how much of it is already active
* the sub-division's long-record climatology, variability and trend
  (1901-2017 monthly series; a fixed background, not a future value)
* the calendar - lead time and day of year

What they predict is stated plainly in `replay.py`: an IMD Large Excess
rainfall day, L days after the origin. That is a **weather risk proxy**, not a
forecast bust, because no archived forecast exists to bust (see
`core/hindcast.py`). The distinction is carried through every payload.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from . import climate
from .archive import Archive, SiteDay
from .domain import ALL_SITES_BY_ID, Location

#: Ordered predictor names. The trained parameter file stores this list and the
#: loader refuses a mismatch, so adding a feature without retraining fails loudly
#: instead of silently scrambling the coefficients.
REPLAY_PREDICTORS: tuple[str, ...] = (
    "lead_time",
    "antecedent_1d",
    "antecedent_3d",
    "antecedent_7d",
    "antecedent_anomaly",
    "origin_departure",
    "wet_day_fraction",
    "wet_spell_length",
    "dry_spell_length",
    "trend_3d",
    "large_excess_recency",
    "state_wet_fraction",
    "state_anomaly",
    "rain_climatology",
    "annual_variability",
    "monsoon_share",
    "climate_trend",
    "convective_index",
    "historical_skill",
    "doy_sin",
    "doy_cos",
)

REPLAY_PREDICTOR_META: dict[str, tuple[str, str]] = {
    "lead_time": ("Lead Time", "Days between the origin and the day being assessed."),
    "antecedent_1d": ("Rain on Origin Day", "Observed rainfall on T, as a multiple of the site's daily normal."),
    "antecedent_3d": ("3-Day Antecedent", "Mean observed rainfall over T-2..T, against normal."),
    "antecedent_7d": ("7-Day Antecedent", "Mean observed rainfall over T-6..T, against normal."),
    "antecedent_anomaly": ("Antecedent Anomaly", "How far the last three days sit from the sub-division's climatological daily mean."),
    "origin_departure": ("Departure at Origin", "IMD percentage departure from normal on the origin day, scaled."),
    "wet_day_fraction": ("Wet-Day Fraction", "Share of the last seven observed days with measurable rain."),
    "wet_spell_length": ("Wet Spell", "Consecutive wet days ending at the origin."),
    "dry_spell_length": ("Dry Spell", "Consecutive dry days ending at the origin."),
    "trend_3d": ("3-Day Tendency", "Whether rainfall is building or easing across the last three observed days."),
    "large_excess_recency": ("Recent Large Excess", "How recently the site last recorded an IMD Large Excess day."),
    "state_wet_fraction": ("State Active Fraction", "Share of the state's districts running Large Excess on the origin day."),
    "state_anomaly": ("State Anomaly", "State area-mean rainfall against normal on the origin day."),
    "rain_climatology": ("Climatological Rainfall", "Mean rainfall for the assessed calendar month, 1901-2017."),
    "annual_variability": ("Interannual Variability", "Coefficient of variation of annual rainfall over the full record."),
    "monsoon_share": ("Monsoon Share", "Fraction of annual rainfall that falls in June-September."),
    "climate_trend": ("Long-Record Trend", "Sen's slope of monsoon rainfall per decade, scaled."),
    "convective_index": ("Convective Character", "How much of the rainfall comes from short-lived convection."),
    "historical_skill": ("Regional Predictability", "Long-run predictability derived from measured variability."),
    "doy_sin": ("Season (sin)", "Position in the annual cycle."),
    "doy_cos": ("Season (cos)", "Position in the annual cycle."),
}

#: Minimum antecedent days required before an origin is usable. Below this the
#: antecedent features are built from too little record to mean anything, and
#: the origin is reported as unavailable rather than padded.
MIN_ANTECEDENT_DAYS = 5

#: A day counts as wet at IMD's own "measurable rainfall" threshold.
WET_DAY_MM = 2.5


def _ratio(actual: float, normal: float, cap: float = 8.0) -> float:
    if normal <= 0.05:
        return min(actual / 0.05, cap) if actual > 0 else 0.0
    return min(actual / normal, cap)


def _soft(x: float, k: float) -> float:
    """Smooth 0-1 compression. Hard clipping pins values at the bounds and
    throws away the ordering above them, which a tree model then cannot use."""
    return x / (x + k) if x > 0 else 0.0


def _spells(history: list[SiteDay]) -> tuple[int, int]:
    """(wet spell, dry spell) ending at the most recent observed day."""
    wet = dry = 0
    for row in reversed(history):
        if row.actual >= WET_DAY_MM:
            if dry:
                break
            wet += 1
        else:
            if wet:
                break
            dry += 1
    return wet, dry


def _large_excess_recency(history: list[SiteDay]) -> float:
    """1.0 if the most recent observed day was Large Excess, decaying back."""
    for back, row in enumerate(reversed(history)):
        if row.category == "Large Excess":
            return math.exp(-0.45 * back)
    return 0.0


def available(archive: Archive, location_id: str) -> bool:
    """Whether this origin has enough antecedent record for a prediction."""
    return len(archive.history(location_id, 7)) >= MIN_ANTECEDENT_DAYS


def build_vector(
    archive: Archive, location_id: str, valid_day: date
) -> dict[str, float] | None:
    """Origin-only predictors for one site and one valid day.

    Returns None when the archive does not carry enough antecedent record.
    It never substitutes a climatological guess for a missing observation:
    a gap is reported as a gap.
    """
    site: Location | None = ALL_SITES_BY_ID.get(location_id)
    if site is None:
        return None

    history = archive.history(location_id, 7)
    if len(history) < MIN_ANTECEDENT_DAYS:
        return None

    origin = archive.origin
    lead = (valid_day - origin).days

    last = history[-1]
    recent3 = history[-3:]
    normal3 = sum(r.normal for r in recent3) / len(recent3)
    actual3 = sum(r.actual for r in recent3) / len(recent3)
    normal7 = sum(r.normal for r in history) / len(history)
    actual7 = sum(r.actual for r in history) / len(history)

    clim_daily = site.rain_climatology_for(valid_day.month)

    wet_spell, dry_spell = _spells(history)
    wet_days = sum(1 for r in history if r.actual >= WET_DAY_MM) / len(history)

    # Is rainfall building or easing? Mean of the last three observed days
    # against the three before them. Needs six days; below that there is no
    # tendency to measure and the feature is flat rather than guessed.
    prior3 = history[-6:-3]
    if prior3:
        tendency = actual3 - sum(r.actual for r in prior3) / len(prior3)
    else:
        tendency = 0.0

    state_wet = archive.state_wet_fraction(site.obs_state, origin)
    state_anom = archive.state_anomaly(site.obs_state, origin)

    trend = climate.trend(site.subdivision)
    trend_scaled = (trend.percent_per_decade / 10.0) if trend else 0.0

    clim = site._climatology
    if clim is not None and clim.annual_mean > 0:
        monsoon_share = sum(clim.month_mean(m) for m in (6, 7, 8, 9)) / clim.annual_mean
    else:
        monsoon_share = 0.75

    doy = valid_day.timetuple().tm_yday
    angle = 2.0 * math.pi * doy / 365.25

    return {
        "lead_time": float(lead),
        "antecedent_1d": _ratio(last.actual, last.normal),
        "antecedent_3d": _ratio(actual3, normal3),
        "antecedent_7d": _ratio(actual7, normal7),
        "antecedent_anomaly": _soft(actual3 / clim_daily if clim_daily > 0 else 0.0, 1.0),
        "origin_departure": max(-1.0, min((last.departure_pct or 0.0) / 100.0, 5.0)),
        "wet_day_fraction": wet_days,
        "wet_spell_length": _soft(float(wet_spell), 2.0),
        "dry_spell_length": _soft(float(dry_spell), 2.0),
        "trend_3d": max(-1.0, min(tendency / max(normal3, 1.0), 1.0)),
        "large_excess_recency": _large_excess_recency(history),
        "state_wet_fraction": state_wet if state_wet is not None else 0.0,
        "state_anomaly": min(state_anom, 6.0) if state_anom is not None else 1.0,
        "rain_climatology": _soft(clim_daily, 6.0),
        "annual_variability": site.annual_variability,
        "monsoon_share": monsoon_share,
        "climate_trend": max(-1.0, min(trend_scaled, 1.0)),
        "convective_index": site.convective_index,
        "historical_skill": site.historical_skill,
        "doy_sin": math.sin(angle),
        "doy_cos": math.cos(angle),
    }


def as_array(vector: dict[str, float]) -> list[float]:
    return [vector[name] for name in REPLAY_PREDICTORS]
