"""AtmosGuard HTTP API.

Route handlers stay thin: validate inputs, delegate to `app.core.service`,
return. Every payload that carries simulated numbers also carries `data_mode`
and `demo_notice` so no client can render them as operational output by
accident.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..core import alerts as alerts_core
from ..core import climate, risk_model, scenarios, service, verification, warnings as warnings_core
from ..core import hindcast, monthly, replay, station_replay
from ..ingest import imd_live, live_weather
from ..ingest import sources as ingest_sources
from ..core.domain import (
    ALL_SITES_BY_ID,
    LOCATIONS,
    MODELS,
    MODELS_BY_ID,
    REGIONS,
    RISK_BANDS,
    VARIABLES,
    VARIABLES_BY_ID,
)
from ..schemas import (
    AlertsResponse,
    MetaResponse,
    NetworkResponse,
    RiskResponse,
    VerificationResponse,
)

router = APIRouter(prefix="/api")

HORIZONS = [3, 4, 5, 6, 7]

BAND_COLORS = {
    "LOW": "#22c55e",
    "MODERATE": "#eab308",
    "HIGH": "#f97316",
    "SEVERE": "#ef4444",
}


def _reference_date() -> date:
    return date.fromisoformat(settings.demo_reference_date)


def _parse_date(value: str | None) -> date:
    if not value:
        return _reference_date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date '{value}'") from exc


def _validate(location_id: str, variable_id: str, model_id: str, horizon: int) -> None:
    if location_id not in ALL_SITES_BY_ID:
        raise HTTPException(status_code=404, detail=f"Unknown location '{location_id}'")
    if variable_id not in VARIABLES_BY_ID:
        raise HTTPException(status_code=404, detail=f"Unknown variable '{variable_id}'")
    if model_id not in MODELS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Unknown model '{model_id}'")
    if horizon not in HORIZONS:
        raise HTTPException(
            status_code=422, detail=f"Forecast horizon must be one of {HORIZONS}"
        )


@router.get("/meta", response_model=MetaResponse)
def meta() -> dict:
    """Everything the client needs to render its selectors and legends."""
    default = scenarios.SCENARIOS_BY_ID[scenarios.DEFAULT_SCENARIO_ID]
    return {
        "app_name": settings.app_name,
        "tagline": settings.tagline,
        "version": settings.version,
        "data_mode": settings.data_mode,
        "demo_notice": service.DEMO_NOTICE if settings.is_demo else None,
        "reference_date": settings.demo_reference_date,
        "locations": [
            {**loc.__dict__, "featured": True}
            for loc in LOCATIONS
        ],
        "regions": [{**loc.__dict__, "featured": False} for loc in REGIONS],
        "variables": [v.__dict__ for v in VARIABLES],
        "models": [m.__dict__ for m in MODELS],
        "risk_bands": [
            {"name": name, "min": lo, "max": hi, "color": BAND_COLORS[name]}
            for name, lo, hi, _upper in RISK_BANDS
        ],
        "horizons": HORIZONS,
        "scenarios": [s.__dict__ for s in scenarios.SCENARIOS],
        "default_selection": {
            "location_id": "jaipur",
            "variable_id": "rainfall",
            "model_id": "ecmwf",
            "horizon": 5,
            "base_date": imd_live._today_str(),
            "scenario_id": None,
        },
        "disclaimer": service.DISCLAIMER,
    }


@router.get("/risk", response_model=RiskResponse)
def risk(
    location: str = Query(..., description="Location or region id"),
    horizon: int = Query(5, ge=3, le=7, description="Forecast horizon in days"),
    variable: str = Query("rainfall"),
    model: str = Query("ecmwf"),
    forecast_date: str | None = Query(None, description="Initialisation date (ISO)"),
) -> dict:
    """Forecast bust risk, explanation, ensemble, analogues and verification."""
    _validate(location, variable, model, horizon)
    return service.risk_bundle(location, variable, model, _parse_date(forecast_date), horizon)


@router.get("/scenario/{scenario_id}", response_model=RiskResponse)
def scenario(scenario_id: str) -> dict:
    """Resolve a curated Demo Mode scenario."""
    if scenario_id not in scenarios.SCENARIOS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Unknown scenario '{scenario_id}'")
    return service.resolve_scenario(scenario_id)


@router.get("/network", response_model=NetworkResponse)
def network(
    horizon: int = Query(5, ge=3, le=7),
    variable: str = Query("rainfall"),
    model: str = Query("ecmwf"),
    forecast_date: str | None = Query(None),
) -> dict:
    """Risk across the whole monitoring network - powers the map and KPI row."""
    _validate(next(iter(ALL_SITES_BY_ID)), variable, model, horizon)
    base_date = _parse_date(forecast_date)
    summary = alerts_core.network_summary(base_date.isoformat(), variable, horizon, model)
    return {
        **summary,
        "variable_id": variable,
        "horizon": horizon,
        "model_id": model,
        "base_date": base_date.isoformat(),
        "data_mode": settings.data_mode,
        "demo_notice": service.DEMO_NOTICE if settings.is_demo else None,
    }


@router.get("/alerts", response_model=AlertsResponse)
def alert_list(
    forecast_date: str | None = Query(None),
    model: str = Query("ecmwf"),
    severity: str | None = Query(None, description="Filter: LOW/MODERATE/HIGH/SEVERE"),
) -> dict:
    """Active early-warning alerts across the monitoring network."""
    if model not in MODELS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Unknown model '{model}'")
    base_date = _parse_date(forecast_date)
    items = list(alerts_core.scan(base_date.isoformat(), model))

    counts: dict[str, int] = {"LOW": 0, "MODERATE": 0, "HIGH": 0, "SEVERE": 0}
    for item in items:
        counts[str(item["severity"])] += 1

    if severity:
        wanted = severity.upper()
        if wanted not in counts:
            raise HTTPException(status_code=422, detail=f"Unknown severity '{severity}'")
        items = [i for i in items if i["severity"] == wanted]

    return {
        "alerts": items,
        "counts": counts,
        "threshold": alerts_core.ALERT_THRESHOLD,
        "probability_threshold": alerts_core.ALERT_PROBABILITY,
        "base_date": base_date.isoformat(),
        "data_mode": settings.data_mode,
        "demo_notice": service.DEMO_NOTICE if settings.is_demo else None,
        "disclaimer": service.DISCLAIMER,
    }


@router.get("/verification/model", response_model=VerificationResponse)
def model_verification(forecast_date: str | None = Query(None)) -> dict:
    """Risk-model classification performance, computed over the dataset."""
    base_date = _parse_date(forecast_date)
    return {
        "model_performance": verification.model_performance(base_date),
        "label": "MVP Demonstration Metrics"
        if settings.is_demo
        else "Operational verification",
        "data_mode": settings.data_mode,
        "demo_notice": service.DEMO_NOTICE if settings.is_demo else None,
        "disclaimer": service.DISCLAIMER,
    }


@router.get("/verification/forecast")
def forecast_verification(
    location: str = Query(...),
    variable: str = Query("rainfall"),
    forecast_date: str | None = Query(None),
    lookback: int = Query(21, ge=7, le=90),
) -> dict:
    """Rolling forecast-vs-observation verification for one site."""
    if location not in ALL_SITES_BY_ID:
        raise HTTPException(status_code=404, detail=f"Unknown location '{location}'")
    if variable not in VARIABLES_BY_ID:
        raise HTTPException(status_code=404, detail=f"Unknown variable '{variable}'")
    base_date = _parse_date(forecast_date)
    payload = verification.forecast_verification(location, variable, base_date, lookback)
    return {
        **payload,
        "location_id": location,
        "variable_id": variable,
        "label": "MVP Demonstration Metrics" if settings.is_demo else "Operational verification",
        "data_mode": settings.data_mode,
    }


@router.get("/warnings")
def warning_map(
    horizon: int = Query(5, ge=3, le=7),
    model: str = Query("ecmwf"),
    forecast_date: str | None = Query(None),
) -> dict:
    """State-level forecast-reliability levels, in the familiar four colours.

    Not IMD weather warnings: what is graded here is how dependable the forecast
    looks, not what the weather will do. The response carries that distinction
    in `disclaimer`, and every client is expected to show it.
    """
    if model not in MODELS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Unknown model '{model}'")
    if horizon not in HORIZONS:
        raise HTTPException(status_code=422, detail=f"Forecast horizon must be one of {HORIZONS}")

    base_date = _parse_date(forecast_date)
    states = warnings_core.state_warnings(base_date, horizon, model)
    return {
        "states": states,
        **warnings_core.summary(states),
        "base_date": base_date.isoformat(),
        "valid_date": (base_date + timedelta(days=horizon)).isoformat(),
        "horizon": horizon,
        "model_id": model,
        "data_mode": settings.data_mode,
        "demo_notice": service.DEMO_NOTICE if settings.is_demo else None,
    }


@router.get("/sources")
def data_sources() -> dict:
    """The catalogue of official data sources, with references.

    Status is honest: only datasets physically present and wired in are marked
    "in use". Everything else is a documented route to data this system could
    consume, not a live connection.
    """
    return {
        "sources": [s.__dict__ for s in ingest_sources.SOURCES],
        "in_use": [s.id for s in ingest_sources.in_use()],
        "counts": {
            level: len(ingest_sources.by_access(level))
            for level in ingest_sources.ACCESS_ORDER
        },
        "note": "Portal addresses are stable; deep links to individual files are not. "
        "Confirm the exact path at the source.",
    }


@router.get("/climate/{location_id}")
def climate_profile(location_id: str) -> dict:
    """Long-record climate context for a site's IMD sub-division.

    Trend, variability, the distribution of past monsoons against IMD's own
    departure categories, and the decadal record - all from the published
    1901-2017 series. This is the background a forecaster reads a single
    forecast against.
    """
    site = ALL_SITES_BY_ID.get(location_id)
    if site is None:
        raise HTTPException(status_code=404, detail=f"Unknown location '{location_id}'")
    payload = climate.profile(site.subdivision)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No climate record for sub-division '{site.subdivision}'",
        )
    return {**payload, "location_id": site.id, "location_name": site.name}


@router.get("/system/status")
def system_status(forecast_date: str | None = Query(None)) -> dict:
    """Data-source and pipeline status."""
    return service.system_status(_parse_date(forecast_date))


@router.get("/model/card")
def model_card() -> dict:
    """Model card for the risk estimator currently in use."""
    return risk_model.model_card()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "data_mode": settings.data_mode, "version": settings.version}


# ---------------------------------------------------------------------------
# Historical replay - additive. None of the endpoints above change behaviour.
# ---------------------------------------------------------------------------


@router.get("/replay/availability")
def replay_availability(origin: str | None = Query(None)) -> dict:
    """What a replay from this origin can and cannot do, before it runs.

    Answers for both modes. Mode A needs an archived NWP forecast and says so
    when none exists; Mode B needs antecedent observations and says which days
    are missing. Origins the archive does not reach - every date before the
    daily record begins - are reported as unavailable, never approximated.
    """
    return replay.availability(_parse_date(origin))


@router.get("/replay/origins")
def replay_origins() -> dict:
    """Origin dates the observational archive can actually support."""
    origins = replay.usable_origins()
    start, end = replay.archive_mod.coverage()
    # Default to the most recent origin whose whole 7-day window can still be
    # verified. The later origins are offered too - they are legitimate, and
    # their unverifiable days are shown as gaps - but opening on one would put
    # six empty rows in front of a first-time reader.
    fully_verifiable = [d for d in origins if (end - d).days >= max(replay.LEADS)]
    default = (fully_verifiable or origins)[-1] if origins else None
    return {
        "origins": [d.isoformat() for d in origins],
        "count": len(origins),
        "default": default.isoformat() if default else None,
        "fully_verifiable_through": fully_verifiable[-1].isoformat() if fully_verifiable else None,
        "archive_start": start.isoformat(),
        "archive_end": end.isoformat(),
        "min_antecedent_days": replay.rf.MIN_ANTECEDENT_DAYS,
        "note": "The front of the archive is consumed by the antecedent window "
        "and the back by the lead time, so a 22-day record yields fewer origins "
        "than it has days.",
    }


@router.get("/replay/run")
def replay_run(
    origin: str | None = Query(None),
    location_id: str = Query("jaipur"),
) -> dict:
    """A full 7-day replay for one site: predict from <= T, then verify T+1..T+7.

    The two phases run in sequence and cannot see each other's data - the
    prediction phase holds a guarded archive that raises on any read past the
    origin. The returned `audit_log` records what each phase was permitted to
    read.
    """
    if location_id not in ALL_SITES_BY_ID:
        raise HTTPException(status_code=404, detail=f"Unknown location '{location_id}'")
    try:
        return replay.replay_window(_parse_date(origin), location_id)
    except replay.ReplayUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/replay/backtest")
def replay_backtest() -> dict:
    """Walk-forward replay across every usable origin and every site.

    Reports the in-sample figure and the out-of-sample figure side by side, plus
    the model's own held-out metrics. The last two are the honest ones and the
    payload says so.
    """
    try:
        return replay.backtest()
    except replay.ReplayUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/replay/model")
def replay_model_card() -> dict:
    """Model card for the replay estimator: what it predicts, and how well."""
    model = replay.load_model()
    if model is None:
        raise HTTPException(
            status_code=409,
            detail="The replay model has not been trained. Run "
            "`python -m scripts.train_replay_model` in backend/.",
        )
    return {
        "name": "Replay risk model",
        "kind": "Logistic regression (L2, IRLS)",
        "model_version": replay._model_version(model),
        "mode": "B",
        "mode_name": "Historical weather risk proxy",
        "mode_note": model.mode_note,
        "event": model.event,
        "threshold": model.threshold,
        "threshold_note": "Fixed at 0.50 before evaluation and never tuned on "
        "the held-out origins.",
        "predictors": [
            {
                "name": name,
                "label": replay.rf.REPLAY_PREDICTOR_META[name][0],
                "description": replay.rf.REPLAY_PREDICTOR_META[name][1],
                "coefficient": round(model.coefficients[name], 4),
            }
            for name in model.predictors
        ],
        "explanation_method": "Exact Shapley values (closed form for a model "
        "linear in the log-odds).",
        "training": model.training,
        "metrics": model.metrics,
        "caveat": model.caveat,
        "leakage_controls": [
            "Features are built through core.archive.Archive, which raises "
            "LeakageError on any read after the origin date.",
            "Validation runs through core.archive.Outcomes, which raises on any "
            "read at or before the origin date.",
            "The two phases are separate functions; predictions are frozen "
            "dataclasses by the time verification begins.",
            "The train/test split is temporal, by origin date, because "
            "neighbouring days share a weather system.",
        ],
    }


@router.get("/replay/requirements")
def replay_requirements(origin: str | None = Query(None)) -> dict:
    """Exactly what data a genuine Mode A validation of this origin would need."""
    day = _parse_date(origin)
    payload = hindcast.requirements(day)
    state = replay.availability(day)
    # Answer the observation question against the real archive rather than
    # leaving it open.
    for need in payload["needs"]:
        if need["item"] == "Daily observed rainfall":
            need["present"] = not state["verification"]["unverifiable_days"]
            need["missing_days"] = state["verification"]["unverifiable_days"]
    payload["mode_a_available"] = state["mode_a"]["available"]
    payload["mode_b_available"] = state["mode_b"]["available"]
    return payload


# ---------------------------------------------------------------------------
# Monthly replay over the 1901-2017 sub-division record
# ---------------------------------------------------------------------------


@router.get("/monthly/meta")
def monthly_meta() -> dict:
    """Sub-divisions, the year span, and what this replay can and cannot do."""
    model = monthly.load_model()
    first, last = monthly.record_span()
    return {
        "subdivisions": list(monthly.subdivisions()),
        "record_start": first,
        "record_end": last,
        "test_from_year": monthly.TEST_FROM_YEAR,
        "extreme_z": monthly.EXTREME_Z,
        "resolution": "month",
        "resolution_note": (
            "The sub-division file holds one figure per sub-division per month. "
            "A date inside a month selects that whole month; individual days "
            "cannot be resolved and no daily value is derived from a monthly "
            "total."
        ),
        "model_trained": model is not None,
        "event": model.event if model else None,
        "threshold_note": model.threshold_note if model else None,
        "training": model.training if model else None,
        "caveat": model.caveat if model else None,
    }


@router.get("/monthly/replay")
def monthly_replay(
    on: str | None = Query(None, description="Any date; selects the month containing it"),
    subdivision: str | None = Query(None),
) -> dict:
    """Predict the month containing `on`, from the record up to the month before.

    Give it 2015-08-05 and it answers for August 2015, using nothing later than
    July 2015, then sets that against what the published record says August 2015
    actually did - for every sub-division at once, or one if named.
    """
    try:
        day = _parse_date(on) if on else date(2015, 8, 5)
    except HTTPException:
        raise
    target = monthly.YearMonth.containing(day)
    origin = target.shift(-1)

    first, last = monthly.record_span()
    if not first <= target.year <= last:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The sub-division record covers {first}-{last}. "
                f"{target.label} lies outside it, and nothing is extrapolated."
            ),
        )

    if subdivision:
        resolved = monthly.resolve(subdivision)
        if resolved is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown sub-division '{subdivision}'"
            )
        names = [resolved]
    else:
        names = list(monthly.subdivisions())

    try:
        rows = []
        for name in names:
            # Attributions only when one sub-division was asked for: a
            # whole-country sweep shows none of them.
            prediction = monthly.generate_monthly_prediction(
                origin, name, target, explain=bool(subdivision)
            )
            if prediction is None:
                continue
            rows.append(
                {
                    "prediction": prediction,
                    "validation": monthly.validate_monthly_prediction(prediction),
                }
            )
    except monthly.MonthlyUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    verified = [r for r in rows if r["validation"].get("observed_available")]
    counts: dict[str, int] = {}
    for row in verified:
        verdict = str(row["validation"]["verdict"])
        counts[verdict] = counts.get(verdict, 0) + 1
    hits = counts.get("hit", 0)
    misses = counts.get("miss", 0)
    false_alarms = counts.get("false alarm", 0)

    model = monthly.load_model()
    return {
        "requested_date": day.isoformat(),
        "target": target.isoformat(),
        "target_label": target.label,
        "origin": origin.isoformat(),
        "origin_label": origin.label,
        "held_out": target.year >= monthly.TEST_FROM_YEAR,
        "resolution_note": model.resolution_note if model else None,
        "event": model.event if model else None,
        "rows": rows,
        "summary": {
            "subdivisions": len(rows),
            "verified": len(verified),
            **counts,
            "correct": hits + counts.get("correct negative", 0),
            "accuracy": round((hits + counts.get("correct negative", 0)) / len(verified), 4)
            if verified
            else None,
            "hit_rate": round(hits / (hits + misses), 4) if hits + misses else None,
            "false_alarm_ratio": round(false_alarms / (hits + false_alarms), 4)
            if hits + false_alarms
            else None,
            "actual_extremes": sum(
                1 for r in verified if r["validation"].get("actual_extreme")
            ),
        },
    }


@router.get("/monthly/model")
def monthly_model_card() -> dict:
    """Model card for the monthly estimator."""
    model = monthly.load_model()
    if model is None:
        raise HTTPException(
            status_code=409,
            detail="The monthly model has not been trained. Run "
            "`python -m scripts.train_monthly_model` in backend/.",
        )
    return {
        "name": "Monthly extreme-rainfall model",
        "kind": "Logistic regression (L2, IRLS), one per target",
        "resolution": "month",
        "resolution_note": model.resolution_note,
        "event": model.event,
        "nominal_threshold": model.nominal_threshold,
        "threshold_note": model.threshold_note,
        "targets": {
            name: {
                "operating_threshold": block["operating_threshold"],
                "metrics": block["metrics"],
            }
            for name, block in model.targets.items()
        },
        "predictors": [
            {
                "name": name,
                "label": monthly.MONTHLY_PREDICTOR_META[name][0],
                "description": monthly.MONTHLY_PREDICTOR_META[name][1],
                "coefficients": {
                    t: round(block["coefficients"][name], 4)
                    for t, block in model.targets.items()
                },
            }
            for name in model.predictors
        ],
        "explanation_method": "Exact Shapley values (closed form for a model "
        "linear in the log-odds).",
        "training": model.training,
        "caveat": model.caveat,
        "leakage_controls": [
            "Features are built through MonthlyArchive, which raises "
            "MonthlyLeakageError on any read after the origin month.",
            "Validation runs through MonthlyOutcomes, which raises on any read "
            "at or before it.",
            "Climatology is an expanding window: for a target in year Y it is "
            "computed from years strictly before Y, so no test year informs its "
            "own baseline.",
            "The split is a block by target year - everything from 2010 is held "
            "out, not a shuffled fraction.",
            "The operating threshold is the quantile matching the training base "
            "rate, chosen on training years alone and frozen before scoring.",
        ],
    }


# ---------------------------------------------------------------------------
# 7-day station replay, 2010-2017 (NOAA GHCN-Daily)
# ---------------------------------------------------------------------------


def _station_card() -> dict:
    models = station_replay.load_models()
    if models is None:
        raise HTTPException(
            status_code=409,
            detail="The station models have not been trained. Run "
            "`python -m scripts.train_station_model` in backend/.",
        )
    return models["card"]  # type: ignore[return-value]


@router.get("/stations/meta")
def stations_meta() -> dict:
    """Stations, the replayable date range, and the model's held-out record."""
    card = _station_card()
    first = station_replay.TEST_START
    last = station_replay.LAST_DAY - timedelta(days=max(station_replay.LEADS))
    return {
        "stations": [s.__dict__ for s in station_replay.stations()],
        "default_station": "IN022021900",
        "default_date": "2015-08-17",
        "first_date": first.isoformat(),
        "last_date": last.isoformat(),
        "train_period": card["training"]["train_period"],
        "test_period": card["training"]["test_period"],
        "forecast_note": card["forecast_note"],
        "bust_definition": card["bust_definition"],
        "thresholds": card["thresholds"],
        "overall": card["metrics"]["overall"],
        "by_lead": card["metrics"]["by_lead"],
        "by_year": card["metrics"]["by_year"],
        "bust_any": {
            k: card["metrics"]["bust_any"][k]
            for k in (
                "rows", "roc_auc", "brier", "brier_climatology", "confusion_operating",
                "reliability", "call_accuracy_operating", "call_accuracy_at_50",
                "call_accuracy_always_no",
            )
        },
        "source": card["training"]["source"],
        "source_url": "https://registry.opendata.aws/noaa-ghcn/",
    }


