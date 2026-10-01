# The risk model — how to train it, and how to extend it

AtmosGuard scores forecast bust risk with a model fitted on real IMD district
rainfall observations. This document covers running the training, reading the
result, and adding predictors of your own.

## Quick start

```bash
make fit            # or: cd backend && python -m scripts.train_models
```

That builds the dataset, fits three estimators, compares them on a held-out
split, saves all three and records the winner. It takes about a minute.

```
  4,180 forecasts x 28 predictors, bust rate 0.163
  temporal split: 2,850 train / 1,330 held out

model              train  held out    Brier
xgboost            0.973     0.911    0.094
logistic           0.896     0.900    0.105
random_forest      0.949     0.898    0.112

xgboost beats logistic by +0.011 - selected.

ablation (no ensemble-derived predictors): held-out 0.710
```

The app picks the selected model up automatically on the next request — there
is nothing else to wire.

To train a single estimator: `python -m scripts.train_models --model random_forest`.

## What is being predicted

A **bust**: a forecast whose error exceeds the routine error for that lead time
*at that site*. Site-relative matters — judged against one national threshold,
"bust" becomes a proxy for "rainy", and the model duly learns that wet regions
bust more, which is the opposite of the truth.

The label comes from real IMD observations. The base rate is about 17%.

## The three estimators

| | What it is | Why it's here |
|---|---|---|
| **Logistic regression** | Linear in the log-odds, standardised inputs | The incumbent, and the bar. Its Shapley values have a closed form, so it is fully explainable by construction. |
| **Random forest** | 400 bagged trees, depth 6 | Captures interactions a linear model cannot, and is hard to overfit. But gives no *signed* per-prediction attribution. |
| **XGBoost** | 160 boosted stumps, depth 3, heavy regularisation | Usually strongest on tabular data this size — and it computes **exact TreeSHAP** internally, so it costs nothing in explainability. |

Selection is on held-out ROC-AUC, with a deliberate tie-break toward the simpler
model: a tree ensemble must beat the logistic by at least `MIN_GAIN` (0.01) to
be chosen. Below that the extra opacity is not worth it.

## Why the split is temporal, not random

Earlier valid dates train; later ones test. This is not a style preference.

Neighbouring days share a weather system, so a **shuffled** split puts
near-duplicates of training rows into the test set. Every model then looks
excellent and the number means nothing operationally, where the future is
always unseen. If you change `TRAIN_FRACTION`, keep the split temporal.

## Reading the output

Watch the **train vs held-out gap**, not just the held-out score.

An earlier XGBoost configuration (350 trees, depth 4) reached a training AUC of
**1.000** — it had memorised the training weeks outright. Held-out barely moved,
which is the tell that the extra capacity was fitting noise. The current
configuration is deliberately small: 160 shallow stumps, `min_child_weight=14`,
`reg_lambda=6`, `gamma=0.5`.

If you raise capacity and the held-out score does not move, put it back.

## The predictors

Twenty-eight, in `app/core/predictors.py`, in five groups:

- **Ensemble shape** — spread, spread anomaly, spread growth between lead times,
  skew, interquartile ratio, member range, share of members above IMD's
  heavy-rain threshold, deterministic-to-mean offset.
- **Synoptic state** — regime change, transition proximity, pressure tendency,
  synoptic forcing, moisture anomaly.
- **Agreement** — between NWP centres, between successive runs, and against
  historical analogues.
- **Climatology** — the site's real IMD normal for the month, interannual
  variability, monsoon concentration, long-record trend, convective character,
  forecast anomaly against normal, three-day accumulation.
- **Season and lead** — lead time, and day-of-year as a sine/cosine pair so a
  tree can split on season without a discontinuity at New Year.

The top of the fitted importance list is `forecast_anomaly`, `spread_anomaly`,
`regime_change`, `model_disagreement` and `spread_growth` — which is roughly
what the meteorology would predict, and a useful sanity check.

## Adding a predictor

1. Compute it in `build_vector()` in `app/core/predictors.py`.
2. Add its name to `PREDICTOR_NAMES` — **order is the model's column order**, so
   append rather than insert.
3. Add a label and one-line description to `PREDICTOR_META`; the explanation
   panel reads them.
4. Retrain: `make fit`.

Two rules that are load-bearing:

**Clip every ratio.** `spread_growth` once reached 28 because the Day-3 spread
was near zero. That is a measurement artefact, not a signal, and a tree will
happily split on it. `tests/test_ml.py` asserts the bounds.

**Never let a value go non-finite.** A single NaN poisons a whole ensemble's
prediction. There is a test that sweeps the network for this.

The registry records the predictor list it was trained on, and
`model_registry.load()` refuses a model whose list no longer matches. Scoring a
model against reordered columns produces plausible nonsense, which is the worst
failure mode available here — so the mismatch is a hard stop rather than a
warning.

## Explainability

For XGBoost the explanation panel shows **exact TreeSHAP** values, obtained from
`pred_contribs=True`. These are the real Shapley values for the model that made
the prediction, not an importance ranking standing in for one.
`tests/test_ml.py` asserts the additivity guarantee: base value plus
contributions, through the link function, must reproduce the model's own output.

A random forest has no equivalent. If one is ever selected, attributions fall
back to global importances and `contribution_kind` reports `importance`, so the
UI does not imply a precision it does not have.

## Read the headline score with this

Held-out AUC is **0.911**. Do not take that at face value.

The ensemble here is *reconstructed around the real observed outcome*, so
anything derived from it carries some information about that outcome by
construction. `forecast_anomaly` is the clearest case: it is the forecast
against normal, and the forecast is a blend containing the truth. With archived
NWP that link would be far weaker, because a real forecast is made without
knowing what happens.

Training measures this rather than asserting it. Every run refits the selected
model with the twelve ensemble-derived predictors removed:

| | Held-out AUC |
|---|---:|
| All 28 predictors | **0.911** ← optimistic ceiling |
| Ensemble-derived dropped (16 predictors) | **0.710** ← floor |

A production system on archived NWP would land between those two. Quote the
range, not the ceiling.

Run the ablation yourself with `python -m scripts.train_models --ablate`.

Two further limits worth stating:

- The observation window is **22 days**, so the held-out set is small and the
  number carries real uncertainty either way.
- With a window that short, the demo's reference date sits *inside* the training
  period. In production the displayed forecast would post-date all training
  data.

The binding constraint is not the estimator — it is the reconstructed ensemble.
Real ensemble members would do more for this score than any amount of
hyperparameter tuning. See [DATA_SOURCES.md](DATA_SOURCES.md) for the two routes
to them.
