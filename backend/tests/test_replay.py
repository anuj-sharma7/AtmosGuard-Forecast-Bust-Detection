"""Tests for the historical replay.

Most of these guard one property: the prediction phase must not be able to read
the outcome. That is the difference between a backtest worth reporting and one
that is not, and it is the kind of thing that breaks silently, so it is tested
directly rather than assumed.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core import archive as archive_mod
from app.core import hindcast, replay
from app.core import replay_features as rf
from app.core.archive import Archive, LeakageError, Outcomes
from app.core.domain import ALL_SITES

ORIGIN = date(2026, 9, 2)


# --- leakage guards --------------------------------------------------------


def test_archive_refuses_to_read_past_its_origin():
    arch = Archive(origin=ORIGIN)
    assert arch.observation("jaipur", ORIGIN) is not None
    with pytest.raises(LeakageError):
        arch.observation("jaipur", ORIGIN + timedelta(days=1))


def test_archive_history_never_extends_past_the_origin():
    history = Archive(origin=ORIGIN).history("jaipur", 7)
    assert history
    assert all(row.day <= ORIGIN for row in history)
    assert history == sorted(history, key=lambda r: r.day)


def test_outcomes_refuses_to_read_at_or_before_the_origin():
    outcomes = Outcomes(origin=ORIGIN)
    assert outcomes.actual("jaipur", ORIGIN + timedelta(days=1)) is not None
    with pytest.raises(LeakageError):
        outcomes.actual("jaipur", ORIGIN)


def test_state_context_is_also_guarded():
    arch = Archive(origin=ORIGIN)
    with pytest.raises(LeakageError):
        arch.state_wet_fraction("RAJASTHAN", ORIGIN + timedelta(days=1))
    with pytest.raises(LeakageError):
        arch.state_anomaly("RAJASTHAN", ORIGIN + timedelta(days=1))


def test_features_are_identical_regardless_of_the_valid_day_outcome():
    """Two leads from the same origin share every non-calendar predictor.

    If an outcome had leaked in, the antecedent and state features would differ
    between leads, because the days they verify against differ.
    """
    arch = Archive(origin=ORIGIN)
    a = rf.build_vector(arch, "jaipur", ORIGIN + timedelta(days=1))
    b = rf.build_vector(arch, "jaipur", ORIGIN + timedelta(days=7))
    assert a and b
    calendar = {"lead_time", "doy_sin", "doy_cos", "rain_climatology"}
    for name in rf.REPLAY_PREDICTORS:
        if name not in calendar:
            assert a[name] == pytest.approx(b[name]), name


def test_generate_prediction_never_constructs_an_outcomes_reader(monkeypatch):
    """Phase 1 must have no route to the answer, even indirectly."""

    def explode(*args, **kwargs):  # pragma: no cover - only runs on failure
        raise AssertionError("prediction phase constructed an Outcomes reader")

    monkeypatch.setattr(replay, "Outcomes", explode)
    prediction = replay.generate_prediction(ORIGIN, "jaipur", 5)
    assert prediction is not None
    assert prediction.probability > 0.0


# --- prediction ------------------------------------------------------------


def test_prediction_is_a_model_output_not_a_constant():
    values = {
        replay.generate_prediction(ORIGIN, site.id, 3).probability
        for site in ALL_SITES[:12]
        if replay.generate_prediction(ORIGIN, site.id, 3) is not None
    }
    assert len(values) > 6, "probabilities should vary across sites"
    assert all(0.0 < v < 1.0 for v in values)


def test_threshold_is_fixed_at_one_half():
    model = replay.load_model()
    assert model is not None
    assert model.threshold == 0.50


def test_contributions_sum_to_the_log_odds():
    """Exact Shapley: attributions plus base must reconstruct the log-odds."""
    import math

    model = replay.load_model()
    vector = rf.build_vector(Archive(origin=ORIGIN), "coastal-karnataka", ORIGIN + timedelta(days=4))
    contrib, base = model.contributions(vector)
    log_odds = base + sum(contrib.values())
    reconstructed = 1.0 / (1.0 + math.exp(-log_odds))
    assert reconstructed == pytest.approx(model.probability(vector), abs=1e-9)


def test_evidence_window_ends_at_or_before_the_origin():
    prediction = replay.generate_prediction(ORIGIN, "jaipur", 6)
    assert date.fromisoformat(prediction.evidence_window[1]) <= ORIGIN


def test_run_and_prediction_ids_are_reproducible():
    a = replay.generate_prediction(ORIGIN, "jaipur", 5)
    b = replay.generate_prediction(ORIGIN, "jaipur", 5)
    assert a.prediction_id == b.prediction_id
    assert a.run_id == b.run_id
    c = replay.generate_prediction(ORIGIN, "jaipur", 6)
    assert c.prediction_id != a.prediction_id


# --- validation ------------------------------------------------------------


def test_validation_reports_a_missing_observation_rather_than_filling_it():
    _, end = archive_mod.coverage()
    origin = end - timedelta(days=1)
    prediction = replay.generate_prediction(origin, "jaipur", 7)
    assert prediction is not None
    result = replay.validate_prediction_against_actual(prediction)
    assert result.observed_available is False
    assert result.observed_rainfall is None
    assert result.actual_event is None
    assert result.outcome == "not verifiable"
    assert "not zero" in (result.note or "")


def test_validated_observation_matches_the_published_record():
    prediction = replay.generate_prediction(ORIGIN, "jaipur", 3)
    result = replay.validate_prediction_against_actual(prediction)
    published = archive_mod._site_day("jaipur", prediction.valid_day)
    assert result.observed_available is True
    assert result.observed_rainfall == pytest.approx(published.actual, abs=0.01)
    assert result.observed_category == published.category


def test_outcome_labels_follow_the_confusion_matrix():
    assert replay._outcome(True, True) == "hit"
    assert replay._outcome(True, False) == "false alarm"
    assert replay._outcome(False, True) == "miss"
    assert replay._outcome(False, False) == "correct negative"
    assert replay._outcome(True, None) == "not verifiable"


# --- availability and modes ------------------------------------------------


def test_mode_a_is_unavailable_because_no_hindcast_exists():
    state = replay.availability(ORIGIN)
    assert state["mode_a"]["available"] is False
    assert "archived NWP forecast" in state["mode_a"]["reason"]
    assert state["mode_a"]["candidate_archives"]


def test_hindcast_reader_raises_rather_than_approximating():
    with pytest.raises(hindcast.HindcastUnavailable):
        hindcast.ensemble(date(2016, 9, 4), "jaipur")


def test_september_2016_reports_missing_data_and_runs_nothing():
    state = replay.availability(date(2016, 9, 4))
    assert state["mode_a"]["available"] is False
    assert state["mode_b"]["available"] is False
    assert "2016-09-04" in state["mode_b"]["missing_antecedent_days"]
    result = replay.replay_window(date(2016, 9, 4), "jaipur")
    assert result["predictions"] == []
    assert result["summary"] is None


def test_replay_window_runs_both_phases_in_order():
    result = replay.replay_window(ORIGIN, "coastal-karnataka")
    phases = [entry["phase"] for entry in result["audit_log"]]
    assert phases.index("1 - prediction") < phases.index("2 - validation")
    assert len(result["predictions"]) == len(result["validations"])


def test_replay_window_never_claims_to_be_forecast_bust_validation():
    result = replay.replay_window(ORIGIN, "jaipur")
    assert result["mode"] == "B"
    assert "NOT forecast-bust validation" in result["mode_note"]


# --- backtest --------------------------------------------------------------


def test_backtest_separates_in_sample_from_out_of_sample():
    report = replay.backtest()
    assert report["overall"]["roc_auc"] is not None
    assert report["out_of_sample"]["roc_auc"] is not None
    train = set(replay.load_model().training["train_origins"])
    assert not (set(report["out_of_sample"]["origins"]) & train)


def test_backtest_scores_no_day_the_archive_does_not_cover():
    report = replay.backtest()
    assert report["counts"]["skipped_no_observation"] > 0
    assert report["counts"]["prediction_outcome_pairs"] > 0


def test_backtest_skill_decays_with_lead_time():
    """Day 1 should beat Day 7. A flat profile would suggest a leak."""
    by_lead = {row["lead_time"]: row["roc_auc"] for row in replay.backtest()["by_lead"]}
    assert by_lead[1] > by_lead[7]


def test_usable_origins_lie_inside_the_archive():
    start, end = archive_mod.coverage()
    origins = replay.usable_origins()
    assert origins
    assert all(start <= d <= end for d in origins)
    assert origins[0] >= start + timedelta(days=rf.MIN_ANTECEDENT_DAYS - 1)
