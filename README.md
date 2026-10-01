# AtmosGuard

**Reads the forecast before it fails.**

AtmosGuard is an AI-based **forecast bust risk and early-warning system** for
medium-range (Day 3–7) weather forecasts. It does not forecast the weather. It
assesses how likely an existing forecast is to be *wrong*, explains why, and
raises the flag before the event — so a forecaster can shift weight onto
ensemble and short-range guidance while there is still time to act.

> AtmosGuard is an experimental AI-based decision-support system. It does not
> replace official forecasts or warnings issued by authorized meteorological
> agencies.

---

## The problem

A Day 5 rainfall forecast can look perfectly confident and still be badly wrong.
Forecast busts are usually recognised *after* the event, when the damage to
planning decisions is already done. The information needed to anticipate them —
ensemble disagreement, a regime transition inside the forecast window, models
that cannot agree, a forecast that keeps jumping between runs — is present in
the data days beforehand, but scattered across products nobody reads together.

AtmosGuard pulls those signals into one number, explains what drove it, and
tracks how it evolves as the event approaches.

---

## Quick start

Two commands. The backend serves the built UI, so the demo runs from a single
process on <http://127.0.0.1:8000>.

```bash
make install     # Python venv + npm install
make demo        # build the UI, then serve API + UI on :8000
```

