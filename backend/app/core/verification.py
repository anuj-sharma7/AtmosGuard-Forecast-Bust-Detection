"""Forecast verification and risk-model performance metrics.

Two distinct kinds of verification live here, and the UI keeps them apart:

1. **Forecast verification** - how well the *weather forecast* did against the
   observed / reanalysis value (RMSE, MAE, bias, anomaly correlation).
2. **Risk-model verification** - how well the *bust-risk classifier* did at
   flagging the forecasts that went on to bust (ROC-AUC, precision, recall,
   F1, Brier score, reliability).

Both are computed from the demonstration dataset at request time; none of the
numbers are hard-coded, so retuning the generator moves them honestly. The
metric implementations are plain numpy so the MVP has no scikit-learn
dependency, and they are unit-tested against known cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import numpy as np

from ..config import settings
from . import imd, risk_model, synthetic
from .domain import ALL_SITES, ALL_SITES_BY_ID, VARIABLES_BY_ID
from .features import extract_features

#: A forecast counts as a "bust" when its error exceeds this multiple of the
#: routine error for its lead time (see `lead_error_scale`). At 1.0 a bust is
#: simply "worse than a normal forecast at this range", which gives a base rate
#: near 20% across the demonstration dataset - frequent enough for the
#: classification metrics to be meaningful, rare enough to stay the exception.
#: Operational deployments would set this from an agency's own impact criteria.
BUST_THRESHOLD = 1.0

#: Error scale per variable: the *typical* Day-5 deterministic RMSE of the
#: demonstration dataset, in native units. Defining the bust threshold as a
#: multiple of the routine error is what makes "bust" mean "materially worse
#: than a normal forecast" rather than "large number".
#: Measured with `python -m scripts.calibrate`; re-derive after any change to
#: the forecast reconstruction, or the bust threshold drifts away from what a
#: routine forecast error actually is and the base rate collapses.
ERROR_SCALE = {"rainfall": 6.3, "temperature": 1.6, "wind": 1.3, "pressure": 1.75}


@dataclass(frozen=True)
class ErrorRecord:
    forecast: float
    observed: float
    error: float
    normalised_error: float
    bust: bool


def site_error_scale(location_id: str, variable_id: str, horizon: int, month: int) -> float:
    """Routine forecast error for one site, lead time and season.

    Rainfall error scales with how much rain a place gets: a 15 mm miss is
    routine on the Konkan coast in July and a serious failure in west Rajasthan.
    Judging every site against one national threshold made "bust" a proxy for
    "rainy", and the fitted model duly learned that high-skill (wet) regions
    bust more - the opposite of the truth. Normalising by the site's own
    climatology removes that confound.
    """
    scale = lead_error_scale(variable_id, horizon)
    if variable_id != "rainfall":
        return scale
    site = ALL_SITES_BY_ID.get(location_id)
    if site is None:
        return scale
    reference = 8.0  # mm/day, roughly the network-median monsoon climatology
    ratio = site.rain_climatology_for(month) / reference
    return scale * (0.45 + 0.55 * float(np.clip(ratio, 0.15, 3.5)))


def lead_error_scale(variable_id: str, horizon: int) -> float:
    """Routine forecast error at a given lead time.

    ERROR_SCALE is quoted at Day 5; error grows with lead time, so a fixed
    threshold would classify almost nothing as a bust at Day 3 and almost
    everything at Day 7. Scaling the threshold by lead makes "bust" mean
    *anomalously bad for this lead time*, which is the question a forecaster
    is actually asking, and keeps the base rate stable across the horizon
    selector so the classification metrics stay comparable.
    """
    return ERROR_SCALE[variable_id] * (horizon / 5.0) ** 0.7


def error_record(
    location_id: str, variable_id: str, base_date: date, horizon: int
) -> ErrorRecord:
    """Forecast-vs-observation for one (location, variable, valid time)."""
    members = settings.ensemble_members
    fc = synthetic.ensemble_forecast(location_id, variable_id, "ensemble", base_date, members)
    forecast = float(fc.deterministic[horizon - 1])
    observed = synthetic.observation(location_id, variable_id, base_date, horizon, members)

    error = forecast - observed
    valid = base_date + timedelta(days=horizon)
    scale = site_error_scale(location_id, variable_id, horizon, valid.month)
    if variable_id == "rainfall":
        # Also relative to the magnitude of the event itself: a 20 mm miss on a
        # 120 mm event is not the same failure as a 20 mm miss on a 5 mm event.
        scale = max(scale, 0.30 * max(forecast, observed))
    normalised = abs(error) / scale
    return ErrorRecord(forecast, observed, error, normalised, normalised > BUST_THRESHOLD)


def verification_valid_days(base_date: date, lookback_days: int) -> list[date]:
    """Valid dates to verify against, newest last.

    For rainfall the real IMD district record covers a fixed window, so the
    series is clipped to it rather than running off the end of the data into
    simulated truth. Reporting twenty-one points when only sixteen are measured
    would quietly mix real and simulated verification in one chart.
    """
    start, end = imd.observation_window()
    # Clamp into the observed window from either side: a reference date before
    # the record starts is as much a miss as one after it ends.
    latest = min(max(base_date, start), end)
    earliest = max(latest - timedelta(days=lookback_days - 1), start)
    days: list[date] = []
    day = earliest
    while day <= latest:
        days.append(day)
        day += timedelta(days=1)
    return days


def forecast_verification(
    location_id: str, variable_id: str, base_date: date, lookback_days: int = 21
) -> dict[str, object]:
    """Rolling forecast-vs-observation verification for the Day-5 forecast."""
    var = VARIABLES_BY_ID[variable_id]
    series: list[dict[str, object]] = []
    forecasts: list[float] = []
    observations: list[float] = []

    for valid in verification_valid_days(base_date, lookback_days):
        init = valid - timedelta(days=5)
        rec = error_record(location_id, variable_id, init, 5)
        series.append(
            {
                "date": valid.isoformat(),
                "forecast": round(rec.forecast, 2),
                "observed": round(rec.observed, 2),
                "error": round(rec.error, 2),
                "bust": rec.bust,
            }
        )
        forecasts.append(rec.forecast)
        observations.append(rec.observed)

    if not forecasts:
        return {"series": [], "unit": var.unit, "metrics": {
            "rmse": 0.0, "mae": 0.0, "bias": 0.0, "acc": 0.0, "skill": 0.0,
            "sample_size": 0, "bust_count": 0}}

    f = np.array(forecasts)
    o = np.array(observations)
    err = f - o

    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    bias = float(np.mean(err))

    # Climatology reference. Where IMD publishes a daily normal, use it: a
    # climatology estimated from the same short window being verified is both
    # biased and unstable, and IMD's normals are computed over decades.
    published = [
        synthetic.published_normal(location_id, variable_id, date.fromisoformat(str(row["date"])))
        for row in series
    ]
    if all(value is not None for value in published) and published:
        reference = np.array([float(v) for v in published])
        reference_source = "IMD published daily normal"
    else:
        reference = np.full_like(o, float(o.mean()))
        reference_source = "sample mean over the verification window"

    # Anomaly correlation, against that reference.
    fa, oa = f - reference, o - reference
    denom = float(np.sqrt(np.sum(fa**2) * np.sum(oa**2)))
    acc = float(np.sum(fa * oa) / denom) if denom > 1e-9 else 0.0

    # Mean-squared-error skill score against the same reference.
    mse_clim = float(np.mean((o - reference) ** 2))
    skill = float(1.0 - (rmse**2) / mse_clim) if mse_clim > 1e-9 else 0.0

    return {
        "series": series,
        "unit": var.unit,
        "metrics": {
            "rmse": round(rmse, 2),
            "mae": round(mae, 2),
            "bias": round(bias, 2),
            "acc": round(acc, 3),
            "skill": round(float(np.clip(skill, -1.0, 1.0)), 3),
            "sample_size": len(series),
            "bust_count": sum(1 for s in series if s["bust"]),
            "reference": reference_source,
        },
    }


# ---------------------------------------------------------------------------
# Risk-model classification metrics
# ---------------------------------------------------------------------------


def roc_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """ROC-AUC via the Mann-Whitney U statistic, with correct tie handling."""
    pos = y_true == 1
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(y_score, kind="mergesort")
    ranks = np.empty(len(y_score), dtype=float)
    ranks[order] = np.arange(1, len(y_score) + 1, dtype=float)
    # Average ranks within tied groups so ties contribute 0.5 rather than 1.
    sorted_scores = y_score[order]
    i = 0
    while i < len(sorted_scores):
        j = i
        while j + 1 < len(sorted_scores) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = np.mean(ranks[order[i : j + 1]])
        i = j + 1
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def classification_metrics(y_true: np.ndarray, y_score: np.ndarray, threshold: float) -> dict:
    y_pred = (y_score >= threshold).astype(int)
    tp = int(np.sum((y_pred == 1) & (y_true == 1)))
    fp = int(np.sum((y_pred == 1) & (y_true == 0)))
    fn = int(np.sum((y_pred == 0) & (y_true == 1)))
    tn = int(np.sum((y_pred == 0) & (y_true == 0)))

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "accuracy": round((tp + tn) / max(len(y_true), 1), 3),
        "confusion_matrix": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
        },
    }


def band_reliability(y_true: np.ndarray, y_score: np.ndarray) -> list[dict]:
    """Observed bust rate within each AtmosGuard risk band.

    This is the honest calibration statement for the product. The bust-risk
    score is a *risk index*, not a raw probability: a score of 79 does not mean
    "79% of such forecasts bust". What it means is defined here empirically -
    forecasts scored SEVERE bust several times more often than those scored
    LOW - and that monotonic separation is what a forecaster actually acts on.
    """
    from .domain import RISK_BANDS

    out: list[dict] = []
    lower = 0.0
    for name, _lo, _hi, upper in RISK_BANDS:
        hi = 1.0 if np.isinf(upper) else upper / 100.0
        mask = (y_score > lower) & (y_score <= hi) if lower > 0 else (y_score <= hi)
        count = int(mask.sum())
        out.append(
            {
                "band": name,
                "range": f"{int(lower * 100)}-{int(hi * 100)}",
                "observed_bust_rate": round(float(y_true[mask].mean()) if count else 0.0, 4),
                "count": count,
                "share": round(count / max(len(y_true), 1), 4),
            }
        )
        lower = hi
    return out


def reliability_curve(y_true: np.ndarray, y_score: np.ndarray, bins: int = 10) -> list[dict]:
    """Calibration curve: predicted risk vs observed bust frequency."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    out: list[dict] = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (y_score >= lo) & (y_score < hi if i < bins - 1 else y_score <= hi)
        count = int(mask.sum())
        out.append(
            {
                "bin": f"{int(lo * 100)}-{int(hi * 100)}%",
                "predicted": round(float(y_score[mask].mean()) if count else (lo + hi) / 2, 4),
                "observed": round(float(y_true[mask].mean()) if count else 0.0, 4),
                "count": count,
            }
        )
    return out


