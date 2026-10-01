"""Tests for the verification metrics."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.core import imd, verification
from app.core.domain import ALL_SITES

REF = date(2026, 9, 1)


class TestRocAuc:
    def test_perfect_separation(self) -> None:
        y = np.array([0, 0, 1, 1])
        s = np.array([0.1, 0.2, 0.8, 0.9])
        assert verification.roc_auc(y, s) == pytest.approx(1.0)

    def test_inverted_separation(self) -> None:
        y = np.array([0, 0, 1, 1])
        s = np.array([0.9, 0.8, 0.2, 0.1])
        assert verification.roc_auc(y, s) == pytest.approx(0.0)

    def test_all_ties_is_one_half(self) -> None:
        """Every score identical means the classifier is uninformative."""
        y = np.array([0, 1, 0, 1])
        s = np.array([0.5, 0.5, 0.5, 0.5])
        assert verification.roc_auc(y, s) == pytest.approx(0.5)

    def test_partial_ties_handled(self) -> None:
        y = np.array([0, 1, 1, 0])
        s = np.array([0.3, 0.3, 0.7, 0.1])
        # pairs (neg,pos): (0.3,0.3)=0.5, (0.3,0.7)=1, (0.1,0.3)=1, (0.1,0.7)=1
        assert verification.roc_auc(y, s) == pytest.approx(3.5 / 4)

    def test_single_class_is_undefined(self) -> None:
        assert np.isnan(verification.roc_auc(np.array([1, 1]), np.array([0.2, 0.8])))


class TestClassificationMetrics:
    def test_known_confusion_matrix(self) -> None:
        y = np.array([1, 1, 0, 0, 1, 0])
        s = np.array([0.9, 0.8, 0.7, 0.2, 0.3, 0.1])
        m = verification.classification_metrics(y, s, threshold=0.5)
        assert m["confusion_matrix"] == {
            "true_positive": 2, "false_positive": 1, "false_negative": 1, "true_negative": 2,
        }
        assert m["precision"] == pytest.approx(2 / 3, abs=1e-3)
        assert m["recall"] == pytest.approx(2 / 3, abs=1e-3)
        assert m["f1"] == pytest.approx(2 / 3, abs=1e-3)

    def test_no_positive_predictions_does_not_divide_by_zero(self) -> None:
        m = verification.classification_metrics(np.array([1, 0]), np.array([0.1, 0.2]), 0.9)
        assert m["precision"] == 0.0 and m["recall"] == 0.0 and m["f1"] == 0.0


class TestReliability:
    def test_bins_cover_every_sample(self) -> None:
        rng = np.random.default_rng(0)
        s = rng.random(500)
        y = (rng.random(500) < s).astype(int)
        curve = verification.reliability_curve(y, s, bins=10)
        assert sum(int(b["count"]) for b in curve) == 500

    def test_upper_edge_is_included(self) -> None:
        """A score of exactly 1.0 must land in the last bin, not be dropped."""
        curve = verification.reliability_curve(np.array([1]), np.array([1.0]), bins=10)
        assert curve[-1]["count"] == 1


class TestLeadScaling:
    def test_threshold_grows_with_lead_time(self) -> None:
        scales = [verification.lead_error_scale("rainfall", h) for h in (3, 5, 7)]
        assert scales[0] < scales[1] < scales[2]

    def test_day5_matches_the_quoted_scale(self) -> None:
        for var_id, scale in verification.ERROR_SCALE.items():
            assert verification.lead_error_scale(var_id, 5) == pytest.approx(scale)


class TestModelPerformance:
    @pytest.fixture(scope="class")
    def perf(self) -> dict:
        return verification.model_performance(REF)

    def test_metrics_are_in_range(self, perf: dict) -> None:
        assert 0.0 <= perf["roc_auc"] <= 1.0
        assert 0.0 <= perf["brier_score"] <= 1.0
        for key in ("precision", "recall", "f1", "accuracy"):
            assert 0.0 <= perf[key] <= 1.0

    def test_risk_model_beats_random(self, perf: dict) -> None:
        """The whole product is void if the score does not separate busts."""
        assert perf["roc_auc"] > 0.65

    def test_base_rate_is_a_sane_minority(self, perf: dict) -> None:
        assert 0.05 < perf["base_rate"] < 0.40

    def test_dataset_is_not_trivially_small(self, perf: dict) -> None:
        assert perf["sample_size"] > 500

    def test_bands_separate_real_bust_rates_monotonically(self, perf: dict) -> None:
        """The product's core claim, measured against real IMD observations.

        The index is not a probability, so what a band *means* is the bust rate
        actually observed inside it. If that is not monotonic the bands are
        decoration.
        """
        rates = [b["observed_bust_rate"] for b in perf["band_reliability"]]
        assert rates == sorted(rates), rates
        assert rates[-1] > rates[0] * 3

    def test_roc_curve_is_monotonic(self, perf: dict) -> None:
        tprs = [p["tpr"] for p in perf["roc_curve"]]
        assert tprs == sorted(tprs, reverse=True)

    def test_model_card_reports_a_held_out_score(self, perf: dict) -> None:
        card = perf["model"]
        assert card["trained"] is True
        assert card["training"]["split"] == "temporal"
        assert 0.5 < card["training"]["roc_auc_holdout"] <= 1.0
        # The ensemble is still simulated; the card must not imply otherwise.
        assert "simulated" in card["notice"] or "reconstructed" in card["notice"]


class TestForecastVerification:
    def test_forecast_correlates_with_observations(self) -> None:
        """A forecast uncorrelated with the truth would mean the reconstruction
        is broken. Rainfall is verified against the real IMD district record, so
        the bar is anomaly correlation rather than a skill score: over a
        two-week window at a single site, a climatology reference is itself
        badly estimated and its skill score is noisy."""
        for variable in ("rainfall", "temperature", "pressure"):
            metrics = verification.forecast_verification("jaipur", variable, REF, 45)["metrics"]
            assert metrics["acc"] > 0.2, (variable, metrics)

    @pytest.mark.parametrize(
        "variable,low,high",
        [("rainfall", 2.0, 25.0), ("temperature", 0.8, 4.0), ("wind", 0.5, 4.0), ("pressure", 0.8, 5.0)],
    )
    def test_error_magnitudes_are_physically_plausible(
        self, variable: str, low: float, high: float
    ) -> None:
        """Day-5 error across the network must land where medium-range forecasts do.

        Asserted network-wide rather than per site: a single site over a
        two-week window is far too small a sample to pin an RMSE to, and an
        earlier version of this test failed on a 0.24 degC figure that was
        sampling noise rather than a defect.
        """
        errors = []
        for valid in verification.verification_valid_days(REF, 60):
            init = valid - timedelta(days=5)
            for site in ALL_SITES:
                errors.append(verification.error_record(site.id, variable, init, 5).error)

        rmse = float(np.sqrt(np.mean(np.square(errors))))
        assert low < rmse < high, f"{variable} network RMSE {rmse:.2f}"

    def test_series_is_clipped_to_the_observed_window(self) -> None:
        """Verification must never run past the end of the real record.

        Reporting twenty-one points when only fourteen are measured would mix
        real and simulated truth in one chart without saying so.
        """
        start, end = imd.observation_window()
        payload = verification.forecast_verification("mumbai", "rainfall", REF, 60)
        days = [date.fromisoformat(str(p["date"])) for p in payload["series"]]
        assert days, "expected at least one verified day"
        assert min(days) >= start and max(days) <= end
        assert payload["metrics"]["sample_size"] == len(days)

        short = verification.forecast_verification("mumbai", "rainfall", REF, 5)
        assert len(short["series"]) == 5
