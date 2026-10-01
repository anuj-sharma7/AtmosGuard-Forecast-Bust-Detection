"""Historical replay and 7-day validation.

Two phases, in two functions, that cannot see each other's data:

    generate_prediction(origin, site, lead)          # reads <= T only
    validate_prediction_against_actual(prediction)   # reads T+1..T+7 only

The separation is enforced by `core/archive`: the prediction phase holds an
`Archive`, which raises `LeakageError` on any read past the origin, and the
validation phase holds an `Outcomes`, which raises on any read at or before it.
Neither object can do the other's job. That is deliberate - in a backtest the
difference between 0.68 and 0.95 is usually one accidental read of the answer.

Two modes, kept apart everywhere:

**Mode A - forecast-bust validation.** Takes an archived NWP forecast
initialised at or before T, compares it with what was observed, and labels the
cases where the forecast failed. This is the real thing. It requires a hindcast
archive, and **none is present** (`core/hindcast.py` says exactly what is
missing). Mode A therefore reports unavailable. It is never simulated.

**Mode B - historical weather risk proxy.** Estimates, from information
available at T only, the probability that a site records an IMD *Large Excess*
rainfall day at T+L, then checks that against the published observation. It is
a real, verifiable, leak-free prediction about the weather. It is **not** a
forecast bust, and nothing here calls it one.

Every observed value comes from the IMD district daily record. Where the record
does not cover a day, the day is reported as uncovered. Nothing is interpolated,
distributed or filled.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from . import archive as archive_mod
from . import hindcast
from . import replay_features as rf
from .archive import Archive, LeakageError, Outcomes, SiteDay
from .domain import ALL_SITES, ALL_SITES_BY_ID, Location

MODEL_PATH = Path(__file__).resolve().parent / "models" / "replay_model.json"

#: Lead times the replay product covers.
LEADS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)


class ReplayUnavailable(RuntimeError):
    """Raised when the archive does not cover what a replay needs."""


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayModel:
    predictors: tuple[str, ...]
    intercept: float
    coefficients: dict[str, float]
    feature_mean: dict[str, float]
    feature_sd: dict[str, float]
    threshold: float
    event: dict
    mode_note: str
    training: dict
    metrics: dict
    caveat: str

    def standardise(self, vector: dict[str, float]) -> dict[str, float]:
        return {
            name: (vector[name] - self.feature_mean[name]) / self.feature_sd[name]
            for name in self.predictors
        }

    def probability(self, vector: dict[str, float]) -> float:
        """Calibrated probability from the fitted logistic. Never a constant,
        never a random draw - the sigmoid of a fitted linear predictor."""
        z = self.standardise(vector)
        eta = self.intercept + sum(self.coefficients[n] * z[n] for n in self.predictors)
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(eta, 30.0))))

    def contributions(self, vector: dict[str, float]) -> tuple[dict[str, float], float]:
        """Exact Shapley values.

        For a model linear in the log-odds the Shapley value of feature i has a
        closed form, w_i * (x_i - E[x_i]), and the attributions sum exactly to
        the log-odds minus the base value. No sampling, no approximation.
        """
        z = self.standardise(vector)
        contrib = {n: self.coefficients[n] * z[n] for n in self.predictors}
        return contrib, self.intercept


@lru_cache(maxsize=1)
def load_model() -> ReplayModel | None:
    """The fitted replay model, or None if it has not been trained yet.

    The stored predictor list is checked against the live one. Adding a feature
    without retraining silently scrambles the coefficients, so a mismatch is
    refused rather than tolerated.
    """
    if not MODEL_PATH.is_file():
        return None
    raw = json.loads(MODEL_PATH.read_text())
    if tuple(raw.get("predictors", ())) != rf.REPLAY_PREDICTORS:
        return None
    return ReplayModel(
        predictors=tuple(raw["predictors"]),
        intercept=float(raw["intercept"]),
        coefficients=dict(raw["coefficients"]),
        feature_mean=dict(raw["feature_mean"]),
        feature_sd=dict(raw["feature_sd"]),
        threshold=float(raw["threshold"]),
        event=dict(raw["event"]),
        mode_note=str(raw["mode_note"]),
        training=dict(raw["training"]),
        metrics=dict(raw["metrics"]),
        caveat=str(raw["caveat"]),
    )


# ---------------------------------------------------------------------------
# Phase 1 - prediction. Reads <= T. Never reads an outcome.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayPrediction:
    """A prediction formed at `origin` for `valid_day`, using only data <= origin."""

    run_id: str
    prediction_id: str
    mode: str
    origin: date
    valid_day: date
    lead_time: int
    location_id: str
    location_name: str
    subdivision: str
    probability: float
    predicted_event: bool
    threshold: float
    features: dict[str, float]
    contributions: dict[str, float]
    base_value: float
    #: Everything the prediction was allowed to see, for the audit trail.
    evidence_window: tuple[str, str]
    model_version: str


def _run_id(origin: date, model_version: str, scope: str) -> str:
    """Stable identifier for a replay run. Same inputs, same id, always."""
    payload = f"{scope}|{origin.isoformat()}|{model_version}".encode()
    return hashlib.blake2b(payload, digest_size=8).hexdigest()


def _prediction_id(run_id: str, location_id: str, lead: int) -> str:
    payload = f"{run_id}|{location_id}|{lead}".encode()
    return hashlib.blake2b(payload, digest_size=8).hexdigest()


def _model_version(model: ReplayModel) -> str:
    payload = json.dumps(
        {"c": model.coefficients, "i": model.intercept, "t": model.threshold},
        sort_keys=True,
    ).encode()
    return "replay-logistic-" + hashlib.blake2b(payload, digest_size=4).hexdigest()


def generate_prediction(
    origin: date,
    location_id: str,
    lead: int,
    run_id: str | None = None,
) -> ReplayPrediction | None:
    """Phase 1. Form a prediction for origin + lead, from data <= origin.

    Holds an `Archive`, which refuses any read past the origin. It never
    constructs an `Outcomes`, so it has no route to the answer at all.

    Returns None when the archive lacks the antecedent record this origin needs.
    """
    model = load_model()
    if model is None:
        raise ReplayUnavailable(
            "The replay model has not been trained. Run "
            "`python -m scripts.train_replay_model` in backend/."
        )
    site: Location | None = ALL_SITES_BY_ID.get(location_id)
    if site is None:
        raise ReplayUnavailable(f"Unknown location '{location_id}'")
    if lead not in LEADS:
        raise ReplayUnavailable(f"Lead time must be one of {LEADS}")

    arch = Archive(origin=origin)
    valid_day = origin + timedelta(days=lead)
    vector = rf.build_vector(arch, location_id, valid_day)
    if vector is None:
        return None

    probability = model.probability(vector)
    contrib, base = model.contributions(vector)
    version = _model_version(model)
    rid = run_id or _run_id(origin, version, "single")

    history = arch.history(location_id, 7)
    window = (
        (history[0].day.isoformat(), history[-1].day.isoformat())
        if history
        else (origin.isoformat(), origin.isoformat())
    )

    return ReplayPrediction(
        run_id=rid,
        prediction_id=_prediction_id(rid, location_id, lead),
        mode="B",
        origin=origin,
        valid_day=valid_day,
        lead_time=lead,
        location_id=site.id,
        location_name=site.name,
        subdivision=site.subdivision,
        probability=round(probability, 6),
        predicted_event=probability >= model.threshold,
        threshold=model.threshold,
        features={k: round(v, 6) for k, v in vector.items()},
        contributions={k: round(v, 6) for k, v in contrib.items()},
        base_value=round(base, 6),
        evidence_window=window,
        model_version=version,
    )


# ---------------------------------------------------------------------------
# Phase 2 - validation. Reads T+1..T+7. Runs strictly after phase 1.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayValidation:
    """What actually happened, set against a prediction that never saw it."""

    prediction_id: str
    valid_day: date
    observed_available: bool
    observed_rainfall: float | None
    observed_normal: float | None
    observed_departure_pct: float | None
    observed_category: str | None
    actual_event: bool | None
    predicted_event: bool
    probability: float
    outcome: str
    note: str | None = None


def _outcome(predicted: bool, actual: bool | None) -> str:
    if actual is None:
        return "not verifiable"
    if predicted and actual:
        return "hit"
    if predicted and not actual:
        return "false alarm"
    if not predicted and actual:
        return "miss"
    return "correct negative"


def validate_prediction_against_actual(
    prediction: ReplayPrediction,
) -> ReplayValidation:
    """Phase 2. Compare a finished prediction with the published observation.

    Holds an `Outcomes`, which refuses to read anything at or before the origin,
    and takes the prediction as an immutable input. There is no path by which
    this function can change what was predicted.

    When the observational record does not cover the valid day, the result is
    `observed_available: false`. It is never filled in.
    """
    model = load_model()
    threshold = model.threshold if model else prediction.threshold
    outcomes = Outcomes(origin=prediction.origin)
    actual: SiteDay | None = outcomes.actual(prediction.location_id, prediction.valid_day)

    if actual is None:
        start, end = archive_mod.coverage()
        return ReplayValidation(
            prediction_id=prediction.prediction_id,
            valid_day=prediction.valid_day,
            observed_available=False,
            observed_rainfall=None,
            observed_normal=None,
            observed_departure_pct=None,
            observed_category=None,
            actual_event=None,
            predicted_event=prediction.predicted_event,
            probability=prediction.probability,
            outcome="not verifiable",
            note=(
                f"The daily observational record covers {start.isoformat()} to "
                f"{end.isoformat()} and does not include "
                f"{prediction.valid_day.isoformat()}. The observation is absent, "
                "not zero - no value is substituted."
            ),
        )

    event_label = model.event["label"] if model else "Large Excess"
    actual_event = actual.category == event_label

    return ReplayValidation(
        prediction_id=prediction.prediction_id,
        valid_day=prediction.valid_day,
        observed_available=True,
        observed_rainfall=round(actual.actual, 2),
        observed_normal=round(actual.normal, 2),
        observed_departure_pct=(
            round(actual.departure_pct, 1) if actual.departure_pct is not None else None
        ),
        observed_category=actual.category,
        actual_event=actual_event,
        predicted_event=prediction.probability >= threshold,
        probability=prediction.probability,
        outcome=_outcome(prediction.probability >= threshold, actual_event),
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class AuditEntry:
    step: str
    phase: str
    detail: str
    reads: str
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


def availability(origin: date, leads: tuple[int, ...] = LEADS) -> dict[str, object]:
    """What a replay from this origin can and cannot do, before running it.

    Answers both modes honestly, including for origins the archive does not
    reach at all - which is the case for every date before 2026-08-19.
    """
    start, end = archive_mod.coverage()
    valid_days = [origin + timedelta(days=l) for l in leads]
    antecedent = [origin - timedelta(days=d) for d in range(rf.MIN_ANTECEDENT_DAYS)]

    missing_valid = archive_mod.missing_days(valid_days)
    missing_antecedent = archive_mod.missing_days(antecedent)

    hc = hindcast.availability(origin)

    mode_b_ok = not missing_antecedent
    return {
        "origin": origin.isoformat(),
        "leads": list(leads),
        "valid_days": [d.isoformat() for d in valid_days],
        "archive": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": (end - start).days + 1,
            "source": "IMD district-wise daily rainfall",
        },
        "mode_a": {
            "id": "A",
            "name": "Forecast-bust validation",
            "available": hc.available,
            "reason": hc.reason,
            "looked_for": list(hc.looked_for),
            "candidate_archives": list(hc.candidates),
        },
        "mode_b": {
            "id": "B",
            "name": "Historical weather risk proxy",
            "available": mode_b_ok,
            "reason": (
                "Antecedent observations available; predictions can be formed."
                if mode_b_ok
                else (
                    f"The daily observational record covers {start.isoformat()} to "
                    f"{end.isoformat()}. This origin needs observations for "
                    + ", ".join(d.isoformat() for d in missing_antecedent[:4])
                    + (" and others" if len(missing_antecedent) > 4 else "")
                    + ", which are not present. Missing daily data must be imported "
                    "(scripts/import_imd_daily_rainfall.py), never generated."
                )
            ),
            "missing_antecedent_days": [d.isoformat() for d in missing_antecedent],
        },
        "verification": {
            "verifiable_days": [
                d.isoformat() for d in valid_days if d not in missing_valid
            ],
            "unverifiable_days": [d.isoformat() for d in missing_valid],
            "note": "Predictions for unverifiable days are still formed and shown; "
            "they simply carry no outcome. No observation is invented to score them.",
        },
        "model_trained": load_model() is not None,
    }


def replay_window(
    origin: date,
    location_id: str,
    leads: tuple[int, ...] = LEADS,
) -> dict[str, object]:
    """A full 7-day replay for one site: predict everything, then verify it.

    The two loops below are the whole point. The first completes before the
    second begins, and the predictions it produces are frozen dataclasses - so
    even if the verification loop wanted to influence them, it could not.
    """
    site = ALL_SITES_BY_ID.get(location_id)
    if site is None:
        raise ReplayUnavailable(f"Unknown location '{location_id}'")

    model = load_model()
    if model is None:
        raise ReplayUnavailable(
            "The replay model has not been trained. Run "
            "`python -m scripts.train_replay_model` in backend/."
        )

    state = availability(origin, leads)
    version = _model_version(model)
    run = _run_id(origin, version, f"window:{location_id}")
    audit: list[AuditEntry] = [
        AuditEntry(
            step="availability",
            phase="pre-flight",
            detail=f"Mode A available: {state['mode_a']['available']}. "
            f"Mode B available: {state['mode_b']['available']}.",
            reads="dataset coverage only",
        )
    ]

    if not state["mode_b"]["available"]:
        audit.append(
            AuditEntry(
                step="abort",
                phase="pre-flight",
                detail="Insufficient antecedent observations. No prediction formed.",
                reads="none",
            )
        )
        return {
            "run_id": run,
            "mode": "B",
            "origin": origin.isoformat(),
            "location_id": site.id,
            "location_name": site.name,
            "availability": state,
            "predictions": [],
            "validations": [],
            "summary": None,
            "audit_log": [asdict(a) for a in audit],
            "model_version": version,
        }

    # ---- Phase 1: predict. Nothing in this block can read an outcome. ----
    predictions: list[ReplayPrediction] = []
    for lead in leads:
        pred = generate_prediction(origin, location_id, lead, run_id=run)
        if pred is not None:
            predictions.append(pred)
    audit.append(
        AuditEntry(
            step="generate_prediction",
            phase="1 - prediction",
            detail=f"{len(predictions)} prediction(s) formed for leads "
            f"{[p.lead_time for p in predictions]}.",
            reads=f"observations <= {origin.isoformat()} (Archive guard active)",
        )
    )

    # ---- Phase 2: verify. Runs only now, on frozen predictions. ----
    validations = [validate_prediction_against_actual(p) for p in predictions]
    verified = [v for v in validations if v.observed_available]
    audit.append(
        AuditEntry(
            step="validate_prediction_against_actual",
            phase="2 - validation",
            detail=f"{len(verified)} of {len(validations)} prediction(s) had a "
            "published observation to verify against.",
            reads=f"observations > {origin.isoformat()} (Outcomes guard active)",
        )
    )

    return {
        "run_id": run,
        "mode": "B",
        "mode_name": "Historical weather risk proxy",
        "mode_note": model.mode_note,
        "event": model.event,
        "origin": origin.isoformat(),
        "location_id": site.id,
        "location_name": site.name,
        "subdivision": site.subdivision,
        "threshold": model.threshold,
        "availability": state,
        "predictions": [_pred_payload(p) for p in predictions],
        "validations": [_val_payload(v) for v in validations],
        "summary": _summary(validations),
        "audit_log": [asdict(a) for a in audit],
        "model_version": version,
    }


def _pred_payload(p: ReplayPrediction) -> dict[str, object]:
    top = sorted(p.contributions.items(), key=lambda kv: -abs(kv[1]))[:6]
    return {
        "prediction_id": p.prediction_id,
        "origin": p.origin.isoformat(),
        "valid_day": p.valid_day.isoformat(),
        "lead_time": p.lead_time,
        "location_id": p.location_id,
        "probability": p.probability,
        "predicted_event": p.predicted_event,
        "threshold": p.threshold,
        "evidence_window": list(p.evidence_window),
        "base_value": p.base_value,
        "contributions": [
            {
                "feature": name,
                "label": rf.REPLAY_PREDICTOR_META[name][0],
                "description": rf.REPLAY_PREDICTOR_META[name][1],
                "value": p.features[name],
                "contribution": value,
            }
            for name, value in top
        ],
    }


def _val_payload(v: ReplayValidation) -> dict[str, object]:
    return {
        "prediction_id": v.prediction_id,
        "valid_day": v.valid_day.isoformat(),
        "observed_available": v.observed_available,
        "observed_rainfall": v.observed_rainfall,
        "observed_normal": v.observed_normal,
        "observed_departure_pct": v.observed_departure_pct,
        "observed_category": v.observed_category,
        "actual_event": v.actual_event,
        "predicted_event": v.predicted_event,
        "probability": v.probability,
        "outcome": v.outcome,
        "note": v.note,
    }


def _summary(validations: list[ReplayValidation]) -> dict[str, object] | None:
    verified = [v for v in validations if v.observed_available]
    if not verified:
        return None
    counts = {"hit": 0, "false alarm": 0, "miss": 0, "correct negative": 0}
    for v in verified:
        counts[v.outcome] = counts.get(v.outcome, 0) + 1
    correct = counts["hit"] + counts["correct negative"]
    return {
        "verified_days": len(verified),
        "unverified_days": len(validations) - len(verified),
        **counts,
        "correct": correct,
        "hit_rate": (
            round(counts["hit"] / (counts["hit"] + counts["miss"]), 4)
            if counts["hit"] + counts["miss"]
            else None
        ),
        "false_alarm_ratio": (
            round(counts["false alarm"] / (counts["hit"] + counts["false alarm"]), 4)
            if counts["hit"] + counts["false alarm"]
            else None
        ),
        "note": "Counts from a single 7-day window. Seven cases cannot support a "
        "skill claim; the backtest endpoint aggregates across all origins.",
    }


# ---------------------------------------------------------------------------
# Walk-forward backtest
# ---------------------------------------------------------------------------


def usable_origins() -> list[date]:
    """Origins with enough antecedent record behind them and a lead ahead.

    The front of the archive is consumed by the antecedent window and the back
    by the lead time, so a 22-day record yields far fewer than 22 origins. That
    arithmetic is reported rather than hidden.
    """
    start, end = archive_mod.coverage()
    first = start + timedelta(days=rf.MIN_ANTECEDENT_DAYS - 1)
    last = end - timedelta(days=1)
    out: list[date] = []
    day = first
    while day <= last:
        out.append(day)
        day += timedelta(days=1)
    return out


def _roc_auc(y: list[int], s: list[float]) -> float | None:
    """Mann-Whitney U with tie correction. None when one class is absent."""
    pos = sum(y)
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        return None
    order = sorted(range(len(s)), key=lambda i: s[i])
    ranks = [0.0] * len(s)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and s[order[j + 1]] == s[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    rank_sum = sum(r for r, label in zip(ranks, y) if label == 1)
    return round((rank_sum - pos * (pos + 1) / 2.0) / (pos * neg), 4)


def _confusion(y: list[int], s: list[float], threshold: float) -> dict[str, object]:
    tp = fp = fn = tn = 0
    for label, score in zip(y, s):
        flag = score >= threshold
        if flag and label:
            tp += 1
        elif flag:
            fp += 1
        elif label:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "threshold": threshold,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(
            2 * precision * recall / (precision + recall) if precision + recall else 0.0, 4
        ),
        "accuracy": round((tp + tn) / len(y), 4) if y else None,
        "base_rate": round(sum(y) / len(y), 4) if y else None,
    }


def _reliability(y: list[int], s: list[float], bins: int = 5) -> list[dict[str, object]]:
    """Observed frequency against predicted probability.

    A calibrated model sits on the diagonal. Bins are reported with their
    counts so a bin holding four cases is not read as evidence.
    """
    out: list[dict[str, object]] = []
    width = 1.0 / bins
    for b in range(bins):
        lo, hi = b * width, (b + 1) * width
        idx = [
            i
            for i, score in enumerate(s)
            if (score >= lo and score < hi) or (b == bins - 1 and score == 1.0)
        ]
        out.append(
            {
                "bin_lower": round(lo, 2),
                "bin_upper": round(hi, 2),
                "count": len(idx),
                "mean_predicted": round(sum(s[i] for i in idx) / len(idx), 4) if idx else None,
                "observed_rate": round(sum(y[i] for i in idx) / len(idx), 4) if idx else None,
            }
        )
    return out


def _group_metrics(
    rows: list[dict], key: str, threshold: float, min_count: int = 20
) -> list[dict[str, object]]:
    groups: dict[object, list[dict]] = {}
    for row in rows:
        groups.setdefault(row[key], []).append(row)
    out: list[dict[str, object]] = []
    for value, items in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(items) < min_count:
            continue
        y = [r["actual"] for r in items]
        s = [r["probability"] for r in items]
        out.append(
            {
                key: value,
                "count": len(items),
                "events": sum(y),
                "roc_auc": _roc_auc(y, s),
                "brier": round(sum((a - b) ** 2 for a, b in zip(s, y)) / len(y), 4),
                **{
                    k: v
                    for k, v in _confusion(y, s, threshold).items()
                    if k in {"precision", "recall", "f1", "base_rate"}
                },
            }
        )
    return out


@lru_cache(maxsize=8)
def backtest(leads: tuple[int, ...] = LEADS) -> dict[str, object]:
    """Walk-forward replay across every usable origin and every site.

    For each origin in turn: form predictions from data up to that origin, then
    verify them against what followed. The origin advances one day at a time and
    never looks beyond itself - which is what "walk-forward" has to mean if the
    number at the end is to be worth reading.

    The model's own held-out metrics (from `scripts/train_replay_model`) are
    reported alongside, and they are the ones to trust: this backtest spans
    origins the model was fitted on as well as ones it was not, so its headline
    figure is optimistic by construction. Both are shown rather than the
    flattering one alone.
    """
    model = load_model()
    if model is None:
        raise ReplayUnavailable(
            "The replay model has not been trained. Run "
            "`python -m scripts.train_replay_model` in backend/."
        )

    origins = usable_origins()
    rows: list[dict] = []
    skipped_unverifiable = 0

    for origin in origins:
        arch = Archive(origin=origin)
        outcomes = Outcomes(origin=origin)
        for site in ALL_SITES:
            for lead in leads:
                valid = origin + timedelta(days=lead)
                vector = rf.build_vector(arch, site.id, valid)
                if vector is None:
                    continue
                probability = model.probability(vector)
                actual = outcomes.actual(site.id, valid)
                if actual is None:
                    skipped_unverifiable += 1
                    continue
                rows.append(
                    {
                        "origin": origin.isoformat(),
                        "valid": valid.isoformat(),
                        "lead_time": lead,
                        "location_id": site.id,
                        "subdivision": site.subdivision,
                        "probability": probability,
                        "actual": 1 if actual.category == model.event["label"] else 0,
                    }
                )

    if not rows:
        raise ReplayUnavailable("No verifiable prediction-outcome pairs in the archive.")

    y = [r["actual"] for r in rows]
    s = [r["probability"] for r in rows]
    train_origins = set(model.training.get("train_origins", []))
    out_of_sample = [r for r in rows if r["origin"] not in train_origins]

    payload: dict[str, object] = {
        "mode": "B",
        "mode_name": "Historical weather risk proxy",
        "mode_note": model.mode_note,
        "event": model.event,
        "threshold": model.threshold,
        "model_version": _model_version(model),
        "window": {
            "origins": [d.isoformat() for d in origins],
            "origin_count": len(origins),
            "archive_start": archive_mod.coverage()[0].isoformat(),
            "archive_end": archive_mod.coverage()[1].isoformat(),
            "sites": len(ALL_SITES),
            "leads": list(leads),
        },
        "counts": {
            "prediction_outcome_pairs": len(rows),
            "events": sum(y),
            "skipped_no_observation": skipped_unverifiable,
        },
        "overall": {
            "roc_auc": _roc_auc(y, s),
            "brier": round(sum((a - b) ** 2 for a, b in zip(s, y)) / len(y), 4),
            "confusion": _confusion(y, s, model.threshold),
            "reliability": _reliability(y, s),
        },
        "out_of_sample": (
            {
                "origins": sorted({r["origin"] for r in out_of_sample}),
                "count": len(out_of_sample),
                "roc_auc": _roc_auc(
                    [r["actual"] for r in out_of_sample],
                    [r["probability"] for r in out_of_sample],
                ),
                "confusion": _confusion(
                    [r["actual"] for r in out_of_sample],
                    [r["probability"] for r in out_of_sample],
                    model.threshold,
                ),
            }
            if out_of_sample
            else None
        ),
        "by_lead": _group_metrics(rows, "lead_time", model.threshold),
        "by_subdivision": _group_metrics(rows, "subdivision", model.threshold, min_count=40),
        "by_origin": _group_metrics(rows, "origin", model.threshold, min_count=40),
        "model_holdout": model.metrics,
        "caveat": model.caveat,
        "honesty_note": (
            "The 'overall' figure spans origins the model was fitted on, so it is "
            "optimistic. 'out_of_sample' and 'model_holdout' are the honest ones. "
            "Every observed value is a published IMD measurement; days the record "
            "does not cover are counted under skipped_no_observation and scored "
            "nowhere."
        ),
    }
    return payload