Or without `make`:

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
npm --prefix frontend install && npm --prefix frontend run build
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8000
```

On **Windows** (PowerShell), with Python 3.11+ and Node 18+ installed:

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt
npm --prefix frontend install
npm --prefix frontend run build
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Then open <http://127.0.0.1:8000>. Checked from a clean virtualenv and a clean
`npm ci`: the full test suite passes and the UI builds.

For frontend development with hot reload, run the API and Vite separately:

```bash
make dev-api     # FastAPI on :8000
make dev-ui      # Vite on :5173, proxying /api to :8000
```

To produce a **single self-contained HTML file** — the whole dashboard with the
API responses baked in, no backend required:

```bash
make static      # -> frontend/atmosguard-static.html
```

The client serves from the embedded snapshot when one is present and falls back
to the live API when it is not, so the same build works both ways. Coverage is
scoped deliberately: every site for rainfall across all lead times, plus the
other variables and models for the ten featured cities. Combinations outside
that set say so rather than failing silently.

**What you should see on first load:** the flagship case — Jaipur, Day 5
rainfall from the 26 August 2026 run, a **65.8 HIGH** bust-risk index. That
forecast was valid on 31 August, when IMD recorded **0.0 mm against a daily
normal of 2.9 mm**.

---

## The demo in 60 seconds

1. The dashboard opens on the national risk map with **Jaipur selected**.
2. The gauge reads **70% — HIGH RISK**, forecast confidence 30%.
3. **"Why is this forecast at risk?"** ranks the drivers: atmospheric regime
   change, ensemble spread, historical analogue mismatch.
4. The **ensemble chart** shows 42 members fanning apart, with spread measured
   against what is normal for that lead time.
5. **Historical analogues** surface past situations with the same pattern, and
   whether their forecasts busted.
6. The **risk escalation timeline** shows successive model runs for the same
   valid date: risk rising as the event approaches.
7. Change **location, lead time, variable or model** — every panel re-derives.

`Demo Mode` (top right) offers curated cases covering every band, from a
low-risk settled pattern to the dataset's most extreme bust.

---

## The data

Two published IMD datasets sit underneath the system.

| Dataset | Size | What it provides |
|---|---|---|
| **IMD sub-division monthly rainfall, 1901–2017** | 36 sub-divisions × 117 years | Real rainfall climatology, and the real *interannual variability* of each region |
| **IMD district-wise daily rainfall** | 16,001 district-days, 728 districts | Real observed rainfall against IMD's own daily normal, with departure categories |

Nothing about a site is hand-tuned any more. Its rainfall climatology, its
long-run skill and its convective character are all **measured** from the
1901–2017 record. That matters because the model weights those quantities — if
they were invented, the ranking they produce would be too. The measured values
are also meteorologically recognisable: Konkan sits at 28.4 mm/day in peak
monsoon while Chennai sits at 2.7 mm/day (its rain is the north-east monsoon,
not the south-west), and West Rajasthan's interannual CV of 0.37 against
Kerala's 0.15 is exactly the predictability gap a forecaster would expect.

**What is not real:** NWP ensemble members. No agency publishes archived
ensembles as CSV. So the ensemble is *reconstructed* around the real observed
outcome — it starts near the truth and reverts toward climatology in proportion
to lead time, regime transition strength and the site's measured skill. Every
API response says which is which, and the UI labels the two separately in its
header rather than calling everything "simulated" or implying it is all
measured.

## Climate context

Beyond the forecast itself, the dashboard reads the 117-year sub-division
record: the trend, the spread of past outcomes, and how often each IMD rainfall
category has actually occurred. A single forecast is only unusual relative to
that background.

Trends use **Mann-Kendall with Sen's slope**, not least squares. Rainfall series
are skewed and occasionally carry a monster year; a least-squares slope is
dragged around by those years while a rank-based test and a median-of-pairwise-
slopes estimator are not. Categories are **IMD's own** (Excess >= +20%, Normal
+/-19%, Deficient -20% to -59%, Scanty -60% to -99%), so every figure can be
checked against IMD's published statistics.

What it finds is consistent with the published literature: Kerala's monsoon is
declining at 24.9 mm/decade (p = 0.013) and Jharkhand's at 12.4 mm/decade
(p = 0.010), while East Rajasthan and Vidarbha show no significant trend.

## Data sources

Thirteen official sources are catalogued in **[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)**
with portal, licence, access route and what each would feed. The System page in
the app shows the same catalogue.

The status column is the point: **two datasets are in use** — the ones actually
in this repository — and the rest are documented routes, not live connections.

```bash
python -m app.ingest.download --list          # the catalogue
python -m app.ingest.download --source <id>   # fetch, or print how to
```

`app/ingest/` holds working clients for the **data.gov.in** API and **ECMWF open
data** (the free 51-member ensemble that would remove this system's last
modelled component). Their parsing and pagination are unit-tested against
fixtures; the HTTP calls themselves are not, because they were written where
egress to those hosts is blocked. Treat the first live run as the test.

## How the risk score works

### Predictors

Weights are **fitted**, not asserted. The MVP began with hand-set physical
priors; measured against the real IMD record they did not survive contact —
the heaviest-weighted predictor correlated 0.06 with actual busts and the
analogue term 0.00, and the resulting ranking scored ROC-AUC 0.57, barely
better than chance. Estimating them from the data is what makes the score mean
anything.

| Predictor | Fitted coefficient | What it measures |
|---|---:|---|
| Ensemble spread | **+4.14** | Member disagreement **relative to the climatological spread for that lead time** |
| Model disagreement | +3.00 | Spread between the ECMWF, NCUM and GFS deterministic runs |
| Forecast persistence | +1.97 | Run-to-run jumpiness for the same valid time |
| Atmospheric regime change | +0.89 | Strength of the pattern transition inside the forecast window |
| Rapid pressure change | +0.50 | 24 h MSLP tendency around the valid time |
| Historical analogue mismatch | −0.23 | Contributes little — the demonstration catalogue is not tied to the observed record |
| Historical skill | +0.19 | Long-run skill, from real interannual variability |

The fit puts ensemble spread on top, which is what the meteorology says it
should be. That agreement is asserted as a test (`test_ensemble_spread_is_the_dominant_predictor`),
because when a stale spread climatology once saturated that feature, the fit
quietly demoted it and held-out AUC fell from 0.80 to 0.60.

The single most important design choice is that spread is a **anomaly**, not a
raw number. "Is the Day 5 spread large?" is unanswerable without knowing what
Day 5 spread normally looks like. A Day 3 forecast still carrying Day 6 levels
of disagreement is a red flag even though its absolute spread is unremarkable —
and that is precisely what makes the risk *escalate* as a failing forecast
approaches its valid time.

### The estimator

**Gradient-boosted trees (XGBoost), fitted on real IMD observations.**
`scripts/train_models.py` fits three estimators on the same data and judges them
the same way, on a temporal hold-out:

| Model | Train | **Held out** | Brier |
|---|---:|---:|---:|
| **XGBoost** | 0.973 | **0.911** | 0.094 |
| Logistic regression | 0.896 | 0.900 | 0.105 |
| Random forest | 0.949 | 0.898 | 0.112 |

**Read 0.911 with its caveat.** The ensemble is reconstructed around the real
observed outcome, so predictors derived from it carry some information about
that outcome. Training measures the effect rather than asserting it: refitting
without the twelve ensemble-derived predictors gives **0.710**. The ceiling is
0.911, the floor is 0.710, and archived NWP would land between them. Quote the
range.

Selection favours the simpler model on ties: a tree ensemble must beat the
logistic by a real margin to be chosen, because below that the extra opacity is
not worth it. XGBoost is picked here, and **its attributions are exact
TreeSHAP** — the real Shapley values for the model that made the prediction, not
an importance ranking standing in for one. A test asserts the additivity
guarantee.

Widening the predictor set from 7 to 28 moved held-out AUC from 0.702 to 0.911 —
far more than any hyperparameter tuning did. Full details, including how to add
your own predictors, are in **[docs/ML_MODEL.md](docs/ML_MODEL.md)**.

### The previous baseline

A **logistic regression fitted on real IMD observations** (`scripts/fit_model.py`),
kept linear in the log-odds for two reasons:

- For such a model the Shapley value of predictor *i* is exactly
  `cᵢ · (xᵢ − E[xᵢ])`. The contributions in the explanation panel are therefore
  **real additive attributions** — the same quantity SHAP reports for a logistic
  model — not a SHAP-shaped decoration.
- Seven parameters cannot overfit thousands of rows, so the held-out score is
  trustworthy rather than a story about capacity.

Evaluation uses a **temporal** split: earlier valid dates train, later ones
test. A random split would leak, because neighbouring days share a weather
system, and the held-out score would flatter the model while meaning nothing
operationally — in deployment the future is always unseen.

`app/core/model_params.json` holds the fit, so swapping in a gradient-boosted
model with `shap.TreeExplainer` changes one file and no API contract.

### The score is an index, not a probability

A score of 79 does **not** mean "79% of such forecasts bust". It is a
calibrated 0–100 risk **index**. What the bands mean is measured empirically and
shown on the Verification page:

| Band | Score | Share of forecasts | **Observed bust rate** |
|---|---|---:|---:|
| LOW | 0–30 | 30% | **3.1%** |
| MODERATE | 31–60 | 29% | **11.9%** |
| HIGH | 61–80 | 20% | **24.5%** |
| SEVERE | 81–100 | 20% | **39.0%** |

A forecast scored SEVERE busts about **13× more often** than one scored LOW,
measured against real IMD observations. That monotonic separation — not a
literal probability reading — is what a forecaster acts on, and it is why
ROC-AUC is the headline metric.

Concretely, the index is the **percentile of the fitted bust probability across
the monitored network**. A monotonic transform cannot change the ranking or the
ROC-AUC, but it stops a ~17% base rate from collapsing every forecast into the
LOW band.

---

## Verification

Every number on the Verification page is **computed from the dataset at request
time**. None are hard-coded.

| Metric | Value |
|---|---:|
| **ROC-AUC (held out, temporal split)** | **0.911** |
| ROC-AUC (ablated — no ensemble predictors) | 0.710 |
| ROC-AUC (train) | 0.973 |
| Brier score | 0.258 |
| Precision @ threshold | 0.32 |
| Recall @ threshold | 0.72 |
| F1 | 0.44 |
| Bust base rate | 17.4% |
| Sample size | 1,596 forecasts |

Forecast skill and anomaly correlation are measured against **IMD's published
daily normals**, not a mean estimated from the verification window — a
climatology estimated from the same fortnight it scores is both biased and
unstable, and fixing it moved Jaipur's Day-5 rainfall skill from −0.01 to 0.48.

A bust is an error larger than the routine error for that lead time **at that
site**. Normalising per site matters: judged against one national threshold,
"bust" became a proxy for "rainy", and the fit duly learned that high-skill wet
regions bust more — the opposite of the truth.

Forecast verification (the other question — how did the *weather* forecast do?)
is reported separately as RMSE, MAE, bias, anomaly correlation and skill against
climatology.

---

## Historical replay

A separate page, and a separate model, answering a separate question: pick a
past date, form predictions from everything known up to it, then check them
against what the IMD record says actually happened.

It needed to be separate because the operational risk score above is built on
the reconstructed ensemble, and that reconstruction is anchored to the
observation it is later verified against. That is legitimate for a live
demonstration — it is what makes the demo's ensemble spread genuinely
informative — and it is invalid as a backtest, because the features already
contain the answer. So the replay uses 21 predictors that touch none of it:
antecedent rainfall, wet and dry spells, the state's field at the origin, and
the sub-division's long-record climatology, variability and trend.

The no-leakage rule is enforced structurally rather than by convention:

```python
archive  = Archive(origin=T)     # prediction phase.  Raises past T.
outcomes = Outcomes(origin=T)    # validation phase.  Raises at or before T.
```

Neither type can do the other's job, and `generate_prediction()` completes and
freezes its output before `validate_prediction_against_actual()` runs.

| Metric | Value |
|---|---:|
| **ROC-AUC (held-out origins)** | **0.682** |
| ROC-AUC (walk-forward, out-of-sample) | 0.650 |
| ROC-AUC (walk-forward, all origins) | 0.725 |
| ROC-AUC (training origins) | 0.813 |
| Brier score (held out) | 0.154 |
| Base rate | 16.5% |
| Skill by lead, D1 → D7 | 0.831 → 0.581 |

Unimpressive numbers, and that is the point — they are what a leak-free
backtest of a genuinely hard problem looks like. The lead-time decay is the
most reassuring line in the table: predictability really does fall away with
range, and a model scoring 0.83 at Day 7 as well as Day 1 would be reading the
answer.

**Two modes, never conflated.** Mode A — validating a real archived forecast
against what happened — is **unavailable**, because no hindcast archive exists
here and one cannot be reconstructed from observations without inventing it.
Mode B, the historical weather risk proxy that does run, predicts an *observed*
IMD Large Excess day and is never described as a forecast bust.

**Two datasets are missing, and both have an interface rather than a
substitute.** The daily record spans 22 days, so every origin outside it —
including 05-Sep-2016 — reports as unverifiable;
`scripts/import_imd_daily_rainfall.py` accepts a published daily file and
refuses to fill a gap. `core/hindcast.py` defines the hindcast manifest
contract and names the archives (TIGGE, ECMWF reforecasts, NCMRWF NEPS) that
hold what Mode A needs.

### 7-day station replay, 2010-2021

Pick any date from 2010 to 2021 and one of 28 Indian stations. Using only
observations up to that date, the system forecasts the next seven days - max
and min temperature, chance of rain - and the probability each day's forecast
will bust. Then it scores itself against the real
[NOAA GHCN-Daily](https://registry.opendata.aws/noaa-ghcn/) observations for
those seven days.

Fitted on 1995-2009; **every day of 2010-2021 is held out** - 858,284
forecasts the model never saw. The published preview can replay every one of
those dates; `make parity` proves its output equals the live API.

| | Model | Normal only |
|---|---:|---:|
| Max temp error | **1.29 C** | 1.61 C |
| Max temp within IMD's +/-2 C | **79.5%** | |
| Rain / no-rain correct | **64.0%** | 62.5% |
| Bust ROC-AUC | **0.718** | |

At Day 1 the forecast ties "tomorrow is like today"; from Day 2 it beats it,
by 0.38 C at Day 7. Rain a week out is barely better than the calendar, and the
page says so. The forecast is statistical, not NWP - no archived NWP exists
here - and every payload says that too.

### Monthly replay, 1901-2017

The daily archive is 22 days, so anything before it can only be replayed at the
resolution the record actually has. The sub-division file holds **one figure per
sub-division per month** - August 2015 in Vidarbha is a single number, 288.9 mm -
so a second replay predicts a whole calendar month from everything known up to
the month before, and checks it against what IMD recorded. No daily value is
ever derived from a monthly total.

Train 1935-2009; **2010-2017 held out as a block**, 2,454 sub-division-months
the model never saw. Three targets, because "extreme" without a direction is
not a claim anyone can check:

| Target | AUC train | **AUC 2010-17** | Base rate |
|---|---:|---:|---:|
| Extreme (either side) | 0.640 | **0.644** | 0.240 |
| Dry extreme | 0.723 | **0.721** | 0.120 |
| Wet extreme | 0.590 | **0.587** | 0.121 |

Train and held-out agree to within 0.004 on every target - no overfitting, just
a genuinely hard problem. The split between dry and wet is the real finding:
droughts are slow persistent regimes and are forecastable a month out, while a
flood that delivers a month's rain in three days leaves almost nothing in the
preceding month to see. Sep 2014 in Jammu & Kashmir (+319%) and Jun 2013 in
Uttarakhand (+205%) are both **misses**; Jul 2015 in Marathwada (-85%) is a
hit. That is what the AUC table says should happen.

The climatology is an expanding window - for a target in year Y it uses only
years before Y - so no held-out year informs its own baseline.

Full detail in **[docs/HISTORICAL_REPLAY.md](docs/HISTORICAL_REPLAY.md)**.

---

## The ensemble reconstruction

The one component that is not measured. Its construction matters, because a
careless version makes every number downstream meaningless — and the first
version did.

Generating the forecast from climatology alone scored **ROC-AUC 0.466 against
real observations**: worse than random, because nothing in the forecast knew
what the weather actually did. So the forecast is reconstructed around the real
outcome instead:

```
real IMD observation for the valid date
   → forecast starts near it, reverts toward climatology in proportion to
     lead time, regime-transition strength and the site's measured skill
   → ensemble members perturbed around that, with spread tied to the same
     reversion — a forecast that has reverted *is* an uncertain forecast
   → spread, model disagreement, persistence → the risk score
   → verified against the real observation