@router.get("/stations/replay")
def stations_replay(
    on: str | None = Query(None, description="Origin date, 2010-01-01 to 2021-12-24"),
    station: str | None = Query(None),
) -> dict:
    """Forecast the 7 days after `on` from data up to `on`, then check them.

    Phase 1 forms the forecast and the bust probability of each day. Phase 2
    opens the record for the seven days that followed and scores it. The model
    was fitted on 1995-2009, so any origin from 2010 is one it has never seen.
    """
    _station_card()
    origin = _parse_date(on) if on else date(2015, 8, 17)
    station_id = station or "IN022021900"
    if origin < station_replay.TEST_START:
        raise HTTPException(
            status_code=422,
            detail="Pick a date from 2010 onward. Earlier dates fall in the model's "
            "training years, where a replay would be scored on data it learned from.",
        )
    try:
        forecast = station_replay.generate_forecast(station_id, origin)
    except station_replay.StationReplayUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    validation = station_replay.validate_forecast(forecast)
    return {
        **forecast,
        "validation": validation,
        "forecast_note": _station_card()["forecast_note"],
    }


@router.get("/stations/model")
def stations_model_card() -> dict:
    """Full model card for the station forecast and bust models."""
    card = _station_card()
    return {
        "name": "7-day station forecast and bust model",
        "kind": "Histogram gradient boosting: 4 weather models + 3 bust classifiers",
        **card,
        "leakage_controls": [
            "Origin features are built only from arrays shifted backward in time; "
            "a negative lag raises.",
            "Climatology comes from 1995-2009 alone - no held-out year contributes "
            "to the normal it is judged against.",
            "Fitted on 1995-2009; every origin and every target day in 2010-2017 "
            "is held out. A training forecast landing in 2010 is dropped.",
            "The bust classifiers learn from out-of-fold forecasts: five blocks of "
            "three years, each forecast by a model that never saw it.",
            "Thresholds and the persistence shrinkage are chosen on the out-of-fold "
            "training forecasts, frozen before 2010-2017 is scored.",
            "Unreported observations stay missing. They are never filled with zero.",
        ],
    }


