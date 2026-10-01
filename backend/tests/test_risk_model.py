"""Tests for the baseline risk model and its attributions."""

from __future__ import annotations

import numpy as np
import pytest

from app.core import risk_model
from app.core.domain import risk_category


class TestRiskCategory:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (0.0, "LOW"), (30.0, "LOW"), (30.4, "MODERATE"), (31.0, "MODERATE"),
            (60.0, "MODERATE"),
            # Regression: the original band table left a gap between 60 and 61,
            # so 60.6 silently fell through to LOW.
            (60.6, "HIGH"),
            (61.0, "HIGH"), (80.0, "HIGH"), (80.5, "SEVERE"),
            (81.0, "SEVERE"), (100.0, "SEVERE"), (112.0, "SEVERE"),
        ],
    )
    def test_bands_have_no_gaps(self, score: float, expected: str) -> None:
        assert risk_category(score) == expected

    def test_every_score_maps_to_a_band(self) -> None:
        for score in np.arange(0.0, 100.05, 0.05):
            assert risk_category(float(score)) in {"LOW", "MODERATE", "HIGH", "SEVERE"}


class TestFittedParameters:
    def test_display_weights_sum_to_one(self) -> None:
        """Display weights are influence shares, so they must still total 1."""
        assert sum(risk_model.WEIGHTS.values()) == pytest.approx(1.0)

    def test_every_coefficient_has_display_metadata(self) -> None:
        for key in risk_model.COEFFICIENTS:
            assert key in risk_model.FEATURE_META
            assert risk_model.FEATURE_META[key]["label"]
            assert risk_model.FEATURE_META[key]["description"]

    def test_ensemble_spread_is_the_dominant_predictor(self) -> None:
        """The fit must agree with the physics, or something is wrong upstream.

        Ensemble spread is the textbook precursor of a forecast bust. When a
        stale spread climatology once saturated this feature, the fit demoted
        it and held-out AUC collapsed - so this assertion is a canary for that
        whole class of bug.
        """
        strongest = max(risk_model.COEFFICIENTS, key=lambda k: abs(risk_model.COEFFICIENTS[k]))
        assert strongest == "ensemble_spread"
        assert risk_model.COEFFICIENTS["ensemble_spread"] > 0

    def test_holdout_score_beats_chance(self) -> None:
        assert risk_model.TRAINING["roc_auc_holdout"] > 0.60

    def test_split_is_temporal_not_random(self) -> None:
        """A random split leaks: neighbouring days share a weather system."""
        assert risk_model.TRAINING["split"] == "temporal"

    def test_index_knots_are_monotonic(self) -> None:
        knots = risk_model.INDEX_KNOTS
        assert len(knots) == 101
        assert knots == sorted(knots)


class TestAssessment:
    @staticmethod
    def _features(value: float) -> dict[str, float]:
        return {k: value for k in risk_model.PREDICTORS}

    def test_score_follows_each_fitted_coefficient(self) -> None:
        """Raising a driver must move risk in the direction the fit assigned it.

        Unlike the hand-set priors this replaced, the coefficients are not all
        positive - the data does not oblige - so the assertion is directional
        rather than uniformly increasing.
        """
        base = self._features(0.5)
        baseline = risk_model.bust_probability(base, 0.5)
        for key, coefficient in risk_model.COEFFICIENTS.items():
            if key == "historical_skill" or abs(coefficient) < 1e-6:
                continue
            raised = risk_model.bust_probability({**base, key: 0.9}, 0.5)
            if coefficient > 0:
                assert raised > baseline, key
            else:
                assert raised < baseline, key

    def test_historical_skill_follows_its_fitted_sign(self) -> None:
        low = risk_model.bust_probability(self._features(0.6), 0.20)
        high = risk_model.bust_probability(self._features(0.6), 0.80)
        if risk_model.COEFFICIENTS["historical_skill"] < 0:
            assert high < low
        else:
            assert high > low

    def test_score_bounds(self) -> None:
        assert 0.0 <= risk_model.assess(self._features(0.0), 0.95).score <= 1.0
        assert 0.0 <= risk_model.assess(self._features(1.0), 0.05).score <= 1.0

    def test_forecast_confidence_is_complement_of_risk(self) -> None:
        a = risk_model.assess(self._features(0.7), 0.5)
        assert a.forecast_confidence == pytest.approx(1.0 - a.score)

    def test_category_matches_score(self) -> None:
        a = risk_model.assess(self._features(0.8), 0.3)
        assert a.category == risk_category(a.score_pct)

    def test_contributions_are_exact_shapley_values(self) -> None:
        """For a model linear in the logit, phi_i = c_i * (x_i - E[x_i]) exactly.

        This is the property that lets the UI describe these as real additive
        attributions rather than a SHAP-shaped decoration.
        """
        features = self._features(0.62)
        assessment = risk_model.assess(features, 0.5)
        base = risk_model.baseline_features()
        values = {**features, "historical_skill": 0.5}

        by_name = {str(c["feature"]): float(c["contribution"]) for c in assessment.contributions}
        for key, coefficient in risk_model.COEFFICIENTS.items():
            expected = coefficient * (values[key] - base[key])
            assert by_name[key] == pytest.approx(expected, abs=1e-4)

    def test_contributions_reconstruct_the_logit(self) -> None:
        """Additivity: base logit + sum(contributions) == this forecast's logit."""
        features = self._features(0.73)
        skill = 0.42
        assessment = risk_model.assess(features, skill)
        base = risk_model.baseline_features()
        values = {**features, "historical_skill": skill}

        base_logit = risk_model.INTERCEPT + sum(
            risk_model.COEFFICIENTS[k] * base[k] for k in risk_model.COEFFICIENTS
        )
        actual_logit = risk_model.INTERCEPT + sum(
            risk_model.COEFFICIENTS[k] * values[k] for k in risk_model.COEFFICIENTS
        )
        total = base_logit + sum(float(c["contribution"]) for c in assessment.contributions)
        # Contributions are rounded to 4dp in the payload.
        assert total == pytest.approx(actual_logit, abs=5e-3)

    def test_contributions_sorted_by_absolute_magnitude(self) -> None:
        assessment = risk_model.assess(self._features(0.55), 0.4)
        magnitudes = [abs(float(c["contribution"])) for c in assessment.contributions]
        assert magnitudes == sorted(magnitudes, reverse=True)


class TestNarrative:
    def test_names_the_leading_driver(self) -> None:
        features = {k: 0.2 for k in risk_model.PREDICTORS}
        features["ensemble_spread"] = 0.97
        assessment = risk_model.assess(features, 0.4)
        text = risk_model.narrative(assessment, "Jaipur", 5, "Rainfall")
        assert "Jaipur" in text and "Day 5" in text
        assert "ensemble members show unusually large disagreement" in text

    def test_handles_an_all_benign_case(self) -> None:
        text = risk_model.narrative(
            risk_model.assess({k: 0.01 for k in risk_model.PREDICTORS}, 0.95),
            "Mumbai", 3, "Rainfall",
        )
        assert "Mumbai" in text
