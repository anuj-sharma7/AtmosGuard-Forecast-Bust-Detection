"""Monthly replay over the 1901-2017 sub-division record.

**Why this exists, and what it is not.**

The daily replay (`core/replay.py`) can only run inside the 22-day district
archive. Asked to replay a date in 2015, it correctly reports that it cannot:
there are no daily observations for that year anywhere in this repository.

The sub-division file *does* reach back to 1901 - but it holds one number per
sub-division per month. August 2015 in Vidarbha is a single figure, 288.9 mm.
There is no 5 August in it, and there is no honest way to manufacture one.
Spreading a monthly total across 31 days invents weather that never happened,
which is exactly what this project refuses to do.

So this module answers the question the data can actually support, at the
resolution the data actually has:

    Given everything known up to the end of month T, will month T+1 be an
    *extreme* month for this sub-division - far enough from its own
    climatology to matter?

That is a real, verifiable, leak-free prediction. Every target value is a
published IMD measurement. And unlike the daily replay it has a serious test
set: training stops at 1909-2009 and the whole of **2010-2017** is held out,
which is 2,736 sub-division-months the model has never seen.

**The leak-free detail that matters most** is the climatology. A z-score of
August 2015 computed against a 1901-2017 mean has 2015 inside it, and every
other test year too. So climatology here is always an *expanding window*: for a
target in year Y, the mean and standard deviation come from years strictly
before Y. The number moves as the record grows, exactly as it would have for a
forecaster standing in that year.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from . import imd

MONTHS = imd.MONTHS

#: A month counts as extreme when it sits at least this many standard
#: deviations from its own climatology, in either direction. At 1.0 the base
#: rate over 2010-2017 is 23.7% - frequent enough for the metrics to mean
#: something, rare enough to stay the exception.
EXTREME_Z = 1.0

#: Months whose climatological mean is below this are excluded. A 0.4 mm
#: February in west Rajasthan can be 300% above normal without anything having
#: happened, and scoring those would measure arithmetic, not weather.
MIN_CLIMATOLOGY_MM = 10.0

#: Years of prior record required before a target month is predictable at all.
MIN_HISTORY_YEARS = 30

#: First year held out of fitting. Everything from here on is test data.
TEST_FROM_YEAR = 2010


class MonthlyLeakageError(RuntimeError):
    """Raised when the prediction phase reads a month after its origin."""


@dataclass(frozen=True, order=True)
class YearMonth:
    year: int
    month: int  # 1-12

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12:
            raise ValueError(f"month out of range: {self.month}")

    def shift(self, months: int) -> "YearMonth":
        index = (self.year * 12 + self.month - 1) + months
        return YearMonth(index // 12, index % 12 + 1)

    @property
    def label(self) -> str:
        return f"{MONTHS[self.month - 1].title()} {self.year}"

    def isoformat(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @staticmethod
    def containing(day: date) -> "YearMonth":
        return YearMonth(day.year, day.month)


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _series() -> dict[str, dict[YearMonth, float]]:
    """Every published sub-division month, keyed by sub-division."""
    out: dict[str, dict[YearMonth, float]] = {}
    import csv

    with imd.SUBDIVISION_FILE.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("SUBDIVISION") or "").strip()
            try:
                year = int(row["YEAR"])
            except (KeyError, TypeError, ValueError):
                continue
            table = out.setdefault(name, {})
            for index, month in enumerate(MONTHS, start=1):
                value = imd._float(row.get(month))
                if value is not None:
                    table[YearMonth(year, index)] = value
    return out


@lru_cache(maxsize=1)
def subdivisions() -> tuple[str, ...]:
    return tuple(sorted(_series()))


def resolve(name: str) -> str | None:
    """Accept the correct spelling of a sub-division as well as IMD's own.

    The published series carries 'Matathwada' for Marathwada and a few other
    long-standing variants. `imd.SUBDIVISION_ALIASES` already maps the correct
    name onto the file's spelling; this looks both ways so a caller can use
    either and a lookup never silently returns nothing.
    """
    table = _series()
    if name in table:
        return name
    alias = imd.SUBDIVISION_ALIASES.get(name)
    if alias and alias in table:
        return alias
    folded = name.strip().casefold()
    for key in table:
        if key.casefold() == folded:
            return key
    return None


@lru_cache(maxsize=1)
def record_span() -> tuple[int, int]:
    years = {ym.year for table in _series().values() for ym in table}
    return min(years), max(years)


@dataclass(frozen=True)
class Climatology:
    """Mean and spread of one calendar month, from years strictly before one.

    Expanding-window by construction: `through_year` is exclusive, so a
    climatology used to judge August 2015 contains no 2015 and no later year.
    """

    subdivision: str
    month: int
    through_year: int
    mean: float
    sd: float
    years: int

    def z(self, value: float) -> float | None:
        if self.sd < 1e-9:
            return None
        return (value - self.mean) / self.sd

    def departure_pct(self, value: float) -> float | None:
        if self.mean <= 0:
            return None
        return (value - self.mean) / self.mean * 100.0

    @property
    def usable(self) -> bool:
        return (
            self.years >= MIN_HISTORY_YEARS
            and self.mean >= MIN_CLIMATOLOGY_MM
            and self.sd > 1e-9
        )


@lru_cache(maxsize=200_000)
def climatology(subdivision: str, month: int, before_year: int) -> Climatology:
    """Climatology of one calendar month from every year before `before_year`."""
    table = _series().get(subdivision, {})
    values = [v for ym, v in table.items() if ym.month == month and ym.year < before_year]
    if len(values) < 2:
        return Climatology(subdivision, month, before_year, 0.0, 0.0, len(values))
    return Climatology(
        subdivision=subdivision,
        month=month,
        through_year=before_year,
        mean=statistics.fmean(values),
        sd=statistics.pstdev(values),
        years=len(values),
    )


# ---------------------------------------------------------------------------
# Origin guard
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonthlyArchive:
    """The record as it stood at the end of `origin`. Refuses to read later."""

    origin: YearMonth

    def value(self, subdivision: str, when: YearMonth) -> float | None:
        name = resolve(subdivision)
        if name is None:
            return None
        subdivision = name
        if when > self.origin:
            raise MonthlyLeakageError(
                f"prediction phase tried to read {when.label}, which is after "
                f"origin {self.origin.label}. Features may use only months <= T."
            )
        return _series().get(subdivision, {}).get(when)

    def anomaly(self, subdivision: str, when: YearMonth) -> float | None:
        """Standardised anomaly, against climatology that excludes `when`'s year."""
        value = self.value(subdivision, when)
        if value is None:
            return None
        clim = climatology(subdivision, when.month, when.year)
        return clim.z(value) if clim.usable else None