# ---------------------------------------------------------------------------
# Live IMD feed
# ---------------------------------------------------------------------------


@router.get("/imd/live")
def imd_live_status(refresh: bool = Query(False)) -> dict:
    """Whether real IMD city forecasts are flowing, and if not, exactly why.

    Only a server whose public IP is registered with the IMD key can connect.
    No demonstration data is ever substituted: outside the `connected` state
    the city list is empty and the message says what to fix.
    """
    return imd_live.status(refresh=refresh)


@router.get("/imd/cityforecast")
def imd_city_forecast() -> dict:
    """Official IMD 7-Day City Forecast & Warning Bulletin for 113+ weather stations across India."""
    return imd_live.get_live_city_forecasts()


@router.get("/imd/bust/{location_id}")
def imd_bust_for_location(location_id: str) -> dict:
    """Return live IMD bust prediction for the nearest station to a dashboard location."""
    import math

    site = ALL_SITES_BY_ID.get(location_id)
    if site is None:
        loc = next((l for l in LOCATIONS if l.id == location_id), None)
        if loc is None:
            raise HTTPException(status_code=404, detail=f"Unknown location '{location_id}'")
        ref_lat, ref_lon, ref_name = loc.lat, loc.lon, loc.name
    else:
        ref_lat, ref_lon, ref_name = site.lat, site.lon, site.name

    payload = imd_live.get_live_city_forecasts()
    stations = payload.get("stations", [])
    if not stations:
        raise HTTPException(status_code=503, detail="IMD city forecast data not available")

    def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    best = min(stations, key=lambda s: haversine(ref_lat, ref_lon, s.get("lat", 20.0), s.get("lon", 78.0)))
    dist_km = haversine(ref_lat, ref_lon, best.get("lat", 20.0), best.get("lon", 78.0))

    return {
        "location_id": location_id,
        "location_name": ref_name,
        "matched_station": best.get("station_name"),
        "matched_state": best.get("state"),
        "distance_km": round(dist_km, 1),
        "date": best.get("date") or payload.get("bulletin_date"),
        "bulletin_date": best.get("bulletin_date") or payload.get("bulletin_date"),
        "forecast_valid_from": payload.get("forecast_valid_from"),
        "forecast_valid_to": payload.get("forecast_valid_to"),
        "last_updated": payload.get("last_updated"),
        "past_24_hrs_rainfall": best.get("past_24_hrs_rainfall"),
        "today_max_temp": best.get("today_max_temp"),
        "today_min_temp": best.get("today_min_temp"),
        "todays_forecast": best.get("todays_forecast"),
        "day_1_warning": best.get("day_1_warning"),
        "day_1_warning_color": best.get("day_1_warning_color"),
        "forecast_7days": best.get("forecast_7days", []),
        "bust_risk_score": best.get("bust_risk_score"),
        "bust_category": best.get("bust_category"),
        "bust_drivers": best.get("bust_drivers", []),
        "recommendation": best.get("recommendation"),
        "humidity_0830": best.get("humidity_0830"),
        "sunrise_time": best.get("sunrise_time"),
        "sunset_time": best.get("sunset_time"),
        "subdivision": best.get("subdivision") or best.get("state"),
        "live_current": live_weather.fetch_live_weather(
            best.get("lat", 20.0),
            best.get("lon", 78.0),
            location_name=best.get("station_name", ref_name),
        ),
        "source": payload.get("source"),
        "updated_at": payload.get("updated_at"),
    }


