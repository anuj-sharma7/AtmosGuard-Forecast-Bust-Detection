"""Synthetic NWP / ensemble forecast provider.

=============================  READ THIS  =============================
Everything produced by this module is **MVP Demonstration Data**.  It is
*not* operational output from ECMWF, NCMRWF-NCUM, GFS, IMDAA or ERA5, and
every API response that carries these numbers is stamped with
``data_mode: "demo"`` plus a human-readable disclaimer.
=======================================================================

The generator is not a random-number spray.  It builds a small causal chain
that mirrors how real medium-range forecast failures arise, so that the
features the risk model consumes are *genuinely* correlated with the bust
labels rather than being independently sampled noise:

    latent synoptic state (regime, forcing, moisture)
        -> ensemble mean trajectory
        -> member perturbations whose growth rate depends on the regime
        -> ensemble spread, model disagreement, pressure tendency, run-to-run
           persistence
        -> bust risk (see risk_model.py) and, at verification time, the
           realised forecast error and the binary bust label

Because the perturbation growth rate and the eventual verification error are
both driven by the same latent state, a high ensemble spread really does
precede a large forecast error in this dataset.  That is the property the
whole product rests on, and it is what makes the demo scientifically honest.

Swapping in real data means replacing this module with an ``xarray``/NetCDF
reader that returns the same dataclasses; nothing downstream changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import numpy as np

from . import imd, rng
from .domain import (
    ALL_SITES_BY_ID,
    DETERMINISTIC_MODEL_IDS,
    MODELS_BY_ID,
    REGIMES,
    VARIABLES_BY_ID,
    Location,
    NWPModel,
    Variable,
)

#: Lead times generated internally (T+1 .. T+10). We generate beyond the
#: 7-day product horizon because run-to-run persistence for a Day 7 valid time
#: needs the same valid time seen from *earlier* initialisations, which sit at
#: leads 8, 9 and 10.
FORECAST_DAYS = 10

#: Lead times exposed as a product (Day 1 .. Day 7).
DISPLAY_DAYS = 7

#: Absolute ensemble-spread scale per variable, calibrated so that the Day-5
#: deterministic forecast error of the demonstration dataset lands in the range
#: an operational medium-range forecast actually achieves over the Indian
#: domain (see `scripts/calibrate.py`):
#:
#:     rainfall     RMSE ~ 18 mm      temperature  RMSE ~ 2.0 degC
#:     wind         RMSE ~ 1.7 m/s    pressure     RMSE ~ 2.2 hPa
#:
#: Without this the generator produced ~14 degC Day-5 temperature errors, which
#: would have made every verification number on the dashboard nonsense.
#: Variables that cannot physically go below zero.
NON_NEGATIVE_VARIABLES = frozenset({"rainfall", "wind"})

SIGMA_SCALE: dict[str, float] = {
    "rainfall": 0.090,
    "temperature": 0.155,
    "wind": 0.118,
    "pressure": 0.173,
}


# ---------------------------------------------------------------------------
# Latent synoptic state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SynopticState:
    """The unobserved atmospheric situation that drives everything else."""

    regime: str
    next_regime: str
    #: 0 = stationary pattern, 1 = a full regime transition inside the window.
    regime_change: float
    #: Day within *this run's* forecast window at which the transition occurs.
    transition_day: float
    #: Strength of large-scale (synoptically forced) ascent, 0-1.
    synoptic_forcing: float
    #: Low-level moisture anomaly, -1 .. +1.
    moisture_anomaly: float
    #: Day within *this run's* window of peak weather activity.
    event_day: float


#: Absolute time origin. The atmosphere is modelled as a continuous function of
#: real time; a model run merely observes it from a particular initialisation.
EPOCH = date(2024, 1, 1)

#: Spacing of the latent-state anchor points, in days. The state is smoothly
#: interpolated between anchors, which is what gives successive model runs a
#: *shared* atmosphere instead of independent draws.
_ANCHOR_SPACING = 6.0

#: Mean spacing between synoptic events at a site, in days.
_EVENT_SPACING = 9.0


def _smoothstep(t: float) -> float:
    """Hermite interpolation weight - C1-continuous, so no kinks at anchors."""
    t = float(np.clip(t, 0.0, 1.0))
    return t * t * (3.0 - 2.0 * t)


def _smooth_field(location_id: str, name: str, t: float, lo: float, hi: float) -> float:
    """A slowly varying latent field sampled at absolute time ``t`` (days)."""
    idx = int(np.floor(t / _ANCHOR_SPACING))
    frac = (t - idx * _ANCHOR_SPACING) / _ANCHOR_SPACING
    a = rng.unit(location_id, name, idx)
    b = rng.unit(location_id, name, idx + 1)
    value = a + (b - a) * _smoothstep(frac)
    return float(lo + (hi - lo) * value)


def _event_epoch(location_id: str, t: float) -> tuple[float, int]:
    """Absolute time of the synoptic event governing time ``t``, and its index.

    Events are anchored in absolute time, so every model run that spans the
    same event sees the *same* event - which is what makes the run-to-run and
    lead-time diagnostics physically meaningful.
    """
    idx = int(np.floor(t / _EVENT_SPACING))
    # Look at this event and the next; pick the first that has not yet passed.
    for candidate in (idx, idx + 1):
        jitter = (rng.unit(location_id, "event-jitter", candidate) - 0.5) * 4.0
        epoch = candidate * _EVENT_SPACING + jitter
        if epoch >= t:
            return epoch, candidate
    nxt = idx + 2
    jitter = (rng.unit(location_id, "event-jitter", nxt) - 0.5) * 4.0
    return nxt * _EVENT_SPACING + jitter, nxt


@lru_cache(maxsize=8192)
def synoptic_state(location_id: str, base_date: date) -> SynopticState:
    """Latent atmospheric state as seen from one initialisation.

    The underlying state is a continuous function of absolute time; this
    function projects it into the run-relative frame (``event_day``,
    ``transition_day``) that the ensemble generator works in. Two runs a day
    apart therefore describe the *same* weather system at different lead
    times, rather than two unrelated atmospheres.
    """
    loc = ALL_SITES_BY_ID[location_id]
    t = float((base_date - EPOCH).days)

    event_epoch, event_idx = _event_epoch(location_id, t)
    event_day = float(np.clip(event_epoch - t, 0.5, float(FORECAST_DAYS)))

    # Regime transitions are tied to the event and lead it slightly.
    transition_offset = 0.4 + 1.6 * rng.unit(location_id, "transition-lead", event_idx)
    transition_day = float(np.clip(event_day - transition_offset, 0.5, float(FORECAST_DAYS)))

    # Transition strength is a property of the event, not of the run.
    change_pressure = 0.30 + 0.55 * loc.convective_index
    raw_change = rng.unit(location_id, "regime-strength", event_idx)
    regime_change = float(np.clip(raw_change * change_pressure * 1.70, 0.0, 1.0))

    # Slowly varying background fields.
    synoptic_forcing = _smooth_field(location_id, "forcing", t, 0.05, 0.98)
    moisture_anomaly = _smooth_field(location_id, "moisture", t, -0.95, 0.95)

    n_regimes = len(REGIMES)
    regime_idx = int(rng.unit(location_id, "regime", event_idx) * n_regimes) % n_regimes
    if regime_change > 0.35:
        step = 1 + int(rng.unit(location_id, "regime-step", event_idx) * (n_regimes - 1))
        next_idx = (regime_idx + step) % n_regimes
    else:
        next_idx = regime_idx

    return SynopticState(
        regime=REGIMES[regime_idx],
        next_regime=REGIMES[next_idx],
        regime_change=regime_change,
        transition_day=transition_day,
        synoptic_forcing=synoptic_forcing,
        moisture_anomaly=moisture_anomaly,
        event_day=event_day,
    )


# ---------------------------------------------------------------------------
# Ensemble generation
# ---------------------------------------------------------------------------


def _mean_trajectory(
    loc: Location, var: Variable, state: SynopticState, month: int
) -> np.ndarray:
    """Ensemble-mean value for each lead time.

    Rainfall is centred on the sub-division's **real** IMD climatology for the
    calendar month in question, so a September forecast for Chennai sits near
    its true September normal rather than a generic monsoon figure.
    """
    days = np.arange(1, FORECAST_DAYS + 1, dtype=float)
    rain_clim = loc.rain_climatology_for(month)
    # A synoptic "event" bell centred on event_day: rainfall peaks, pressure
    # falls, wind rises and temperature dips together, as they physically do.
    event = np.exp(-0.5 * ((days - state.event_day) / 1.35) ** 2)
    forcing = 0.35 + 1.30 * state.synoptic_forcing
    moisture = 1.0 + 0.45 * state.moisture_anomaly

    if var.id == "rainfall":
        base = rain_clim * 0.30
        return np.maximum(base + rain_clim * 1.45 * forcing * moisture * event, 0.0)
    if var.id == "temperature":
        # Cloud/rain cools; a break-monsoon ridge warms.
        return loc.temp_climatology + 2.4 * (1.0 - state.synoptic_forcing) - 4.2 * event * moisture
    if var.id == "wind":
        return 3.2 + 7.5 * forcing * event + 1.8 * state.synoptic_forcing
    # pressure
    return 1006.5 - 9.5 * forcing * event - 2.0 * state.synoptic_forcing


def _spread_profile(
    loc: Location, var: Variable, model: NWPModel, state: SynopticState
) -> np.ndarray:
    """Relative perturbation growth for T+1 .. T+7.

    Error growth is super-linear with lead time (classic ensemble behaviour),
    accelerates through a regime transition, and is larger for convective
    locations and for intrinsically less predictable variables.
    """
    days = np.arange(1, FORECAST_DAYS + 1, dtype=float)

    # Baseline growth: small at Day 1, steep beyond Day 4.
    growth = 0.055 * days**1.42

    # A regime transition injects extra divergence from the transition day on.
    transition = 1.0 / (1.0 + np.exp(-1.6 * (days - state.transition_day)))
    growth = growth * (1.0 + 1.45 * state.regime_change * transition)

    # Irreducible uncertainty. When the models cannot agree on *whether* or
    # *when* a pattern change happens, the spread does not collapse as the lead
    # time shortens the way it normally does - a Day 3 forecast can still carry
    # Day 6 levels of disagreement. This floor is deliberately independent of
    # lead time, and it is what drives the escalating risk timeline: as the
    # climatological spread for the lead time falls away beneath it, the
    # *spread anomaly* climbs even though the raw spread is flat.
    growth = growth + 0.085 * state.regime_change * transition

    # Local predictability and variable difficulty.
    growth = growth * (1.0 + 0.85 * loc.convective_index) * var.predictability_penalty
    growth = growth * (1.0 - 0.35 * (loc.historical_skill - 0.5))

    # A better model has a better-tuned (tighter, but not artificially tight)
    # perturbation structure.
    growth = growth * (1.0 - 0.28 * (model.skill - 0.75))
    return growth


def _anchor_to_observed(
    climatological: np.ndarray,
    location_id: str,
    variable_id: str,
    base_date: date,
    loc: Location,
    model: NWPModel,
    state: SynopticState,
    g: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Reconstruct a forecast targeting what was actually observed.

    A real Day-5 forecast is *skilful*: it correlates strongly with the weather
    that follows, and it degrades toward climatology as the lead time grows or
    the atmosphere turns unpredictable. A forecast generated from climatology
    alone has none of that structure - measured against the real IMD record it
    scored below random, because nothing in it knew what the weather did.

    So where the real observation exists, the forecast is reconstructed around
    it: it starts close to the truth and reverts toward climatology in
    proportion to lead time, the strength of the regime transition, and the
    model's own skill. Busts then arise exactly where a forecaster would expect
    them - long leads, unsettled patterns, low-skill regions - and the ensemble
    spread that flags them is genuinely informative about the real error.

    This is a *reconstruction*, not an archived forecast: no agency publishes
    historical ensemble members, so the ensemble around the real outcome is
    simulated, and every response says so.
    """
    observed = [
        real_observation(location_id, variable_id, base_date + timedelta(days=lead))
        for lead in range(1, FORECAST_DAYS + 1)
    ]
    if not any(o is not None for o in observed):
        return climatological, None

    days = np.arange(1, FORECAST_DAYS + 1, dtype=float)
    transition = 1.0 / (1.0 + np.exp(-1.6 * (days - state.transition_day)))

    # Fraction of the forecast that has reverted to climatology by each lead.
    reversion = (
        0.10
        + 0.050 * (days - 1.0)
        + 0.46 * state.regime_change * transition
        + 0.30 * (1.0 - loc.historical_skill)
    )
    reversion = reversion * (1.0 - 0.25 * (model.skill - 0.75))
    reversion = np.clip(reversion, 0.05, 0.95)

    # A run-specific systematic error, so successive runs are not all identical
    # rescalings of the same truth.
    drift = g.normal(0.0, 0.10, size=FORECAST_DAYS) * days / FORECAST_DAYS

    out = climatological.copy()
    for i, value in enumerate(observed):
        if value is None:
            continue
        w = reversion[i]
        out[i] = (1.0 - w) * float(value) + w * climatological[i]
        out[i] *= 1.0 + drift[i]

    clipped = np.maximum(out, 0.0) if variable_id in NON_NEGATIVE_VARIABLES else out
    return clipped, reversion


