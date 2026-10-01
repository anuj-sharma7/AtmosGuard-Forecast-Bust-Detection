"""AtmosGuard forecast-bust risk model.

Fitted by logistic regression on **real IMD district rainfall observations**
(see `scripts/fit_model.py`), replacing the hand-set physical priors the MVP
started with. That replacement was not cosmetic. Measured against the real
record, the priors put 23% of the weight on a predictor correlating 0.06 with
actual busts and 18% on one correlating 0.00, and the ranking they produced
scored ROC-AUC 0.57 - barely better than chance. Estimating the weights from
the data instead is what makes the score mean something.

Two properties are kept deliberately:

* **Linear in the log-odds.** For such a model the Shapley value of predictor
  *i* is exactly ``c_i * (x_i - E[x_i])``, so the contributions shown in the
  explanation panel are real additive attributions - the same quantity SHAP
  reports for a logistic model - rather than a SHAP-shaped decoration.
* **Honest evaluation.** The reported ROC-AUC is held out on a *temporal*
  split: earlier valid dates train, later ones test. A random split would leak,
  because neighbouring days share a weather system.

The estimator is swappable: `scripts/fit_model.py` writes `model_params.json`,
and a gradient-boosted model with `shap.TreeExplainer` drops into the same seam.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import model_registry
from .domain import ALL_SITES_BY_ID, VARIABLES_BY_ID, risk_category

PARAMS_PATH = Path(__file__).parent / "model_params.json"

MODEL_NAME = "atmosguard-logistic"
MODEL_VERSION = "0.2.0"

with PARAMS_PATH.open() as _handle:
    PARAMS: dict = json.load(_handle)

#: Fitted log-odds coefficients, one per predictor.
COEFFICIENTS: dict[str, float] = PARAMS["coefficients"]
INTERCEPT: float = PARAMS["intercept"]

#: E[x] over the training set - the base value attributions are measured from.
FEATURE_MEANS: dict[str, float] = PARAMS["feature_means"]

#: Percentiles of the fitted probability across the monitored network, used to
#: map a low-base-rate probability onto the 0-100 index.
INDEX_KNOTS: list[float] = PARAMS["index_knots"]

TRAINING: dict = PARAMS["training"]

#: Predictors extracted per forecast. `historical_skill` is a site property and
#: is handled alongside them, not extracted per run.
PREDICTORS: tuple[str, ...] = (
    "ensemble_spread",
    "regime_change",
    "analogue_mismatch",
    "pressure_change",
    "forecast_persistence",
    "model_disagreement",
)

#: Display weights: each predictor's share of total absolute influence, derived
#: from the fit rather than asserted ahead of it.
_influence = sum(abs(c) for c in COEFFICIENTS.values()) or 1.0
WEIGHTS: dict[str, float] = {k: abs(v) / _influence for k, v in COEFFICIENTS.items()}

FEATURE_META: dict[str, dict[str, str]] = {
    "ensemble_spread": {
        "label": "Ensemble Spread",
        "description": "Disagreement between ensemble members at the selected lead time, "
        "measured against what is normal for that lead time. The strongest single "
        "predictor of a bust in the fitted model.",
    },
    "regime_change": {
        "label": "Atmospheric Regime Change",
        "description": "Strength of the large-scale pattern transition occurring inside "
        "the forecast window. Transitions are a classic source of medium-range failure.",
    },
    "analogue_mismatch": {
        "label": "Historical Analogue Mismatch",
        "description": "How poorly the current pattern matches historical situations with "
        "known outcomes. Contributes little in the fitted model - the demonstration "
        "analogue catalogue is not tied to the observed record.",
    },
    "pressure_change": {
        "label": "Rapid Pressure Change",
        "description": "Magnitude of the 24 h mean-sea-level-pressure tendency around the "
        "valid time. Fast-evolving systems are harder to time correctly.",
    },
    "forecast_persistence": {
        "label": "Forecast Persistence",
        "description": "Run-to-run jumpiness of the forecast for this valid time. A forecast "
        "that keeps changing between initialisations has not settled.",
    },
    "model_disagreement": {
        "label": "Model Disagreement",
        "description": "Spread between the ECMWF, NCMRWF-NCUM and GFS deterministic runs.",
    },
    "historical_skill": {
        "label": "Historical Skill",
        "description": "Long-run skill for this sub-division, derived from the real "
        "interannual variability of its rainfall in the IMD 1901-2017 record.",
    },
}


@dataclass(frozen=True)
class RiskAssessment:
    score: float  # 0-1 (index / 100)
    score_pct: float  # 0-100 risk index
    category: str
    forecast_confidence: float
    model_confidence: float
    features: dict[str, float]
    contributions: list[dict[str, object]]
    base_value: float
    #: The fitted bust probability behind the index.
    probability: float


def _sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0))))


def baseline_features() -> dict[str, float]:
    """E[x] over the training set - the SHAP base value reference."""
    return dict(FEATURE_MEANS)


def bust_probability(features: dict[str, float], historical_skill: float) -> float:
    """Fitted probability that this forecast busts."""
    values = {**features, "historical_skill": historical_skill}
    return _sigmoid(INTERCEPT + sum(COEFFICIENTS[k] * values[k] for k in COEFFICIENTS))


def predictor_label(name: str) -> str:
    from .predictors import PREDICTOR_META

    if name in PREDICTOR_META:
        return PREDICTOR_META[name][0]
    return FEATURE_META.get(name, {}).get("label", name.replace("_", " ").title())


def predictor_description(name: str) -> str:
    from .predictors import PREDICTOR_META

    if name in PREDICTOR_META:
        return PREDICTOR_META[name][1]
    return FEATURE_META.get(name, {}).get("description", "")


def to_index(probability: float, knots: list[float] | None = None) -> float:
    """Map a fitted probability onto the 0-100 AtmosGuard risk index.

    The bust base rate is around 16%, so the raw probability rarely exceeds 0.4
    and every forecast would sit in the LOW band. The index is the
    probability's **percentile across the monitored network**: a monotonic
    transform, so it cannot change the ranking or the ROC-AUC, but it gives the
    four bands their intended spread. What each band is worth in observed bust
    rate is measured and reported on the Verification page.
    """
    knots = knots or INDEX_KNOTS
    if probability <= knots[0]:
        return 0.0
    if probability >= knots[-1]:
        return 100.0
    hi = int(np.searchsorted(knots, probability, side="left"))
    lo = max(hi - 1, 0)
    span = knots[hi] - knots[lo]
    frac = (probability - knots[lo]) / span if span > 1e-12 else 0.0
    return float(min(100.0, max(0.0, lo + frac)))


def assess(
    features: dict[str, float],
    historical_skill: float,
    vector: dict[str, float] | None = None,
) -> RiskAssessment:
    """Score a forecast and produce additive attributions.

    With a full predictor vector and a trained model present, both come from
    that model - and for the gradient-boosted estimator the attributions are
    exact TreeSHAP. Without either, the logistic baseline handles it, so every
    caller works whether or not training has been run.
    """
    values = {**features, "historical_skill": historical_skill}
    trained = model_registry.load() if vector else None

    if trained is not None and vector:
        probability = trained.predict(vector)
        raw_contributions, _base = trained.contributions(vector)
        score_pct = round(to_index(probability, trained.registry.get("index_knots")), 1)
        contributions = [
            {
                "feature": name,
                "label": predictor_label(name),
                "description": predictor_description(name),
                "value": round(float(vector[name]), 4),
                "contribution": round(float(amount), 4),
                "direction": "increases" if amount >= 0 else "decreases",
            }
            for name, amount in raw_contributions.items()
            if abs(amount) > 1e-6
        ]
    else:
        probability = bust_probability(features, historical_skill)
        score_pct = round(to_index(probability), 1)
        contributions = [
            {
                "feature": name,
                "label": FEATURE_META[name]["label"],
                "description": FEATURE_META[name]["description"],
                "value": round(float(values[name]), 4),
                "contribution": round(float(coefficient * (values[name] - FEATURE_MEANS[name])), 4),
                "direction": "increases"
                if coefficient * (values[name] - FEATURE_MEANS[name]) >= 0
                else "decreases",
            }
            for name, coefficient in COEFFICIENTS.items()
        ]

    contributions.sort(key=lambda c: abs(float(c["contribution"])), reverse=True)

    base_probability = _sigmoid(
        INTERCEPT + sum(COEFFICIENTS[k] * FEATURE_MEANS[k] for k in COEFFICIENTS)
    )
    if trained is not None and vector:
        base_probability = float(trained.registry.get("training", {}).get("base_rate", base_probability))

    # Confidence in the assessment itself: high when the drivers agree with one
    # another and the index sits away from a band boundary. Deliberately
    # distinct from forecast confidence, which describes the weather forecast.
    coherence_keys = PREDICTORS if not (trained and vector) else (
        "ensemble_spread", "regime_change", "analogue_mismatch",
        "pressure_change", "forecast_persistence", "model_disagreement",
    )
    driver_values = np.array([values.get(k, 0.5) for k in coherence_keys])
    coherence = 1.0 - float(driver_values.std()) / 0.45
    edge_distance = min(abs(score_pct - b) for b in (30.5, 60.5, 80.5))
    decisiveness = min(edge_distance / 18.0, 1.0)
    model_confidence = float(np.clip(0.55 + 0.28 * coherence + 0.20 * decisiveness, 0.35, 0.97))

    return RiskAssessment(
        score=float(score_pct / 100.0),
        score_pct=score_pct,
        category=risk_category(score_pct),
        forecast_confidence=float(np.clip(1.0 - score_pct / 100.0, 0.0, 1.0)),
        model_confidence=model_confidence,
        features=values,
        contributions=contributions,
        base_value=float(base_probability),
        probability=float(probability),
    )


def narrative(
    assessment: RiskAssessment, location_name: str, horizon: int, variable_label: str
) -> str:
    """Plain-language explanation that tracks the actual top drivers."""
    positives = [c for c in assessment.contributions if float(c["contribution"]) > 0]
    negatives = [c for c in assessment.contributions if float(c["contribution"]) < 0]
    category = assessment.category

    if not positives:
        return (
            f"The Day {horizon} {variable_label.lower()} forecast for {location_name} is assessed "
            f"as {category} bust risk. Every monitored driver sits at or below its dataset "
            "average, with ensemble members clustering closely around the mean."
        )

    lead = {
        "LOW": f"The Day {horizon} {variable_label.lower()} forecast for {location_name} is "
        "currently assessed as low bust risk",
        "MODERATE": f"The Day {horizon} {variable_label.lower()} forecast for {location_name} "
        "carries a moderate risk of busting",
        "HIGH": f"The Day {horizon} {variable_label.lower()} forecast for {location_name} is "
        "flagged as high risk",
        "SEVERE": f"The Day {horizon} {variable_label.lower()} forecast for {location_name} is "
        "flagged as severe bust risk",
    }[category]

    detail = {
        "ensemble_spread": "ensemble members show unusually large disagreement for this lead time",
        "regime_change": "the large-scale atmospheric pattern is transitioning inside the "
        "forecast window",
        "analogue_mismatch": "the current pattern differs from the historical analogues on record",
        "pressure_change": "mean-sea-level pressure is changing rapidly around the valid time",
        "forecast_persistence": "the forecast for this valid time has been jumping between "
        "successive model runs",
        "model_disagreement": "the ECMWF, NCMRWF-NCUM and GFS runs disagree materially",
        "historical_skill": "this sub-division has low long-run medium-range skill",
    }
    reasons = "; ".join(
        detail[str(c["feature"])] for c in positives[:2] if str(c["feature"]) in detail
    )

    text = f"{lead}, primarily because {reasons}."
    if negatives:
        text += (
            f" Partially offsetting this, {str(negatives[0]['label']).lower()} is more favourable "
            "than the dataset average."
        )
    text += (
        f" Assessed forecast confidence is {assessment.forecast_confidence * 100:.0f}%; "
        f"confidence in this risk assessment is {assessment.model_confidence * 100:.0f}%."
    )
    return text


def model_card() -> dict[str, object]:
    trained = model_registry.card()
    if trained.get("trained"):
        return {
            "name": f"atmosguard-{trained['name']}",
            "version": "0.3.0",
            "kind": trained["kind"],
            "trained": True,
            "weights": trained["importances"],
            "predictors": trained["predictors"],
            "contribution_kind": trained["contribution_kind"],
            "comparison": trained["comparison"],
            "training": {
                **trained["training"],
                "roc_auc_holdout": trained["roc_auc_holdout"],
                "roc_auc_train": trained["roc_auc_train"],
                "roc_auc_ablated": trained.get("roc_auc_ablated"),
                "brier_holdout": trained["brier_holdout"],
            },
            "ablation_note": trained.get("ablation_note"),
            "explanation_method": trained["explanation_method"],
            "notice": "Gradient-boosted trees fitted on real IMD district rainfall "
            "observations, selected over a random forest and a logistic regression on "
            "held-out ROC-AUC with a temporal split. Attributions are exact TreeSHAP. "
            "Ensemble fields are reconstructed, not live NWP output - see the System page.",
        }
    return {
        "name": MODEL_NAME,
        "version": MODEL_VERSION,
        "kind": "logistic-regression",
        "trained": True,
        "weights": WEIGHTS,
        "coefficients": COEFFICIENTS,
        "intercept": INTERCEPT,
        "training": TRAINING,
        "explanation_method": "exact additive attribution in log-odds "
        "(Shapley values for a model linear in the logit)",
        "notice": "Fitted by logistic regression on real IMD district rainfall observations "
        "with a temporal train/test split; the reported ROC-AUC is held out. Ensemble "
        "fields are reconstructed around the real observed outcome, not archived NWP "
        "output - see the System page.",
    }


def location_skill(location_id: str, variable_id: str) -> float:
    """Long-run skill for a site and variable, 0-1.

    The site term comes from the real IMD interannual record; the variable term
    reflects that rainfall is far harder to predict at medium range than MSLP.
    """
    site = ALL_SITES_BY_ID[location_id]
    variable = VARIABLES_BY_ID[variable_id]
    factor = 1.25 - 0.55 * variable.predictability_penalty
    return float(np.clip(site.historical_skill * factor, 0.05, 0.95))