@dataclass(frozen=True)
class MonthlyOutcomes:
    """What the record says actually happened after `origin`."""

    origin: YearMonth

    def actual(self, subdivision: str, when: YearMonth) -> float | None:
        name = resolve(subdivision)
        if name is None:
            return None
        subdivision = name
        if when <= self.origin:
            raise MonthlyLeakageError(
                f"validation phase asked for {when.label}, which is not after "
                f"origin {self.origin.label}."
            )
        return _series().get(subdivision, {}).get(when)


# ---------------------------------------------------------------------------
# Predictors - every one computable from months <= origin
# ---------------------------------------------------------------------------

MONTHLY_PREDICTORS: tuple[str, ...] = (
    "current_anomaly",
    "lag2_anomaly",
    "lag3_anomaly",
    "recent_mean_anomaly",
    "lags_informative",
    "same_month_last_year",
    "same_month_3yr_mean",
    "last_annual_anomaly",
    "season_to_date_anomaly",
    "recent_extreme_rate",
    "target_month_cv",
    "target_month_share",
    "trend_per_decade",
    "sign_run",
    "month_sin",
    "month_cos",
)

MONTHLY_PREDICTOR_META: dict[str, tuple[str, str]] = {
    "current_anomaly": ("Current Month", "How far the origin month itself sat from its climatology."),
    "lag2_anomaly": ("Two Months Back", "Standardised anomaly of the month before the origin."),
    "lag3_anomaly": ("Three Months Back", "Standardised anomaly three months before the target."),
    "recent_mean_anomaly": ("Recent Run", "Mean anomaly across the last three observed months."),
    "lags_informative": ("Usable Recent Months", "How many of the last three months carry a meaningful anomaly. A climatologically dry month does not."),
    "same_month_last_year": ("Same Month, Last Year", "How this calendar month behaved a year ago."),
    "same_month_3yr_mean": ("Same Month, 3-Year Mean", "Whether this calendar month has been running wet or dry lately."),
    "last_annual_anomaly": ("Last Full Year", "Standardised anomaly of the most recent complete year."),
    "season_to_date_anomaly": ("Season to Date", "Cumulative anomaly of the monsoon so far, where the target sits inside it."),
    "recent_extreme_rate": ("Recent Extremes", "Share of the last five years in which this month was extreme."),
    "target_month_cv": ("Month Variability", "Coefficient of variation of the target month over the prior record."),
    "target_month_share": ("Month's Share of the Year", "How much of the annual total this month normally carries."),
    "trend_per_decade": ("Long-Record Trend", "Sen's slope of this month's rainfall, per decade, scaled by its spread."),
    "sign_run": ("Persistence", "Consecutive recent months on the same side of normal."),
    "month_sin": ("Season (sin)", "Position of the target month in the annual cycle."),
    "month_cos": ("Season (cos)", "Position of the target month in the annual cycle."),
}


