"""Fit the monthly replay model. Train to 2009, hold out 2010-2017 entirely.

    python -m scripts.train_monthly_model
    python -m scripts.train_monthly_model --report   # print, write nothing

The split is not a fraction of a shuffled pile. Every target month from 2010
onward is held out as a block, so the test set is eight consecutive years the
model has never seen - the same window the sub-division file is usually asked
about, and one whose monsoons are on the public record.

What is predicted is whether a sub-division's month lands at least one standard
deviation from its own climatology, in either direction. The climatology is
expanding: for a target in year Y it is computed from years strictly before Y,
so nothing about 2015 informs the judgement of August 2015, and no test year
leaks into the baseline of any other.

Threshold fixed at 0.50 before evaluation. The test years take no part in
fitting, feature selection or thresholding.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import monthly as M  # noqa: E402

OUT_PATH = Path(__file__).resolve().parents[1] / "app" / "core" / "models" / "monthly_model.json"

#: Nominal decision threshold, frozen before evaluation. Reported because it is
#: the conventional one - and because at this base rate it never fires, which is
#: worth showing rather than hiding.
THRESHOLD = 0.50

#: The threshold actually used to call an event. Chosen on the TRAINING years
#: alone, as the quantile matching the training base rate, then frozen. The
#: held-out years take no part in picking it, so it is not tuning on the test
#: set - it is calibrating the operating point before the test exists.
def operating_threshold(scores: np.ndarray, labels: np.ndarray) -> float:
    return float(np.quantile(scores, 1.0 - labels.mean()))


L2 = 2.0

#: Earliest target year. Before this there is not enough prior record for the
#: expanding-window climatology to be worth anything.
FIRST_TARGET_YEAR = 1935


def build_dataset(years: range) -> tuple[np.ndarray, dict[str, np.ndarray], list[dict]]:
    """Predictors, the three target labels, and an index for the breakdowns.

    Three labels rather than one, because "extreme" without a direction is not
    a claim anyone can act on or check. A month can be far from normal by being
    a flood or a failure, and those are different events with different causes.
    """
    rows: list[list[float]] = []
    labels: dict[str, list[int]] = {"extreme": [], "wet": [], "dry": []}
    index: list[dict] = []

    for subdivision in M.subdivisions():
        for year in years:
            for month in range(1, 13):
                target = M.YearMonth(year, month)
                origin = target.shift(-1)
                archive = M.MonthlyArchive(origin=origin)
                try:
                    vector = M.build_vector(archive, subdivision, target)
                except M.MonthlyLeakageError:  # pragma: no cover - guard, not flow
                    raise
                if vector is None:
                    continue
                result = M.outcome(subdivision, target)
                if result is None:
                    continue
                rows.append(M.as_array(vector))
                labels["extreme"].append(1 if result.extreme else 0)
                labels["wet"].append(1 if result.z >= M.EXTREME_Z else 0)
                labels["dry"].append(1 if result.z <= -M.EXTREME_Z else 0)
                index.append(
                    {
                        "subdivision": subdivision,
                        "target": target.isoformat(),
                        "year": year,
                        "month": month,
                        "z": result.z,
                    }
                )

    return (
        np.asarray(rows, dtype=float),
        {k: np.asarray(v, dtype=int) for k, v in labels.items()},
        index,
    )


def fit_logistic(x: np.ndarray, y: np.ndarray, l2: float = L2) -> np.ndarray:
    n, k = x.shape
    design = np.hstack([np.ones((n, 1)), x])
    beta = np.zeros(k + 1)
    penalty = np.eye(k + 1) * l2
    penalty[0, 0] = 0.0
    for _ in range(80):
        eta = design @ beta
        p = 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))
        w = np.clip(p * (1.0 - p), 1e-6, None)
        try:
            step = np.linalg.solve(
                design.T @ (design * w[:, None]) + penalty,
                design.T @ (y - p) - penalty @ beta,
            )
        except np.linalg.LinAlgError:
            break
        beta = beta + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return beta


def predict(beta: np.ndarray, x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(beta[0] + x @ beta[1:], -30, 30)))


def roc_auc(y: np.ndarray, s: np.ndarray) -> float | None:
    pos, neg = int(y.sum()), int((1 - y).sum())
    if pos == 0 or neg == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[order[j + 1]] == s[order[i]]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return round(float((ranks[y == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg)), 4)


def confusion(y: np.ndarray, s: np.ndarray, threshold: float = THRESHOLD) -> dict:
    pred = (s >= threshold).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "threshold": threshold,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall) if precision + recall else 0.0, 4),
        "accuracy": round((tp + tn) / max(len(y), 1), 4),
        "base_rate": round(float(y.mean()), 4),
    }


def reliability(y: np.ndarray, s: np.ndarray, bins: int = 5) -> list[dict]:
    out = []
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


def grouped(y: np.ndarray, s: np.ndarray, index: list[dict], key: str, minimum: int = 25) -> list[dict]:
    keys = np.asarray([r[key] for r in index])
    out = []
    for value in sorted(set(keys.tolist())):
        mask = keys == value
        if mask.sum() < minimum:
            continue
        out.append(
            {
                key: value if not isinstance(value, np.integer) else int(value),
                "count": int(mask.sum()),
                "events": int(y[mask].sum()),
                "roc_auc": roc_auc(y[mask], s[mask]),
                "brier": round(float(np.mean((s[mask] - y[mask]) ** 2)), 4),
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    _, last = M.record_span()
    print("building training set (walks the whole 1901-2017 record)...")
    x_tr, y_tr, ix_tr = build_dataset(range(FIRST_TARGET_YEAR, M.TEST_FROM_YEAR))
    print("building held-out set 2010-2017...")
    x_te, y_te, ix_te = build_dataset(range(M.TEST_FROM_YEAR, last + 1))

    mean, sd = x_tr.mean(axis=0), x_tr.std(axis=0)
    sd[sd < 1e-9] = 1.0
    z_tr, z_te = (x_tr - mean) / sd, (x_te - mean) / sd

    targets: dict[str, dict] = {}
    for name in ("extreme", "wet", "dry"):
        beta = fit_logistic(z_tr, y_tr[name])
        s_tr, s_te = predict(beta, z_tr), predict(beta, z_te)
        operating = operating_threshold(s_tr, y_tr[name])
        targets[name] = {
            "intercept": float(beta[0]),
            "coefficients": {n: float(b) for n, b in zip(M.MONTHLY_PREDICTORS, beta[1:])},
            "operating_threshold": round(operating, 4),
            "metrics": {
                "roc_auc_train": roc_auc(y_tr[name], s_tr),
                "roc_auc_holdout": roc_auc(y_te[name], s_te),
                "brier_train": round(float(np.mean((s_tr - y_tr[name]) ** 2)), 4),
                "brier_holdout": round(float(np.mean((s_te - y_te[name]) ** 2)), 4),
                "confusion_holdout": confusion(y_te[name], s_te, operating),
                "confusion_holdout_at_50": confusion(y_te[name], s_te, THRESHOLD),
                "reliability_holdout": reliability(y_te[name], s_te),
                "by_year_holdout": grouped(y_te[name], s_te, ix_te, "year"),
                "by_month_holdout": grouped(y_te[name], s_te, ix_te, "month"),
            },
        }
        if name == "extreme":
            targets[name]["metrics"]["by_subdivision_holdout"] = grouped(
                y_te[name], s_te, ix_te, "subdivision", minimum=40
            )

    payload = {
        "predictors": list(M.MONTHLY_PREDICTORS),
        "feature_mean": {n: float(m) for n, m in zip(M.MONTHLY_PREDICTORS, mean)},
        "feature_sd": {n: float(v) for n, v in zip(M.MONTHLY_PREDICTORS, sd)},
        "targets": targets,
        "nominal_threshold": THRESHOLD,
        "threshold_note": (
            "Two thresholds are reported. 0.50 is the conventional one and at this "
            "base rate it never fires - shown rather than hidden. The operating "
            "threshold is the quantile matching the TRAINING base rate, picked on "
            "the training years alone and frozen before 2010-2017 was scored."
        ),
        "event": {
            "label": "Extreme month",
            "definition": f"Sub-division monthly rainfall at least {M.EXTREME_Z} standard "
            "deviations from its own climatology. 'Wet' is the positive side, "
            "'dry' the negative.",
            "source": "IMD sub-divisional monthly rainfall, 1901-2017.",
            "climatology": "Expanding window: for a target in year Y, computed from "
            "years strictly before Y, so no test year informs its own baseline.",
        },
        "resolution": "month",
        "resolution_note": (
            "The sub-division file holds one figure per month. This model predicts a "
            "whole calendar month and cannot resolve individual days. No daily value "
            "is derived from a monthly total."
        ),
        "training": {
            "train_years": [FIRST_TARGET_YEAR, M.TEST_FROM_YEAR - 1],
            "test_years": [M.TEST_FROM_YEAR, last],
            "train_rows": int(len(y_tr["extreme"])),
            "test_rows": int(len(y_te["extreme"])),
            "base_rates_train": {k: round(float(v.mean()), 4) for k, v in y_tr.items()},
            "base_rates_test": {k: round(float(v.mean()), 4) for k, v in y_te.items()},
            "split": "block, by target year",
            "l2": L2,
            "subdivisions": len(M.subdivisions()),
            "min_climatology_mm": M.MIN_CLIMATOLOGY_MM,
            "min_history_years": M.MIN_HISTORY_YEARS,
        },
        "caveat": (
            "ROC-AUC around 0.64 is modest, and it is what a month-ahead rainfall "
            "prediction built only from a rainfall series honestly scores. The "
            "dominant driver of Indian monsoon anomalies is ENSO, and no ENSO index "
            "is present in this dataset. Adding one is the obvious next step; "
            "reporting a higher number without it would not be."
        ),
    }

    print(f"\ntrain rows {len(y_tr['extreme']):,}   test rows {len(y_te['extreme']):,}")
    for name, block in targets.items():
        m = block["metrics"]
        c = m["confusion_holdout"]
        print(
            f"  {name:8} AUC train {m['roc_auc_train']}  2010-17 {m['roc_auc_holdout']}"
            f"  | thr {block['operating_threshold']}"
            f"  precision {c['precision']}  recall {c['recall']}  base {c['base_rate']}"
        )

    if args.report:
        print("\n--report: nothing written.")
        return
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {OUT_PATH.name}")


if __name__ == "__main__":
    main()
