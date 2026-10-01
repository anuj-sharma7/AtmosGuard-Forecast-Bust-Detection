"""Tests for the 7-day station replay on NOAA GHCN-Daily.

The first group is the one that matters: it proves, rather than asserts, that
a forecast made at T cannot see anything after T - by corrupting every
observation after T and checking that nothing at T moves.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.core import station_replay as S

DELHI = "IN022021900"
ORIGIN = date(2015, 8, 17)


# --- leakage ---------------------------------------------------------------


def test_negative_lag_is_refused():
    with pytest.raises(ValueError):
        S._lag(np.arange(10, dtype=np.float32), -1)


def test_corrupting_the_future_leaves_the_forecast_unchanged(monkeypatch):
    """Overwrite every observation after T with nonsense; T's forecast must not move."""
    before = S.generate_forecast(DELHI, ORIGIN)

    t = S.day_index(ORIGIN)
    real = S.archive()
    poisoned = {
        sid: {k: v.copy() for k, v in arrays.items()} for sid, arrays in real.items()
    }
    for arrays in poisoned.values():
        for k in arrays:
            arrays[k][t + 1 :] = 999.0

    S.origin_matrix.cache_clear()
    S._network.cache_clear()
    monkeypatch.setattr(S, "archive", lambda: poisoned)
    try:
        after = S.generate_forecast(DELHI, ORIGIN)
    finally:
        S.origin_matrix.cache_clear()
        S._network.cache_clear()

    for a, b in zip(before["forecast"], after["forecast"]):
        assert a["tmax_c"] == b["tmax_c"]
        assert a["tmin_c"] == b["tmin_c"]
        assert a["rain_probability"] == b["rain_probability"]
        assert a["bust_probability"] == b["bust_probability"]


def test_climatology_is_built_from_training_years_only(monkeypatch):
    """Poison 2010-2017 entirely; the normals must not change."""
    S.climatology.cache_clear()
    clean = S.climatology(DELHI)["tmax_mean"].copy()

    real = S.archive()
    poisoned = {sid: {k: v.copy() for k, v in a.items()} for sid, a in real.items()}
    start = S.day_index(S.TEST_START)
    for arrays in poisoned.values():
        for k in arrays:
            arrays[k][start:] = -50.0
    S.climatology.cache_clear()
    monkeypatch.setattr(S, "archive", lambda: poisoned)
    try:
        dirty = S.climatology(DELHI)["tmax_mean"]
    finally:
        S.climatology.cache_clear()
    np.testing.assert_allclose(clean, dirty)


def test_validation_only_reads_days_after_the_origin():
    forecast = S.generate_forecast(DELHI, ORIGIN)
    forecast["forecast"][0]["date"] = ORIGIN.isoformat()
    with pytest.raises(ValueError):
        S.validate_forecast(forecast)


# --- data hygiene ----------------------------------------------------------


def test_missing_observations_stay_missing():
    arrays = S.archive()[DELHI]
    assert np.isnan(arrays["prcp"]).any(), "expected unreported rainfall days"
    # Nothing was filled with zero: reported zeros exist, but so do gaps.
    reported = arrays["prcp"][~np.isnan(arrays["prcp"])]
    assert (reported == 0).any()


def test_unreported_days_are_not_scored():
    result = S.validate_forecast(S.generate_forecast("IN020040900", ORIGIN))
    unverifiable = [r for r in result["rows"] if r["verdict"] == "not verifiable"]
    for row in unverifiable:
        assert row["observed_tmax_c"] is None and row["observed_rain_mm"] is None
        assert row["actual_bust"] is None


def test_every_station_has_real_held_out_coverage():
    """Selection was on 2010-2017 coverage; 2018-2021 was added afterwards and
    is sparser at some stations (Goa, Minicoy). Those gaps stay gaps."""
    selection_end = S.day_index(date(2017, 12, 31)) + 1
    for station in S.stations():
        tmax = S.archive()[station.station_id]["tmax"]
        assert (~np.isnan(tmax[S.day_index(S.TEST_START):selection_end])).mean() > 0.75, station.name
        assert (~np.isnan(tmax[S.day_index(S.TEST_START):])).mean() > 0.5, station.name