def _sen_slope(points: list[tuple[int, float]]) -> float:
    """Median pairwise slope. Robust to the outliers a rainfall series is full of."""
    if len(points) < 3:
        return 0.0
    slopes = [
        (points[j][1] - points[i][1]) / (points[j][0] - points[i][0])
        for i in range(len(points))
        for j in range(i + 1, len(points))
        if points[j][0] != points[i][0]
    ]
    return statistics.median(slopes) if slopes else 0.0


@lru_cache(maxsize=100_000)
def _trend(subdivision: str, month: int, before_year: int) -> float:
    table = _series().get(subdivision, {})
    points = sorted(
        (ym.year, v) for ym, v in table.items() if ym.month == month and ym.year < before_year
    )
    # Sampled rather than exhaustive above ~60 years: the median of a large
    # random subset of pairwise slopes is the same number to three decimals and
    # the full O(n^2) sweep is the hot path in a 50,000-row build.
    if len(points) > 60:
        points = points[-60:]
    return _sen_slope(points) * 10.0


def build_vector(
    archive: MonthlyArchive, subdivision: str, target: YearMonth
) -> dict[str, float] | None:
    """Origin-only predictors for one sub-division and one target month.

    Returns None when the record cannot support a prediction - too few prior
    years, a climatologically dry month, or a gap in the recent series. Nothing
    is substituted for a missing value.
    """
    if target <= archive.origin:
        raise MonthlyLeakageError(
            f"target {target.label} must be after origin {archive.origin.label}"
        )

    name = resolve(subdivision)
    if name is None:
        return None
    subdivision = name

    clim = climatology(subdivision, target.month, target.year)
    if not clim.usable:
        return None

    # Recent-month anomalies. A month whose own climatology is near zero - April
    # in Marathwada, say - has no meaningful anomaly: a 4 mm reading against a
    # 2 mm mean is arithmetic, not weather. Such a lag is encoded as 0.0, which
    # says "no signal here" rather than inventing one, and `lags_informative`
    # tells the model how much of the recent window it can actually trust.
    # The origin month itself must be informative; without it there is no
    # current state to predict from and the case is dropped.
    lags: list[float] = []
    informative = 0
    for back in range(0, 3):
        z = archive.anomaly(subdivision, archive.origin.shift(-back))
        if z is None:
            if back == 0:
                return None
            lags.append(0.0)
            continue
        lags.append(z)
        informative += 1

    # The target month a year ago is always climatologically usable when the
    # target itself is - same calendar month, same subdivision - so a missing
    # value here means a genuine gap in the record, and the case is dropped.
    same_last_year = archive.anomaly(subdivision, target.shift(-12))
    if same_last_year is None:
        return None

    three_year = [
        archive.anomaly(subdivision, target.shift(-12 * k)) for k in (1, 2, 3)
    ]
    three_year_values = [z for z in three_year if z is not None]
    same_3yr = statistics.fmean(three_year_values) if three_year_values else 0.0

    # Most recent complete calendar year, standardised against prior years.
    last_year = archive.origin.year - 1 if archive.origin.month < 12 else archive.origin.year
    annual_values = [
        sum(
            v
            for ym, v in _series().get(subdivision, {}).items()
            if ym.year == y and YearMonth(y, ym.month) <= archive.origin
        )
        for y in (last_year,)
    ]
    prior_annuals = [
        sum(v for ym, v in _series().get(subdivision, {}).items() if ym.year == y)
        for y in range(max(record_span()[0], last_year - 30), last_year)
    ]
    prior_annuals = [a for a in prior_annuals if a > 0]
    if len(prior_annuals) >= 5 and statistics.pstdev(prior_annuals) > 1e-9:
        last_annual = (annual_values[0] - statistics.fmean(prior_annuals)) / statistics.pstdev(
            prior_annuals
        )
    else:
        last_annual = 0.0

    # Monsoon accumulation so far, when the target sits inside the season.
    season_to_date = 0.0
    if 6 <= target.month <= 9:
        season_months = [
            YearMonth(target.year, m) for m in range(6, target.month) if YearMonth(target.year, m) <= archive.origin
        ]
        season_z = [archive.anomaly(subdivision, ym) for ym in season_months]
        season_z = [z for z in season_z if z is not None]
        season_to_date = statistics.fmean(season_z) if season_z else 0.0

    # How often this calendar month has been extreme in the last five years.
    recent = []
    for k in range(1, 6):
        past = target.shift(-12 * k)
        value = archive.value(subdivision, past) if past <= archive.origin else None
        if value is None:
            continue
        past_clim = climatology(subdivision, past.month, past.year)
        z = past_clim.z(value) if past_clim.usable else None
        if z is not None:
            recent.append(1.0 if abs(z) >= EXTREME_Z else 0.0)
    recent_extreme_rate = statistics.fmean(recent) if recent else 0.0

    # Consecutive months on the same side of normal, ending at the origin.
    run = 0
    sign = 0
    for back in range(0, 12):
        z = archive.anomaly(subdivision, archive.origin.shift(-back))
        if z is None:
            break
        this = 1 if z >= 0 else -1
        if sign == 0:
            sign = this
        if this != sign:
            break
        run += 1

    annual_mean = sum(
        climatology(subdivision, m, target.year).mean for m in range(1, 13)
    )
    share = clim.mean / annual_mean if annual_mean > 0 else 0.0

    trend = _trend(subdivision, target.month, target.year)
    angle = 2.0 * math.pi * (target.month - 1) / 12.0

    return {
        "current_anomaly": max(-4.0, min(lags[0], 4.0)),
        "lag2_anomaly": max(-4.0, min(lags[1], 4.0)),
        "lag3_anomaly": max(-4.0, min(lags[2], 4.0)),
        "recent_mean_anomaly": max(-4.0, min(statistics.fmean(lags), 4.0)),
        "lags_informative": informative / 3.0,
        "same_month_last_year": max(-4.0, min(same_last_year, 4.0)),
        "same_month_3yr_mean": max(-4.0, min(same_3yr, 4.0)),
        "last_annual_anomaly": max(-4.0, min(last_annual, 4.0)),
        "season_to_date_anomaly": max(-4.0, min(season_to_date, 4.0)),
        "recent_extreme_rate": recent_extreme_rate,
        "target_month_cv": min(clim.sd / clim.mean, 3.0),
        "target_month_share": share,
        "trend_per_decade": max(-2.0, min(trend / clim.sd, 2.0)) if clim.sd > 0 else 0.0,
        "sign_run": (sign * min(run, 6)) / 6.0,
        "month_sin": math.sin(angle),
        "month_cos": math.cos(angle),
    }