@router.get("/imd/alerts")
def imd_realtime_alerts(
    threshold: float = Query(50.0, ge=0.0, le=100.0, description="Minimum bust score to include (0-100)"),
    severity: str | None = Query(None, description="Filter: HIGH or SEVERE"),
) -> dict:
    """Real-time early-warning alerts from live IMD 113-station city forecast data.

    Unlike /api/alerts which uses the historical ensemble model on demo data,
    these alerts are sourced from today's official IMD City Forecast & Warning
    Bulletin — real stations, real warnings, real observed rainfall.

    Threshold defaults to 50 (HIGH+). Use threshold=70 for SEVERE only.
    """
    result = imd_live.realtime_imd_alerts(threshold=threshold)

    if severity:
        wanted = severity.upper()
        result["alerts"] = [a for a in result["alerts"] if a["severity"] == wanted]

    return result


@router.get("/weather/live")
def get_live_weather(
    lat: float = Query(..., description="Latitude in decimal degrees"),
    lon: float = Query(..., description="Longitude in decimal degrees"),
    location: str = Query("", description="City or station name"),
) -> dict:
    """Fetch current real-time atmospheric observations (temperature, rainfall, humidity, wind) with MSN connector & WMO telemetry."""
    return live_weather.fetch_live_weather(lat, lon, location_name=location)


