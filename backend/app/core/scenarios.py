"""Curated demonstration scenarios ("Demo Mode").

Each scenario is a real point in the demonstration dataset - a specific site,
variable, lead time and initialisation - chosen because it lands cleanly in one
risk band. Nothing here overrides the model: switching Demo Mode on selects a
situation, it does not inject a score. `tests/test_scenarios.py` asserts that
each one still resolves to its intended band, so a retune of the generator
fails the test suite instead of silently degrading the live demo.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    summary: str
    expected_band: str
    location_id: str
    variable_id: str
    model_id: str
    horizon: int
    base_date: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "low",
        "Low Bust Risk",
        "A settled short-range picture over the Deccan. Ensemble members cluster "
        "tightly, the pattern is stationary, and nothing in the predictor set is "
        "flagging.",
        "LOW",
        "bengaluru", "rainfall", "ecmwf", 3, "2026-08-26",
    ),
    Scenario(
        "moderate",
        "Moderate Bust Risk",
        "Gradual evolution over the Gangetic plain. Spread is a little above normal "
        "for the lead time and the forecast has drifted between runs, but no single "
        "driver dominates.",
        "MODERATE",
        "patna", "rainfall", "ecmwf", 3, "2026-08-26",
    ),
    Scenario(
        "high",
        "High Bust Risk - flagship case",
        "The AtmosGuard headline case. The Day 5 forecast for Jaipur from the "
        "26 August 2026 run carried 4.3 mm against a normal near 4 mm - unremarkable "
        "on its face. It verified on 31 August at 0.0 mm. The ensemble had already "
        "fanned out and the forecast had been drifting between runs for days.",
        "HIGH",
        "jaipur", "rainfall", "ecmwf", 5, "2026-08-26",
    ),
    Scenario(
        "severe",
        "Severe Bust Risk",
        "A Day 5 forecast for the Kashmir valley during an unsettled spell, with "
        "high spread, a regime transition inside the window and a forecast that has "
        "not settled between runs.",
        "SEVERE",
        "srinagar", "rainfall", "ecmwf", 5, "2026-08-26",
    ),
    Scenario(
        "extreme",
        "Extreme Forecast Bust",
        "The worst case in the current dataset: a Day 4 forecast for the Karnataka "
        "coast, where ensemble spread, model disagreement and run-to-run instability "
        "all peak together during an active offshore spell. This is what AtmosGuard "
        "is built to catch.",
        "SEVERE",
        "coastal-karnataka", "rainfall", "ecmwf", 4, "2026-08-26",
    ),
)
SCENARIOS_BY_ID = {s.id: s for s in SCENARIOS}

#: The scenario shown when the dashboard first loads.
DEFAULT_SCENARIO_ID = "high"