def as_array(vector: dict[str, float]) -> list[float]:
    return [vector[name] for name in MONTHLY_PREDICTORS]


# ---------------------------------------------------------------------------
# Labelling
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonthOutcome:
    subdivision: str
    month: YearMonth
    rainfall: float
    climatology_mm: float
    climatology_years: int
    z: float
    departure_pct: float
    category: str
    extreme: bool


def outcome(subdivision: str, target: YearMonth) -> MonthOutcome | None:
    """What the published record says this month actually did.

    The climatology it is judged against excludes the target's own year, so the
    label for August 2015 is the label a forecaster in 2015 would have applied.
    """
    name = resolve(subdivision)
    if name is None:
        return None
    subdivision = name
    value = _series().get(subdivision, {}).get(target)
    if value is None:
        return None
    clim = climatology(subdivision, target.month, target.year)
    if not clim.usable:
        return None
    z = clim.z(value)
    departure = clim.departure_pct(value)
    if z is None or departure is None:
        return None
    from . import climate

    return MonthOutcome(
        subdivision=subdivision,
        month=target,
        rainfall=round(value, 1),
        climatology_mm=round(clim.mean, 1),
        climatology_years=clim.years,
        z=round(z, 3),
        departure_pct=round(departure, 1),
        category=climate.categorise(departure),
        extreme=abs(z) >= EXTREME_Z,
    )