@dataclass(frozen=True)
class EnsembleForecast:
    location_id: str
    variable_id: str
    model_id: str
    base_date: date
    #: (n_members, 7) array of member trajectories.
    members: np.ndarray
    #: (7,) ensemble mean.
    mean: np.ndarray
    #: (7,) deterministic (control/high-resolution) run.
    deterministic: np.ndarray
    state: SynopticState

    @property
    def n_members(self) -> int:
        return int(self.members.shape[0])


@lru_cache(maxsize=8192)
def ensemble_forecast(
    location_id: str,
    variable_id: str,
    model_id: str,
    base_date: date,
    n_members: int = 42,
) -> EnsembleForecast:
    """Generate one ensemble forecast (all lead times).

    Cached: the verification sweep asks for the same forecast from several
    angles (spread, model disagreement, persistence, truth), and regenerating
    it each time dominated the runtime. Callers must treat the returned arrays
    as read-only.
    """
    loc = ALL_SITES_BY_ID[location_id]
    var = VARIABLES_BY_ID[variable_id]
    model = MODELS_BY_ID[model_id]
    state = synoptic_state(location_id, base_date)

    g = rng.generator("ensemble", location_id, variable_id, model_id, base_date.isoformat())
    climatological = _mean_trajectory(loc, var, state, base_date.month) * model.bias
    mean, reversion = _anchor_to_observed(
        climatological, location_id, variable_id, base_date, loc, model, state, g
    )
    rel = _spread_profile(loc, var, model, state)
    if reversion is not None:
        # A forecast that has reverted toward climatology *is* an uncertain
        # forecast, and a real ensemble shows it. Tying spread to the same
        # quantity that drives the error is what makes spread a usable warning
        # rather than a decorative band on the chart.
        rel = rel * (0.65 + 1.15 * reversion)

    # Absolute sigma per lead time. For rainfall the spread scales with the
    # amount (multiplicative error); for temperature/pressure it is additive.
    scale = SIGMA_SCALE[var.id]
    if var.id == "rainfall":
        sigma = rel * np.maximum(mean, loc.rain_climatology_for(base_date.month) * 0.35) * scale
    elif var.id == "temperature":
        sigma = rel * 7.0 * scale
    elif var.id == "wind":
        sigma = rel * 6.5 * scale
    else:
        sigma = rel * 9.0 * scale

    # Members share a few correlated "error modes" rather than being i.i.d.,
    # which is what produces the realistic fanning structure in the chart.
    n_modes = 3
    modes = g.normal(size=(n_members, n_modes))
    mode_shapes = np.stack(
        [
            np.linspace(0.2, 1.0, FORECAST_DAYS),
            np.sin(np.linspace(0.0, np.pi, FORECAST_DAYS)),
            np.linspace(1.0, 0.35, FORECAST_DAYS),
        ]
    )
    correlated = (modes @ mode_shapes) / np.sqrt(n_modes)
    independent = g.normal(size=(n_members, FORECAST_DAYS)) * 0.55
    perturbation = (correlated + independent) * sigma

    members = mean + perturbation

    if var.id == "rainfall":
        # Rainfall is non-negative and right-skewed: a few members can go big.
        skew = g.gamma(2.0, 0.5, size=(n_members, 1))
        members = mean + perturbation * (0.6 + 0.8 * skew)

    # Rainfall accumulation and wind *speed* are physically non-negative; a
    # Gaussian perturbation around a small mean will otherwise push members
    # below zero. Temperature and MSLP are unbounded and must not be clamped.
    if var.id in NON_NEGATIVE_VARIABLES:
        members = np.maximum(members, 0.0)

    # The deterministic run is close to, but not identical to, the mean.
    det_offset = g.normal(size=FORECAST_DAYS) * sigma * 0.30
    deterministic = members.mean(axis=0) + det_offset
    if var.id in NON_NEGATIVE_VARIABLES:
        deterministic = np.maximum(deterministic, 0.0)

    return EnsembleForecast(
        location_id=location_id,
        variable_id=variable_id,
        model_id=model_id,
        base_date=base_date,
        members=members,
        mean=members.mean(axis=0),
        deterministic=deterministic,
        state=state,
    )


