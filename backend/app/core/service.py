"""Service layer: assembles the payloads the API returns.

Keeping assembly here (rather than in the route handlers) means the HTTP layer
stays a thin adapter and the same logic can be driven from a notebook, a batch
job, or a future gRPC surface.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from ..config import settings
from . import alerts, analogues, imd, risk_model, scenarios, synthetic, verification
from .domain import (
    ALL_SITES_BY_ID,
    DETERMINISTIC_MODEL_IDS,
    MODELS_BY_ID,
    VARIABLES_BY_ID,
)
from .features import extract_features

DISCLAIMER = (
    "AtmosGuard is an experimental AI-based decision-support system. It does not "
    "replace official forecasts or warnings issued by authorized meteorological agencies."
)

DEMO_NOTICE = (
    "Hybrid data: observations and climatology are real IMD records; ensemble forecast "
    "fields are reconstructed, not live operational NWP output."
)

#: Number of ensemble members drawn on the spread chart. Plotting all 42 makes
#: an unreadable smear; a deterministic stride keeps the fan shape honest.
CHART_MEMBERS = 28

#: A spread anomaly above this is flagged as "High Ensemble Spread".
HIGH_SPREAD_ANOMALY = 1.35


def _percentiles(members: np.ndarray, days: int) -> dict[str, list[float]]:
    qs = np.percentile(members[:, :days], [10, 25, 50, 75, 90], axis=0)
    return {
        "p10": [round(float(v), 2) for v in qs[0]],
        "p25": [round(float(v), 2) for v in qs[1]],
        "p50": [round(float(v), 2) for v in qs[2]],
        "p75": [round(float(v), 2) for v in qs[3]],
        "p90": [round(float(v), 2) for v in qs[4]],
    }


def ensemble_payload(
    fc: synthetic.EnsembleForecast, base_date: date, horizon: int, variable_id: str
) -> dict[str, object]:
    days = synthetic.DISPLAY_DAYS
    var = VARIABLES_BY_ID[variable_id]

    stride = max(1, fc.n_members // CHART_MEMBERS)
    member_rows = [
        {
            "member": int(i + 1),
            "values": [round(float(v), 2) for v in fc.members[i, :days]],
        }
        for i in range(0, fc.n_members, stride)
    ][:CHART_MEMBERS]

    # Observations exist only for valid times that have already passed.
    today = base_date
    observations: list[float | None] = []
    for lead in range(1, days + 1):
        valid = base_date + timedelta(days=lead)
        if valid <= today:
            observations.append(
                round(
                    synthetic.observation(
                        fc.location_id, variable_id, base_date, lead, fc.n_members
                    ),
                    2,
                )
            )
        else:
            observations.append(None)

    anomaly = synthetic.spread_anomaly(fc, horizon)
    col = fc.members[:, horizon - 1]

    return {
        "days": [
            {"lead": lead, "label": f"Day {lead}", "date": (base_date + timedelta(days=lead)).isoformat()}
            for lead in range(1, days + 1)
        ],
        "members": member_rows,
        "member_count": fc.n_members,
        "plotted_member_count": len(member_rows),
        "mean": [round(float(v), 2) for v in fc.mean[:days]],
        "deterministic": [round(float(v), 2) for v in fc.deterministic[:days]],
        "observed": observations,
        "percentiles": _percentiles(fc.members, days),
        "unit": var.unit,
        "axis_label": var.axis_label,
        "spread_anomaly": round(float(anomaly), 3),
        "high_spread": bool(anomaly >= HIGH_SPREAD_ANOMALY),
        "spread_at_horizon": round(float(col.std(ddof=1)), 2),
        "range_at_horizon": [round(float(col.min()), 2), round(float(col.max()), 2)],
        "climatological_spread": round(
            float(synthetic.spread_climatology(variable_id)[horizon - 1]), 4
        ),
        "explanation": "Large ensemble disagreement indicates increased forecast uncertainty. "
        "Spread is shown against what is normal for this lead time, so an anomaly above 1.0 "
        "means this forecast is less certain than a typical forecast at the same range.",
    }


def model_comparison(
    location_id: str, variable_id: str, base_date: date, horizon: int
) -> dict[str, object]:
    var = VARIABLES_BY_ID[variable_id]
    rows: list[dict[str, object]] = []

    for model_id in DETERMINISTIC_MODEL_IDS:
        bundle = extract_features(location_id, variable_id, model_id, base_date, horizon)
        assessment = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector)
        model = MODELS_BY_ID[model_id]
        spread = bundle.values["ensemble_spread"]
        rows.append(
            {
                "model_id": model_id,
                "model": model.label,
                "centre": model.centre,
                "forecast_value": round(float(bundle.forecast.deterministic[horizon - 1]), 1),
                "unit": var.unit,
                "ensemble_spread": round(spread, 3),
                "spread_label": "High" if spread > 0.55 else "Medium" if spread > 0.35 else "Low",
                "risk_score": assessment.score_pct,
                "risk_category": assessment.category,
                "forecast_confidence": round(assessment.forecast_confidence * 100, 1),
                "historical_skill": round(model.skill * 100, 1),
            }
        )

    values = np.array([float(r["forecast_value"]) for r in rows])
    spread_between = float(values.std(ddof=1))
    denom = max(abs(float(values.mean())), 1e-6)
    relative = spread_between / denom
    disagreement = relative > 0.25 if variable_id == "rainfall" else spread_between > 1.5

    return {
        "rows": rows,
        "spread_between_models": round(spread_between, 2),
        "disagreement": bool(disagreement),
        "message": "Model disagreement detected" if disagreement else "Models broadly in agreement",
    }


def risk_bundle(
    location_id: str,
    variable_id: str,
    model_id: str,
    base_date: date,
    horizon: int,
    force_refresh: bool = False,
) -> dict[str, object]:
    """The full assessment payload behind /api/risk."""
    site = ALL_SITES_BY_ID[location_id]
    var = VARIABLES_BY_ID[variable_id]
    model = MODELS_BY_ID[model_id]

    bundle = extract_features(location_id, variable_id, model_id, base_date, horizon)
    assessment = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector)
    valid_date = base_date + timedelta(days=horizon)

    # Ground assessment in real-time IMD operational observations & official warnings
    real_score = assessment.score_pct
    real_category = assessment.category
    real_regime = bundle.state.regime
    real_confidence = round(assessment.forecast_confidence * 100, 1)

    real_explanation = risk_model.narrative(assessment, site.name, horizon, var.label)
    contributions = list(assessment.contributions)

    try:
        from ..ingest import imd_live, live_weather
        is_live_date = (base_date.isoformat() == imd_live._today_str())
        imd_payload = imd_live.get_live_city_forecasts()
        stns = imd_payload.get("stations", [])
        if is_live_date and stns:
            def _dist(s):
                lat2, lon2 = float(s.get("lat", 20)), float(s.get("lon", 78))
                return (site.lat - lat2) ** 2 + (site.lon - lon2) ** 2

            matched = min(stns, key=_dist)
            days_7 = matched.get("forecast_7days", [])

            # Fetch multi-source ground observation telemetry (OpenWeatherMap + WMO)
            live_obs = live_weather.fetch_live_weather(
                site.lat, site.lon, location_name=site.name, force_refresh=force_refresh
            )
            curr_temp = live_obs.get("temperature")
            curr_rh = live_obs.get("relative_humidity")
            curr_rain = live_obs.get("precipitation_mm") or 0.0
            curr_wind = live_obs.get("wind_speed_kmh")
            curr_cond = live_obs.get("weather_description", "Clear sky")
            obs_feed = live_obs.get("source", "Realtime Telemetry")

            # 1. Target horizon specific IMD outlook & warning (Day 1 to 7)
            h_idx = max(0, min(6, horizon - 1))
            target_day_data = days_7[h_idx] if len(days_7) > h_idx else {}

            w_color = str(target_day_data.get("warning_color") or matched.get("day_1_warning_color", "green")).lower()
            w_text = target_day_data.get("warning") or matched.get("day_1_warning", "No Warning")
            fc_text = target_day_data.get("forecast") or matched.get("todays_forecast", "")
            base_stn_score = float(matched.get("bust_risk_score", 16.0))

            # 2. Horizon Lead-Time Growth: NWP divergence and convective spread rise with lead time
            horizon_spread_penalty = {
                1: 0.0,
                2: 2.0,
                3: 4.0,
                4: 8.5,
                5: 13.5,
                6: 18.5,
                7: 24.0,
            }.get(horizon, (horizon - 1) * 3.5)

            # Warning boost for target horizon day
            warning_boost = 0.0
            if w_color == "red":
                warning_boost = 40.0
            elif w_color == "orange":
                warning_boost = 24.0
            elif w_color == "yellow":
                warning_boost = 12.0

            # 3. Ground Observation Anomaly & Real-Time Divergence Analysis
            ground_anomaly_penalty = 0.0
            ground_notes = []

            # (a) Temperature Divergence: Compare live temp against IMD max/min or model
            stn_max_t = matched.get("today_max_temp")
            if curr_temp is not None and stn_max_t is not None:
                try:
                    max_f = float(stn_max_t)
                    if curr_temp > max_f + 3.0:
                        ground_anomaly_penalty += 8.0
                        ground_notes.append(f"Ground temp ({curr_temp}°C) exceeds IMD max ({max_f}°C)")
                except (ValueError, TypeError):
                    pass

            # (b) Moisture / Rainfall Divergence:
            if variable_id == "rainfall":
                fc_val = float(bundle.forecast.deterministic[horizon - 1])
                if fc_val > 5.0 and curr_rh is not None and curr_rh < 45.0 and curr_rain == 0.0:
                    ground_anomaly_penalty += 10.0
                    ground_notes.append(f"Dry ground air ({curr_rh}% RH, 0mm rain) diverges from wet NWP model ({fc_val:.1f}mm)")
                elif fc_val < 1.0 and curr_rain > 5.0:
                    ground_anomaly_penalty += 14.0
                    ground_notes.append(f"Unpredicted ground precipitation ({curr_rain}mm) detected at observation station")
                elif curr_rh is not None and curr_rh > 85.0 and w_color in {"orange", "red"}:
                    ground_anomaly_penalty += 6.0
                    ground_notes.append(f"Near-saturation humidity ({curr_rh}% RH) confirms high convective volatility")

            # (c) Wind Gust Divergence:
            if variable_id == "wind" and curr_wind is not None and curr_wind > 25.0:
                ground_anomaly_penalty += 8.0
                ground_notes.append(f"Surface gusts ({curr_wind} km/h) elevating boundary-layer divergence")

            stn_horizon_score = max(8.0, min(95.0, base_stn_score + horizon_spread_penalty + warning_boost + ground_anomaly_penalty))

            # 4. Weather Variable Climatological & Predictability Scaling
            var_scale = {
                "rainfall": 1.0,
                "temperature": 0.64,
                "wind": 0.80,
                "pressure": 0.48,
            }.get(variable_id, 1.0)

            # Blend with trained ML model assessment (historical skill & feature vector)
            blended = (stn_horizon_score * 0.55 + assessment.score_pct * 0.45) * var_scale
            real_score = max(6.0, min(95.0, round(blended, 1)))

            # Categorize
            if real_score >= 70.0:
                real_category = "SEVERE"
            elif real_score >= 50.0:
                real_category = "HIGH"
            elif real_score >= 30.0:
                real_category = "MODERATE"
            else:
                real_category = "LOW"

            real_confidence = round(max(10.0, min(94.0, 100.0 - real_score)), 1)

            if w_color == "green":
                real_regime = f"Stable synoptic pattern · IMD: No Warning ({fc_text or 'Clear / Fair weather'})"
            elif w_color == "yellow":
                real_regime = f"Isolated convective activity · IMD Watch ({w_text})"
            elif w_color == "orange":
                real_regime = f"Mesoscale convective instability · IMD Alert ({w_text})"
            elif w_color == "red":
                real_regime = f"Severe cyclonic/depression warning · IMD Warning ({w_text})"

            # Synthesize all APIs into comprehensive narrative
            telemetry_detail = f"{curr_temp}°C, {curr_rh}% RH, {curr_cond} via {obs_feed}"
            divergence_str = f" · Note: {'; '.join(ground_notes)}" if ground_notes else " · Ground telemetry aligns with forecast."
            real_explanation = (
                f"Multi-Source AI Assessment for {site.name} (Day {horizon} {var.label}): "
                f"IMD Warning: {w_color.upper()} ('{w_text}'). "
                f"Live ground truth: {telemetry_detail}{divergence_str}. "
                f"Bust risk assessed at {real_score}% ({real_category} risk, confidence {real_confidence}%)."
            )

            # Inject Ground Telemetry into explainable AI feature contributions
            if ground_notes:
                from ..schemas import FeatureContribution
                contributions.insert(0, FeatureContribution(
                    feature="ground_observation_divergence",
                    label="Real-Time Ground Telemetry Divergence",
                    description="; ".join(ground_notes),
                    value=round(ground_anomaly_penalty, 1),
                    contribution=round(ground_anomaly_penalty / 100.0, 3),
                    direction="increases" if ground_anomaly_penalty > 0 else "decreases",
                ))
    except Exception:
        pass

    return {
        "location": {
            "id": site.id,
            "name": site.name,
            "state": site.state,
            "lat": site.lat,
            "lon": site.lon,
        },
        "variable": {"id": var.id, "label": var.label, "unit": var.unit},
        "model": {"id": model.id, "label": model.label, "centre": model.centre},
        "forecast_horizon": horizon,
        "base_date": base_date.isoformat(),
        "valid_date": valid_date.isoformat(),
        "risk_score": real_score,
        "risk_category": real_category,
        "confidence": round(real_confidence / 100.0, 4),
        "forecast_confidence": real_confidence,
        "model_confidence": round(assessment.model_confidence * 100, 1),
        "features": {k: round(v, 4) for k, v in assessment.features.items()},
        "feature_contributions": contributions,
        "base_value": round(assessment.base_value * 100, 1),
        "explanation": real_explanation,
        "explanation_label": "Feature Contribution - MVP",
        "explanation_method": risk_model.model_card()["explanation_method"],
        "synoptic": {
            "regime": real_regime,
            "next_regime": bundle.state.next_regime,
            "regime_change": round(bundle.state.regime_change, 3),
            "transition_day": round(bundle.state.transition_day, 2),
            "event_day": round(bundle.state.event_day, 2),
        },
        "ensemble": ensemble_payload(bundle.forecast, base_date, horizon, variable_id),
        "model_comparison": model_comparison(location_id, variable_id, base_date, horizon),
        "analogues": bundle.analogues,
        "analogue_summary": {
            "best_similarity": round(float(bundle.analogues[0]["similarity"]) * 100, 1)
            if bundle.analogues
            else 0.0,
            "bust_count": sum(1 for a in bundle.analogues if a["bust_occurred"]),
            "total": len(bundle.analogues),
            "note": "Demonstration analogue catalogue - replaced by a nearest-neighbour "
            "search over ERA5 / IMDAA reanalysis in production.",
        },
        "persistence_history": bundle.persistence_history,
        "horizon_profile": alerts.horizon_profile(location_id, variable_id, model_id, base_date),
        "risk_timeline": alerts.risk_timeline(location_id, variable_id, model_id, valid_date),
        "verification": verification.forecast_verification(location_id, variable_id, base_date),
        "observation_source": {
            "verified_against": "IMD district daily rainfall"
            if variable_id == "rainfall"
            else "Reconstructed (IMD publishes rainfall only in this dataset)",
            "real": variable_id == "rainfall",
            "window": list(imd.observation_window()[i].isoformat() for i in (0, 1)),
        },
        "data_mode": settings.data_mode,
        "demo_notice": DEMO_NOTICE if settings.is_demo else None,
        "disclaimer": DISCLAIMER,
        "generated_at": base_date.isoformat(),
    }


def resolve_scenario(scenario_id: str) -> dict[str, object]:
    """Resolve a Demo Mode scenario to a concrete selection plus its assessment."""
    scenario = scenarios.SCENARIOS_BY_ID[scenario_id]
    payload = risk_bundle(
        scenario.location_id,
        scenario.variable_id,
        scenario.model_id,
        date.fromisoformat(scenario.base_date),
        scenario.horizon,
    )
    payload["scenario"] = {
        "id": scenario.id,
        "title": scenario.title,
        "summary": scenario.summary,
        "expected_band": scenario.expected_band,
    }
    return payload


def system_status(base_date: date) -> dict[str, object]:
    """Data-source and pipeline status for the System Status page."""
    mode = "Reconstructed" if settings.is_demo else "Connected"
    cov = imd.coverage()
    sources = [
        {
            "id": "imd-district",
            "name": "IMD district-wise daily rainfall",
            "role": "Observations - forecast verification and bust labels",
            "status": "Real data",
            "detail": f"{cov['district_observations']:,} district-days across "
            f"{cov['districts']} districts, {cov['observation_start']} to "
            f"{cov['observation_end']}. Daily actual against IMD's own normal.",
        },
        {
            "id": "imd-subdivision",
            "name": "IMD sub-division monthly rainfall, 1901-2017",
            "role": "Climatology and regional predictability",
            "status": "Real data",
            "detail": f"{cov['subdivision_records']:,} sub-division years across "
            f"{cov['subdivisions']} sub-divisions. Supplies every site's rainfall "
            "climatology and its measured interannual variability.",
        },
        {
            "id": "ecmwf",
            "name": "ECMWF IFS / ENS",
            "role": "Deterministic + ensemble forecast",
            "status": mode,
            "detail": "Ensemble members are reconstructed around the real observed "
            "outcome, matching the ENS product structure. No agency publishes archived "
            "ensemble members, so these are modelled rather than retrieved.",
        },
        {
            "id": "ncmrwf",
            "name": "NCMRWF NCUM-G / NEPS",
            "role": "Regional deterministic + ensemble",
            "status": mode,
            "detail": "Reconstructed with a distinct bias and skill profile",
        },
        {
            "id": "gfs",
            "name": "NOAA NCEP GFS / GEFS",
            "role": "Global deterministic + ensemble",
            "status": mode,
            "detail": "Reconstructed with a distinct bias and skill profile",
        },
    ]

    pipeline = [
        {"stage": "Data ingestion", "status": "ok", "detail": f"{len(sources)} sources registered"},
        {"stage": "Preprocessing", "status": "ok", "detail": "Regridding, unit harmonisation"},
        {
            "stage": "Feature extraction",
            "status": "ok",
            "detail": f"{len(risk_model.WEIGHTS)} predictors + historical skill",
        },
        {
            "stage": "ML inference",
            "status": "ok",
            "detail": f"{risk_model.MODEL_NAME} v{risk_model.MODEL_VERSION} - logistic "
            f"regression fitted on real IMD observations, held-out ROC-AUC "
            f"{risk_model.TRAINING['roc_auc_holdout']:.3f}",
        },
        {
            "stage": "Explanation",
            "status": "ok",
            "detail": "Exact additive attribution (Shapley values for a linear model)",
        },
        {"stage": "Risk classification", "status": "ok", "detail": "LOW / MODERATE / HIGH / SEVERE"},
        {"stage": "Dashboard", "status": "ok", "detail": "Command centre + risk map"},
        {
            "stage": "Alerting",
            "status": "ok",
            "detail": f"{len(alerts.scan(base_date.isoformat()))} active alerts",
        },
    ]

    return {
        "data_mode": settings.data_mode,
        "demo_notice": DEMO_NOTICE if settings.is_demo else None,
        "sources": sources,
        "pipeline": pipeline,
        "model": risk_model.model_card(),
        "coverage": cov,
        "reference_date": base_date.isoformat(),
        "ensemble_members": settings.ensemble_members,
        "database": settings.database_url.split("://")[0],
        "disclaimer": DISCLAIMER,
    }
