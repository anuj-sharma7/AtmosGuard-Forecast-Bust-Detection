"""Train the 7-day station forecast and its bust-probability models.

    python -m scripts.train_station_model
    python -m scripts.train_station_model --report    # print, write nothing

Fitted on **1995-2009**. Every origin in **2010-2021** is held out, and so is
every target day in it - a training row whose forecast would land in 2010 is
dropped, not kept.

Two layers, trained in the order they have to be:

1. **The weather forecast.** Maximum and minimum temperature (as standardised
   anomalies against the 1995-2009 normal), the chance of a rain day, and the
   rain amount if it rains. Histogram gradient boosting, which handles the
   unreported values natively - nothing is filled in.

2. **The bust probability.** The chance that layer 1's forecast for a given
   day will fail - a temperature error beyond 3 C (IMD counts +/-2 C as
   correct), or a rainfall forecast two or more IMD classes off. This layer
   has to learn from forecasts that were *genuinely out of sample*: a model
   scored on data it was fitted to looks far better than it is, and a bust
   classifier trained on those flattering errors would learn that busts
   almost never happen. So the training years are split into five blocks of
   three years, each block is forecast by a model that never saw it, and the
   bust classifiers learn from those out-of-fold errors.

Thresholds: 0.50 is reported, and so is an operating threshold matched to the
training base rate - chosen on the out-of-fold training forecasts, frozen
before a single 2010-2017 day is scored.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import station_replay as S  # noqa: E402

FOLD_YEARS = ((1995, 1997), (1998, 2000), (2001, 2003), (2004, 2006), (2007, 2009))

#: Origins are sampled every other day for fitting. Adjacent days share a
#: weather system, so the skipped day carries little new information, and it
#: halves the fitting time. Evaluation uses every day.
TRAIN_STRIDE = 2


def build(first: date, last: date, stride: int) -> dict[str, np.ndarray]:
    """Feature rows and targets for origins in [first, last], all stations, all leads.

    A row is kept only if its target day also lies in [first, last]: a
    training forecast that would land in the held-out years is dropped.
    """
    xs, tmax, tmin, rain, sid_ix, origin_ix, lead_ix = [], [], [], [], [], [], []
    lo = max(S.day_index(first), 7)
    hi = S.day_index(last)
    for n, station in enumerate(S.stations()):
        arr = S.archive()[station.station_id]
        clim = S.climatology(station.station_id)
        doy = S._doy()
        for lead in S.LEADS:
            origins = np.arange(lo, hi - lead + 1, stride)
            target = origins + lead
            x = S.feature_rows(station.station_id, origins, lead)
            xs.append(x)
            d = doy[target]
            tmax.append((arr["tmax"][target] - clim["tmax_mean"][d]) / clim["tmax_sd"][d])
            tmin.append((arr["tmin"][target] - clim["tmin_mean"][d]) / clim["tmin_sd"][d])
            rain.append(arr["prcp"][target])
            sid_ix.append(np.full(origins.shape, n))
            origin_ix.append(origins)
            lead_ix.append(np.full(origins.shape, lead))
    return {
        "x": np.vstack(xs),
        "tmax": np.concatenate(tmax),
        "tmin": np.concatenate(tmin),
        "rain": np.concatenate(rain),
        "station": np.concatenate(sid_ix),
        "origin": np.concatenate(origin_ix),
        "lead": np.concatenate(lead_ix),
    }


def regressor(loss: str = "squared_error"):
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(
        loss=loss, max_iter=250, learning_rate=0.05, max_leaf_nodes=15,
        min_samples_leaf=400, l2_regularization=1.0, random_state=7,
    )


def classifier():
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        max_iter=250, learning_rate=0.08, max_leaf_nodes=31,
        min_samples_leaf=80, l2_regularization=1.0, random_state=7,
    )


def fit_weather(d: dict[str, np.ndarray]) -> dict[str, object]:
    """The four weather models. Each is fitted only where its target was reported."""
    out = {}
    for name in ("tmax", "tmin"):
        ok = ~np.isnan(d[name])
        # Target is the change from persistence; absolute-error loss because
        # the change is heavy-tailed - mostly small, occasionally large - and
        # MAE and the +/-2 C criterion are what the forecast is judged on.
        change = d[name][ok] - S.reference_anomaly(d["x"][ok], name)
        out[name] = regressor("absolute_error").fit(d["x"][ok], change)
    ok = ~np.isnan(d["rain"])
    out["rain_prob"] = classifier().fit(d["x"][ok], (d["rain"][ok] >= S.RAIN_DAY_MM).astype(int))
    wet = ok & (np.nan_to_num(d["rain"]) >= S.RAIN_DAY_MM)
    out["rain_amount"] = regressor().fit(d["x"][wet], np.log1p(d["rain"][wet]))
    return out


def forecast_rows(models: dict, d: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Physical-unit forecasts for every row, grouped by station and lead."""
    n = len(d["lead"])
    fc = {k: np.full(n, np.nan, dtype=np.float32) for k in ("tmax", "tmin", "p_rain", "rain_mm")}
    bust_x = np.full((n, len(S.FEATURES) + len(S.BUST_EXTRA)), np.nan, dtype=np.float32)
    for n_station, station in enumerate(S.stations()):
        for lead in S.LEADS:
            mask = (d["station"] == n_station) & (d["lead"] == lead)
            if not mask.any():
                continue
            origins = d["origin"][mask]
            x = d["x"][mask]
            block = S.forecast_block(models, x, station.station_id, origins, lead)
            for k in fc:
                fc[k][mask] = block[k]
            bust_x[mask] = S.bust_inputs(x, block, station.station_id, origins, lead)
    return {**fc, "bust_x": bust_x}