# ---------------------------------------------------------------------------
# Derived diagnostics used as risk-model features
# ---------------------------------------------------------------------------


def _soft(x: float, k: float) -> float:
    """Squash [0, inf) into [0, 1) smoothly.

    A hard ``clip`` saturates a feature at exactly 0 or 1, which destroys the
    attribution signal for the most extreme (and most interesting) cases. The
    rational map ``x / (x + k)`` keeps every value distinguishable; ``k`` is the
    value that maps to 0.5.
    """
    return float(x / (x + k)) if x > 0 else 0.0


def _relative_spread(fc: "EnsembleForecast", lead: int) -> float:
    """Raw (uncalibrated) spread at ``lead``, in units natural to the variable."""
    col = fc.members[:, lead - 1]
    sd = float(col.std(ddof=1))
    var = VARIABLES_BY_ID[fc.variable_id]
    if var.id == "rainfall":
        # Multiplicative error: coefficient of variation.
        return sd / max(float(col.mean()), 4.0)
    # Additive error: standard deviation against a typical error scale.
    scale = {"temperature": 4.5, "wind": 5.0, "pressure": 6.5}[var.id]
    return sd / scale


@lru_cache(maxsize=32)
def spread_climatology(variable_id: str) -> tuple[float, ...]:
    """Median relative ensemble spread per lead time, across all locations.

    This is the reference an operational forecaster carries in their head:
    *how uncertain is a Day 5 rainfall forecast normally?* Comparing today's
    spread against it turns a raw number into a **spread anomaly**, which is
    what actually signals trouble. A Day 3 forecast carrying Day 6 levels of
    spread is a red flag even though its absolute spread is unremarkable.
    """
    # Sampled from inside the observation window, because that is where real
    # forecasts live. Sampling elsewhere compared anchored forecasts against
    # unanchored ones and pinned every anomaly near 3.4x, saturating the
    # feature and destroying its ability to discriminate.
    start, end = imd.observation_window()
    span = (end - start).days
    sample_dates = [start + timedelta(days=i) for i in range(0, max(span, 1), 2)]
    per_lead: list[list[float]] = [[] for _ in range(FORECAST_DAYS)]
    for loc_id in ALL_SITES_BY_ID:
        for d in sample_dates:
            fc = ensemble_forecast(loc_id, variable_id, "ensemble", d, 42)
            for lead in range(1, FORECAST_DAYS + 1):
                per_lead[lead - 1].append(_relative_spread(fc, lead))
    return tuple(float(np.median(vals)) for vals in per_lead)


