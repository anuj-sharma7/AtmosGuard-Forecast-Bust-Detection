"""Tests for the monthly replay over the 1901-2017 sub-division record.

The leakage surface here is wider than in the daily replay, because the
climatology is itself derived from the record. A z-score of August 2015 taken
against a 1901-2017 mean has 2015 inside it, and every other held-out year too.
Several of these tests exist purely to pin that down.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core import monthly as M

TARGET = M.YearMonth(2015, 8)
ORIGIN = TARGET.shift(-1)


# --- arithmetic ------------------------------------------------------------


def test_year_month_shifts_across_year_boundaries():
    assert M.YearMonth(2015, 1).shift(-1) == M.YearMonth(2014, 12)
    assert M.YearMonth(2015, 12).shift(1) == M.YearMonth(2016, 1)
    assert M.YearMonth(2015, 8).shift(-12) == M.YearMonth(2014, 8)
    assert M.YearMonth(2015, 6).shift(7) == M.YearMonth(2016, 1)


def test_year_month_rejects_an_impossible_month():
    with pytest.raises(ValueError):
        M.YearMonth(2015, 13)


def test_a_date_selects_the_month_containing_it():
    assert M.YearMonth.containing(date(2015, 8, 5)) == M.YearMonth(2015, 8)
    assert M.YearMonth.containing(date(2015, 8, 31)) == M.YearMonth(2015, 8)


# --- leakage guards --------------------------------------------------------


def test_archive_refuses_to_read_after_its_origin():
    archive = M.MonthlyArchive(origin=ORIGIN)
    assert archive.value("Vidarbha", ORIGIN) is not None
    with pytest.raises(M.MonthlyLeakageError):
        archive.value("Vidarbha", TARGET)


def test_outcomes_refuses_to_read_at_or_before_the_origin():
    outcomes = M.MonthlyOutcomes(origin=ORIGIN)
    assert outcomes.actual("Vidarbha", TARGET) is not None
    with pytest.raises(M.MonthlyLeakageError):
        outcomes.actual("Vidarbha", ORIGIN)


def test_build_vector_refuses_a_target_at_or_before_the_origin():
    with pytest.raises(M.MonthlyLeakageError):
        M.build_vector(M.MonthlyArchive(origin=ORIGIN), "Vidarbha", ORIGIN)


def test_climatology_excludes_the_target_year_and_everything_after():
    """The decisive one: a 2015 baseline must not contain 2015, or 2016, or 2017."""
    clim = M.climatology("Vidarbha", 8, 2015)
    series = M._series()["Vidarbha"]
    included = [v for ym, v in series.items() if ym.month == 8 and ym.year < 2015]
    assert clim.years == len(included)
    assert clim.mean == pytest.approx(sum(included) / len(included))

    # And it genuinely moves as the record grows - it is not a fixed constant
    # dressed up as an expanding window.
    assert M.climatology("Vidarbha", 8, 2016).years == clim.years + 1


def test_climatology_for_an_earlier_year_is_built_from_fewer_years():
    assert M.climatology("Kerala", 7, 1960).years < M.climatology("Kerala", 7, 2010).years


# --- coverage and refusal --------------------------------------------------


def test_climatologically_dry_months_are_excluded_rather_than_scored():
    """A 0.4 mm February against a 0.2 mm mean is arithmetic, not weather."""
    dry = [
        M.climatology(s, m, 2015)
        for s in M.subdivisions()
        for m in (1, 2, 3)
        if M.climatology(s, m, 2015).mean < M.MIN_CLIMATOLOGY_MM
    ]
    assert dry, "expected some climatologically dry sub-division months"
    assert all(not c.usable for c in dry)


def test_outcome_is_none_where_the_record_has_no_usable_figure():
    assert M.outcome("Nowhere At All", TARGET) is None


def test_subdivision_aliases_resolve_both_ways():
    assert M.resolve("Marathwada") == "Matathwada"
    assert M.resolve("Matathwada") == "Matathwada"
    assert M.resolve("Odisha") == "Orissa"
    assert M.resolve("Nowhere At All") is None


def test_marathwada_is_predictable_despite_a_dry_lag_month():
    """April is climatologically dry there; that must not kill the whole case."""
    vector = M.build_vector(M.MonthlyArchive(origin=M.YearMonth(2015, 6)), "Marathwada", M.YearMonth(2015, 7))
    assert vector is not None
    assert vector["lags_informative"] < 1.0


# --- labelling -------------------------------------------------------------


def test_outcome_matches_the_published_figure():
    result = M.outcome("Vidarbha", TARGET)
    assert result is not None
    assert result.rainfall == pytest.approx(M._series()["Vidarbha"][TARGET], abs=0.05)
    assert result.extreme is (abs(result.z) >= M.EXTREME_Z)


def test_a_known_extreme_is_labelled_extreme():
    """September 2014 in Jammu & Kashmir - the floods - is unambiguous."""
    result = M.outcome("Jammu & Kashmir", M.YearMonth(2014, 9))
    assert result is not None
    assert result.z > 3.0
    assert result.extreme
    assert result.category == "Large Excess"


# --- prediction and validation ---------------------------------------------


def test_prediction_is_a_model_output_not_a_constant():
    values = set()
    for name in M.subdivisions()[:15]:
        prediction = M.generate_monthly_prediction(ORIGIN, name, TARGET)
        if prediction is not None:
            values.add(prediction["extreme"]["probability"])
    assert len(values) > 8
    assert all(0.0 < v < 1.0 for v in values)


def test_contributions_reconstruct_the_probability_exactly():
    import math

    model = M.load_model()
    vector = M.build_vector(M.MonthlyArchive(origin=ORIGIN), "Vidarbha", TARGET)
    contrib, base = model.contributions(vector, "extreme")
    reconstructed = 1.0 / (1.0 + math.exp(-(base + sum(contrib.values()))))
    assert reconstructed == pytest.approx(model.probability(vector, "extreme"), abs=1e-9)


def test_wet_and_dry_are_separate_models():
    prediction = M.generate_monthly_prediction(ORIGIN, "Vidarbha", TARGET)
    assert prediction["wet"]["probability"] != prediction["dry"]["probability"]
    assert prediction["wet"]["threshold"] != prediction["dry"]["threshold"]


def test_validation_reports_the_published_figure_and_a_verdict():
    prediction = M.generate_monthly_prediction(ORIGIN, "Vidarbha", TARGET)
    result = M.validate_monthly_prediction(prediction)
    assert result["observed_available"] is True
    assert result["rainfall_mm"] == pytest.approx(288.9, abs=0.05)
    assert result["verdict"] in {"hit", "miss", "false alarm", "correct negative"}
    assert result["source"].startswith("IMD sub-divisional")


def test_validation_reports_a_gap_rather_than_filling_it():
    prediction = M.generate_monthly_prediction(ORIGIN, "Vidarbha", TARGET)
    prediction = {**prediction, "subdivision": "Nowhere At All"}
    result = M.validate_monthly_prediction(prediction)
    assert result["observed_available"] is False
    assert "No value is substituted" in result["note"]


def test_the_model_was_never_fitted_on_the_years_it_is_checked_against():
    training = M.load_model().training
    first_test, last_test = training["test_years"]
    assert training["train_years"][1] < first_test
    assert first_test == M.TEST_FROM_YEAR
    assert 2015 >= first_test and 2015 <= last_test


def test_held_out_skill_is_reported_and_is_not_a_perfect_score():
    """A month-ahead rainfall model scoring near 1.0 would mean a leak."""
    targets = M.load_model().targets
    for name in ("extreme", "wet", "dry"):
        auc = targets[name]["metrics"]["roc_auc_holdout"]
        assert 0.5 < auc < 0.85, f"{name} held-out AUC out of plausible range: {auc}"


def test_dry_extremes_are_more_predictable_than_wet_ones():
    """Persistent drought regimes are forecastable a month out; single flood
    events are not. If this ever inverted, something would be wrong."""
    targets = M.load_model().targets
    assert (
        targets["dry"]["metrics"]["roc_auc_holdout"]
        > targets["wet"]["metrics"]["roc_auc_holdout"]
    )
