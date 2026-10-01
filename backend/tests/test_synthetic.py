"""Tests for the synthetic NWP provider."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.core import synthetic
from app.core.domain import ALL_SITES, VARIABLES

REF = date(2026, 9, 1)


class TestDeterminism:
    def test_same_inputs_give_identical_output(self) -> None:
        a = synthetic.ensemble_forecast("jaipur", "rainfall", "ecmwf", REF, 42)
        b = synthetic.ensemble_forecast("jaipur", "rainfall", "ecmwf", REF, 42)
        np.testing.assert_array_equal(a.members, b.members)

    def test_different_locations_differ(self) -> None:
        a = synthetic.ensemble_forecast("jaipur", "rainfall", "ecmwf", REF, 42)
        b = synthetic.ensemble_forecast("delhi", "rainfall", "ecmwf", REF, 42)
        assert not np.array_equal(a.members, b.members)


class TestPhysicalPlausibility:
    def test_rainfall_is_never_negative(self) -> None:
        for site in ALL_SITES[:8]:
            fc = synthetic.ensemble_forecast(site.id, "rainfall", "ecmwf", REF, 42)
            assert fc.members.min() >= 0.0
            assert min(fc.deterministic) >= 0.0

    @pytest.mark.parametrize(
        "variable,low,high",
        [("temperature", -15.0, 55.0), ("pressure", 960.0, 1050.0), ("wind", 0.0, 60.0)],
    )
    def test_values_stay_in_physical_range(self, variable: str, low: float, high: float) -> None:
        for site in ALL_SITES[:8]:
            fc = synthetic.ensemble_forecast(site.id, variable, "ecmwf", REF, 42)
            # Wind is clamped at exactly 0.0, so the bound is inclusive.
            assert fc.members.min() >= low
            assert fc.members.max() < high

    def test_spread_grows_with_lead_time(self) -> None:
        """Error growth is the defining property of an ensemble forecast."""
        for site in ALL_SITES[:10]:
            fc = synthetic.ensemble_forecast(site.id, "temperature", "ecmwf", REF, 42)
            early = float(fc.members[:, 0].std(ddof=1))
            late = float(fc.members[:, 6].std(ddof=1))
            assert late > early, site.id


class TestTemporalCoherence:
    def test_consecutive_runs_see_the_same_atmosphere(self) -> None:
        """Two runs a day apart must not describe unrelated weather.

        Without this the risk timeline (one valid date seen from successive
        initialisations) is noise rather than an escalation signal.
        """
        for site in ALL_SITES[:10]:
            today = synthetic.synoptic_state(site.id, REF)
            tomorrow = synthetic.synoptic_state(site.id, REF + timedelta(days=1))
            assert abs(today.synoptic_forcing - tomorrow.synoptic_forcing) < 0.30, site.id
            assert abs(today.moisture_anomaly - tomorrow.moisture_anomaly) < 0.45, site.id

    def test_event_stays_anchored_in_absolute_time(self) -> None:
        """The same weather system must keep the same valid date across runs."""
        state_a = synthetic.synoptic_state("jaipur", REF)
        state_b = synthetic.synoptic_state("jaipur", REF + timedelta(days=1))
        # event_day is run-relative, so a one-day-later run should see the same
        # event one day closer (unless the event has just passed).
        if state_b.event_day > 0.6:
            assert state_a.event_day - state_b.event_day == pytest.approx(1.0, abs=0.15)


class TestSpreadAnomaly:
    def test_climatology_grows_with_lead(self) -> None:
        for var in VARIABLES:
            clim = synthetic.spread_climatology(var.id)
            assert clim[6] > clim[0], var.id

    def test_anomaly_is_near_one_on_average(self) -> None:
        """An anomaly is only meaningful if the typical case sits near 1.

        Regression: the spread climatology was once sampled from dates outside
        the observation window, comparing anchored forecasts against unanchored
        ones. Every anomaly pinned near 3.4, the feature saturated, and held-out
        ROC-AUC fell from 0.80 to 0.60. This assertion catches that directly.
        """
        for var in VARIABLES:
            ratios = [
                synthetic.spread_anomaly(
                    synthetic.ensemble_forecast(site.id, var.id, "ensemble", REF, 42), 5
                )
                for site in ALL_SITES
            ]
            assert 0.4 < float(np.median(ratios)) < 2.2, var.id

    def test_normalised_spread_is_bounded(self) -> None:
        for site in ALL_SITES[:10]:
            for var in VARIABLES:
                fc = synthetic.ensemble_forecast(site.id, var.id, "ecmwf", REF, 42)
                for horizon in (3, 5, 7):
                    assert 0.0 <= synthetic.normalised_spread(fc, horizon) <= 1.0


class TestPersistence:
    def test_history_is_available_at_every_horizon(self) -> None:
        """Day 7 needs runs at leads 8-10, which is why the generator runs to T+10."""
        for horizon in (3, 4, 5, 6, 7):
            score, history = synthetic.run_to_run_persistence(
                "jaipur", "rainfall", "ecmwf", REF, horizon, 42
            )
            assert len(history) >= 2, horizon
            assert 0.0 <= score <= 1.0

    def test_history_all_verifies_at_the_same_valid_time(self) -> None:
        _score, history = synthetic.run_to_run_persistence("jaipur", "rainfall", "ecmwf", REF, 5, 42)
        valid_times = {
            date.fromisoformat(str(h["init_date"])) + timedelta(days=int(h["lead_time"]))
            for h in history
        }
        assert len(valid_times) == 1