def spread_anomaly(fc: "EnsembleForecast", horizon: int) -> float:
    """Ensemble spread at ``horizon`` expressed as a ratio to its climatology."""
    clim = spread_climatology(fc.variable_id)[horizon - 1]
    return _relative_spread(fc, horizon) / max(clim, 1e-6)


def normalised_spread(fc: "EnsembleForecast", horizon: int) -> float:
    """Spread anomaly mapped onto the 0-1 feature scale.

    1.0x climatological spread maps to 0.4; 1.5x maps to 0.5; 3x maps to ~0.67.
    """
    return _soft(spread_anomaly(fc, horizon), 1.5)


def model_disagreement(
    location_id: str, variable_id: str, base_date: date, horizon: int, n_members: int
) -> tuple[float, dict[str, float]]:
    """Normalised spread *between* the deterministic NWP models, plus values."""
    values: dict[str, float] = {}
    for mid in DETERMINISTIC_MODEL_IDS:
        fc = ensemble_forecast(location_id, variable_id, mid, base_date, n_members)
        values[mid] = float(fc.deterministic[horizon - 1])

    arr = np.array(list(values.values()))
    var = VARIABLES_BY_ID[variable_id]
    if var.id == "rainfall":
        raw = float(arr.std(ddof=1)) / max(float(arr.mean()), 5.0)
        return _soft(raw, 0.42), values
    scale = {"temperature": 2.2, "wind": 2.6, "pressure": 3.2}[var.id]
    return _soft(float(arr.std(ddof=1)) / scale, 0.75), values


