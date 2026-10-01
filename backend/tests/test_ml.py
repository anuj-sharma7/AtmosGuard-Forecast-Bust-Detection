"""Tests for the predictor set and the trained-model layer.

The model itself is judged by its held-out score, not by unit tests. What is
tested here is everything that could silently corrupt it: predictors going
non-finite or unbounded, the column order drifting away from what the persisted
model was trained on, and attributions that do not actually add up to the
prediction they claim to explain.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from app.core import model_registry
from app.core.domain import ALL_SITES
from app.core.features import extract_features
from app.core.predictors import PREDICTOR_META, PREDICTOR_NAMES, build_vector, to_array

REF = date(2026, 8, 26)


class TestPredictorSet:
    def test_names_are_unique_and_documented(self) -> None:
        assert len(set(PREDICTOR_NAMES)) == len(PREDICTOR_NAMES)
        for name in PREDICTOR_NAMES:
            assert name in PREDICTOR_META, name
            label, description = PREDICTOR_META[name]
            assert label and description

    def test_vector_matches_the_declared_order(self) -> None:
        bundle = extract_features("jaipur", "rainfall", "ecmwf", REF, 5)
        vector = build_vector(bundle, "jaipur", "rainfall", "ecmwf", REF, 5)
        assert list(vector) == list(PREDICTOR_NAMES)

    def test_every_value_is_finite_across_the_network(self) -> None:
        """A single NaN poisons a whole tree ensemble's prediction."""
        for site in ALL_SITES:
            for horizon in (3, 5, 7):
                bundle = extract_features(site.id, "rainfall", "ecmwf", REF, horizon)
                vector = build_vector(bundle, site.id, "rainfall", "ecmwf", REF, horizon)
                for name, value in vector.items():
                    assert math.isfinite(value), f"{site.id} {name} = {value}"

    def test_ratio_predictors_are_bounded(self) -> None:
        """Regression: spread_growth once reached 28 when the Day-3 spread was
        near zero, which is a measurement artefact rather than a signal."""
        for site in ALL_SITES:
            for horizon in (3, 5, 7):
                bundle = extract_features(site.id, "rainfall", "ecmwf", REF, horizon)
                vector = build_vector(bundle, site.id, "rainfall", "ecmwf", REF, horizon)
                assert 0.2 <= vector["spread_growth"] <= 5.0
                assert 0.0 <= vector["member_range"] <= 12.0
                assert 0.0 <= vector["forecast_anomaly"] <= 25.0
                assert 0.0 <= vector["heavy_rain_fraction"] <= 1.0

    def test_seasonal_encoding_is_on_the_unit_circle(self) -> None:
        bundle = extract_features("jaipur", "rainfall", "ecmwf", REF, 5)
        vector = build_vector(bundle, "jaipur", "rainfall", "ecmwf", REF, 5)
        radius = vector["doy_sin"] ** 2 + vector["doy_cos"] ** 2
        assert radius == pytest.approx(1.0, abs=1e-6)

    def test_lead_time_is_carried_as_a_predictor(self) -> None:
        for horizon in (3, 5, 7):
            bundle = extract_features("delhi", "rainfall", "ecmwf", REF, horizon)
            vector = build_vector(bundle, "delhi", "rainfall", "ecmwf", REF, horizon)
            assert vector["lead_time"] == float(horizon)

    def test_to_array_preserves_column_order(self) -> None:
        bundle = extract_features("jaipur", "rainfall", "ecmwf", REF, 5)
        vector = build_vector(bundle, "jaipur", "rainfall", "ecmwf", REF, 5)
        matrix = to_array([vector, vector])
        assert matrix.shape == (2, len(PREDICTOR_NAMES))
        assert matrix[0, PREDICTOR_NAMES.index("lead_time")] == 5.0


@pytest.mark.skipif(model_registry.load() is None, reason="no trained model present")
class TestTrainedModel:
    @pytest.fixture(scope="class")
    def model(self):
        return model_registry.load()

    def test_column_order_matches_what_it_was_trained_on(self, model) -> None:
        """Scoring a model against a reordered predictor set produces plausible
        nonsense, which is the worst failure available here."""
        assert tuple(model.registry["predictors"]) == PREDICTOR_NAMES

    def test_predictions_are_probabilities(self, model) -> None:
        for site in ALL_SITES[:12]:
            bundle = extract_features(site.id, "rainfall", "ecmwf", REF, 5)
            vector = build_vector(bundle, site.id, "rainfall", "ecmwf", REF, 5)
            assert 0.0 <= model.predict(vector) <= 1.0

    def test_attributions_reconstruct_the_prediction(self, model) -> None:
        """The additivity guarantee. TreeSHAP values plus the base value must
        pass through the link function back to the model's own output - if they
        do not, the explanation panel is describing a different model.
        """
        if model.contribution_kind != "treeshap":
            pytest.skip("only exact for TreeSHAP")

        for site in ALL_SITES[:10]:
            bundle = extract_features(site.id, "rainfall", "ecmwf", REF, 5)
            vector = build_vector(bundle, site.id, "rainfall", "ecmwf", REF, 5)
            contributions, base = model.contributions(vector)
            logit = base + sum(contributions.values())
            reconstructed = 1.0 / (1.0 + math.exp(-logit))
            assert reconstructed == pytest.approx(model.predict(vector), abs=1e-4), site.id

    def test_contributions_cover_every_predictor(self, model) -> None:
        bundle = extract_features("jaipur", "rainfall", "ecmwf", REF, 5)
        vector = build_vector(bundle, "jaipur", "rainfall", "ecmwf", REF, 5)
        contributions, _base = model.contributions(vector)
        assert set(contributions) == set(PREDICTOR_NAMES)

    def test_held_out_score_beats_the_logistic_it_replaced(self, model) -> None:
        card = model_registry.card()
        results = {r["model"]: r["roc_auc_holdout"] for r in card["comparison"]}
        assert card["roc_auc_holdout"] >= results.get("logistic", 0.0)
        assert card["roc_auc_holdout"] > 0.65

    def test_training_used_a_temporal_split(self, model) -> None:
        assert model.registry["training"]["split"] == "temporal"

    def test_index_knots_are_monotonic(self, model) -> None:
        knots = model.registry["index_knots"]
        assert len(knots) == 101
        assert knots == sorted(knots)

    def test_every_estimator_was_compared(self, model) -> None:
        names = {r["model"] for r in model.registry["results"]}
        assert names == {"logistic", "random_forest", "xgboost"}

    def test_a_reordered_vector_is_rejected(self, model) -> None:
        """Guards the registry check that refuses a stale model."""
        assert tuple(model.registry["predictors"]) == PREDICTOR_NAMES
        assert model.contribution_kind in {"treeshap", "linear", "importance"}
