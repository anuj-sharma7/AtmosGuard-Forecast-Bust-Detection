"""Early-warning alert engine.

An alert is raised when the assessed bust risk for a monitored site crosses the
HIGH band (61%). Alerts are *decision support*: they say "this forecast may be
unreliable", never "this weather will happen". That distinction is enforced in
the wording here and repeated throughout the UI.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from . import risk_model
from .domain import ALL_SITES, ALL_SITES_BY_ID, LOCATIONS, VARIABLES_BY_ID
from .features import extract_features

#: Risk index (0-100) at which a forecast is *shown* as high risk.
ALERT_THRESHOLD = 61.0

#: Fitted bust probability at which an alert is actually *raised*.
#:
#: The index is a percentile across the monitored network, so a fixed index
#: threshold flags a fixed fraction of forecasts by construction - 61 would
#: alert on roughly two in five, which no duty forecaster would tolerate.
#: Alerting on the underlying probability instead makes the rate respond to
#: how unsettled the atmosphere actually is: quiet weeks produce few alerts,
#: disturbed ones produce many. 0.34 is about twice the ~0.17 base rate, i.e.
#: "this forecast is twice as likely as usual to bust".
ALERT_PROBABILITY = 0.34

#: Variables the alert engine scans.
#:
#: Rainfall only, deliberately. The risk model is fitted on real IMD rainfall
#: observations; temperature, wind and pressure have no observed record in the
#: datasets in use, so their predictors follow a different distribution and the
#: fitted coefficients do not transfer. Scoring them anyway produced alerts that
#: looked confident and meant nothing - temperature swamped the list with
#: probabilities near 0.7. The other variables remain fully explorable on the
#: analysis pages, where they are labelled as reconstructed.
MONITORED_VARIABLES = ("rainfall",)

#: Lead times scanned by the alert engine.
MONITORED_HORIZONS = (3, 4, 5, 6, 7)

_FEATURED_IDS = frozenset(loc.id for loc in LOCATIONS)


def risk_timeline(
    location_id: str, variable_id: str, model_id: str, valid_date: date, max_lead: int = 7
) -> list[dict[str, object]]:
    """How the assessed risk for one *valid date* evolved as lead time shortened.

    This is the core value proposition made visible. Each row is a different
    model initialisation, all verifying on the same day: Day 7 out, then Day 6,
    and so on. A forecast heading for a bust shows risk climbing well before the
    event - which is the early warning AtmosGuard exists to give.
    """
    rows: list[dict[str, object]] = []
    for lead in range(max_lead, 2, -1):
        init = valid_date - timedelta(days=lead)
        bundle = extract_features(location_id, variable_id, model_id, init, lead)
        assessment = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector)
        rows.append(
            {
                "lead_time": lead,
                "label": f"Day {lead}",
                "init_date": init.isoformat(),
                "risk_score": assessment.score_pct,
                "risk_category": assessment.category,
                "forecast_confidence": round(assessment.forecast_confidence * 100, 1),
            }
        )
    return rows


def horizon_profile(
    location_id: str, variable_id: str, model_id: str, base_date: date
) -> list[dict[str, object]]:
    """Risk at every lead time from a *single* initialisation (Day 3 .. Day 7)."""
    rows: list[dict[str, object]] = []
    for horizon in MONITORED_HORIZONS:
        bundle = extract_features(location_id, variable_id, model_id, base_date, horizon)
        assessment = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector)
        rows.append(
            {
                "horizon": horizon,
                "label": f"Day {horizon}",
                "valid_date": (base_date + timedelta(days=horizon)).isoformat(),
                "risk_score": assessment.score_pct,
                "risk_category": assessment.category,
                "forecast_confidence": round(assessment.forecast_confidence * 100, 1),
                "model_confidence": round(assessment.model_confidence * 100, 1),
            }
        )
    return rows


def _reason(assessment: risk_model.RiskAssessment) -> str:
    drivers = [c for c in assessment.contributions if float(c["contribution"]) > 0][:2]
    if not drivers:
        return "Elevated ensemble uncertainty"
    return " + ".join(str(c["label"]) for c in drivers)


@lru_cache(maxsize=8)
def scan(base_date_iso: str, model_id: str = "ecmwf") -> tuple[dict[str, object], ...]:
    """Scan the monitoring network and return active alerts, worst first."""
    base_date = date.fromisoformat(base_date_iso)
    alerts: list[dict[str, object]] = []

    for site in ALL_SITES:
        for variable_id in MONITORED_VARIABLES:
            worst: tuple[float, int, risk_model.RiskAssessment] | None = None
            for horizon in MONITORED_HORIZONS:
                bundle = extract_features(site.id, variable_id, model_id, base_date, horizon)
                assessment = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector)
                if worst is None or assessment.probability > worst[2].probability:
                    worst = (assessment.score_pct, horizon, assessment)

            assert worst is not None
            score, horizon, assessment = worst
            if assessment.probability < ALERT_PROBABILITY:
                continue

            var = VARIABLES_BY_ID[variable_id]
            alerts.append(
                {
                    "id": f"{site.id}-{variable_id}-{base_date_iso}",
                    "location_id": site.id,
                    "location_name": site.name,
                    "state": site.state,
                    "lat": site.lat,
                    "lon": site.lon,
                    "variable_id": variable_id,
                    "variable_label": var.label,
                    "horizon": horizon,
                    "valid_date": (base_date + timedelta(days=horizon)).isoformat(),
                    "issued_at": base_date.isoformat(),
                    "risk_score": score,
                    "bust_probability": round(assessment.probability, 4),
                    "severity": assessment.category,
                    "model_confidence": round(assessment.model_confidence * 100, 1),
                    "forecast_confidence": round(assessment.forecast_confidence * 100, 1),
                    "reason": _reason(assessment),
                    "headline": f"{assessment.category} bust risk - {site.name} "
                    f"Day {horizon} {var.label.lower()} forecast",
                    "status": "Monitoring",
                    "recommended_action": "Consider increased reliance on ensemble and "
                    "short-range guidance for this valid time; re-assess at the next model run.",
                }
            )

    alerts.sort(key=lambda a: float(a["risk_score"]), reverse=True)
    return tuple(alerts)


@lru_cache(maxsize=64)
def network_summary(
    base_date_iso: str, variable_id: str, horizon: int, model_id: str
) -> dict[str, object]:
    """Per-site risk across the whole network - powers the map and the KPI row."""
    base_date = date.fromisoformat(base_date_iso)
    sites: list[dict[str, object]] = []
    counts = {"LOW": 0, "MODERATE": 0, "HIGH": 0, "SEVERE": 0}

    for site in ALL_SITES:
        bundle = extract_features(site.id, variable_id, model_id, base_date, horizon)
        assessment = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector)
        counts[assessment.category] += 1
        sites.append(
            {
                "id": site.id,
                "name": site.name,
                "state": site.state,
                "lat": site.lat,
                "lon": site.lon,
                "featured": site.id in _FEATURED_IDS,
                "risk_score": assessment.score_pct,
                "risk_category": assessment.category,
                "forecast_confidence": round(assessment.forecast_confidence * 100, 1),
                "model_confidence": round(assessment.model_confidence * 100, 1),
                "ensemble_spread": round(bundle.values["ensemble_spread"], 3),
                "regime_change": round(bundle.values["regime_change"], 3),
                "regime": bundle.state.regime,
                "top_driver": _reason(assessment),
            }
        )

    sites.sort(key=lambda s: float(s["risk_score"]), reverse=True)
    mean_conf = sum(float(s["model_confidence"]) for s in sites) / len(sites) if sites else 0.0
    return {
        "sites": sites,
        "counts": counts,
        "high_risk_areas": counts["HIGH"] + counts["SEVERE"],
        "highest_risk": sites[0] if sites else None,
        "mean_model_confidence": round(mean_conf, 1),
        "network_size": len(sites),
    }


def site_lookup(site_id: str):
    return ALL_SITES_BY_ID.get(site_id)