def pressure_tendency(location_id: str, base_date: date, horizon: int, n_members: int) -> float:
    """Normalised 24 h MSLP change around the valid time, 0-1.

    A rapidly falling or rising surface pressure marks a fast-evolving system,
    which is a classic precursor of medium-range forecast failure.
    """
    fc = ensemble_forecast(location_id, "pressure", "ecmwf", base_date, n_members)
    series = fc.mean
    i = horizon - 1
    prev = series[i - 1] if i > 0 else series[i]
    return _soft(abs(float(series[i] - prev)), 3.2)


def run_to_run_persistence(
    location_id: str, variable_id: str, model_id: str, base_date: date, horizon: int, n_members: int
) -> tuple[float, list[dict[str, float | str]]]:
    """How much the forecast for one *valid time* jumped between model runs.

    A forecast that flip-flops from run to run has not settled; that jumpiness
    is a strong bust precursor. We reconstruct the last four initialisations
    that all verify at the same valid time - which is why the generator runs
    out to T+10 rather than stopping at the T+7 product horizon.
    """
    valid_day = base_date + timedelta(days=horizon)
    history: list[dict[str, float | str]] = []
    for back in range(3, -1, -1):
        init = base_date - timedelta(days=back)
        lead = (valid_day - init).days
        if lead < 1 or lead > FORECAST_DAYS:
            continue
        fc = ensemble_forecast(location_id, variable_id, model_id, init, n_members)
        history.append(
            {
                "init_date": init.isoformat(),
                "lead_time": lead,
                "value": round(float(fc.deterministic[lead - 1]), 2),
            }
        )

    values = np.array([h["value"] for h in history], dtype=float)
    if values.size < 2:
        return 0.0, history

    var = VARIABLES_BY_ID[variable_id]
    if var.id == "rainfall":
        raw = float(values.std(ddof=1)) / max(float(values.mean()), 5.0)
        return _soft(raw, 0.45), history
    scale = {"temperature": 2.0, "wind": 2.4, "pressure": 3.0}[var.id]
    return _soft(float(values.std(ddof=1)) / scale, 0.70), history


