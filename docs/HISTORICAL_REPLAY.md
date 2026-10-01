# Historical Replay and Validation

Three replays, because the data in this repository comes at three
resolutions:

| | **7-day station replay** | Daily validation | Monthly replay |
|---|---|---|---|
| Source | **NOAA GHCN-Daily**, 28 Indian stations | IMD district daily rainfall | IMD sub-division monthly |
| Covers | **1995 → 2021, daily** | 2026-08-19 → 2026-09-09 | 1901 → 2017 |
| Pick | **any date 2010–2021** | an origin in the 22 days | any month 2010–2017 |
| Forecast | max/min temp + rain, **T+1 … T+7** | rain event, T+1 … T+7 | whole month |
| Held out | **2010–2021, entirely** | 4 origins | 2010–2017 |
| Test cases | **858,284** | 1,064 | 2,454 |

The monthly replay stops at 2017 because the IMD sub-division file does.

To pick a date like 17 August 2015 and see the week that followed, use the
**[7-day station replay](#7-day-station-replay-20102017)**.

---

## Daily replay

Pick a past date, form predictions from everything known up to it, then check
them against what the IMD record says actually happened.

This document covers what the replay does, what it deliberately refuses to do,
and what data would be needed to make it do more.

---

## Two modes, kept apart

### Mode A — forecast-bust validation

The real thing. Take an archived NWP forecast initialised on or before the
origin date, compare it with the observation, and label the cases where the
forecast failed.

**Status: unavailable.** No hindcast archive exists in this repository. A
forecast bust needs the forecast that busted, and it cannot be reconstructed
from observations without inventing it. `/api/replay/availability` reports this
for every origin, together with the archives that do hold the required data
(TIGGE, ECMWF reforecasts, NCMRWF NEPS) and how to obtain them.

Mode A is never simulated, approximated or stood in for.

### Mode B — historical weather risk proxy

What actually runs. From information available at the origin date only,
estimate the probability that a site records an **IMD Large Excess** rainfall
day at T+1 … T+7, then check that against the published observation.

This is a real, verifiable, leak-free prediction about the weather. It is
**not** a forecast bust, and nothing in the code, the API or the UI calls it
one.

The event is IMD's own published departure category — observed rainfall at
least 60% above the published daily normal — taken from the `Daily Category`
column of the district daily file. It is not a label this system invented.

---

## The no-leakage rule, and how it is enforced

For an origin date T, a prediction may use only data dated on or before T.
Anything valid at T+1 or later is the answer.

Convention does not survive contact with a codebase, so the rule is
structural rather than documentary:

```python
archive  = Archive(origin=T)     # prediction phase.  Raises past T.
outcomes = Outcomes(origin=T)    # validation phase.  Raises at or before T.
```

`Archive` physically refuses a read beyond its origin and raises
`LeakageError`. `Outcomes` refuses a read at or before it. Neither type can do
the other's job — `Outcomes` has no feature-building methods at all — and the
two phases are separate functions:

```python
generate_prediction(origin, location_id, lead)     # phase 1
validate_prediction_against_actual(prediction)     # phase 2
```

Phase 1 completes before phase 2 begins, and its output is a frozen dataclass,
so even if the validation loop wanted to influence a prediction it could not.
`tests/test_replay.py` asserts both guards directly, including that phase 1
never constructs an `Outcomes` reader.

### Why this needed its own predictor set

The operational bust-risk model (`core/predictors.py`, 28 predictors) is built
on the reconstructed ensemble, and that reconstruction is anchored to the
observation it is later verified against — legitimate for a live demonstration,
which is what it was built for, and invalid as a backtest, because the features
already contain the answer.

So the replay uses `core/replay_features.py` instead: 21 predictors, none of
them touching the ensemble. Antecedent rainfall and its departure from normal,
wet and dry spell lengths, the state's field on the origin day, the
sub-division's long-record climatology, variability and Mann-Kendall trend, and
the calendar.

---

## Protocol

Fixed before any number was looked at.

| | |
|---|---|
| Split | **Temporal**, by origin date. Adjacent days share a weather system, so a shuffled split would put near-duplicates of the training rows in the test set. |
| Threshold | **0.50, frozen.** Not tuned on the test origins, not tuned at all. |
| Test origins | Touched once, to report. No part in fitting, feature selection or thresholding. |
| Probability | `predict_proba`-equivalent output of a fitted logistic. Never a constant, never `Math.random()`. |
| Attribution | Exact Shapley values. The model is linear in the log-odds, so each has a closed form and they sum precisely to the log-odds. No sampling. |

---

## Measured results

From `python -m scripts.train_replay_model` and `/api/replay/backtest`.
Reproduce them; they are not written down anywhere by hand.

| Metric | Value |
|---|---|
| ROC-AUC, training origins | 0.813 |
| **ROC-AUC, held-out origins** | **0.682** |
| Brier, held-out | 0.154 |
| Base rate | 0.165 |
| Walk-forward, all origins | 0.725 |
| **Walk-forward, out-of-sample origins** | **0.650** |

At the fixed 0.50 threshold on the held-out origins: precision 0.261, recall
0.227, F1 0.243.

Skill by lead time, out-of-sample:

| Lead | D1 | D2 | D3 | D4 | D5 | D6 | D7 |
|---|---|---|---|---|---|---|---|
| ROC-AUC | 0.831 | 0.762 | 0.695 | 0.659 | 0.629 | 0.568 | 0.581 |

That decay is the most reassuring number on the page. Predictability really
does fall away with lead time; a model that scored 0.83 at Day 7 as well as Day
1 would be reading the answer.

**The honest caveat**, which travels with the model card and is printed on the
page: the daily observational archive is 22 days long. That yields 17 usable
origins, 11 of which reach a full 7-day window. A held-out estimate from this
few origins has wide error bars whatever it says. These are working figures,
not performance claims. The fix is more daily data, not a different estimator.

---

## What is missing, precisely

### 1. Daily observed rainfall outside 2026-08-19 → 2026-09-09

The archive is 22 days. **Every origin outside it is unverifiable**, including
05-Sep-2016. `/api/replay/availability?origin=2016-09-04` says so rather than
producing something.

The 1901–2017 sub-division file does cover September 2016 — as a **monthly
total**, one number for the month. A monthly total cannot be divided into daily
values. It is not interpolated, distributed across 30 days, or otherwise turned
into weather that never happened.

**Interface:** `scripts/import_imd_daily_rainfall.py`. It accepts a published
daily CSV, matches column names case-insensitively (including IMD's own
`Departue` and `Acutual` typos), rejects rows whose date it cannot parse,
rejects rows with no measurement — a missing measurement is not zero rainfall —
and refuses to fill any gap. `make replay-archive` prints current coverage and
the four routes to more of it.

### 2. An archived NWP forecast

**Interface:** `core/hindcast.py`. It defines the manifest contract, scans
`data/hindcast/`, and reports exactly which files it looked for. The decoder is
deliberately unimplemented: writing a GRIB reader against a file nobody has
seen produces untestable code that will be wrong.

Drop a conforming archive into `data/hindcast/` and Mode A becomes reachable
with no change downstream.

---

## API

| Endpoint | Returns |
|---|---|
| `GET /api/replay/origins` | Origin dates the archive supports, and which reach a full 7-day window. |
| `GET /api/replay/availability?origin=` | Mode A and Mode B availability, with reasons and missing days. |
| `GET /api/replay/run?origin=&location_id=` | A full 7-day replay: predictions, validations, summary, audit log. |
| `GET /api/replay/backtest` | Walk-forward across every origin and site, in-sample and out-of-sample side by side. |
| `GET /api/replay/model` | Model card: predictors, coefficients, metrics, leakage controls. |
| `GET /api/replay/requirements?origin=` | What a genuine Mode A validation of that origin would need. |

## Storage

`replay_runs`, `replay_predictions`, `replay_contributions`,
`replay_validations` and `audit_log` in `app/db/schema.sql`. Kept separate from
`risk_predictions` because the two objects are not the same thing, and merging
them would lose exactly the distinction the replay exists to preserve.

Two constraints enforce the rule at the storage layer too:

```sql
CHECK (evidence_end <= origin_date)
CHECK (valid_date > origin_date)
```

and a validation row with no observation cannot carry a label:

```sql
CHECK (observed_available = 1 OR actual_bust IS NULL)
```

## Reproducibility

Run IDs are derived from the origin date and the model version, prediction IDs
from the run, site and lead. The same inputs always produce the same
identifiers and the same numbers. Every run carries its model version, the
evidence window it was allowed to read, and an audit log of what each phase
read. CSV and JSON exports carry all of it.

## Commands

```bash
make fit-replay        # fit the replay model, print held-out metrics
make replay-archive    # show archive coverage and where more data comes from
make replay-archive FILE=downloaded.csv   # import a published daily file
make test              # 171 tests, 23 of them replay leakage guards
```


---

# Monthly replay (1901–2017)

## What it answers, and at what resolution

Give it any date in the record — 5 August 2015, say — and it predicts the
**month containing that date** from everything known up to the end of the month
before, then sets the answer against what IMD actually recorded.

It cannot give you seven daily values for 5 August 2015, and nothing here
pretends otherwise. The sub-division file holds **one figure per sub-division
per month**: August 2015 in Vidarbha is a single number, 288.9 mm. There is no
5 August in it. Dividing that total across 31 days would manufacture weather
that never happened, which is the one thing this project will not do.

So the resolution notice sits at the top of the page, not in a footnote.

## The event

A month is **extreme** when it sits at least 1.0 standard deviation from its own
climatology — wet or dry. Base rate over the held-out years: 24.0%.

Three separate models are fitted, because "extreme" without a direction is not
a claim anyone can act on: `extreme` (either side), `wet`, and `dry`.

## The leakage detail that matters most

A z-score of August 2015 taken against a 1901–2017 mean has 2015 inside it —
and 2016, and 2017. So climatology here is an **expanding window**: for a target
in year Y, the mean and standard deviation come from years strictly before Y.
The baseline moves as the record grows, exactly as it would have for a
forecaster standing in that year. `tests/test_monthly.py` asserts this directly.

On top of that, `MonthlyArchive` raises `MonthlyLeakageError` on any read after
the origin month, `MonthlyOutcomes` raises on any read at or before it, and the
split is a **block by target year**: everything from 2010 is held out, not a
shuffled fraction.

## Measured results

Train 1935–2009 (23,133 sub-division-months). Test **2010–2017**
(2,454 sub-division-months), never seen during fitting.

| Target | AUC train | **AUC 2010–17** | Precision | Recall | Base rate |
|---|---:|---:|---:|---:|---:|
| Extreme (either) | 0.640 | **0.644** | 0.334 | 0.365 | 0.240 |
| Dry extreme | 0.723 | **0.721** | 0.229 | 0.252 | 0.120 |
| Wet extreme | 0.590 | **0.587** | 0.183 | 0.142 | 0.121 |

Train and held-out are within 0.004 of each other on every target. There is no
overfitting here; there is simply not much signal, and the model is honest
about how much.

**The interesting result is the split between dry and wet.** Droughts are
forecastable a month ahead — they are slow, persistent regimes, and the model
reaches 0.721 on them. Floods are not: a single synoptic event that dumps a
month's rain in three days leaves almost no trace in the preceding month, and
the model manages 0.587, barely above chance. That is a real property of the
atmosphere, not a defect, and it shows up in the case studies:

| Case | Predicted | Actual | Verdict |
|---|---|---|---|
| Sep 2014, Jammu & Kashmir (the floods) | extreme 22% | +319%, z = +3.96 | **miss** |
| Jun 2013, Uttarakhand (the disaster) | extreme 30% | +205%, z = +4.07 | **miss** |
| Jul 2015, Marathwada (drought year) | dry 20% (fired) | −85%, z = −2.11 | **hit** |
| Aug 2015, Vidarbha | extreme 32% | +1%, z = +0.04 | correct negative |

Two catastrophic wet events missed, one drought caught. That is exactly what
the AUC table predicts, and reporting it is the point.

## Thresholds

Two are carried, and both are shown:

- **0.50** — the conventional one. At this base rate it never fires, which is
  worth showing rather than hiding.
- **The operating threshold** — the quantile matching the *training* base rate,
  picked on the training years alone and frozen before 2010–2017 was scored.
  0.320 for extreme, 0.210 for dry, 0.184 for wet.

Picking an operating point on training data is calibration. Picking it on the
test set would be tuning, and is not done.

## The honest caveat

ROC-AUC around 0.64 is modest, and it is what a month-ahead rainfall prediction
built **only from a rainfall series** honestly scores. The dominant driver of
Indian monsoon anomalies is ENSO, and no ENSO index exists in this dataset.
Adding one (NOAA ONI, freely published back to 1950) is the obvious next step.
Reporting a higher number without it would not be.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/monthly/meta` | Sub-divisions, record span, resolution notice, training window. |
| `GET /api/monthly/replay?on=&subdivision=` | Predict and verify the month containing `on`, for one sub-division or all 36. |
| `GET /api/monthly/model` | Model card: three targets, coefficients, held-out metrics, leakage controls. |

## Commands

```bash
make fit-monthly       # fit all three targets, print held-out metrics
make test              # 300 tests
```


---

# 7-day station replay (2010–2021)

## What it does

Pick any date from 1 January 2010 to 24 December 2021, and one of 28 Indian
stations. Using **only observations up to and including that date**, the system
forecasts the next seven days — maximum temperature, minimum temperature, the
chance of rain and its amount — and the **probability that each day's forecast
will bust**. Then it opens the record for those seven days and scores itself.

Every observed value is a real, quality-controlled station observation. You
can check any of them on NOAA's station page (linked from each replay) or any
other public archive.

## The data

**NOAA Global Historical Climatology Network – Daily**, the archive Indian
synoptic stations report into through the WMO. Public domain, quality
controlled, mirrored on the AWS Open Data registry — which is reachable from
this environment when the IMD hosts are not.

`scripts/import_ghcn_daily.py` builds it. Station selection is a fixed rule, not
a hand-picked list: every Indian station with at least 2,300 quality-passed
maximum-temperature reports in 2010–2017 **and** 3,000 in 1995–2009 is kept.
The archive was later extended to 2021 for the same 28 stations; the rule was
not re-run over the longer window, because admitting new stations would have
changed the model. Reporting thins in 2018–2021 at a few stations (Goa and
Minicoy are the worst); those days show as not reported.
Twenty-eight pass, from Amritsar to Thiruvananthapuram and Jaisalmer to Ranchi.
Any value carrying a NOAA quality flag is dropped.

**Missing stays missing.** Indian stations often don't report rainfall on dry
days. An absent value is never read as 0 mm: it is NaN into the model (which
handles it natively) and "not reported" in verification, where that day is not
scored.

## Is the forecast NWP?

No, and every payload says so. No archived numerical forecast for these dates
exists in this repository. The forecast being checked — and whose failure the
bust probability anticipates — is this system's own, learned from each
station's history and the network around it.

## Leakage — proved, not asserted

- Every origin feature is built from arrays shifted **backward** in time. A
  negative lag raises.
- `tests/test_station_replay.py` overwrites **every observation after T with
  999** and checks that the forecast and bust probabilities at T don't move.
- Climatology comes from 1995–2009 alone; a test poisons all of 2010–2017 and
  checks the normals are unchanged.
- Fitted on **1995–2009**. A training forecast whose target lands in 2010 is
  dropped.
- The bust classifiers learn from **out-of-fold** forecasts — five 3-year
  blocks, each forecast by a model that never saw it. Trained on in-sample
  errors, they would learn that busts almost never happen.
- The call threshold and the persistence shrinkage are chosen on those
  out-of-fold training forecasts, frozen before 2010–2017 is scored.

## What counts as a bust

- **Temperature:** forecast max or min more than **3 °C** from the observation.
  IMD's own verification counts ±2 °C as correct; a bust is a clear step past it.
- **Rain:** forecast **two or more IMD classes** from what fell — forecast
  no rain, observed moderate; forecast light, observed heavy.
- **Any:** either. A day with neither observation reported isn't scored.

## Held-out results — every day of 2010–2021

858,284 forecasts, 28 stations, none seen in fitting.

| | Model | Normal only |
|---|---:|---:|
| Max temp error, all leads | **1.29 °C** | 1.61 °C |
| Max temp within ±2 °C | **79.5%** | — |
| Rain / no-rain correct | **64.0%** | 62.5% |
| Bust ROC-AUC | **0.718** | |
| Bust Brier | **0.128** | 0.139 |

| Lead | Max temp error | "Same as today" | Within ±2 °C | Bust AUC |
|---|---:|---:|---:|---:|
| Day 1 | 0.83 °C | 0.82 °C | 90% | 0.750 |
| Day 2 | 1.14 °C | 1.27 °C | 83% | 0.714 |
| Day 3 | 1.28 °C | 1.49 °C | 80% | 0.704 |
| Day 5 | 1.39 °C | 1.70 °C | 76% | 0.700 |
| Day 7 | 1.45 °C | 1.82 °C | 75% | 0.695 |

Year by year the numbers barely move — bust AUC between 0.70 and 0.74 and
77–83% of days within ±2 °C in every year from 2010 to 2021. 2018–2021 are the
furthest the model gets from its training data, and they score like 2010.

### Why there is no "90% accuracy" figure

Only 16.7% of forecast days bust. A rule that always says "no bust" is right
**83.3%** of the time and warns of nothing. This model's calls are right
77.3% of the time, because it deliberately gives some of that up to catch
busts. Any accuracy figure — 90% included — is dominated by the base rate
and says almost nothing, so the page leads with ROC-AUC and shows the
always-no baseline beside the accuracy. The numbers are computed, not chosen:
no result on the page is written by hand.

Read plainly:

- **Temperature is genuinely forecast.** At Day 1 the model ties "tomorrow is
  like today" — temperature is that persistent — and from Day 2 it beats it,
  by 0.38 °C at Day 7.
- **Rain is the weak spot.** A week out, from station records alone,
  rain/no-rain is barely better than the calendar (64.1% vs 63.0%). The UI shows
  the *chance* of rain for that reason, not a flat "no rain".
- **Bust probability has real skill** (AUC 0.72, Brier beats climatology) and
  it decays with lead, which is what honest skill does.

An earlier version fitted the temperature anomaly directly and **lost to
persistence at Day 1** (0.92 °C vs 0.81 °C on the same rows). Trees approximate
a straight line in steps. The fix: model the *change* from persistence with an
absolute-error loss, and shrink that change per lead by a weight chosen on
out-of-fold training data.

## Example: 17 August 2015

| Station | Max temp within ±2 °C | Max temp error | Bust calls correct |
|---|---:|---:|---:|
| New Delhi / Safdarjung | 7 / 7 | 0.60 °C | 6 / 7 |
| Bangalore | 4 / 7 | 1.51 °C | 7 / 7 |
| Chennai / Meenambakkam | 5 / 6 | 1.35 °C | 4 / 6 |

Delhi recorded 55.9 mm on 24 August. The model had put that day's bust
probability over the call threshold, so it's a **hit**. Chennai's rain on
21–22 August was **missed**. Both are shown.

## Every date in the static preview

858,000 forecasts are far too many to embed in a page, so a published build
ships one packed file per station (`scripts/export_station_sidecar.py`, about
1 MB each) and the page rebuilds whichever date a reader picks. Parity is
structural: forecast days come from `station_replay.format_day` and verdicts
from `station_replay.score_day` — the functions the live API calls — and the
browser only unpacks integers. Scoring is done in integer tenths, because in
floating point 38.2 − 35.2 is 3.0000000000000036, which would call a 3 °C bust
that neither a reader nor JavaScript would.

`make parity` compiles the browser module, rebuilds 1,285 replays across all
28 stations from the files — including leap days and the first and last
origins — and compares them with the API field by field. Last run: **0
mismatches**.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/stations/meta` | Stations, date range, held-out track record |
| `GET /api/stations/replay?on=&station=` | 7-day forecast from `on`, then verification |
| `GET /api/stations/model` | Model card, thresholds, leakage controls |

## Commands

```bash
python -m scripts.import_ghcn_daily          # rebuild data/ghcn/ from NOAA
make fit-station                             # retrain (about 4 minutes)
make static && make parity                   # static build, then prove it matches the API
```
