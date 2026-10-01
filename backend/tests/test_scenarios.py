"""Demo Mode guard rails.

If a change to the generator or the model moves a curated scenario out of its
intended risk band, the live demo silently stops telling the story it promises.
These tests make that a build failure instead.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core import risk_model, scenarios
from app.core.features import extract_features


@pytest.mark.parametrize("scenario", scenarios.SCENARIOS, ids=lambda s: s.id)
def test_scenario_lands_in_its_band(scenario: scenarios.Scenario) -> None:
    bundle = extract_features(
        scenario.location_id,
        scenario.variable_id,
        scenario.model_id,
        date.fromisoformat(scenario.base_date),
        scenario.horizon,
    )
    assessment = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector)
    assert assessment.category == scenario.expected_band, (
        f"{scenario.id}: expected {scenario.expected_band}, got "
        f"{assessment.category} ({assessment.score_pct}%)"
    )


def test_every_band_is_demonstrated() -> None:
    bands = {s.expected_band for s in scenarios.SCENARIOS}
    assert bands == {"LOW", "MODERATE", "HIGH", "SEVERE"}


def test_flagship_scenario_is_the_jaipur_high_risk_case() -> None:
    """The spec's headline demo: Jaipur, Day 5, rainfall, high risk near 78%."""
    flagship = scenarios.SCENARIOS_BY_ID[scenarios.DEFAULT_SCENARIO_ID]
    assert flagship.location_id == "jaipur"
    assert flagship.variable_id == "rainfall"
    assert flagship.horizon == 5

    bundle = extract_features(
        flagship.location_id, flagship.variable_id, flagship.model_id,
        date.fromisoformat(flagship.base_date), flagship.horizon,
    )
    assessment = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector)
    assert assessment.category == "HIGH"
    assert 61.0 <= assessment.score_pct <= 80.0


def test_extreme_scenario_is_the_worst_case() -> None:
    """Demo Mode's extreme case must outrank the ordinary severe case."""
    scores = {}
    for sid in ("severe", "extreme"):
        s = scenarios.SCENARIOS_BY_ID[sid]
        bundle = extract_features(
            s.location_id, s.variable_id, s.model_id, date.fromisoformat(s.base_date), s.horizon
        )
        scores[sid] = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector).score_pct
    assert scores["extreme"] > scores["severe"]