def test_the_archive_reaches_2021():
    assert S.LAST_DAY == date(2021, 12, 31)
    reported_2021 = sum(
        int((~np.isnan(S.archive()[s.station_id]["tmax"][S.day_index(date(2021, 1, 1)):])).sum())
        for s in S.stations()
    )
    assert reported_2021 > 5000


# --- the forecast ----------------------------------------------------------


def test_forecast_covers_seven_days_after_the_origin():
    forecast = S.generate_forecast(DELHI, ORIGIN)
    dates = [d["date"] for d in forecast["forecast"]]
    assert dates == [(ORIGIN + timedelta(days=k)).isoformat() for k in range(1, 8)]
    assert forecast["evidence_through"] == ORIGIN.isoformat()


def test_forecast_is_physically_plausible():
    forecast = S.generate_forecast(DELHI, ORIGIN)
    for day in forecast["forecast"]:
        assert 15 < day["tmax_c"] < 50
        assert day["tmin_c"] < day["tmax_c"]
        assert 0.0 <= day["rain_probability"] <= 1.0
        assert day["rain_mm"] >= 0.0
        assert 0.0 < day["bust_probability"] < 1.0


def test_bust_probability_is_a_model_output_not_a_constant():
    values = {
        day["bust_probability"]
        for sid in (DELHI, "IN009010100", "IN020040900", "IN019180500")
        for day in S.generate_forecast(sid, ORIGIN)["forecast"]
    }
    assert len(values) > 15


def test_origins_outside_the_archive_are_refused():
    with pytest.raises(S.StationReplayUnavailable):
        S.generate_forecast(DELHI, date(2021, 12, 30))
    with pytest.raises(S.StationReplayUnavailable):
        S.generate_forecast(DELHI, date(1995, 1, 3))
    with pytest.raises(S.StationReplayUnavailable):
        S.generate_forecast("NOT-A-STATION", ORIGIN)


# --- verification ----------------------------------------------------------


def test_observed_values_match_the_archive():
    result = S.validate_forecast(S.generate_forecast(DELHI, ORIGIN))
    arrays = S.archive()[DELHI]
    for row in result["rows"]:
        i = S.day_index(date.fromisoformat(row["date"]))
        if row["observed_tmax_c"] is not None:
            assert row["observed_tmax_c"] == pytest.approx(float(arrays["tmax"][i]), abs=0.05)


def test_bust_definition_follows_the_stated_thresholds():
    result = S.validate_forecast(S.generate_forecast(DELHI, ORIGIN))
    for row in result["rows"]:
        if row["tmax_error_c"] is not None and abs(row["tmax_error_c"]) > S.TEMP_BUST_C:
            assert row["temperature_bust"] is True


def test_rain_classes_follow_imd_bounds():
    assert S.RAIN_CLASSES[S.rain_class(0.0)][0] == "No / very light"
    assert S.RAIN_CLASSES[S.rain_class(2.5)][0] == "Light"
    assert S.RAIN_CLASSES[S.rain_class(64.5)][0] == "Heavy"
    assert S.RAIN_CLASSES[S.rain_class(210.0)][0] == "Extremely heavy"


# --- the model's record ----------------------------------------------------


def test_the_model_was_fitted_before_the_years_it_is_checked_on():
    card = S.load_models()["card"]
    assert card["training"]["train_period"][1] < card["training"]["test_period"][0]


def test_forecast_beats_climatology_and_persistence_beyond_day_one():
    card = S.load_models()["card"]
    for row in card["metrics"]["by_lead"]:
        assert row["tmax_mae_c"] < row["tmax_mae_climatology_c"]
        if row["lead"] >= 2:
            assert row["tmax_mae_same_rows_as_persistence_c"] < row["tmax_mae_persistence_c"]


def test_bust_skill_is_real_and_decays_with_lead():
    card = S.load_models()["card"]
    auc = {r["lead"]: r["bust_auc"] for r in card["metrics"]["by_lead"]}
    assert 0.6 < auc[7] < auc[1] < 0.9, "a near-perfect or flat profile would suggest a leak"
    bust = card["metrics"]["bust_any"]
    assert bust["brier"] < bust["brier_climatology"]