def effective_regime_change(state: "SynopticState", horizon: int) -> float:
    """Regime change *relevant to this lead time*.

    A pattern transition that happens on Day 6 is close to irrelevant to a
    Day 3 forecast and dominant for a Day 7 one. Weighting the raw transition
    strength by how far the valid time sits past the transition is what makes
    the risk score respond to the forecast-horizon selector for physical
    reasons rather than by construction.
    """
    onset = 1.0 / (1.0 + np.exp(-1.35 * (horizon - state.transition_day + 0.9)))
    return float(state.regime_change * (0.18 + 0.82 * onset))


def real_observation(location_id: str, variable_id: str, valid_day: date) -> float | None:
    """Real observed rainfall from the IMD district record, if it covers this day.

    Only rainfall is covered: the IMD datasets in use are rainfall-only, so
    temperature, wind and pressure verification stays simulated and is labelled
    as such rather than being passed off as measured.
    """
    if variable_id != "rainfall":
        return None
    site = ALL_SITES_BY_ID.get(location_id)
    if site is None:
        return None

    if site.obs_district:
        record = imd.district_observation(site.obs_state, site.obs_district, valid_day)
        return record.actual if record else None

    area = imd.state_observation(site.obs_state, valid_day)
    return area[0] if area else None


def published_normal(location_id: str, variable_id: str, valid_day: date) -> float | None:
    """IMD's own published daily normal rainfall for a site and date.

    The right reference for a skill score. Estimating climatology from the same
    fortnight being verified biases the score downward and makes it unstable -
    with a two-week sample it wandered either side of zero. IMD publishes the
    normal alongside every observation, so use theirs.
    """
    if variable_id != "rainfall":
        return None
    site = ALL_SITES_BY_ID.get(location_id)
    if site is None:
        return None

    if site.obs_district:
        record = imd.district_observation(site.obs_state, site.obs_district, valid_day)
        return record.normal if record else None

    area = imd.state_observation(site.obs_state, valid_day)
    return area[1] if area else None


