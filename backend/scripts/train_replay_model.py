"""Fit the historical-replay risk model on origin-only predictors.

    python -m scripts.train_replay_model
    python -m scripts.train_replay_model --report   # print, write nothing

This is a separate model from the operational bust-risk estimator in
``scripts/train_models.py``, and deliberately so. That one is trained on
predictors derived from the reconstructed ensemble, and the reconstruction is
anchored to the observation it is later verified against - fine for a live
demonstration, useless as a backtest, because the features already contain the
answer.

This model sees only what existed at the origin date (``core/replay_features``,
guarded by ``core/archive.Archive``), so its held-out number means what a
held-out number is supposed to mean.

What it predicts is an **IMD Large Excess rainfall day** at the site, L days
after the origin - IMD's own published departure category, not a label this
system invented. That is a weather-risk proxy. It is *not* a forecast bust:
a bust needs the forecast that busted, and no archived forecast exists (see
``core/hindcast.py``). Nothing here should ever be described as forecast-bust
validation.

Protocol, fixed before any number was looked at:

* **Temporal split.** Earlier origins train, later origins test. Adjacent days
  share a weather system, so a shuffled split would put near-duplicates of the
  training rows in the test set.
* **Threshold frozen at 0.50** before evaluation. Not tuned on the test set,
  not tuned at all.
* **The test origins are touched once**, to report. They take no part in
  fitting, feature selection or thresholding.

The honest caveat, stated here because it travels into the model card: the
daily observational archive is 22 days long. That bounds the number of usable
origins to single digits, and a held-out estimate from a handful of origins has
wide error bars whatever it says. The fix is more daily data
(``scripts/import_imd_daily_rainfall.py``), not a different estimator.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import archive as archive_mod  # noqa: E402
from app.core import replay_features as rf  # noqa: E402
from app.core.archive import Archive, Outcomes  # noqa: E402
from app.core.domain import ALL_SITES  # noqa: E402

OUT_PATH = Path(__file__).resolve().parents[1] / "app" / "core" / "models" / "replay_model.json"

#: Lead times the replay product covers.
LEADS = (1, 2, 3, 4, 5, 6, 7)

#: Fraction of usable origins used for fitting. The rest are held out.
TRAIN_FRACTION = 0.6

#: Decision threshold, frozen before evaluation and never tuned.
THRESHOLD = 0.50

#: L2 penalty. Fixed at a conventional value rather than swept, because
#: sweeping it on a dataset this small would be fitting the noise twice.
L2 = 1.0

#: The event being predicted, in IMD's own words.
EVENT_LABEL = "Large Excess"


def usable_origins() -> list[date]:
    """Origins with enough antecedent record behind them and 7 days ahead."""
    start, end = archive_mod.coverage()
    first = start + timedelta(days=rf.MIN_ANTECEDENT_DAYS - 1)
    last = end - timedelta(days=max(LEADS))
    out: list[date] = []
    day = first
    while day <= last:
        out.append(day)
        day += timedelta(days=1)
    return out


def build_dataset(origins: list[date]) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    rows: list[list[float]] = []
    labels: list[int] = []
    index: list[dict] = []

    for origin in origins:
        arch = Archive(origin=origin)
        out = Outcomes(origin=origin)
        for site in ALL_SITES:
            for lead in LEADS:
                valid = origin + timedelta(days=lead)
                vector = rf.build_vector(arch, site.id, valid)
                if vector is None:
                    continue
                actual = out.actual(site.id, valid)
                if actual is None:
                    continue
                rows.append(rf.as_array(vector))
                labels.append(1 if actual.category == EVENT_LABEL else 0)
                index.append(
                    {
                        "origin": origin.isoformat(),
                        "valid": valid.isoformat(),
                        "lead": lead,
                        "location_id": site.id,
                    }
                )

    return np.asarray(rows, dtype=float), np.asarray(labels, dtype=int), index


def standardise(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    sd = x.std(axis=0)
    sd[sd < 1e-9] = 1.0
    return (x - mean) / sd, mean, sd


def fit_logistic(x: np.ndarray, y: np.ndarray, l2: float = L2) -> np.ndarray:
    """Penalised logistic regression by IRLS. Returns [intercept, *weights].

    Plain numpy so the served model carries no scikit-learn dependency - the
    API loads a JSON file of coefficients and evaluates a sigmoid.
    """
    n, k = x.shape
    design = np.hstack([np.ones((n, 1)), x])
    beta = np.zeros(k + 1)
    penalty = np.eye(k + 1) * l2
    penalty[0, 0] = 0.0  # never penalise the intercept

    for _ in range(60):
        eta = design @ beta
        p = 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))
        w = np.clip(p * (1.0 - p), 1e-6, None)
        hessian = design.T @ (design * w[:, None]) + penalty
        gradient = design.T @ (y - p) - penalty @ beta
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            break
        beta = beta + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta


def predict(beta: np.ndarray, x: np.ndarray) -> np.ndarray:
    eta = beta[0] + x @ beta[1:]
    return 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))


def roc_auc(y: np.ndarray, s: np.ndarray) -> float:
    """Mann-Whitney U with tie correction."""
    pos, neg = int(y.sum()), int((1 - y).sum())
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[order[j + 1]] == s[order[i]]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def brier(y: np.ndarray, s: np.ndarray) -> float:
    return float(np.mean((s - y) ** 2))


def confusion(y: np.ndarray, s: np.ndarray, threshold: float = THRESHOLD) -> dict:
    pred = (s >= threshold).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": threshold,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round((tp + tn) / max(len(y), 1), 4),
        "base_rate": round(float(y.mean()), 4),
    }


def reliability(y: np.ndarray, s: np.ndarray, bins: int = 5) -> list[dict]:
    out: list[dict] = []
    edges = np.linspace(0.0, 1.0, bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (s >= lo) & (s < hi if hi < 1.0 else s <= hi)
        count = int(mask.sum())
        out.append(
            {
                "bin_lower": round(float(lo), 2),
                "bin_upper": round(float(hi), 2),
                "count": count,
                "mean_predicted": round(float(s[mask].mean()), 4) if count else None,
                "observed_rate": round(float(y[mask].mean()), 4) if count else None,
            }
        )
    return out


def by_lead(y: np.ndarray, s: np.ndarray, index: list[dict]) -> list[dict]:
    leads = np.asarray([r["lead"] for r in index])
    out: list[dict] = []
    for lead in sorted(set(leads.tolist())):
        mask = leads == lead
        if mask.sum() < 2:
            continue
        out.append(
            {
                "lead_time": int(lead),
                "count": int(mask.sum()),
                "events": int(y[mask].sum()),
                "roc_auc": round(roc_auc(y[mask], s[mask]), 4),
                "brier": round(brier(y[mask], s[mask]), 4),
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print metrics, write nothing")
    args = parser.parse_args()

    origins = usable_origins()
    if len(origins) < 4:
        raise SystemExit(
            f"Only {len(origins)} usable origin(s) in the archive "
            f"({archive_mod.coverage()[0]} to {archive_mod.coverage()[1]}). "
            "A temporal split needs more. Extend the daily record with "
            "scripts/import_imd_daily_rainfall.py."
        )

    cut = max(2, int(round(len(origins) * TRAIN_FRACTION)))
    train_origins, test_origins = origins[:cut], origins[cut:]

    x_tr, y_tr, ix_tr = build_dataset(train_origins)
    x_te, y_te, ix_te = build_dataset(test_origins)

    xs_tr, mean, sd = standardise(x_tr)
    beta = fit_logistic(xs_tr, y_tr)

    s_tr = predict(beta, xs_tr)
    s_te = predict(beta, (x_te - mean) / sd)

    payload = {
        "predictors": list(rf.REPLAY_PREDICTORS),
        "intercept": float(beta[0]),
        "coefficients": {n: float(b) for n, b in zip(rf.REPLAY_PREDICTORS, beta[1:])},
        "feature_mean": {n: float(m) for n, m in zip(rf.REPLAY_PREDICTORS, mean)},
        "feature_sd": {n: float(v) for n, v in zip(rf.REPLAY_PREDICTORS, sd)},
        "threshold": THRESHOLD,
        "event": {
            "label": EVENT_LABEL,
            "definition": "IMD published daily departure category 'Large Excess' "
            "(observed rainfall at least 60% above the published daily normal) "
            "at the site on the valid day.",
            "source": "IMD district-wise daily rainfall, Daily Category column.",
        },
        "mode": "B",
        "mode_note": "Historical weather risk proxy. Predicts an observed IMD "
        "Large Excess day from information available at the origin. This is NOT "
        "forecast-bust validation - no archived NWP forecast exists to bust.",
        "training": {
            "origins_total": len(origins),
            "train_origins": [d.isoformat() for d in train_origins],
            "test_origins": [d.isoformat() for d in test_origins],
            "train_rows": int(len(y_tr)),
            "test_rows": int(len(y_te)),
            "train_base_rate": round(float(y_tr.mean()), 4),
            "test_base_rate": round(float(y_te.mean()), 4),
            "split": "temporal",
            "l2": L2,
            "archive_start": archive_mod.coverage()[0].isoformat(),
            "archive_end": archive_mod.coverage()[1].isoformat(),
            "source": "IMD district-wise daily rainfall observations.",
        },
        "metrics": {
            "roc_auc_train": round(roc_auc(y_tr, s_tr), 4),
            "roc_auc_holdout": round(roc_auc(y_te, s_te), 4),
            "brier_train": round(brier(y_tr, s_tr), 4),
            "brier_holdout": round(brier(y_te, s_te), 4),
            "confusion_holdout": confusion(y_te, s_te),
            "reliability_holdout": reliability(y_te, s_te),
            "by_lead_holdout": by_lead(y_te, s_te, ix_te),
        },
        "caveat": (
            f"Fitted on {len(train_origins)} origin dates and held out on "
            f"{len(test_origins)}. The daily observational archive spans "
            f"{archive_mod.coverage()[0]} to {archive_mod.coverage()[1]} - "
            "22 days. A held-out estimate from this few origins has wide error "
            "bars regardless of its value, and it should be read as a working "
            "figure, not a performance claim."
        ),
    }

    print(f"origins            {len(origins)} ({train_origins[0]} .. {test_origins[-1]})")
    print(f"train / test rows  {len(y_tr)} / {len(y_te)}")
    print(f"base rate tr / te  {y_tr.mean():.3f} / {y_te.mean():.3f}")
    print(f"ROC-AUC  train     {payload['metrics']['roc_auc_train']}")
    print(f"ROC-AUC  held-out  {payload['metrics']['roc_auc_holdout']}")
    print(f"Brier    held-out  {payload['metrics']['brier_holdout']}")
    print(f"confusion @0.50    {payload['metrics']['confusion_holdout']}")

    if args.report:
        print("\n--report: nothing written.")
        return

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {OUT_PATH.relative_to(Path(__file__).resolve().parents[2])}")


if __name__ == "__main__":
    main()