```

Busts then arise where a forecaster would expect them — long leads, unsettled
patterns, low-skill regions — and the spread that flags them is genuinely
informative about the real error.

Two further properties matter:

- **The atmosphere evolves in absolute time.** Weather systems are anchored to
  real dates, so successive model runs observe the *same* system at different
  lead times. Without this the escalation timeline is noise.
- **Error scales are calibrated** against the real record, so a Day-5 error
  lands where medium-range forecasts land. Run `python -m scripts.calibrate`
  after any change to the reconstruction, or the bust threshold drifts and the
  base rate collapses.

Swapping in archived NWP means replacing `app/core/synthetic.py` with an
xarray/NetCDF reader returning the same dataclasses. Nothing downstream changes.

---

## Architecture

```
backend/
  app/
    config.py            environment + data-mode switch
    schemas.py           API contract (Pydantic)
    api/routes.py        HTTP layer - thin adapters
    core/
      domain.py          locations, regions, variables, models, risk bands
      rng.py             deterministic seeded randomness
      imd.py             real IMD datasets: climatology + observations
      climate.py         Mann-Kendall trends, IMD categories, decadal record
      predictors.py      the 28-predictor vector for the trained models
      model_registry.py  loads the selected model, exact TreeSHAP attributions
      warnings.py        state-level warning levels for the warning map
      synthetic.py       ensemble reconstruction  <- replace for archived NWP
      features.py        raw fields -> model inputs
      risk_model.py      baseline estimator + attributions
      analogues.py       historical analogue search
      verification.py    forecast + risk-model metrics
      alerts.py          alert engine, timelines, network scan
      scenarios.py       curated Demo Mode cases
      service.py         response assembly
    db/
      schema.sql         PostgreSQL/SQLite-portable schema
      schema_timescale.sql   hypertables + retention
      seed.py            writes the demo dataset through the schema
    ingest/
      sources.py         catalogue of 13 official data sources
      datagov.py         data.gov.in API client
      ecmwf_open.py      ECMWF open ensemble fetcher
      download.py        download CLI
  tests/                 148 tests
  scripts/
    fit_model.py         fits the risk model on real observations
    calibrate.py         re-measures error scales
    export_snapshot.py   exports API responses for a static build