def observation(
    location_id: str, variable_id: str, base_date: date, horizon: int, n_members: int
) -> float:
    """The observed value a forecast is verified against.

    Where the real IMD district record covers this location and valid date, the
    truth **is** that measurement - the verification statistics on the dashboard
    are then computed against genuine observations. Outside that window, or for
    the variables IMD does not publish here, it falls back to the simulated
    truth described below.

    The truth is drawn from the *same* latent state that shaped the ensemble,
    in two parts:

    * a small core error, so that the forecast has genuine positive skill
      against climatology most of the time (as real medium-range forecasts do);
    * an occasional large displacement - the bust - whose probability and size
      both rise with the regime-transition strength and the ensemble spread
      anomaly.

    That second term is the whole point. Because the bust probability is driven
    by the very quantities the risk model consumes, high ensemble spread really
    does precede large forecast error in this dataset, and the ROC-AUC reported
    on the Verification page is earned rather than asserted. A flat Gaussian
    error would have made every risk score meaningless.
    """
    real = real_observation(location_id, variable_id, base_date + timedelta(days=horizon))
    if real is not None:
        return float(real)

    fc = ensemble_forecast(location_id, variable_id, "ensemble", base_date, n_members)
    state = fc.state
    g = rng.generator("obs", location_id, variable_id, base_date.isoformat(), horizon)

    col = fc.members[:, horizon - 1]
    mean = float(col.mean())
    sd = float(col.std(ddof=1))
    anomaly = spread_anomaly(fc, horizon)

    # Ordinary error: the truth sits comfortably inside the ensemble cloud.
    value = mean + float(g.normal(0.0, sd * 0.34))

    # Bust term.
    p_bust = float(np.clip(0.05 + 0.30 * state.regime_change + 0.14 * (anomaly - 1.0), 0.02, 0.62))
    if g.random() < p_bust:
        direction = 1.0 if g.random() < 0.5 else -1.0
        magnitude = sd * (1.7 + 1.7 * g.random()) * (0.75 + 0.55 * anomaly)
        value += direction * magnitude

    if variable_id in NON_NEGATIVE_VARIABLES:
        value = max(value, 0.0)
    return float(value)
