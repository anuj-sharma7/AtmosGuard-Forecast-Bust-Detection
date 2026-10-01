"""Train and compare bust-risk models on the real IMD observation record.

    python -m scripts.train_models                 # compare all, keep the best
    python -m scripts.train_models --model xgboost # train just one

Three estimators are fitted on the same data and judged the same way:

* **Logistic regression** - the incumbent. Linear in the log-odds, so its
  Shapley values have a closed form. It is the bar the others have to clear.
* **Random forest** - bagged trees. Captures interactions the logistic cannot,
  and is hard to overfit, but gives no signed attribution per prediction.
* **Gradient boosting (XGBoost)** - usually the strongest on tabular data of
  this size, and crucially it computes **exact TreeSHAP** internally via
  ``pred_contribs``, so moving to it costs nothing in explainability. That is
  why it is the default when it wins.

Evaluation is a **temporal** split: earlier valid dates train, later ones test.
A random split leaks badly here - neighbouring days share a weather system, so
a shuffled test set contains near-duplicates of training rows and every model
looks excellent. The held-out number is the only one worth reporting.

Selection is on held-out ROC-AUC, with a deliberate tie-break toward the
simpler model: a tree ensemble has to beat the logistic by a real margin
(``MIN_GAIN``) to justify replacing something whose behaviour can be read off
its coefficients.
"""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from app.config import settings
from app.core.domain import ALL_SITES
from app.core import imd
from app.core.features import extract_features
from app.core.predictors import PREDICTOR_NAMES, build_vector, to_array
from app.core.verification import error_record, verification_valid_days

MODEL_DIR = Path(__file__).resolve().parent.parent / "app" / "core" / "models"
REGISTRY = MODEL_DIR / "registry.json"

#: Held-out AUC a tree ensemble must beat the logistic by to be preferred.
#: Below this the extra opacity is not worth it.
MIN_GAIN = 0.01

#: Fraction of valid dates used for training; the rest are held out.
TRAIN_FRACTION = 0.67

HORIZONS = (3, 4, 5, 6, 7)

#: Predictors computed from the ensemble.
#:
#: These matter for an honest reading of the score. The ensemble here is
#: *reconstructed around the real observed outcome*, so anything derived from it
#: carries some information about the outcome by construction - most obviously
#: `forecast_anomaly`, which is the forecast against normal, and the forecast is
#: a blend containing the truth. With archived NWP that relationship would be
#: weaker, because a real forecast is made without knowing what happens.
#:
#: `--ablate` drops this group and refits on climatology, synoptics and lead
#: alone. That score is a floor; the full score is an optimistic ceiling. The
#: truth for a production system sits between them.
ENSEMBLE_DERIVED = (
    "ensemble_spread",
    "spread_anomaly",
    "spread_growth",
    "ensemble_skew",
    "iqr_ratio",
    "member_range",
    "heavy_rain_fraction",
    "det_mean_gap",
    "forecast_anomaly",
    "accum_3day_anomaly",
    "model_disagreement",
    "forecast_persistence",
)