frontend/
  src/
    api/                 typed client + response types
    state/AppState.tsx   the single shared selection
    components/          RiskGauge, RiskMap, EnsembleSpreadChart, ...
    pages/               Dashboard, Analysis, Map, Alerts, Verification, ...
```

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/meta` | Locations, variables, models, bands, scenarios |
| `GET /api/risk` | Full assessment: score, contributions, ensemble, analogues, verification |
| `GET /api/network` | Risk across all monitored sites (map + KPIs) |
| `GET /api/alerts` | Active early warnings |
| `GET /api/scenario/{id}` | A curated Demo Mode case |
| `GET /api/verification/model` | Risk-model performance |
| `GET /api/verification/forecast` | Forecast-vs-observation for one site |
| `GET /api/climate/{location}` | 117-year climate context: trend, categories, decades |
| `GET /api/sources` | The catalogued data sources with references |
| `GET /api/system/status` | Data sources and pipeline state |
| `GET /api/replay/origins` | Origin dates the observational archive supports |
| `GET /api/replay/availability` | Mode A / Mode B availability, with reasons |
| `GET /api/replay/run` | A 7-day replay: predictions, validations, audit log |
| `GET /api/replay/backtest` | Walk-forward skill, in-sample and out-of-sample |
| `GET /api/replay/model` | Replay model card and leakage controls |
| `GET /api/replay/requirements` | What a genuine Mode A validation would need |
| `GET /api/monthly/meta` | Sub-divisions, record span, resolution notice |
| `GET /api/monthly/replay` | Predict and verify the month containing a date |
| `GET /api/monthly/model` | Monthly model card, three targets |
| `GET /api/stations/meta` | 28 NOAA stations, date range, held-out record |
| `GET /api/stations/replay` | 7-day forecast from any 2010-2021 date, then verification |
| `GET /api/stations/model` | Station forecast + bust model card |