@lru_cache(maxsize=4)
def _evaluation_dataset(base_date_iso: str) -> tuple[tuple[float, ...], tuple[int, ...]]:
    """Sweep the demonstration space and pair each risk score with its outcome."""
    base = date.fromisoformat(base_date_iso)
    scores: list[float] = []
    labels: list[int] = []

    # Every valid date the real observation record covers, seen from each lead
    # time. Scoring against dates we cannot verify would be scoring against
    # this system's own simulation.
    for valid in verification_valid_days(base, 60):
        for loc in ALL_SITES:
            for horizon in (3, 5, 7):
                init = valid - timedelta(days=horizon)
                bundle = extract_features(loc.id, "rainfall", "ensemble", init, horizon)
                assessment = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector)
                rec = error_record(loc.id, "rainfall", init, horizon)
                scores.append(assessment.score)
                labels.append(1 if rec.bust else 0)
    return tuple(scores), tuple(labels)


def model_performance(base_date: date) -> dict[str, object]:
    """Full risk-model verification bundle for the Verification page."""
    raw_scores, raw_labels = _evaluation_dataset(base_date.isoformat())
    y_score = np.array(raw_scores, dtype=float)
    y_true = np.array(raw_labels, dtype=int)

    # The operating threshold is the boundary of the HIGH band (61%), which is
    # the point at which AtmosGuard actually raises an alert.
    threshold = 0.61
    metrics = classification_metrics(y_true, y_score, threshold)
    auc = roc_auc(y_true, y_score)
    brier = float(np.mean((y_score - y_true) ** 2))

    # ROC curve points.
    thresholds = np.linspace(0.0, 1.0, 41)
    roc_points = []
    for t in thresholds:
        pred = (y_score >= t).astype(int)
        tp = int(np.sum((pred == 1) & (y_true == 1)))
        fp = int(np.sum((pred == 1) & (y_true == 0)))
        fn = int(np.sum((pred == 0) & (y_true == 1)))
        tn = int(np.sum((pred == 0) & (y_true == 0)))
        tpr = tp / (tp + fn) if tp + fn else 0.0
        fpr = fp / (fp + tn) if fp + tn else 0.0
        roc_points.append({"fpr": round(fpr, 4), "tpr": round(tpr, 4), "threshold": round(float(t), 3)})

    return {
        "operating_threshold": threshold,
        "sample_size": int(len(y_true)),
        "base_rate": round(float(y_true.mean()), 4),
        "roc_auc": round(auc, 3),
        "brier_score": round(brier, 3),
        **metrics,
        "roc_curve": roc_points,
        "reliability": reliability_curve(y_true, y_score),
        "band_reliability": band_reliability(y_true, y_score),
        "score_interpretation": (
            "The bust-risk score is a calibrated risk *index* on a 0-100 scale, not a raw "
            "probability. Its meaning is the observed bust rate within each band, reported "
            "above. Discrimination (ROC-AUC) is the metric that matters for ranking which "
            "forecasts deserve a second look."
        ),
        "model": risk_model.model_card(),
    }
