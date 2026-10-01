"""API contract tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


class TestMeta:
    def test_shape(self, client: TestClient) -> None:
        body = client.get("/api/meta").json()
        assert body["app_name"] == "AtmosGuard"
        assert body["tagline"] == "Reads the forecast before it fails."
        assert len(body["locations"]) == 10
        assert len(body["variables"]) == 4
        assert body["horizons"] == [3, 4, 5, 6, 7]

    def test_risk_bands_are_contiguous_and_coloured(self, client: TestClient) -> None:
        bands = client.get("/api/meta").json()["risk_bands"]
        assert [b["name"] for b in bands] == ["LOW", "MODERATE", "HIGH", "SEVERE"]
        for lower, upper in zip(bands, bands[1:]):
            assert upper["min"] == lower["max"] + 1
        assert all(b["color"].startswith("#") for b in bands)

    def test_default_selection_is_the_flagship_case(self, client: TestClient) -> None:
        default = client.get("/api/meta").json()["default_selection"]
        assert default["location_id"] == "jaipur"
        assert default["variable_id"] == "rainfall"
        assert default["horizon"] == 5


class TestRisk:
    @pytest.fixture(scope="class")
    def flagship(self, client: TestClient) -> dict:
        return client.get(
            "/api/risk", params={"location": "jaipur", "horizon": 5, "variable": "rainfall", "model": "ecmwf"}
        ).json()

    def test_flagship_is_high_risk(self, flagship: dict) -> None:
        assert flagship["risk_category"] == "HIGH"
        assert 61 <= flagship["risk_score"] <= 80

    def test_confidence_complements_risk(self, flagship: dict) -> None:
        assert flagship["forecast_confidence"] == pytest.approx(100 - flagship["risk_score"], abs=0.2)

    def test_carries_provenance_labelling(self, flagship: dict) -> None:
        """Reconstructed numbers must never travel without saying so.

        The system is now hybrid - real IMD observations, reconstructed
        ensemble - so the notice has to distinguish the two rather than calling
        everything simulated or, worse, implying it is all measured.
        """
        assert flagship["data_mode"] == "demo"
        notice = flagship["demo_notice"]
        assert "real IMD" in notice and "reconstructed" in notice
        assert "does not replace official forecasts" in flagship["disclaimer"]
        assert flagship["explanation_label"] == "Feature Contribution - MVP"

    def test_declares_what_it_was_verified_against(self, flagship: dict) -> None:
        source = flagship["observation_source"]
        assert source["real"] is True
        assert "IMD district" in source["verified_against"]
        assert len(source["window"]) == 2

    def test_ensemble_payload_is_complete(self, flagship: dict) -> None:
        ens = flagship["ensemble"]
        assert len(ens["days"]) == 7
        assert 20 <= ens["member_count"] <= 50
        assert all(len(m["values"]) == 7 for m in ens["members"])
        assert len(ens["mean"]) == 7 and len(ens["deterministic"]) == 7
        for key in ("p10", "p25", "p50", "p75", "p90"):
            assert len(ens["percentiles"][key]) == 7

    def test_percentiles_are_ordered(self, flagship: dict) -> None:
        p = flagship["ensemble"]["percentiles"]
        for i in range(7):
            assert p["p10"][i] <= p["p25"][i] <= p["p50"][i] <= p["p75"][i] <= p["p90"][i]

    def test_explanation_mentions_the_location_and_lead(self, flagship: dict) -> None:
        assert "Jaipur" in flagship["explanation"]
        assert "Day 5" in flagship["explanation"]

    def test_analogues_are_ranked(self, flagship: dict) -> None:
        sims = [a["similarity"] for a in flagship["analogues"]]
        assert sims == sorted(sims, reverse=True)
        assert all(0.0 <= s <= 1.0 for s in sims)

    def test_horizon_profile_covers_day_3_to_7(self, flagship: dict) -> None:
        assert [r["horizon"] for r in flagship["horizon_profile"]] == [3, 4, 5, 6, 7]

    def test_risk_timeline_counts_down_the_lead_time(self, flagship: dict) -> None:
        leads = [r["lead_time"] for r in flagship["risk_timeline"]]
        assert leads == [7, 6, 5, 4, 3]

    def test_model_comparison_covers_three_centres(self, flagship: dict) -> None:
        rows = flagship["model_comparison"]["rows"]
        assert {r["model_id"] for r in rows} == {"ecmwf", "ncmrwf", "gfs"}

    def test_selection_changes_the_answer(self, client: TestClient) -> None:
        """The whole product depends on the selectors actually driving the model."""
        base = {"location": "jaipur", "variable": "rainfall", "model": "ecmwf"}
        scores = {
            h: client.get("/api/risk", params={**base, "horizon": h}).json()["risk_score"]
            for h in (3, 5, 7)
        }
        assert len(set(scores.values())) == 3

        by_location = {
            loc: client.get("/api/risk", params={**base, "location": loc, "horizon": 5}).json()["risk_score"]
            for loc in ("jaipur", "mumbai", "guwahati")
        }
        assert len(set(by_location.values())) == 3

    def test_is_deterministic(self, client: TestClient) -> None:
        params = {"location": "delhi", "horizon": 4, "variable": "wind", "model": "gfs"}
        first = client.get("/api/risk", params=params).json()
        second = client.get("/api/risk", params=params).json()
        assert first["risk_score"] == second["risk_score"]
        assert first["ensemble"]["mean"] == second["ensemble"]["mean"]


class TestValidation:
    @pytest.mark.parametrize(
        "params,status",
        [
            ({"location": "atlantis", "horizon": 5}, 404),
            ({"location": "jaipur", "horizon": 5, "variable": "humidity"}, 404),
            ({"location": "jaipur", "horizon": 5, "model": "nonesuch"}, 404),
            ({"location": "jaipur", "horizon": 2}, 422),
            ({"location": "jaipur", "horizon": 9}, 422),
            ({"location": "jaipur", "horizon": 5, "forecast_date": "not-a-date"}, 422),
        ],
    )
    def test_bad_input_is_rejected(self, client: TestClient, params: dict, status: int) -> None:
        assert client.get("/api/risk", params=params).status_code == status


class TestNetwork:
    def test_covers_the_whole_monitoring_network(self, client: TestClient) -> None:
        body = client.get("/api/network", params={"horizon": 5, "variable": "rainfall"}).json()
        assert body["network_size"] == len(body["sites"]) > 30
        assert sum(body["counts"].values()) == body["network_size"]
        assert body["high_risk_areas"] == body["counts"]["HIGH"] + body["counts"]["SEVERE"]

    def test_sites_are_sorted_worst_first(self, client: TestClient) -> None:
        sites = client.get("/api/network", params={"horizon": 5}).json()["sites"]
        scores = [s["risk_score"] for s in sites]
        assert scores == sorted(scores, reverse=True)


class TestAlerts:
    def test_only_high_and_severe_are_raised(self, client: TestClient) -> None:
        body = client.get("/api/alerts").json()
        assert body["threshold"] == 61.0
        for alert in body["alerts"]:
            assert alert["risk_score"] >= 61.0
            assert alert["severity"] in {"HIGH", "SEVERE"}

    def test_severity_filter(self, client: TestClient) -> None:
        body = client.get("/api/alerts", params={"severity": "severe"}).json()
        assert all(a["severity"] == "SEVERE" for a in body["alerts"])

    def test_unknown_severity_rejected(self, client: TestClient) -> None:
        assert client.get("/api/alerts", params={"severity": "critical"}).status_code == 422

    def test_alerts_are_decision_support_not_warnings(self, client: TestClient) -> None:
        body = client.get("/api/alerts").json()
        assert "does not replace official forecasts" in body["disclaimer"]
        for alert in body["alerts"][:5]:
            assert "bust risk" in alert["headline"].lower()


class TestScenarios:
    @pytest.mark.parametrize("sid", ["low", "moderate", "high", "severe", "extreme"])
    def test_each_scenario_resolves(self, client: TestClient, sid: str) -> None:
        body = client.get(f"/api/scenario/{sid}").json()
        assert body["scenario"]["id"] == sid
        assert body["risk_category"] in {"LOW", "MODERATE", "HIGH", "SEVERE"}

    def test_unknown_scenario_is_404(self, client: TestClient) -> None:
        assert client.get("/api/scenario/apocalypse").status_code == 404


class TestVerificationEndpoints:
    def test_model_metrics_report_the_trained_model(self, client: TestClient) -> None:
        body = client.get("/api/verification/model").json()
        card = body["model_performance"]["model"]
        assert card["trained"] is True
        assert card["training"]["source"].startswith("IMD")

    def test_forecast_verification(self, client: TestClient) -> None:
        body = client.get(
            "/api/verification/forecast", params={"location": "jaipur", "variable": "rainfall"}
        ).json()
        assert body["series"], "expected verified days inside the observation window"
        assert set(body["metrics"]) >= {"rmse", "mae", "bias", "acc", "skill"}


class TestSystemStatus:
    def test_declares_real_sources_and_the_fitted_model(self, client: TestClient) -> None:
        body = client.get("/api/system/status").json()
        assert body["data_mode"] == "demo"
        assert any("ECMWF" in s["name"] for s in body["sources"])
        # The two real IMD datasets must be named and marked as real.
        real = [s for s in body["sources"] if s["status"] == "Real data"]
        assert len(real) == 2
        assert all("IMD" in s["name"] for s in real)
        assert body["coverage"]["districts"] > 500
        assert body["model"]["trained"] is True

    def test_health(self, client: TestClient) -> None:
        assert client.get("/api/health").json()["status"] == "ok"