def observed_physical(d: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    tmax = np.full(len(d["lead"]), np.nan, dtype=np.float32)
    tmin = np.full(len(d["lead"]), np.nan, dtype=np.float32)
    for n_station, station in enumerate(S.stations()):
        clim = S.climatology(station.station_id)
        mask = d["station"] == n_station
        doy = S._doy()[d["origin"][mask] + d["lead"][mask]]
        tmax[mask] = d["tmax"][mask] * clim["tmax_sd"][doy] + clim["tmax_mean"][doy]
        tmin[mask] = d["tmin"][mask] * clim["tmin_sd"][doy] + clim["tmin_mean"][doy]
    return {"tmax": tmax, "tmin": tmin, "rain": d["rain"]}


def rain_classes(mm: np.ndarray) -> np.ndarray:
    bounds = np.array([lower for _, lower in S.RAIN_CLASSES[1:]])
    return np.searchsorted(bounds, mm, side="right").astype(float)


def bust_labels(fc: dict[str, np.ndarray], obs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Actual bust flags: 1, 0, or NaN where the relevant observation is absent."""
    tmax_err = np.abs(fc["tmax"] - obs["tmax"])
    tmin_err = np.abs(fc["tmin"] - obs["tmin"])
    temp = np.where(
        np.isnan(tmax_err) & np.isnan(tmin_err),
        np.nan,
        ((np.nan_to_num(tmax_err) > S.TEMP_BUST_C) | (np.nan_to_num(tmin_err) > S.TEMP_BUST_C)).astype(float),
    )
    rain_obs = obs["rain"]
    rain = np.where(
        np.isnan(rain_obs),
        np.nan,
        (np.abs(rain_classes(np.nan_to_num(rain_obs)) - rain_classes(fc["rain_mm"])) >= S.RAIN_BUST_CLASSES).astype(float),
    )
    anyb = np.where(
        np.isnan(temp) & np.isnan(rain),
        np.nan,
        ((np.nan_to_num(temp) > 0) | (np.nan_to_num(rain) > 0)).astype(float),
    )
    return {"bust_temp": temp, "bust_rain": rain, "bust_any": anyb}


def roc_auc(y: np.ndarray, s: np.ndarray) -> float | None:
    from sklearn.metrics import roc_auc_score

    if len(np.unique(y)) < 2:
        return None
    return round(float(roc_auc_score(y, s)), 4)


def confusion(y: np.ndarray, s: np.ndarray, threshold: float) -> dict:
    pred = s >= threshold
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum()); tn = int((~pred & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "threshold": round(float(threshold), 4),
        "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall) if precision + recall else 0.0, 4),
        "accuracy": round((tp + tn) / max(len(y), 1), 4),
        "base_rate": round(float(y.mean()), 4),
    }


def reliability(y: np.ndarray, s: np.ndarray, bins: int = 10) -> list[dict]:
    out = []
    edges = np.linspace(0, 1, bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (s >= lo) & ((s < hi) if hi < 1 else (s <= hi))
        out.append({
            "bin_lower": round(float(lo), 2), "bin_upper": round(float(hi), 2), "count": int(m.sum()),
            "mean_predicted": round(float(s[m].mean()), 4) if m.any() else None,
            "observed_rate": round(float(y[m].mean()), 4) if m.any() else None,
        })
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    t0 = time.time()

    print("building training rows 1995-2009 ...")
    train = build(date(1995, 1, 8), S.TRAIN_END, TRAIN_STRIDE)
    print(f"  {len(train['lead']):,} rows  ({time.time() - t0:.0f}s)")

    # --- out-of-fold forecasts for the bust layer -------------------------
    origin_years = np.array([S.index_day(i).year for i in train["origin"]])
    target_years = np.array([S.index_day(i + l).year for i, l in zip(train["origin"], train["lead"])])
    oof = {k: np.full(len(train["lead"]), np.nan, dtype=np.float32) for k in ("tmax", "tmin", "p_rain", "rain_mm")}
    oof_bust_x = np.full((len(train["lead"]), len(S.FEATURES) + len(S.BUST_EXTRA)), np.nan, dtype=np.float32)
    fold_models = []
    change_oof = {v: np.full(len(train["lead"]), np.nan, dtype=np.float32) for v in ("tmax", "tmin")}
    for first, last in FOLD_YEARS:
        held = (origin_years >= first) & (origin_years <= last)
        # A fitting row whose target falls inside the held block would leak it.
        fit = ~held & ~((target_years >= first) & (target_years <= last))
        sub = {k: v[fit] for k, v in train.items()}
        models = fit_weather(sub)
        fold_models.append((held, models))
        for v in ("tmax", "tmin"):
            change_oof[v][held] = models[v].predict(train["x"][held])
        print(f"  fold {first}-{last} fitted out of sample  ({time.time() - t0:.0f}s)")

    # Shrinkage of the learned correction toward persistence, per variable and
    # lead, chosen to minimise out-of-fold MAE on the TRAINING years.
    shrink: dict[str, dict[str, float]] = {}
    grid = np.linspace(0.0, 1.5, 31)
    for v in ("tmax", "tmin"):
        shrink[v] = {}
        ref = S.reference_anomaly(train["x"], v)
        for lead in S.LEADS:
            m = (train["lead"] == lead) & ~np.isnan(train[v]) & ~np.isnan(change_oof[v])
            errs = [np.mean(np.abs(ref[m] + w * change_oof[v][m] - train[v][m])) for w in grid]
            shrink[v][str(lead)] = round(float(grid[int(np.argmin(errs))]), 2)
    print(f"  shrinkage toward persistence (train OOF): {shrink}")

    for held, models in fold_models:
        part = {k: v[held] for k, v in train.items()}
        fc = forecast_rows({**models, "shrink": shrink}, part)
        for k in oof:
            oof[k][held] = fc[k]
        oof_bust_x[held] = fc["bust_x"]

    labels = bust_labels(oof, observed_physical(train))

    bust_models, thresholds, bust_train_rates = {}, {}, {}
    for name in ("bust_any", "bust_temp", "bust_rain"):
        ok = ~np.isnan(labels[name])
        clf = classifier().fit(oof_bust_x[ok], labels[name][ok].astype(int))
        bust_models[name] = clf
        rate = float(labels[name][ok].mean())
        bust_train_rates[name] = round(rate, 4)
        scores = clf.predict_proba(oof_bust_x[ok])[:, 1]
        thresholds[name] = round(float(np.quantile(scores, 1.0 - rate)), 4)
    print(f"  bust classifiers fitted  ({time.time() - t0:.0f}s)  thresholds {thresholds}")

    weather = {**fit_weather(train), "shrink": shrink}
    print(f"  final weather models fitted on all of 1995-2009  ({time.time() - t0:.0f}s)")

    # --- held-out evaluation, every day of 2010-2017 ----------------------
    print("building held-out rows 2010-2021 ...")
    test = build(S.TEST_START, S.LAST_DAY, 1)
    all_models = {**weather, **bust_models}
    saved_models = {k: v for k, v in all_models.items() if k != "shrink"}
    fc = forecast_rows(all_models, test)
    obs = observed_physical(test)
    lab = bust_labels(fc, obs)

    clim_tmax = np.full(len(test["lead"]), np.nan, dtype=np.float32)
    persist_tmax = np.full(len(test["lead"]), np.nan, dtype=np.float32)
    clim_rain_prob = np.full(len(test["lead"]), np.nan, dtype=np.float32)
    for n_station, station in enumerate(S.stations()):
        m = test["station"] == n_station
        clim = S.climatology(station.station_id)
        doy = S._doy()[test["origin"][m] + test["lead"][m]]
        clim_tmax[m] = clim["tmax_mean"][doy]
        clim_rain_prob[m] = clim["rain_prob"][doy]
        persist_tmax[m] = S.archive()[station.station_id]["tmax"][test["origin"][m]]

    metrics: dict[str, object] = {"by_lead": []}
    for lead in S.LEADS:
        m = test["lead"] == lead
        ok = m & ~np.isnan(obs["tmax"])
        err = np.abs(fc["tmax"][ok] - obs["tmax"][ok])
        err_clim = np.abs(clim_tmax[ok] - obs["tmax"][ok])
        # Persistence needs today's reading; compare the model on those same rows.
        okp = ok & ~np.isnan(persist_tmax)
        err_pers = np.abs(persist_tmax[okp] - obs["tmax"][okp])
        err_model_same = np.abs(fc["tmax"][okp] - obs["tmax"][okp])
        okr = m & ~np.isnan(obs["rain"])
        rain_hit = ((fc["rain_mm"][okr] >= S.RAIN_DAY_MM) == (obs["rain"][okr] >= S.RAIN_DAY_MM)).mean()
        okb = m & ~np.isnan(lab["bust_any"])
        p = bust_models["bust_any"].predict_proba(fc["bust_x"][okb])[:, 1]
        metrics["by_lead"].append({
            "lead": lead,
            "tmax_mae_c": round(float(err.mean()), 2),
            "tmax_mae_climatology_c": round(float(err_clim.mean()), 2),
            "tmax_mae_persistence_c": round(float(err_pers.mean()), 2),
            "tmax_mae_same_rows_as_persistence_c": round(float(err_model_same.mean()), 2),
            "tmax_within_2c": round(float((err <= 2.0).mean()), 4),
            "rain_day_accuracy": round(float(rain_hit), 4),
            "rain_rows": int(okr.sum()),
            "bust_rate": round(float(lab["bust_any"][okb].mean()), 4),
            "bust_auc": roc_auc(lab["bust_any"][okb], p),
        })

    # Per held-out year: one bad or lucky year should be visible, not averaged away.
    years = np.array([S.index_day(o).year for o in test["origin"]])
    metrics["by_year"] = []
    for year in sorted(set(years.tolist())):
        m = years == year
        ok = m & ~np.isnan(obs["tmax"])
        err = np.abs(fc["tmax"][ok] - obs["tmax"][ok])
        okb = m & ~np.isnan(lab["bust_any"])
        yb = lab["bust_any"][okb].astype(int)
        pb = bust_models["bust_any"].predict_proba(fc["bust_x"][okb])[:, 1]
        metrics["by_year"].append({
            "year": int(year),
            "forecasts": int(m.sum()),
            "tmax_mae_c": round(float(err.mean()), 2),
            "tmax_within_2c": round(float((err <= 2.0).mean()), 4),
            "bust_auc": roc_auc(yb, pb),
            "bust_call_accuracy": round(float(((pb >= thresholds["bust_any"]) == (yb == 1)).mean()), 4),
            "bust_rate": round(float(yb.mean()), 4),
        })

    for name in ("bust_any", "bust_temp", "bust_rain"):
        ok = ~np.isnan(lab[name])
        p = bust_models[name].predict_proba(fc["bust_x"][ok])[:, 1]
        y = lab[name][ok].astype(int)
        metrics[name] = {
            # Accuracy is reported next to the score of always saying "no bust",
            # because at a 17% base rate that trivial forecast is already right
            # 83% of the time, and an accuracy figure alone would flatter.
            "call_accuracy_operating": round(float(((p >= thresholds[name]) == (y == 1)).mean()), 4),
            "call_accuracy_at_50": round(float(((p >= 0.5) == (y == 1)).mean()), 4),
            "call_accuracy_always_no": round(float(1.0 - y.mean()), 4),
            "rows": int(ok.sum()),
            "roc_auc": roc_auc(y, p),
            "brier": round(float(np.mean((p - y) ** 2)), 4),
            "brier_climatology": round(float(np.mean((y.mean() - y) ** 2)), 4),
            "confusion_operating": confusion(y, p, thresholds[name]),
            "confusion_at_50": confusion(y, p, 0.5),
            "reliability": reliability(y, p),
        }

    ok = ~np.isnan(obs["tmax"])
    err = np.abs(fc["tmax"][ok] - obs["tmax"][ok])
    okr = ~np.isnan(obs["rain"])
    metrics["overall"] = {
        "tmax_mae_c": round(float(err.mean()), 2),
        "tmax_mae_climatology_c": round(float(np.abs(clim_tmax[ok] - obs["tmax"][ok]).mean()), 2),
        "tmax_within_2c": round(float((err <= 2.0).mean()), 4),
        "tmin_mae_c": round(float(np.nanmean(np.abs(fc["tmin"] - obs["tmin"]))), 2),
        "rain_day_accuracy": round(float(((fc["rain_mm"][okr] >= S.RAIN_DAY_MM) == (obs["rain"][okr] >= S.RAIN_DAY_MM)).mean()), 4),
        "rain_day_accuracy_climatology": round(float(((clim_rain_prob[okr] >= 0.5) == (obs["rain"][okr] >= S.RAIN_DAY_MM)).mean()), 4),
        "rows": int(len(test["lead"])),
    }

    card = {
        "features": list(S.FEATURES),
        "bust_features": list(S.FEATURES) + list(S.BUST_EXTRA),
        "model_files": ["tmax", "tmin", "rain_prob", "rain_amount", "bust_any", "bust_temp", "bust_rain"],
        "thresholds": thresholds,
        "nominal_threshold": 0.5,
        "shrink": shrink,
        "bust_definition": {
            "temperature": f"Forecast max or min temperature more than {S.TEMP_BUST_C} C from the observation "
            "(IMD counts +/-2 C as a correct temperature forecast).",
            "rain": f"Forecast rainfall {S.RAIN_BUST_CLASSES} or more IMD classes from the observation "
            "(e.g. forecast no rain, observed moderate).",
            "any": "Either of the above. A day with neither observation reported is not verifiable.",
        },
        "forecast_note": "The forecast is statistical, learned from station history and the network. "
        "It is not NWP output: no archived numerical forecast for these dates exists here.",
        "training": {
            "train_period": ["1995-01-08", S.TRAIN_END.isoformat()],
            "test_period": [S.TEST_START.isoformat(), S.LAST_DAY.isoformat()],
            "train_rows": int(len(train["lead"])),
            "test_rows": int(len(test["lead"])),
            "train_stride_days": TRAIN_STRIDE,
            "oof_folds": [list(f) for f in FOLD_YEARS],
            "bust_train_rates": bust_train_rates,
            "stations": len(S.stations()),
            "source": "NOAA GHCN-Daily (quality-controlled), public domain.",
        },
        "metrics": metrics,
    }

    print(f"\nheld-out 2010-2021  ({card['metrics']['overall']['rows']:,} forecasts)")
    o = metrics["overall"]
    print(f"  TMAX MAE {o['tmax_mae_c']} C   climatology {o['tmax_mae_climatology_c']} C   within +/-2C {o['tmax_within_2c']:.1%}")
    print(f"  rain-day accuracy {o['rain_day_accuracy']:.1%}   climatology {o['rain_day_accuracy_climatology']:.1%}")
    for name in ("bust_any", "bust_temp", "bust_rain"):
        b = metrics[name]
        print(f"  {name:9} AUC {b['roc_auc']}  Brier {b['brier']} (clim {b['brier_climatology']})  base {b['confusion_operating']['base_rate']}"
              f"  | call accuracy {b['call_accuracy_operating']:.1%} @thr, {b['call_accuracy_at_50']:.1%} @0.5, always-no {b['call_accuracy_always_no']:.1%}")
    for r in metrics["by_lead"]:
        print(f"   D{r['lead']}: TMAX MAE {r['tmax_mae_c']} (clim {r['tmax_mae_climatology_c']}) | same rows: model {r['tmax_mae_same_rows_as_persistence_c']} vs persist {r['tmax_mae_persistence_c']}  "
              f"±2C {r['tmax_within_2c']:.0%}  rain {r['rain_day_accuracy']:.0%}  bust AUC {r['bust_auc']}  rate {r['bust_rate']:.0%}")
    for r in metrics["by_year"]:
        print(f"   {r['year']}: ±2C {r['tmax_within_2c']:.0%}  MAE {r['tmax_mae_c']}  bust AUC {r['bust_auc']}  call acc {r['bust_call_accuracy']:.0%}  base {r['bust_rate']:.0%}")
    print(f"total {time.time() - t0:.0f}s")

    if args.report:
        print("--report: nothing written.")
        return
    import joblib

    S.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, model in saved_models.items():
        joblib.dump(model, S.MODEL_DIR / f"{name}.joblib", compress=3)
    S.CARD_FILE.write_text(json.dumps(card, indent=2) + "\n")
    size = sum(f.stat().st_size for f in S.MODEL_DIR.glob("*.joblib")) / 1_048_576
    print(f"wrote {len(saved_models)} models ({size:.1f} MB) and {S.CARD_FILE.name}")


if __name__ == "__main__":
    main()