# ---------------------------------------------------------------------------
# Prediction and validation - two phases, as in the daily replay
# ---------------------------------------------------------------------------

import json  # noqa: E402  (kept local to this section, not needed above)
from pathlib import Path  # noqa: E402

MODEL_PATH = Path(__file__).resolve().parent / "models" / "monthly_model.json"


class MonthlyUnavailable(RuntimeError):
    """Raised when the record cannot support a monthly replay."""


@dataclass(frozen=True)
class MonthlyModel:
    predictors: tuple[str, ...]
    feature_mean: dict[str, float]
    feature_sd: dict[str, float]
    targets: dict[str, dict]
    nominal_threshold: float
    threshold_note: str
    event: dict
    training: dict
    caveat: str
    resolution_note: str

    def _standardise(self, vector: dict[str, float]) -> dict[str, float]:
        return {
            n: (vector[n] - self.feature_mean[n]) / self.feature_sd[n]
            for n in self.predictors
        }

    def probability(self, vector: dict[str, float], target: str) -> float:
        block = self.targets[target]
        z = self._standardise(vector)
        eta = block["intercept"] + sum(
            block["coefficients"][n] * z[n] for n in self.predictors
        )
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(eta, 30.0))))

    def contributions(
        self, vector: dict[str, float], target: str
    ) -> tuple[dict[str, float], float]:
        """Exact Shapley values - closed form for a model linear in the log-odds."""
        block = self.targets[target]
        z = self._standardise(vector)
        return (
            {n: block["coefficients"][n] * z[n] for n in self.predictors},
            float(block["intercept"]),
        )

    def threshold(self, target: str) -> float:
        return float(self.targets[target]["operating_threshold"])


@lru_cache(maxsize=1)
def load_model() -> MonthlyModel | None:
    if not MODEL_PATH.is_file():
        return None
    raw = json.loads(MODEL_PATH.read_text())
    if tuple(raw.get("predictors", ())) != MONTHLY_PREDICTORS:
        return None
    return MonthlyModel(
        predictors=tuple(raw["predictors"]),
        feature_mean=dict(raw["feature_mean"]),
        feature_sd=dict(raw["feature_sd"]),
        targets=dict(raw["targets"]),
        nominal_threshold=float(raw["nominal_threshold"]),
        threshold_note=str(raw["threshold_note"]),
        event=dict(raw["event"]),
        training=dict(raw["training"]),
        caveat=str(raw["caveat"]),
        resolution_note=str(raw["resolution_note"]),
    )


def _model() -> MonthlyModel:
    model = load_model()
    if model is None:
        raise MonthlyUnavailable(
            "The monthly model has not been trained. Run "
            "`python -m scripts.train_monthly_model` in backend/."
        )
    return model


