"""Seed the local database from the demonstration data provider.

    python -m app.db.seed --days 14

This exists to prove the persistence path end to end: the same objects the API
serves are written through the schema that production would use. It is not
required to run the demo.
"""

from __future__ import annotations

import argparse
import uuid
from datetime import date, datetime, timedelta, timezone

from ..core import analogues, risk_model, synthetic
from ..core.alerts import ALERT_THRESHOLD, scan
from ..core.domain import ALL_SITES, VARIABLES
from ..core.features import extract_features
from ..core.verification import error_record
from ..config import settings
from .session import connect, init_schema


def _uid() -> str:
    return uuid.uuid4().hex


def seed(base_date: date, days: int, variables: tuple[str, ...] = ("rainfall",)) -> dict[str, int]:
    init_schema()
    now = datetime.now(timezone.utc).isoformat()
    counts = {k: 0 for k in ("locations", "forecasts", "members", "features", "risk", "verification", "alerts", "analogues")}

    with connect() as conn:
        model_version_id = f"{risk_model.MODEL_NAME}:{risk_model.MODEL_VERSION}"
        card = risk_model.model_card()
        conn.execute(
            "INSERT OR REPLACE INTO model_versions "
            "(id, name, version, kind, trained, explanation_method, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                model_version_id, card["name"], card["version"], card["kind"],
                int(bool(card["trained"])), card["explanation_method"], card["notice"], now,
            ),
        )

        for site in ALL_SITES:
            conn.execute(
                "INSERT OR REPLACE INTO locations "
                "(id, name, state, lat, lon, is_featured, rain_climatology, temp_climatology, "
                "historical_skill, convective_index) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    site.id, site.name, site.state, site.lat, site.lon,
                    1 if site.id in {s.id for s in ALL_SITES[:10]} else 0,
                    site.rain_climatology, site.temp_climatology,
                    site.historical_skill, site.convective_index,
                ),
            )
            counts["locations"] += 1

        for ev in analogues.CATALOGUE:
            conn.execute(
                "INSERT OR REPLACE INTO historical_analogues "
                "(id, event_date, region, regime, pattern, fingerprint_regime_change, "
                "fingerprint_forcing, fingerprint_moisture, fingerprint_convective, "
                "bust_occurred, outcome, verified_error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ev.id, ev.event_date, ev.region, ev.regime, ev.pattern, *ev.fingerprint,
                 int(ev.bust_occurred), ev.outcome, ev.verified_error),
            )
            counts["analogues"] += 1

        variable_units = {v.id: v.unit for v in VARIABLES}

        for back in range(days):
            init = base_date - timedelta(days=back)
            for site in ALL_SITES:
                for variable_id in variables:
                    fc = synthetic.ensemble_forecast(
                        site.id, variable_id, "ecmwf", init, settings.ensemble_members
                    )
                    for lead in range(1, synthetic.DISPLAY_DAYS + 1):
                        forecast_id = _uid()
                        col = fc.members[:, lead - 1]
                        conn.execute(
                            "INSERT INTO forecasts (id, location_id, variable_id, nwp_model_id, "
                            "base_date, valid_date, lead_time, deterministic_value, ensemble_mean, "
                            "ensemble_sd, unit) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                forecast_id, site.id, variable_id, "ecmwf", init.isoformat(),
                                (init + timedelta(days=lead)).isoformat(), lead,
                                float(fc.deterministic[lead - 1]), float(col.mean()),
                                float(col.std(ddof=1)), variable_units[variable_id],
                            ),
                        )
                        counts["forecasts"] += 1
                        conn.executemany(
                            "INSERT INTO ensemble_members (id, forecast_id, member_number, value) "
                            "VALUES (?,?,?,?)",
                            [(_uid(), forecast_id, i + 1, float(v)) for i, v in enumerate(col)],
                        )
                        counts["members"] += len(col)

                    for lead in (3, 4, 5, 6, 7):
                        bundle = extract_features(site.id, variable_id, "ecmwf", init, lead)
                        assessment = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector)
                        valid = init + timedelta(days=lead)

                        conn.executemany(
                            "INSERT INTO features (id, location_id, variable_id, nwp_model_id, "
                            "base_date, lead_time, feature_name, feature_value) VALUES (?,?,?,?,?,?,?,?)",
                            [
                                (_uid(), site.id, variable_id, "ecmwf", init.isoformat(), lead, k, float(v))
                                for k, v in bundle.values.items()
                            ],
                        )
                        counts["features"] += len(bundle.values)

                        risk_id = _uid()
                        conn.execute(
                            "INSERT INTO risk_predictions (id, location_id, variable_id, nwp_model_id, "
                            "model_version_id, base_date, valid_date, lead_time, risk_score, "
                            "risk_category, forecast_confidence, model_confidence, explanation, created_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                risk_id, site.id, variable_id, "ecmwf", model_version_id,
                                init.isoformat(), valid.isoformat(), lead, assessment.score_pct,
                                assessment.category, assessment.forecast_confidence,
                                assessment.model_confidence,
                                risk_model.narrative(assessment, site.name, lead, variable_id.title()), now,
                            ),
                        )
                        counts["risk"] += 1

                        conn.executemany(
                            "INSERT INTO risk_contributions (id, risk_prediction_id, feature_name, "
                            "feature_value, contribution) VALUES (?,?,?,?,?)",
                            [
                                (_uid(), risk_id, str(c["feature"]), float(c["value"]), float(c["contribution"]))
                                for c in assessment.contributions
                            ],
                        )

                        rec = error_record(site.id, variable_id, init, lead)
                        conn.execute(
                            "INSERT INTO verification_metrics (id, location_id, variable_id, base_date, "
                            "valid_date, lead_time, forecast_value, observed_value, error, "
                            "normalised_error, bust, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                _uid(), site.id, variable_id, init.isoformat(), valid.isoformat(),
                                lead, rec.forecast, rec.observed, rec.error, rec.normalised_error,
                                int(rec.bust), "demo",
                            ),
                        )
                        counts["verification"] += 1

        for alert in scan(base_date.isoformat()):
            conn.execute(
                "INSERT OR REPLACE INTO alerts (id, location_id, variable_id, issued_at, valid_date, "
                "lead_time, severity, risk_score, headline, reason, recommended_action, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(alert["id"]), str(alert["location_id"]), str(alert["variable_id"]),
                    str(alert["issued_at"]), str(alert["valid_date"]), int(alert["horizon"]),
                    str(alert["severity"]), float(alert["risk_score"]), str(alert["headline"]),
                    str(alert["reason"]), str(alert["recommended_action"]), str(alert["status"]),
                ),
            )
            counts["alerts"] += 1

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the AtmosGuard demo database")
    parser.add_argument("--days", type=int, default=7, help="Initialisations to write back from the reference date")
    parser.add_argument("--date", type=str, default=settings.demo_reference_date)
    args = parser.parse_args()

    counts = seed(date.fromisoformat(args.date), args.days)
    print(f"Seeded {settings.database_url}")
    for k, v in counts.items():
        print(f"  {k:<14} {v:>8,}")
    print(f"\nAlert threshold: {ALERT_THRESHOLD}")


if __name__ == "__main__":
    main()
