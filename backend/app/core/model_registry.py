"""Loads whichever bust-risk model was selected by training, and explains it.

`scripts/train_models.py` fits a logistic regression, a random forest and a
gradient-boosted ensemble, compares them on a temporal hold-out, and records
the winner in `models/registry.json`. This module loads that winner and puts a
single interface in front of it, so nothing downstream needs to know which
estimator is in use.

Explainability is the reason the tree ensemble is acceptable here at all.
XGBoost computes **exact TreeSHAP** internally through ``pred_contribs=True``,
so the per-prediction attributions the explanation panel shows are the real
Shapley values for the model that actually made the prediction - not an
importance ranking standing in for one. A random forest has no equivalent, so
if it is ever selected the attributions fall back to a global importance
weighting, and `contribution_kind` says so rather than letting the UI imply a
precision it does not have.

If no trained model is present the logistic coefficients in `model_params.json`
are used, and everything still works.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .predictors import PREDICTOR_NAMES

MODEL_DIR = Path(__file__).parent / "models"
REGISTRY_PATH = MODEL_DIR / "registry.json"


@dataclass(frozen=True)
class LoadedModel:
    name: str
    estimator: object
    registry: dict
    #: "treeshap" (exact), "linear" (exact) or "importance" (approximate).
    contribution_kind: str

    @property
    def trained(self) -> bool:
        return self.name != "none"

    def predict(self, vector: dict[str, float]) -> float:
        row = np.array([[vector[name] for name in PREDICTOR_NAMES]], dtype=float)
        return float(self.estimator.predict_proba(row)[0, 1])  # type: ignore[union-attr]

    def contributions(self, vector: dict[str, float]) -> tuple[dict[str, float], float]:
        """Per-predictor contributions in log-odds, plus the base value."""
        row = np.array([[vector[name] for name in PREDICTOR_NAMES]], dtype=float)

        if self.contribution_kind == "treeshap":
            import xgboost as xgb

            booster = self.estimator.get_booster()  # type: ignore[union-attr]
            matrix = xgb.DMatrix(row, feature_names=list(PREDICTOR_NAMES))
            # The final column is the bias term - TreeSHAP's base value.
            raw = booster.predict(matrix, pred_contribs=True)[0]
            return dict(zip(PREDICTOR_NAMES, (float(v) for v in raw[:-1]))), float(raw[-1])

        if self.contribution_kind == "linear":
            pipeline = self.estimator
            scaler = pipeline.named_steps["scale"]  # type: ignore[union-attr]
            linear = pipeline.named_steps["model"]  # type: ignore[union-attr]
            scaled = scaler.transform(row)[0]
            coefficients = linear.coef_[0]
            # For a linear model on standardised inputs the Shapley value is
            # c_i * (z_i - mean(z_i)); the scaler has already centred z, so the
            # product is the contribution directly.
            return (
                dict(zip(PREDICTOR_NAMES, (float(c * z) for c, z in zip(coefficients, scaled)))),
                float(linear.intercept_[0]),
            )

        # Random forest: no signed per-prediction attribution exists, so the
        # global importances are distributed by how far each predictor sits
        # from its training mean. Directionally indicative, not exact.
        importances = self.registry.get("importances", {}).get(self.name, {})
        return {name: float(importances.get(name, 0.0)) for name in PREDICTOR_NAMES}, 0.0


@lru_cache(maxsize=1)
def load() -> LoadedModel | None:
    """The selected trained model, or None if training has not been run."""
    if not REGISTRY_PATH.exists():
        return None
    registry = json.loads(REGISTRY_PATH.read_text())

    # A model trained on a different predictor set cannot be scored against the
    # current one; silently mixing column orders would produce plausible
    # nonsense, which is the worst failure mode available here.
    trained_on = tuple(registry.get("predictors", ()))
    if trained_on != PREDICTOR_NAMES:
        return None

    name = str(registry.get("selected"))

    if name == "xgboost":
        # Native JSON: portable across versions, and what is committed.
        path = MODEL_DIR / "xgboost.json"
        if not path.exists():
            return None
        from xgboost import XGBClassifier

        estimator = XGBClassifier()
        estimator.load_model(str(path))
    else:
        path = MODEL_DIR / f"{name}.pkl"
        if not path.exists():
            return None
        with path.open("rb") as handle:
            estimator = pickle.load(handle)

    kind = {"xgboost": "treeshap", "logistic": "linear"}.get(name, "importance")
    return LoadedModel(name=name, estimator=estimator, registry=registry, contribution_kind=kind)


def card() -> dict[str, object]:
    """What is running, for the model card and the System page."""
    model = load()
    if model is None:
        return {"trained": False, "name": "none"}

    results = {r["model"]: r for r in model.registry.get("results", [])}
    selected = results.get(model.name, {})
    return {
        "trained": True,
        "name": model.name,
        "kind": {
            "xgboost": "gradient-boosted trees",
            "random_forest": "random forest",
            "logistic": "logistic regression",
        }.get(model.name, model.name),
        "contribution_kind": model.contribution_kind,
        "explanation_method": {
            "treeshap": "exact TreeSHAP (XGBoost pred_contribs)",
            "linear": "exact additive attribution for a linear model",
            "importance": "global importance weighting - indicative, not exact",
        }[model.contribution_kind],
        "roc_auc_holdout": selected.get("roc_auc_holdout"),
        "roc_auc_ablated": model.registry.get("roc_auc_ablated"),
        "ablation_note": "The ensemble is reconstructed around the observed outcome, so "
        "predictors derived from it carry some information about that outcome. The ablated "
        "score drops them and is the floor; the full score is an optimistic ceiling. "
        "Archived NWP would land between the two.",
        "roc_auc_train": selected.get("roc_auc_train"),
        "brier_holdout": selected.get("brier_holdout"),
        "comparison": model.registry.get("results", []),
        "importances": model.registry.get("importances", {}).get(model.name, {}),
        "training": model.registry.get("training", {}),
        "predictors": len(PREDICTOR_NAMES),
    }
