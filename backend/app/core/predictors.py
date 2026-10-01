"""The full predictor set for the trained bust-risk models.

The logistic baseline ran on seven predictors, which is about what a linear
model can carry before collinearity starts doing the work. A gradient-boosted
tree has no such limit, so this module widens the input to twenty-seven and
lets the fit decide what matters.

Everything here is derived from data the system already holds - the IMD
climatology and observation record, and the ensemble - rather than invented to
pad the vector. They fall into five groups:

* **Ensemble shape.** Not just how wide the spread is, but its skew, its
  interquartile range, how fast it grew between lead times, how far the
  deterministic run sits from the mean, and what share of members cross IMD's
  heavy-rain threshold. A distribution that is wide *and* right-skewed is a
  different situation from one that is merely wide.
* **Synoptic state.** Regime transition strength, how close the valid time sits
  to the transition, pressure tendency.
* **Climatology.** The site's real IMD normal for the month, its interannual
  variability, its monsoon concentration and its long-record trend. These say
  how hard this place is to forecast at all.
* **Agreement.** Between NWP centres, and between successive runs of one.
* **Season and lead.** Encoded so a tree can split on them directly, with
  day-of-year as a sine/cosine pair rather than a number that jumps at New Year.

Ordering is fixed by ``PREDICTOR_NAMES`` and must stay stable: it is the column
order the persisted models were trained on.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np

from . import climate, imd, synthetic
from .domain import ALL_SITES_BY_ID, MODELS_BY_ID, VARIABLES_BY_ID

if TYPE_CHECKING:  # import only for typing - `features` imports this module
    from .features import FeatureBundle

#: IMD's heavy-rain threshold, mm/day.
HEAVY_RAIN_MM = 64.5

PREDICTOR_NAMES: tuple[str, ...] = (
    # --- ensemble shape -----------------------------------------------------
    "ensemble_spread",
    "spread_anomaly",
    "spread_growth",
    "ensemble_skew",
    "iqr_ratio",
    "member_range",
    "heavy_rain_fraction",
    "det_mean_gap",
    # --- synoptic state -----------------------------------------------------
    "regime_change",
    "transition_proximity",
    "pressure_change",
    "synoptic_forcing",
    "moisture_anomaly",
    # --- agreement ----------------------------------------------------------
    "model_disagreement",
    "forecast_persistence",
    "analogue_mismatch",
    "analogue_bust_rate",
    # --- climatology --------------------------------------------------------
    "historical_skill",
    "rain_climatology",
    "annual_variability",
    "monsoon_share",
    "climate_trend",
    "convective_index",
    "forecast_anomaly",
    "accum_3day_anomaly",
    # --- season and lead ----------------------------------------------------
    "lead_time",
    "doy_sin",
    "doy_cos",
)

#: Labels and one-line explanations, for the explanation panel.
PREDICTOR_META: dict[str, tuple[str, str]] = {
    "ensemble_spread": ("Ensemble Spread", "Member disagreement at this lead time, against what is normal for it."),
    "spread_anomaly": ("Spread Anomaly", "Raw ratio of today's spread to the lead-time climatology."),
    "spread_growth": ("Spread Growth", "How fast the spread widened between Day h-2 and Day h."),
    "ensemble_skew": ("Ensemble Skew", "Asymmetry of the member distribution. A long right tail means a few members see a much wetter outcome."),
    "iqr_ratio": ("Interquartile Ratio", "Middle-half spread relative to the median - robust to single outlying members."),
    "member_range": ("Member Range", "Full min-to-max span relative to the mean."),
    "heavy_rain_fraction": ("Heavy Rain Members", "Share of members above IMD's 64.5 mm heavy-rain threshold."),
    "det_mean_gap": ("Deterministic Offset", "How far the deterministic run sits from the ensemble mean, in spread units."),
    "regime_change": ("Atmospheric Regime Change", "Strength of the pattern transition inside the forecast window."),
    "transition_proximity": ("Transition Proximity", "How close the valid time sits to the regime transition."),
    "pressure_change": ("Rapid Pressure Change", "24 h mean-sea-level-pressure tendency around the valid time."),
    "synoptic_forcing": ("Synoptic Forcing", "Strength of large-scale ascent."),
    "moisture_anomaly": ("Moisture Anomaly", "Low-level moisture against normal."),
    "model_disagreement": ("Model Disagreement", "Spread between the ECMWF, NCMRWF-NCUM and GFS runs."),
    "forecast_persistence": ("Forecast Persistence", "Run-to-run jumpiness for this valid time."),
    "analogue_mismatch": ("Historical Analogue Mismatch", "How poorly the pattern matches situations with known outcomes."),
    "analogue_bust_rate": ("Analogue Bust Rate", "Share of the matched historical analogues whose forecasts busted."),
    "historical_skill": ("Historical Skill", "Long-run skill for this sub-division, from the IMD 1901-2017 record."),
    "rain_climatology": ("Rainfall Normal", "The sub-division's real IMD normal for this month, mm/day."),
    "annual_variability": ("Interannual Variability", "Coefficient of variation of annual rainfall over 117 years."),
    "monsoon_share": ("Monsoon Concentration", "Share of annual rainfall falling in June-September."),
    "climate_trend": ("Climate Trend", "Long-record monsoon trend, percent per decade."),
    "convective_index": ("Convective Character", "How erratic rainfall is month to month in the real record."),
    "forecast_anomaly": ("Forecast Anomaly", "Forecast rainfall against the site's normal for the month."),
    "accum_3day_anomaly": ("Three-Day Accumulation", "Three-day forecast total against normal - catches prolonged spells."),
    "lead_time": ("Lead Time", "Days ahead. Error grows with range."),
    "doy_sin": ("Season (sin)", "Day of year as a sine component, so the model can split on season."),
    "doy_cos": ("Season (cos)", "Day of year as a cosine component."),
}


def _safe(value: float, default: float = 0.0) -> float:
    return float(value) if np.isfinite(value) else default


def _skew(values: np.ndarray) -> float:
    """Fisher-Pearson skewness. Zero for a symmetric distribution."""
    n = len(values)
    if n < 3:
        return 0.0
    mean = float(values.mean())
    sd = float(values.std(ddof=1))
    if sd < 1e-9:
        return 0.0
    return _safe(float(np.sum((values - mean) ** 3) / (n * sd**3)))


def build_vector(
    bundle: "FeatureBundle",
    location_id: str,
    variable_id: str,
    model_id: str,
    base_date: date,
    horizon: int,
) -> dict[str, float]:
    """Assemble the full predictor vector for one forecast."""
    site = ALL_SITES_BY_ID[location_id]
    forecast = bundle.forecast
    state = bundle.state
    members = forecast.members[:, horizon - 1]
    mean = float(members.mean())
    sd = float(members.std(ddof=1))
    median = float(np.median(members))

    # --- ensemble shape ----------------------------------------------------
    q25, q75 = (float(v) for v in np.percentile(members, [25, 75]))
    spread_anomaly = synthetic.spread_anomaly(forecast, horizon)
    earlier = max(horizon - 2, 1)
    earlier_sd = float(forecast.members[:, earlier - 1].std(ddof=1))
    deterministic = float(forecast.deterministic[horizon - 1])

    # --- climatology -------------------------------------------------------
    valid = base_date + timedelta(days=horizon)
    normal = site.rain_climatology_for(valid.month)
    profile_trend = climate.trend(site.subdivision, "monsoon")
    clim = imd.climatology(site.subdivision)
    monsoon_share = 0.0
    if clim and clim.annual_mean > 0:
        monsoon_share = sum(clim.month_mean(m) for m in (6, 7, 8, 9)) / clim.annual_mean

    days = synthetic.DISPLAY_DAYS
    window = forecast.mean[max(horizon - 2, 0) : min(horizon + 1, days)]
    accum = float(window.sum()) if len(window) else 0.0

    # --- analogues ---------------------------------------------------------
    analogue_busts = (
        sum(1 for a in bundle.analogues if a["bust_occurred"]) / len(bundle.analogues)
        if bundle.analogues
        else 0.5
    )

    doy = valid.timetuple().tm_yday
    variable = VARIABLES_BY_ID[variable_id]

    values = {
        "ensemble_spread": bundle.values["ensemble_spread"],
        "spread_anomaly": _safe(min(spread_anomaly, 8.0)),
        # Clipped: at short lead the denominator can be near zero, and an
        # unclipped ratio of 28 is a measurement artefact, not a signal.
        "spread_growth": float(np.clip(sd / earlier_sd if earlier_sd > 1e-9 else 1.0, 0.2, 5.0)),
        "ensemble_skew": _skew(members),
        "iqr_ratio": _safe((q75 - q25) / median if median > 1e-6 else 0.0),
        "member_range": float(
            np.clip((float(members.max()) - float(members.min())) / mean if mean > 1e-6 else 0.0, 0.0, 12.0)
        ),
        "heavy_rain_fraction": float(np.mean(members >= HEAVY_RAIN_MM))
        if variable_id == "rainfall"
        else 0.0,
        "det_mean_gap": _safe(abs(deterministic - mean) / sd if sd > 1e-9 else 0.0),
        "regime_change": bundle.values["regime_change"],
        "transition_proximity": _safe(1.0 / (1.0 + abs(horizon - state.transition_day))),
        "pressure_change": bundle.values["pressure_change"],
        "synoptic_forcing": state.synoptic_forcing,
        "moisture_anomaly": state.moisture_anomaly,
        "model_disagreement": bundle.values["model_disagreement"],
        "forecast_persistence": bundle.values["forecast_persistence"],
        "analogue_mismatch": bundle.values["analogue_mismatch"],
        "analogue_bust_rate": analogue_busts,
        "historical_skill": bundle.historical_skill,
        "rain_climatology": normal,
        "annual_variability": site.annual_variability,
        "monsoon_share": monsoon_share,
        "climate_trend": profile_trend.percent_per_decade if profile_trend else 0.0,
        "convective_index": site.convective_index,
        "forecast_anomaly": float(
            np.clip(deterministic / normal if normal > 1e-6 else 1.0, 0.0, 25.0)
        )
        if variable_id == "rainfall"
        else 1.0,
        "accum_3day_anomaly": float(
            np.clip(accum / (normal * 3.0) if normal > 1e-6 else 1.0, 0.0, 25.0)
        )
        if variable_id == "rainfall"
        else 1.0,
        "lead_time": float(horizon),
        "doy_sin": math.sin(2 * math.pi * doy / 365.25),
        "doy_cos": math.cos(2 * math.pi * doy / 365.25),
    }
    # Model skill folds into historical skill rather than adding a column that
    # is constant within a model - a tree would split on it as an identifier.
    values["historical_skill"] *= 1.0 + 0.15 * (MODELS_BY_ID[model_id].skill - 0.8)
    values["historical_skill"] *= 1.0 - 0.10 * (variable.predictability_penalty - 0.5)

    return {name: _safe(values[name]) for name in PREDICTOR_NAMES}


def to_array(vectors: list[dict[str, float]]) -> np.ndarray:
    """Stack predictor dicts into the fixed column order the models expect."""
    return np.array([[v[name] for name in PREDICTOR_NAMES] for v in vectors], dtype=float)