Interactive docs at `/docs` when the server is running.

### Database

`schema.sql` runs unchanged on PostgreSQL and SQLite (no `SERIAL`, no `JSONB`,
no arrays; the app supplies surrogate keys). TimescaleDB hypertables and
retention policies are isolated in `schema_timescale.sql`.

```bash
cd backend && ../.venv/bin/python -m app.db.seed --days 7
```

---

## Design notes

**Risk colours are a status palette, not a categorical one.** Green→red is an
ordered severity scale that no single-hue ramp can express, and it is the
convention operational forecasters already read. Those hues are *not*
colour-vision-safe against each other (green vs red is ~4 ΔE under
deuteranopia), so colour never carries the meaning alone: every risk colour
appears with its category label, and on the map risk is redundantly encoded by
**marker radius**.

**Chart series** use a blue/aqua pair validated against the panel surface
(worst-pair CVD ΔE 19.6, normal-vision ΔE 20.9 — clear of every gate).
Observations are truth rather than a model, so they wear ink and a dashed
stroke instead of a series hue. Ensemble members are not categorical series —
which member is which carries no meaning — so they share one recessive hue at
low opacity and appear in no legend.

**The map is vector, not tiles.** India is drawn from real boundary geometry
bundled with the app — 36 states and union territories, simplified from
DataMeet's CC BY 4.0 shapefile (1.07 M vertices down to ~8,100, 129 KB). It
needs no tile CDN, which matters for an operations room behind a restrictive
policy, and at national scale it reads better than raster tiles: street detail
is noise when the marks are sub-divisional risk scores. Tile layers remain as an
option for terrain context.

