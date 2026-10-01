"""7-day station replay, 2010-2021, on real NOAA GHCN-Daily observations.

Pick any date from 2010 to 2021 and a station. The system forms a 7-day
forecast - maximum and minimum temperature and rainfall, day by day - together
with the probability that each day's forecast will bust, using **only
observations up to and including that date**. Then it opens the record for the
seven days that followed and scores itself.

What makes that worth reading is where the model came from: it was fitted on
**1995-2009 only**. Every year from 2010 to 2021 is held out as a block. Any
date a user picks in that window is a date the model never saw, and so is
everything that happened after it.

**The forecast is statistical, not NWP.** No archived numerical weather
prediction for these dates exists in this repository, and none can be
reconstructed from observations without inventing it. So the forecast being
checked - and whose failure the bust probability anticipates - is this
system's own, learned from the station's history and its neighbours. That is
said on every payload.

**Leakage is prevented by construction, not convention.** Every origin feature
is built from arrays shifted *backward* in time (`_lag`), so the value at day T
can only ever see days <= T. `tests/test_station_replay.py` proves it by
corrupting every observation after T and asserting that nothing at T moves.
Climatology comes from 1995-2009 alone, so it contains no test year.

**Missing stays missing.** Indian GHCN stations often do not report rainfall on
dry days. An absent value is NaN all the way through: the model handles it
natively, and verification marks the day "not reported" instead of scoring it
against an invented zero.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "ghcn"
DAILY_FILE = DATA_DIR / "india_daily_1995_2021.csv.gz"
STATIONS_FILE = DATA_DIR / "stations.csv"
MODEL_DIR = Path(__file__).resolve().parent / "models" / "station"
CARD_FILE = MODEL_DIR / "station_model.json"

EPOCH = date(1995, 1, 1)
LAST_DAY = date(2021, 12, 31)
N_DAYS = (LAST_DAY - EPOCH).days + 1

TRAIN_END = date(2009, 12, 31)
TEST_START = date(2010, 1, 1)

LEADS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)

#: IMD's operational temperature verification counts a forecast correct within
#: +/-2 C. A bust is a clear step beyond that tolerance.
TEMP_BUST_C = 3.0

#: IMD daily rainfall classes, lower bounds in mm.
RAIN_CLASSES: tuple[tuple[str, float], ...] = (
    ("No / very light", 0.0),
    ("Light", 2.5),
    ("Moderate", 15.6),
    ("Heavy", 64.5),
    ("Very heavy", 115.6),
    ("Extremely heavy", 204.5),
)
RAIN_DAY_MM = 2.5

#: A rainfall forecast busts when it lands two or more IMD classes from what
#: fell - forecasting "no rain" and getting "moderate", say, or "light" and
#: getting "heavy". One class off is an ordinary forecast error.
RAIN_BUST_CLASSES = 2

#: Half-width of the day-of-year window climatology is pooled over.
CLIM_WINDOW = 15


class StationReplayUnavailable(RuntimeError):
    """Raised when the archive or the trained models are not present."""


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Station:
    station_id: str
    name: str
    lat: float
    lon: float
    elevation_m: float


@lru_cache(maxsize=1)
def stations() -> tuple[Station, ...]:
    if not STATIONS_FILE.is_file():
        return ()
    with STATIONS_FILE.open(newline="") as handle:
        return tuple(
            Station(
                station_id=row["station_id"],
                name=row["name"],
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                elevation_m=float(row["elevation_m"]),
            )
            for row in csv.DictReader(handle)
        )


@lru_cache(maxsize=1)
def stations_by_id() -> dict[str, Station]:
    return {s.station_id: s for s in stations()}


def day_index(day: date) -> int:
    return (day - EPOCH).days


def index_day(index: int) -> date:
    return EPOCH + timedelta(days=int(index))


@lru_cache(maxsize=1)
def archive() -> dict[str, dict[str, np.ndarray]]:
    """{station: {"tmax", "tmin", "prcp": float32[N_DAYS]}} with NaN for unreported."""
    if not DAILY_FILE.is_file():
        raise StationReplayUnavailable(
            "The station archive is missing. Run "
            "`python -m scripts.import_ghcn_daily` in backend/."
        )
    out: dict[str, dict[str, np.ndarray]] = {}
    with gzip.open(DAILY_FILE, "rt", newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        for sid, day, tmax, tmin, prcp in reader:
            arrays = out.get(sid)
            if arrays is None:
                arrays = {k: np.full(N_DAYS, np.nan, dtype=np.float32) for k in ("tmax", "tmin", "prcp")}
                out[sid] = arrays
            i = day_index(date.fromisoformat(day))
            if tmax:
                arrays["tmax"][i] = float(tmax)
            if tmin:
                arrays["tmin"][i] = float(tmin)
            if prcp:
                arrays["prcp"][i] = float(prcp)
    return out


@lru_cache(maxsize=1)
def _doy() -> np.ndarray:
    """Day of year (0-365) for every archive index."""
    return np.array(
        [index_day(i).timetuple().tm_yday - 1 for i in range(N_DAYS)], dtype=np.int16
    )


# ---------------------------------------------------------------------------
# Climatology - 1995-2009 only
# ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def climatology(station_id: str) -> dict[str, np.ndarray]:
    """Day-of-year climatology from the training years alone.

    Pooled over a +/-15 day circular window so each day's normal rests on
    roughly 450 observations rather than 15. Built from 1995-2009 only: no
    held-out year contributes to the normal it is judged against.
    """
    arrays = archive()[station_id]
    doy = _doy()
    train = np.arange(N_DAYS) <= day_index(TRAIN_END)
    out = {
        k: np.full(366, np.nan, dtype=np.float32)
        for k in ("tmax_mean", "tmax_sd", "tmin_mean", "tmin_sd", "rain_prob", "rain_log_mean")
    }
    for d in range(366):
        distance = np.abs(((doy - d + 183) % 366) - 183)
        window = train & (distance <= CLIM_WINDOW)
        for var in ("tmax", "tmin"):
            values = arrays[var][window]
            values = values[~np.isnan(values)]
            if values.size >= 30:
                out[f"{var}_mean"][d] = values.mean()
                out[f"{var}_sd"][d] = max(values.std(), 0.5)
        rain = arrays["prcp"][window]
        rain = rain[~np.isnan(rain)]
        if rain.size >= 20:
            out["rain_prob"][d] = (rain >= RAIN_DAY_MM).mean()
            wet = rain[rain >= RAIN_DAY_MM]
            out["rain_log_mean"][d] = np.log1p(wet).mean() if wet.size else 0.0
    return out


# ---------------------------------------------------------------------------
# Features - origin part uses only days <= T
# ---------------------------------------------------------------------------


def _lag(values: np.ndarray, k: int) -> np.ndarray:
    """values[t - k] at position t; NaN where t - k < 0. k >= 0 only: never ahead."""
    if k < 0:
        raise ValueError("a lag must look backward; negative lags read the future")
    out = np.full_like(values, np.nan)
    if k == 0:
        out[:] = values
    else:
        out[k:] = values[:-k]
    return out


def _window_stats(values: np.ndarray, width: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """nan-mean, nan-std and count of reported values over days t-width+1 .. t."""
    stack = np.stack([_lag(values, k) for k in range(width)])
    count = np.sum(~np.isnan(stack), axis=0).astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, np.nansum(stack, axis=0) / np.maximum(count, 1), np.nan)
        sq = np.nansum(np.where(np.isnan(stack), 0.0, (stack - mean) ** 2), axis=0)
        std = np.where(count > 1, np.sqrt(sq / np.maximum(count - 1, 1)), np.nan)
    return mean.astype(np.float32), std.astype(np.float32), count


ORIGIN_FEATURES: tuple[str, ...] = (
    "tmax_anom_0", "tmax_anom_1", "tmax_anom_2",
    "tmin_anom_0", "tmin_anom_1", "tmin_anom_2",
    "tmax_anom_mean7", "tmax_anom_sd7", "tmin_anom_mean7",
    "tmax_tendency", "dtr_anom_0",
    "prcp_0", "prcp_1", "prcp_2",
    "prcp_sum7", "prcp_reported7", "rain_days7", "days_since_rain",
    "net_tmax_anom", "net_rain_frac", "net_rain_reported",
    "lat", "lon", "elevation",
)

TARGET_FEATURES: tuple[str, ...] = (
    "lead", "doy_sin", "doy_cos",
    "clim_tmax", "clim_tmax_sd", "clim_tmin", "clim_tmin_sd",
    "clim_rain_prob", "clim_rain_log",
)

FEATURES: tuple[str, ...] = ORIGIN_FEATURES + TARGET_FEATURES

FEATURE_LABELS: dict[str, str] = {
    "tmax_anom_0": "Max temp anomaly today",
    "tmax_anom_1": "Max temp anomaly yesterday",
    "tmax_anom_2": "Max temp anomaly 2 days ago",
    "tmin_anom_0": "Min temp anomaly today",
    "tmin_anom_1": "Min temp anomaly yesterday",
    "tmin_anom_2": "Min temp anomaly 2 days ago",
    "tmax_anom_mean7": "7-day max temp anomaly",
    "tmax_anom_sd7": "7-day max temp variability",
    "tmin_anom_mean7": "7-day min temp anomaly",
    "tmax_tendency": "Max temp tendency",
    "dtr_anom_0": "Day-night range anomaly",
    "prcp_0": "Rain today",
    "prcp_1": "Rain yesterday",
    "prcp_2": "Rain 2 days ago",
    "prcp_sum7": "7-day rainfall",
    "prcp_reported7": "Rain reports in last 7 days",
    "rain_days7": "Rain days in last 7",
    "days_since_rain": "Days since last rain",
    "net_tmax_anom": "Network max temp anomaly",
    "net_rain_frac": "Share of stations raining",
    "net_rain_reported": "Stations reporting rain",
    "lat": "Latitude",
    "lon": "Longitude",
    "elevation": "Elevation",
    "lead": "Lead time",
    "doy_sin": "Season (sin)",
    "doy_cos": "Season (cos)",
    "clim_tmax": "Normal max temp",
    "clim_tmax_sd": "Max temp variability (normal)",
    "clim_tmin": "Normal min temp",
    "clim_tmin_sd": "Min temp variability (normal)",
    "clim_rain_prob": "Normal chance of rain",
    "clim_rain_log": "Normal rain amount",
}


@lru_cache(maxsize=1)
def _network() -> dict[str, np.ndarray]:
    """Same-day context across the whole network. Day T only, never later."""
    anoms, rain_hits, rain_reports = [], [], []
    doy = _doy()
    for sid in archive():
        clim = climatology(sid)
        arr = archive()[sid]
        anoms.append((arr["tmax"] - clim["tmax_mean"][doy]) / clim["tmax_sd"][doy])
        reported = ~np.isnan(arr["prcp"])
        rain_reports.append(reported.astype(np.float32))
        rain_hits.append(np.where(reported, (arr["prcp"] >= RAIN_DAY_MM).astype(np.float32), 0.0))
    anoms_a = np.stack(anoms)
    counts = np.sum(~np.isnan(anoms_a), axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        tmax = np.where(counts > 0, np.nansum(anoms_a, axis=0) / np.maximum(counts, 1), np.nan)
    reports = np.sum(rain_reports, axis=0)
    hits = np.sum(rain_hits, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(reports > 0, hits / reports, np.nan)
    return {
        "tmax": tmax.astype(np.float32),
        "rain_frac": frac.astype(np.float32),
        "rain_reported": (reports / len(anoms)).astype(np.float32),
    }


@lru_cache(maxsize=64)
def origin_matrix(station_id: str) -> np.ndarray:
    """Origin features for every day in the archive: shape (N_DAYS, len(ORIGIN_FEATURES)).

    Row t uses only days <= t. Every array is either an observation at t or a
    backward `_lag` of one.
    """
    arr = archive()[station_id]
    clim = climatology(station_id)
    meta = stations_by_id()[station_id]
    doy = _doy()

    tmax_anom = (arr["tmax"] - clim["tmax_mean"][doy]) / clim["tmax_sd"][doy]
    tmin_anom = (arr["tmin"] - clim["tmin_mean"][doy]) / clim["tmin_sd"][doy]
    dtr = arr["tmax"] - arr["tmin"]
    dtr_clim = clim["tmax_mean"][doy] - clim["tmin_mean"][doy]

    tmax_mean7, tmax_sd7, _ = _window_stats(tmax_anom, 7)
    tmin_mean7, _, _ = _window_stats(tmin_anom, 7)
    older, _, _ = _window_stats(_lag(tmax_anom, 3), 4)  # days t-6 .. t-3

    prcp = arr["prcp"]
    prcp_mean7, _, prcp_count7 = _window_stats(prcp, 7)
    rain_flags = np.where(np.isnan(prcp), np.nan, (prcp >= RAIN_DAY_MM).astype(np.float32))
    rain_days7_mean, _, _ = _window_stats(rain_flags, 7)

    # Days since the last reported rain day, capped at 30. Computed with a
    # forward pass over the past only.
    since = np.full(N_DAYS, 30.0, dtype=np.float32)
    last = -10_000
    for t in range(N_DAYS):
        if not np.isnan(prcp[t]) and prcp[t] >= RAIN_DAY_MM:
            last = t
        since[t] = min(t - last, 30)

    net = _network()

    cols = [
        tmax_anom, _lag(tmax_anom, 1), _lag(tmax_anom, 2),
        tmin_anom, _lag(tmin_anom, 1), _lag(tmin_anom, 2),
        tmax_mean7, tmax_sd7, tmin_mean7,
        tmax_anom - older, dtr - dtr_clim,
        prcp, _lag(prcp, 1), _lag(prcp, 2),
        prcp_mean7 * prcp_count7, prcp_count7,
        rain_days7_mean * prcp_count7, since,
        net["tmax"], net["rain_frac"], net["rain_reported"],
        np.full(N_DAYS, meta.lat, dtype=np.float32),
        np.full(N_DAYS, meta.lon, dtype=np.float32),
        np.full(N_DAYS, meta.elevation_m, dtype=np.float32),
    ]
    return np.stack(cols, axis=1).astype(np.float32)


def target_features(station_id: str, target_index: np.ndarray, lead: int) -> np.ndarray:
    """Calendar and climatology of the target day. Known in advance, not observed."""
    clim = climatology(station_id)
    doy = _doy()[target_index]
    angle = 2.0 * np.pi * doy / 366.0
    return np.stack(
        [
            np.full(target_index.shape, lead, dtype=np.float32),
            np.sin(angle).astype(np.float32),
            np.cos(angle).astype(np.float32),
            clim["tmax_mean"][doy], clim["tmax_sd"][doy],
            clim["tmin_mean"][doy], clim["tmin_sd"][doy],
            clim["rain_prob"][doy], clim["rain_log_mean"][doy],
        ],
        axis=1,
    ).astype(np.float32)


def feature_rows(station_id: str, origins: np.ndarray, lead: int) -> np.ndarray:
    """Full feature rows for these origin indices at one lead."""
    return np.hstack(
        [origin_matrix(station_id)[origins], target_features(station_id, origins + lead, lead)]
    )


def rain_class(mm: float | None) -> int | None:
    if mm is None or (isinstance(mm, float) and math.isnan(mm)):
        return None
    index = 0
    for i, (_, lower) in enumerate(RAIN_CLASSES):
        if mm >= lower:
            index = i
    return index


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_models() -> dict[str, object] | None:
    if not CARD_FILE.is_file():
        return None
    card = json.loads(CARD_FILE.read_text())
    if tuple(card.get("features", ())) != FEATURES:
        return None
    try:
        import joblib
    except ImportError:  # pragma: no cover - dependency guard
        return None
    models = {name: joblib.load(MODEL_DIR / f"{name}.joblib") for name in card["model_files"]}
    return {"card": card, "shrink": card.get("shrink", {}), **models}


def _models() -> dict[str, object]:
    models = load_models()
    if models is None:
        raise StationReplayUnavailable(
            "The station models have not been trained. Run "
            "`python -m scripts.train_station_model` in backend/."
        )
    return models


#: Column positions, in the origin features, of today's and yesterday's
#: anomaly for each temperature variable.
_REF_COLUMNS = {"tmax": (0, 1), "tmin": (3, 4)}


def reference_anomaly(x: np.ndarray, var: str) -> np.ndarray:
    """The persistence reference known at T: today's anomaly, else yesterday's,
    else zero - the climatological normal.

    Falling back to the normal is a forecast choice, not a filled observation:
    with no recent reading, "expect a normal day" is the forecast a person
    would make, and nothing pretends a reading was taken.
    """
    today, yesterday = _REF_COLUMNS[var]
    a0, a1 = x[:, today], x[:, yesterday]
    return np.where(~np.isnan(a0), a0, np.where(~np.isnan(a1), a1, 0.0)).astype(np.float32)


def temperature_anomaly(models: dict, x: np.ndarray, var: str, lead: int) -> np.ndarray:
    """Persistence plus a learned correction, shrunk per lead.

    The trees model the *change* from persistence rather than the anomaly
    itself. Day-to-day temperature is strongly persistent, and trees
    approximate a straight line in steps: fitted directly they lost to plain
    "tomorrow is like today" at Day 1. The shrinkage weight for each lead is
    chosen on out-of-fold training forecasts, never on the held-out years.
    """
    shrink = float(models.get("shrink", {}).get(var, {}).get(str(lead), 1.0))
    return reference_anomaly(x, var) + shrink * models[var].predict(x)


def forecast_block(models: dict, x: np.ndarray, station_id: str, origins: np.ndarray, lead: int) -> dict[str, np.ndarray]:
    """The weather forecast for these rows, in physical units."""
    clim = climatology(station_id)
    doy = _doy()[origins + lead]
    tmax = temperature_anomaly(models, x, "tmax", lead) * clim["tmax_sd"][doy] + clim["tmax_mean"][doy]
    tmin = temperature_anomaly(models, x, "tmin", lead) * clim["tmin_sd"][doy] + clim["tmin_mean"][doy]
    p_rain = models["rain_prob"].predict_proba(x)[:, 1]
    amount = np.expm1(np.maximum(models["rain_amount"].predict(x), 0.0))
    amount = np.maximum(amount, RAIN_DAY_MM)
    rain_mm = np.where(p_rain >= 0.5, amount, 0.0)
    return {"tmax": tmax, "tmin": tmin, "p_rain": p_rain, "rain_mm": rain_mm}


def bust_inputs(x: np.ndarray, fc: dict[str, np.ndarray], station_id: str, origins: np.ndarray, lead: int) -> np.ndarray:
    """Features for the bust classifiers: the origin state plus the forecast itself."""
    clim = climatology(station_id)
    doy = _doy()[origins + lead]
    return np.hstack(
        [
            x,
            np.stack(
                [
                    (fc["tmax"] - clim["tmax_mean"][doy]) / clim["tmax_sd"][doy],
                    (fc["tmin"] - clim["tmin_mean"][doy]) / clim["tmin_sd"][doy],
                    fc["p_rain"],
                    np.log1p(fc["rain_mm"]),
                    np.abs(fc["p_rain"] - 0.5),
                ],
                axis=1,
            ),
        ]
    ).astype(np.float32)


BUST_EXTRA: tuple[str, ...] = ("fc_tmax_anom", "fc_tmin_anom", "fc_rain_prob", "fc_rain_log", "fc_rain_confidence")


# ---------------------------------------------------------------------------
# Phase 1 and phase 2
# ---------------------------------------------------------------------------


def _nan_or(value: float, digits: int) -> float | None:
    return None if math.isnan(value) else round(value, digits)


def format_day(
    origin: date,
    lead: int,
    station_id: str,
    tmax: float,
    tmin: float,
    p_rain: float,
    rain_mm: float,
    p_any: float,
    p_temp: float,
    p_rain_bust: float,
) -> dict[str, object]:
    """One forecast day, rounded exactly as it is published.

    Shared by the live API and the static export, so the two cannot drift.
    Rain class is taken from the *published* (rounded) amount, which is also
    the amount verification scores - the class shown and the class judged are
    always the same.
    """
    clim = climatology(station_id)
    d = int(_doy()[day_index(origin) + lead])
    rain_shown = round(float(rain_mm), 1)
    return {
        "lead": lead,
        "date": (origin + timedelta(days=lead)).isoformat(),
        "tmax_c": round(float(tmax), 1),
        "tmin_c": round(float(tmin), 1),
        "rain_probability": round(float(p_rain), 3),
        "rain_mm": rain_shown,
        "rain_class": RAIN_CLASSES[rain_class(rain_shown) or 0][0],
        "normal_tmax_c": round(float(clim["tmax_mean"][d]), 1),
        "normal_tmin_c": round(float(clim["tmin_mean"][d]), 1),
        "normal_rain_probability": _nan_or(float(clim["rain_prob"][d]), 3),
        "bust_probability": round(float(p_any), 4),
        "bust_probability_temperature": round(float(p_temp), 4),
        "bust_probability_rain": round(float(p_rain_bust), 4),
    }


def generate_forecast(station_id: str, origin: date) -> dict[str, object]:
    """Phase 1. Forecast T+1..T+7 and the bust probability of each day.

    Reads `origin_matrix` row T, which by construction depends on days <= T
    only, and target-day climatology, which is a 1995-2009 normal known in
    advance. It never reads an observation after T.
    """
    models = _models()
    station = stations_by_id().get(station_id)
    if station is None:
        raise StationReplayUnavailable(f"Unknown station '{station_id}'")
    if not EPOCH + timedelta(days=7) <= origin <= LAST_DAY - timedelta(days=max(LEADS)):
        raise StationReplayUnavailable(
            f"Origin must fall between {EPOCH + timedelta(days=7)} and "
            f"{LAST_DAY - timedelta(days=max(LEADS))} so that seven days of "
            "history lie behind it and seven days of record lie ahead."
        )

    t = np.array([day_index(origin)])
    days = []
    for lead in LEADS:
        x = feature_rows(station_id, t, lead)
        fc = forecast_block(models, x, station_id, t, lead)
        b = bust_inputs(x, fc, station_id, t, lead)
        days.append(
            format_day(
                origin, lead, station_id,
                fc["tmax"][0], fc["tmin"][0], fc["p_rain"][0], fc["rain_mm"][0],
                models["bust_any"].predict_proba(b)[0, 1],
                models["bust_temp"].predict_proba(b)[0, 1],
                models["bust_rain"].predict_proba(b)[0, 1],
            )
        )

    card = models["card"]
    return {
        "station": station.__dict__,
        "origin": origin.isoformat(),
        "evidence_through": origin.isoformat(),
        "history": history(station_id, origin),
        "forecast": days,
        "thresholds": card["thresholds"],
        "held_out": origin >= TEST_START,
    }


def _observed(value: float) -> float | None:
    return None if np.isnan(value) else float(value)


def history(station_id: str, origin: date) -> list[dict[str, object]]:
    """The seven observed days the forecast was made from, ending at T."""
    arr = archive()[station_id]
    t = day_index(origin)
    out = []
    for back in range(6, -1, -1):
        i = t - back
        out.append(
            {
                "date": index_day(i).isoformat(),
                "tmax_c": _nan_or(float(arr["tmax"][i]), 1),
                "tmin_c": _nan_or(float(arr["tmin"][i]), 1),
                "rain_mm": _nan_or(float(arr["prcp"][i]), 1),
            }
        )
    return out


def _tenths(value: float) -> int:
    """A published value in integer tenths. Scoring is done on these, not on
    floats: 38.2 - 35.2 is 3.0000000000000036 in binary, which would call a
    bust that a person reading the table - and the static build, which does
    the same arithmetic in JavaScript - would not."""
    return int(round(float(value) * 10.0))


def score_day(
    day: dict[str, object],
    tmax: float | None,
    tmin: float | None,
    rain: float | None,
    threshold: float,
) -> dict[str, object]:
    """Score one published forecast day against what was observed.

    Shared by the live API and the static export. Both sides are compared as
    published - forecast and observation rounded to 0.1 and held as integer
    tenths - so what is scored is exactly what is shown.
    """
    fc_tmax, fc_tmin, fc_rain = _tenths(day["tmax_c"]), _tenths(day["tmin_c"]), _tenths(day["rain_mm"])  # type: ignore[arg-type]
    ob_tmax = None if tmax is None else _tenths(tmax)
    ob_tmin = None if tmin is None else _tenths(tmin)
    ob_rain = None if rain is None else _tenths(rain)

    tmax_err = None if ob_tmax is None else fc_tmax - ob_tmax
    tmin_err = None if ob_tmin is None else fc_tmin - ob_tmin
    limit = _tenths(TEMP_BUST_C)
    temp_bust = None
    if tmax_err is not None or tmin_err is not None:
        temp_bust = any(abs(e) > limit for e in (tmax_err, tmin_err) if e is not None)
    rain_bust = None
    if ob_rain is not None:
        rain_bust = abs(rain_class(ob_rain / 10) - rain_class(fc_rain / 10)) >= RAIN_BUST_CLASSES  # type: ignore[operator]

    actual_bust = None if temp_bust is None and rain_bust is None else bool(temp_bust) or bool(rain_bust)
    predicted = float(day["bust_probability"]) >= threshold  # type: ignore[arg-type]
    if actual_bust is None:
        verdict = "not verifiable"
    elif predicted and actual_bust:
        verdict = "hit"
    elif predicted:
        verdict = "false alarm"
    elif actual_bust:
        verdict = "miss"
    else:
        verdict = "correct negative"

    wet = _tenths(RAIN_DAY_MM)
    return {
        "lead": day["lead"],
        "date": day["date"],
        "observed_tmax_c": None if ob_tmax is None else ob_tmax / 10,
        "observed_tmin_c": None if ob_tmin is None else ob_tmin / 10,
        "observed_rain_mm": None if ob_rain is None else ob_rain / 10,
        "observed_rain_class": None if ob_rain is None else RAIN_CLASSES[rain_class(ob_rain / 10)][0],  # type: ignore[index]
        "tmax_error_c": None if tmax_err is None else tmax_err / 10,
        "tmin_error_c": None if tmin_err is None else tmin_err / 10,
        "tmax_within_2c": None if tmax_err is None else abs(tmax_err) <= _tenths(2.0),
        "rain_correct": None if ob_rain is None else (ob_rain >= wet) == (fc_rain >= wet),
        "temperature_bust": temp_bust,
        "rain_bust": rain_bust,
        "actual_bust": actual_bust,
        "predicted_bust": predicted,
        "verdict": verdict,
        "rain_reported": ob_rain is not None,
    }


def summarise(rows: list[dict[str, object]]) -> dict[str, object]:
    verified = [r for r in rows if r["actual_bust"] is not None]
    tmax_checked = [r for r in rows if r["tmax_within_2c"] is not None]
    rain_checked = [r for r in rows if r["rain_correct"] is not None]
    counts: dict[str, int] = {}
    for r in verified:
        counts[str(r["verdict"])] = counts.get(str(r["verdict"]), 0) + 1
    return {
        "days_verified": len(verified),
        **counts,
        "tmax_within_2c": sum(1 for r in tmax_checked if r["tmax_within_2c"]),
        "tmax_checked": len(tmax_checked),
        # Mean of integer tenths, rounded half-up to 0.01 - reproducible
        # to the digit in JavaScript.
        "tmax_mae_c": math.floor(
            sum(abs(_tenths(r["tmax_error_c"])) for r in tmax_checked) * 10 / len(tmax_checked) + 0.5  # type: ignore[arg-type]
        ) / 100
        if tmax_checked
        else None,
        "rain_correct": sum(1 for r in rain_checked if r["rain_correct"]),
        "rain_checked": len(rain_checked),
        "bust_correct": counts.get("hit", 0) + counts.get("correct negative", 0),
    }


def station_page(station_id: str) -> str:
    return f"https://www.ncei.noaa.gov/cdo-web/datasets/GHCND/stations/GHCND:{station_id}/detail"


def validate_forecast(forecast: dict[str, object]) -> dict[str, object]:
    """Phase 2. Open the record for T+1..T+7 and score the finished forecast."""
    station_id = forecast["station"]["station_id"]  # type: ignore[index]
    origin = date.fromisoformat(str(forecast["origin"]))
    arr = archive()[station_id]
    threshold = float(forecast["thresholds"]["bust_any"])  # type: ignore[index]

    rows = []
    for day in forecast["forecast"]:  # type: ignore[union-attr]
        target = date.fromisoformat(day["date"])
        if target <= origin:
            raise ValueError("validation must only read days after the origin")
        i = day_index(target)
        rows.append(
            score_day(
                day,
                _observed(arr["tmax"][i]),
                _observed(arr["tmin"][i]),
                _observed(arr["prcp"][i]),
                threshold,
            )
        )

    return {
        "rows": rows,
        "summary": summarise(rows),
        "source": "NOAA GHCN-Daily, quality-controlled station observations.",
        "station_page": station_page(station_id),
    }
