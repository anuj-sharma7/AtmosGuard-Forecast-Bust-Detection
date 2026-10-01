"""Fit the bust-risk model against the real IMD observation record.

    python -m scripts.fit_model

The MVP originally scored risk with hand-set weights encoding physical priors.
Measured against real IMD district observations those priors did not hold - the
heaviest-weighted predictor correlated 0.06 with actual busts, and the analogue
term correlated 0.00 - so the ranking they produced was close to arbitrary
(ROC-AUC 0.57).

This script replaces assertion with estimation. It fits a logistic regression
of the bust label on the seven predictors, using a **temporal** split: earlier
valid dates train, later ones test. A random split would leak, because
neighbouring days share a weather system; the held-out score would flatter the
model and mean nothing operationally, where the future is always unseen.

The fitted coefficients, the feature means (the SHAP base value) and the score
distribution are written to `app/core/model_params.json`.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from app.config import settings
from app.core import risk_model
from app.core.domain import ALL_SITES
from app.core.features import extract_features
from app.core.verification import error_record, verification_valid_days

OUTPUT = Path(__file__).resolve().parent.parent / "app" / "core" / "model_params.json"

FEATURES = list(risk_model.PREDICTORS) + ["historical_skill"]

#: Ridge penalty. Small - there are seven predictors and thousands of rows -
#: but non-zero so correlated predictors cannot trade off wildly.
L2 = 1.0


def build_dataset(base: date) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    labels: list[int] = []
    days: list[int] = []

    for valid in verification_valid_days(base, 60):
        for site in ALL_SITES:
            for horizon in (3, 4, 5, 6, 7):
                init = valid - timedelta(days=horizon)
                bundle = extract_features(site.id, "rainfall", "ensemble", init, horizon)
                record = error_record(site.id, "rainfall", init, horizon)
                rows.append(
                    [bundle.values[k] for k in risk_model.PREDICTORS] + [bundle.historical_skill]
                )
                labels.append(1 if record.bust else 0)
                days.append(valid.toordinal())

    return np.array(rows), np.array(labels), np.array(days)


def fit_logistic(x: np.ndarray, y: np.ndarray, iterations: int = 300) -> np.ndarray:
    """Newton-Raphson (IRLS) fit with an L2 penalty. Returns [intercept, *coef]."""
    design = np.column_stack([np.ones(len(x)), x])
    beta = np.zeros(design.shape[1])
    penalty = np.eye(design.shape[1]) * L2
    penalty[0, 0] = 0.0  # never penalise the intercept

    for _ in range(iterations):
        eta = design @ beta
        p = 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))
        w = np.clip(p * (1.0 - p), 1e-6, None)
        gradient = design.T @ (y - p) - penalty @ beta
        hessian = (design.T * w) @ design + penalty
        step = np.linalg.solve(hessian, gradient)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta


def roc_auc(y: np.ndarray, s: np.ndarray) -> float:
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order), dtype=float)
    ranks[order] = np.arange(1, len(order) + 1)
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def main() -> None:
    base = date.fromisoformat(settings.demo_reference_date)
    x, y, days = build_dataset(base)
    print(f"dataset: {len(y)} forecasts, bust rate {y.mean():.3f}")

    # Temporal split: the last third of valid dates is held out.
    cutoff = np.quantile(days, 0.67)
    train, test = days <= cutoff, days > cutoff
    print(f"train {train.sum()} (to {date.fromordinal(int(cutoff))}), test {test.sum()}")

    beta = fit_logistic(x[train], y[train])
    intercept, coefficients = float(beta[0]), beta[1:]

    score = lambda m: 1.0 / (1.0 + np.exp(-np.clip(intercept + m @ coefficients, -30, 30)))
    auc_train, auc_test = roc_auc(y[train], score(x[train])), roc_auc(y[test], score(x[test]))
    print(f"\nROC-AUC  train {auc_train:.3f}   held-out {auc_test:.3f}")

    print(f"\n{'predictor':24s}{'coefficient':>13}{'corr(bust)':>12}")
    for name, c in sorted(zip(FEATURES, coefficients), key=lambda t: -abs(t[1])):
        i = FEATURES.index(name)
        print(f"{name:24s}{c:13.3f}{np.corrcoef(x[:, i], y)[0, 1]:12.3f}")

    # The 0-100 index is the percentile of the fitted probability across the
    # whole monitored network, so the risk bands keep their meaning even though
    # the underlying bust probability is a low-base-rate number.
    all_scores = score(x)
    knots = [float(np.quantile(all_scores, q / 100.0)) for q in range(101)]

    OUTPUT.write_text(
        json.dumps(
            {
                "features": FEATURES,
                "intercept": intercept,
                "coefficients": {n: float(c) for n, c in zip(FEATURES, coefficients)},
                "feature_means": {n: float(v) for n, v in zip(FEATURES, x.mean(axis=0))},
                "index_knots": knots,
                "training": {
                    "rows": int(len(y)),
                    "train_rows": int(train.sum()),
                    "test_rows": int(test.sum()),
                    "base_rate": float(y.mean()),
                    "roc_auc_train": round(auc_train, 4),
                    "roc_auc_holdout": round(auc_test, 4),
                    "split": "temporal",
                    "cutoff_date": date.fromordinal(int(cutoff)).isoformat(),
                    "l2": L2,
                    "source": "IMD district daily rainfall observations",
                },
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nwrote {OUTPUT.relative_to(OUTPUT.parents[3])}")


if __name__ == "__main__":
    main()