DataMeet was chosen over the several unlicensed India GeoJSON repositories in
circulation — those carry no rights grant at all, and some explicitly disclaim
accuracy. It is a cartographic aid for locating forecast points, not an
authoritative boundary: official boundaries of India are published by the
Survey of India.

---

## Tests

```bash
make test    # or: cd backend && ../.venv/bin/python -m pytest tests/ -q
```

300 tests covering risk-band boundaries (including the off-by-one gap that made
a score of 60.6 read as LOW), attribution additivity against the closed-form
Shapley values, physical plausibility (rainfall and wind never negative,
spread grows with lead time), temporal coherence of the latent atmosphere,
metric implementations against known cases, Demo Mode band guarantees, and the
full API contract. Several encode bugs this project actually hit: the spread
climatology sampled outside the observation window (which saturated the
strongest predictor), verification running past the end of the real record, and
network-wide error magnitudes asserted network-wide rather than at one site,
where a two-week sample is far too small to pin an RMSE to.

`tests/test_replay.py`, `tests/test_monthly.py` and `tests/test_station_replay.py`
carry 62 of those, and most of them guard one property: that the prediction
phase cannot read the outcome. The strongest overwrites every observation after
the forecast date with 999 and checks that nothing at the forecast date moves. The guards are
asserted directly — a read past the origin must raise, a read at or before it
must raise, two leads from one origin must share every non-calendar predictor,
and the prediction phase must never construct an outcomes reader at all.

`tests/test_scenarios.py` is the guard rail that matters for a live demo: if a
retune moves a curated scenario out of its intended band, the build fails
instead of the demo quietly telling the wrong story.

---

## Roadmap

- Replace the ensemble reconstruction with archived ECMWF / NCMRWF-NCUM / GFS
  ensembles (xarray + NetCDF/GRIB). This is the single change that would most
  improve the held-out score, because it removes the only modelled component.
- Extend beyond rainfall. The model is fitted on rainfall observations only and
  the alert engine is scoped to match; temperature, wind and pressure need
  their own observed records before they can be alerted on.
- Swap the logistic fit for gradient boosting with `shap.TreeExplainer` behind
  the existing explanation seam, once there is more than a 22-day observation
  window to train on.
- Replace the analogue catalogue with nearest-neighbour retrieval over a
  reanalysis archive (500 hPa geopotential, 850 hPa winds, IWV, MSLP).
- Spatial bust risk on the model grid rather than at point locations.
- Alert delivery and acknowledgement workflow with an audit trail.

---

## Not what this is

- **Not a weather warning service.** High bust risk means the forecast may be
  wrong. It says nothing about whether the weather will be severe.
- **Not a forecast.** AtmosGuard produces no prediction of its own.
- **Not a replacement for a meteorological agency.** It is decision support for
  the people who issue official forecasts and warnings.