def build_dataset(base: date) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Predictors, bust labels and the valid date of every forecast.

    Trains on the **whole observed archive**, not the window up to the demo's
    nominal "now". Training is a batch job over all the history you have;
    which forecast the dashboard happens to be displaying is a separate
    question. Tying the two together silently shrank this dataset from 22 days
    to 8 when the demo date moved, and changed which estimator won.

    The caveat, stated plainly: with only a 22-day observation window, the
    demo's reference date sits *inside* the training period. In production the
    displayed forecast would post-date all training data. The temporal split
    below is what keeps the reported score honest regardless.
    """
    vectors: list[dict[str, float]] = []
    labels: list[int] = []
    days: list[int] = []

    start, end = imd.observation_window()
    span = (end - start).days + 1

    for valid in verification_valid_days(end, span):
        for site in ALL_SITES:
            for horizon in HORIZONS:
                init = valid - timedelta(days=horizon)
                bundle = extract_features(site.id, "rainfall", "ensemble", init, horizon)
                vectors.append(
                    build_vector(bundle, site.id, "rainfall", "ensemble", init, horizon)
                )
                labels.append(1 if error_record(site.id, "rainfall", init, horizon).bust else 0)
                days.append(valid.toordinal())

    return to_array(vectors), np.array(labels), np.array(days)


def roc_auc(y: np.ndarray, scores: np.ndarray) -> float:
    positive, negative = scores[y == 1], scores[y == 0]
    if not len(positive) or not len(negative):
        return float("nan")
    order = np.argsort(np.concatenate([positive, negative]), kind="mergesort")
    ranks = np.empty(len(order), dtype=float)
    ranks[order] = np.arange(1, len(order) + 1)
    return float(
        (ranks[: len(positive)].sum() - len(positive) * (len(positive) + 1) / 2)
        / (len(positive) * len(negative))
    )


def brier(y: np.ndarray, scores: np.ndarray) -> float:
    return float(np.mean((scores - y) ** 2))


def fit_logistic(x: np.ndarray, y: np.ndarray):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    # Scaled, because the predictors span millimetres and unit fractions and an
    # unscaled penalty would fall almost entirely on the small-valued ones.
    return Pipeline(
        [
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")),
        ]
    ).fit(x, y)


def fit_random_forest(x: np.ndarray, y: np.ndarray):
    from sklearn.ensemble import RandomForestClassifier

    return RandomForestClassifier(
        n_estimators=400,
        # Depth and leaf size are capped deliberately: with a few thousand rows
        # and a 17% base rate, unconstrained trees memorise the training weeks.
        max_depth=6,
        min_samples_leaf=25,
        max_features="sqrt",
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=7,
    ).fit(x, y)


def fit_xgboost(x: np.ndarray, y: np.ndarray):
    from xgboost import XGBClassifier

    positive = float(y.sum())
    negative = float(len(y) - positive)
    # Deliberately small and heavily regularised. An earlier configuration
    # (350 trees, depth 4) reached a training AUC of 1.000 - it had memorised
    # the training weeks outright. Held-out score barely moved, which is the
    # tell that the extra capacity was fitting noise. Shallow stumps, a high
    # minimum child weight and strong L1/L2 keep train and held-out close
    # enough that the held-out number can be trusted.
    return XGBClassifier(
        n_estimators=160,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.7,
        min_child_weight=14,
        reg_lambda=6.0,
        reg_alpha=1.0,
        gamma=0.5,
        # Rebalances a 17% base rate without resampling.
        scale_pos_weight=negative / positive if positive else 1.0,
        eval_metric="logloss",
        tree_method="hist",
        random_state=7,
    ).fit(x, y)


BUILDERS = {"logistic": fit_logistic, "random_forest": fit_random_forest, "xgboost": fit_xgboost}


def evaluate(name: str, model, x_tr, y_tr, x_te, y_te) -> dict:
    train_scores = model.predict_proba(x_tr)[:, 1]
    test_scores = model.predict_proba(x_te)[:, 1]
    return {
        "model": name,
        "roc_auc_train": round(roc_auc(y_tr, train_scores), 4),
        "roc_auc_holdout": round(roc_auc(y_te, test_scores), 4),
        "brier_holdout": round(brier(y_te, test_scores), 4),
    }


def importances(name: str, model) -> dict[str, float]:
    if name == "logistic":
        weights = np.abs(model.named_steps["model"].coef_[0])
    elif name == "random_forest":
        weights = model.feature_importances_
    else:
        weights = model.feature_importances_
    total = float(weights.sum()) or 1.0
    return {n: round(float(w) / total, 4) for n, w in zip(PREDICTOR_NAMES, weights)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train bust-risk models")
    parser.add_argument("--model", choices=sorted(BUILDERS), help="train only this estimator")
    parser.add_argument("--date", default=settings.demo_reference_date)
    parser.add_argument(
        "--ablate",
        action="store_true",
        help="drop ensemble-derived predictors to measure the score floor",
    )
    args = parser.parse_args()

    base = date.fromisoformat(args.date)
    print("Building dataset ...")
    x, y, days = build_dataset(base)
    print(f"  {len(y):,} forecasts x {x.shape[1]} predictors, bust rate {y.mean():.3f}")

    columns = list(range(len(PREDICTOR_NAMES)))
    if args.ablate:
        columns = [i for i, n in enumerate(PREDICTOR_NAMES) if n not in ENSEMBLE_DERIVED]
        x = x[:, columns]
        print(
            f"  ablation: dropped {len(PREDICTOR_NAMES) - len(columns)} ensemble-derived "
            f"predictors, {len(columns)} remain"
        )

    cutoff = np.quantile(days, TRAIN_FRACTION)
    train, test = days <= cutoff, days > cutoff
    print(
        f"  temporal split at {date.fromordinal(int(cutoff))}: "
        f"{train.sum():,} train / {test.sum():,} held out\n"
    )

    wanted = [args.model] if args.model else list(BUILDERS)
    results: list[dict] = []
    fitted: dict[str, object] = {}

    for name in wanted:
        print(f"Fitting {name} ...")
        model = BUILDERS[name](x[train], y[train])
        fitted[name] = model
        result = evaluate(name, model, x[train], y[train], x[test], y[test])
        results.append(result)
        print(
            f"  ROC-AUC train {result['roc_auc_train']:.3f}  "
            f"held-out {result['roc_auc_holdout']:.3f}  "
            f"Brier {result['brier_holdout']:.3f}"
        )

    print(f"\n{'model':<16}{'train':>8}{'held out':>10}{'Brier':>9}")
    for result in sorted(results, key=lambda r: -r["roc_auc_holdout"]):
        print(
            f"{result['model']:<16}{result['roc_auc_train']:>8.3f}"
            f"{result['roc_auc_holdout']:>10.3f}{result['brier_holdout']:>9.3f}"
        )

    baseline = next((r for r in results if r["model"] == "logistic"), None)
    best = max(results, key=lambda r: r["roc_auc_holdout"])
    if baseline and best["model"] != "logistic":
        gain = best["roc_auc_holdout"] - baseline["roc_auc_holdout"]
        if gain < MIN_GAIN:
            print(
                f"\n{best['model']} beats logistic by only {gain:+.3f} - keeping the "
                "simpler model, whose behaviour can be read off its coefficients."
            )
            best = baseline
        else:
            print(f"\n{best['model']} beats logistic by {gain:+.3f} - selected.")

    if args.ablate:
        print("\nAblation run - nothing saved. Compare against the full-predictor score.")
        return

    # Always measure the floor and store it with the model, so the caveat
    # travels with the number instead of living in someone's memory.
    ablation_columns = [i for i, n in enumerate(PREDICTOR_NAMES) if n not in ENSEMBLE_DERIVED]
    ablated = BUILDERS[best["model"]](x[train][:, ablation_columns], y[train])
    ablated_auc = roc_auc(y[test], ablated.predict_proba(x[test][:, ablation_columns])[:, 1])
    print(
        f"\nablation (no ensemble-derived predictors): held-out {ablated_auc:.3f}\n"
        f"  The ensemble is reconstructed around the observed outcome, so the full\n"
        f"  score of {best['roc_auc_holdout']:.3f} is an optimistic ceiling and this is the floor.\n"
        f"  Archived NWP would land between them."
    )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, model in fitted.items():
        if name == "xgboost":
            # XGBoost's own JSON format, not a pickle: it is portable across
            # library versions and small enough to commit, so a fresh clone
            # scores with the trained model instead of silently falling back to
            # the baseline. A pickle would break on the next sklearn/xgboost
            # upgrade with a confusing error.
            model.save_model(str(MODEL_DIR / "xgboost.json"))
        else:
            # sklearn estimators have no stable serialisation format, so these
            # stay local build artefacts - regenerate with `make fit`.
            with (MODEL_DIR / f"{name}.pkl").open("wb") as handle:
                pickle.dump(model, handle)

    # Percentile knots for the 0-100 index, taken from the selected model's own
    # score distribution across the whole dataset. A ~17% base rate means raw
    # probabilities rarely leave the low range; the percentile mapping is what
    # gives the four risk bands their intended spread without touching the
    # ranking, since a monotonic transform cannot change ROC-AUC.
    selected_model = fitted[best["model"]]
    all_scores = selected_model.predict_proba(x)[:, 1]
    knots = [float(np.quantile(all_scores, q / 100.0)) for q in range(101)]

    REGISTRY.write_text(
        json.dumps(
            {
                "selected": best["model"],
                "index_knots": knots,
                "predictors": list(PREDICTOR_NAMES),
                "results": results,
                "importances": {n: importances(n, m) for n, m in fitted.items()},
                "roc_auc_ablated": round(ablated_auc, 4),
                "ablated_predictors": list(ENSEMBLE_DERIVED),
                "training": {
                    "rows": int(len(y)),
                    "train_rows": int(train.sum()),
                    "test_rows": int(test.sum()),
                    "base_rate": round(float(y.mean()), 4),
                    "split": "temporal",
                    "cutoff_date": date.fromordinal(int(cutoff)).isoformat(),
                    "reference_date": args.date,
                    "source": "IMD district daily rainfall observations",
                },
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nselected: {best['model']}  ->  {REGISTRY.relative_to(REGISTRY.parents[3])}")


if __name__ == "__main__":
    main()