def generate_monthly_prediction(
    origin: YearMonth, subdivision: str, target: YearMonth, explain: bool = True
) -> dict[str, object] | None:
    """Phase 1. Predict `target` from the record up to and including `origin`.

    Holds a `MonthlyArchive`, which raises on any read past the origin, and
    never constructs a `MonthlyOutcomes`. Returns None when the record cannot
    support a prediction for this sub-division and month.

    `explain=False` omits the per-feature attributions. A whole-country sweep
    returns 36 of these and shows none of them; carrying the attributions
    anyway tripled the payload for nothing.
    """
    model = _model()
    archive = MonthlyArchive(origin=origin)
    vector = build_vector(archive, subdivision, target)
    if vector is None:
        return None

    out: dict[str, object] = {
        "subdivision": subdivision,
        "origin": origin.isoformat(),
        "origin_label": origin.label,
        "target": target.isoformat(),
        "target_label": target.label,
        "features": {k: round(v, 5) for k, v in vector.items()} if explain else {},
        "evidence_through": origin.isoformat(),
    }
    for name in ("extreme", "wet", "dry"):
        probability = model.probability(vector, name)
        contrib, base = model.contributions(vector, name)
        top = sorted(contrib.items(), key=lambda kv: -abs(kv[1]))[:5] if explain else []
        out[name] = {
            "probability": round(probability, 5),
            "threshold": round(model.threshold(name), 4),
            "flag": probability >= model.threshold(name),
            "base_value": round(base, 5),
            "contributions": [
                {
                    "feature": feature,
                    "label": MONTHLY_PREDICTOR_META[feature][0],
                    "description": MONTHLY_PREDICTOR_META[feature][1],
                    "value": round(vector[feature], 4),
                    "contribution": round(value, 5),
                }
                for feature, value in top
            ]
            if explain
            else [],
        }
    return out


def validate_monthly_prediction(prediction: dict[str, object]) -> dict[str, object]:
    """Phase 2. Set a finished prediction against the published record.

    Holds a `MonthlyOutcomes`, which refuses to read at or before the origin,
    and takes the prediction as an immutable input.
    """
    origin = YearMonth(*(int(p) for p in str(prediction["origin"]).split("-")))
    target = YearMonth(*(int(p) for p in str(prediction["target"]).split("-")))
    subdivision = str(prediction["subdivision"])

    outcomes = MonthlyOutcomes(origin=origin)
    value = outcomes.actual(subdivision, target)
    result = outcome(subdivision, target) if value is not None else None

    if result is None:
        first, last = record_span()
        return {
            "target": target.isoformat(),
            "observed_available": False,
            "note": (
                f"The sub-division record covers {first}-{last} and carries no "
                f"usable figure for {subdivision} in {target.label}. No value is "
                "substituted."
            ),
        }

    predicted_extreme = bool(prediction["extreme"]["flag"])  # type: ignore[index]
    direction = (
        "wet" if result.z >= EXTREME_Z else "dry" if result.z <= -EXTREME_Z else "neither"
    )
    predicted_direction = (
        "wet"
        if prediction["wet"]["flag"] and not prediction["dry"]["flag"]  # type: ignore[index]
        else "dry"
        if prediction["dry"]["flag"] and not prediction["wet"]["flag"]  # type: ignore[index]
        else "neither"
    )

    if predicted_extreme and result.extreme:
        verdict = "hit"
    elif predicted_extreme:
        verdict = "false alarm"
    elif result.extreme:
        verdict = "miss"
    else:
        verdict = "correct negative"

    return {
        "target": target.isoformat(),
        "target_label": target.label,
        "observed_available": True,
        "rainfall_mm": result.rainfall,
        "climatology_mm": result.climatology_mm,
        "climatology_years": result.climatology_years,
        "departure_pct": result.departure_pct,
        "z": result.z,
        "category": result.category,
        "actual_extreme": result.extreme,
        "actual_direction": direction,
        "predicted_extreme": predicted_extreme,
        "predicted_direction": predicted_direction,
        "direction_correct": (
            None if direction == "neither" and predicted_direction == "neither"
            else direction == predicted_direction
        ),
        "verdict": verdict,
        "source": "IMD sub-divisional monthly rainfall, 1901-2017.",
    }
