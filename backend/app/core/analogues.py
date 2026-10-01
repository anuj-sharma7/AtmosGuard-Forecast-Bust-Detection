"""Historical analogue engine.

The catalogue below is a **demonstration analogue catalogue**: plausible
monsoon-season situations with hand-authored pattern fingerprints and known
outcomes.  It exists to demonstrate the *mechanism* - "we have seen this
atmospheric pattern before, and here is how the forecast performed" - which is
the concept AtmosGuard is built on.

In production this is replaced by a nearest-neighbour search over an ERA5 /
IMDAA reanalysis archive: each historical day is embedded (500 hPa geopotential,
850 hPa winds, IWV, MSLP), the live pattern is embedded the same way, and the
top-k neighbours are retrieved with their verified forecast errors.  The
returned structure is identical, so the frontend does not change.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .synthetic import SynopticState


@dataclass(frozen=True)
class AnalogueEvent:
    id: str
    event_date: str
    region: str
    regime: str
    pattern: str
    #: Fingerprint: (regime_change, synoptic_forcing, moisture_anomaly, convective_share)
    fingerprint: tuple[float, float, float, float]
    bust_occurred: bool
    outcome: str
    #: Verified error of the operational Day 5 forecast, in the event's units.
    verified_error: str


CATALOGUE: tuple[AnalogueEvent, ...] = (
    AnalogueEvent(
        "an-2023-07-18-raj", "18 July 2023", "Rajasthan",
        "Low-pressure area / depression",
        "Monsoon trough shifted north with an embedded low tracking west-northwest",
        (0.82, 0.78, 0.61, 0.74), True, "Forecast Bust",
        "Day 5 rainfall under-forecast by 61 mm",
    ),
    AnalogueEvent(
        "an-2022-08-09-raj", "9 August 2022", "East Rajasthan",
        "Active monsoon trough",
        "Persistent trough position with steady moisture incursion from the Arabian Sea",
        (0.21, 0.66, 0.44, 0.38), False, "Forecast Verified",
        "Day 5 rainfall error 8 mm",
    ),
    AnalogueEvent(
        "an-2021-09-02-mp", "2 September 2021", "Madhya Pradesh",
        "Bay of Bengal cyclonic circulation",
        "Well-marked low moving inland, ensemble split on inland track",
        (0.74, 0.81, 0.55, 0.66), True, "Forecast Bust",
        "Day 5 rainfall over-forecast by 47 mm",
    ),
    AnalogueEvent(
        "an-2023-06-27-guj", "27 June 2023", "Gujarat",
        "Arabian Sea moisture surge",
        "Rapid moisture surge ahead of monsoon onset, sharp MSLP fall",
        (0.68, 0.88, 0.79, 0.58), True, "Forecast Bust",
        "Day 4 rainfall under-forecast by 88 mm",
    ),
    AnalogueEvent(
        "an-2020-07-30-up", "30 July 2020", "Uttar Pradesh",
        "Break monsoon",
        "Trough displaced towards the Himalayan foothills, subsidence over the plains",
        (0.18, 0.24, -0.42, 0.31), False, "Forecast Verified",
        "Day 5 rainfall error 5 mm",
    ),
    AnalogueEvent(
        "an-2022-10-19-tn", "19 October 2022", "Tamil Nadu",
        "Bay of Bengal cyclonic circulation",
        "Northeast monsoon onset with a slow-moving circulation offshore",
        (0.63, 0.72, 0.66, 0.69), True, "Forecast Bust",
        "Day 6 rainfall timing error of 36 h",
    ),
    AnalogueEvent(
        "an-2019-08-04-mah", "4 August 2019", "Maharashtra Ghats",
        "Arabian Sea moisture surge",
        "Strong offshore trough with sustained orographic forcing",
        (0.34, 0.91, 0.84, 0.44), False, "Forecast Verified",
        "Day 5 rainfall error 19 mm",
    ),
    AnalogueEvent(
        "an-2023-08-14-hp", "14 August 2023", "Himachal Pradesh",
        "Western disturbance interaction",
        "Monsoon trough interacting with an incoming western disturbance",
        (0.88, 0.76, 0.58, 0.61), True, "Forecast Bust",
        "Day 5 rainfall under-forecast by 74 mm",
    ),
    AnalogueEvent(
        "an-2021-07-11-del", "11 July 2021", "Delhi NCR",
        "Active monsoon trough",
        "Trough oscillating over the NCR with weak steering flow",
        (0.57, 0.54, 0.36, 0.72), True, "Forecast Bust",
        "Day 3 rainfall over-forecast by 42 mm",
    ),
    AnalogueEvent(
        "an-2020-06-14-wb", "14 June 2020", "West Bengal",
        "Bay of Bengal cyclonic circulation",
        "Post-cyclone moisture residual with a stable synoptic pattern",
        (0.26, 0.62, 0.51, 0.35), False, "Forecast Verified",
        "Day 5 rainfall error 11 mm",
    ),
    AnalogueEvent(
        "an-2022-07-22-as", "22 July 2022", "Assam & Meghalaya",
        "Active monsoon trough",
        "Trough anchored along the foothills, strong low-level jet",
        (0.44, 0.86, 0.88, 0.79), True, "Forecast Bust",
        "Day 4 rainfall under-forecast by 96 mm",
    ),
    AnalogueEvent(
        "an-2019-05-28-ka", "28 May 2019", "Karnataka Interior",
        "Post-monsoon anticyclonic ridge",
        "Pre-monsoon ridge with isolated thermally driven convection",
        (0.12, 0.19, -0.55, 0.86), False, "Forecast Verified",
        "Day 5 temperature error 0.9 degC",
    ),
    AnalogueEvent(
        "an-2023-02-07-jk", "7 February 2023", "Jammu & Kashmir",
        "Western disturbance interaction",
        "Sequence of western disturbances with uncertain snow-rain line",
        (0.71, 0.58, 0.29, 0.33), True, "Forecast Bust",
        "Day 5 precipitation phase error",
    ),
    AnalogueEvent(
        "an-2021-11-16-ap", "16 November 2021", "Coastal Andhra",
        "Bay of Bengal cyclonic circulation",
        "Depression tracking parallel to the coast, large cross-track ensemble spread",
        (0.79, 0.83, 0.72, 0.55), True, "Forecast Bust",
        "Day 5 rainfall displaced 180 km",
    ),
)

#: Relative importance of each fingerprint dimension in the similarity metric.
_DIM_WEIGHTS = np.array([0.38, 0.24, 0.22, 0.16])


def _fingerprint(state: SynopticState, convective_index: float) -> np.ndarray:
    return np.array(
        [state.regime_change, state.synoptic_forcing, state.moisture_anomaly, convective_index]
    )


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Weighted-distance similarity in [0, 1]."""
    # moisture_anomaly spans [-1, 1]; the rest span [0, 1]. Normalise the range
    # so no single dimension dominates by scale alone.
    scale = np.array([1.0, 1.0, 2.0, 1.0])
    diff = np.abs(a - b) / scale
    distance = float(np.sqrt(np.sum(_DIM_WEIGHTS * diff**2)))
    return float(np.clip(1.0 - distance / 0.72, 0.0, 1.0))


def find_analogues(
    state: SynopticState, convective_index: float, regime: str, top_k: int = 4
) -> list[dict[str, object]]:
    """Top-k historical analogues for the current pattern, best first."""
    current = _fingerprint(state, convective_index)
    scored: list[tuple[float, AnalogueEvent]] = []
    for ev in CATALOGUE:
        sim = similarity(current, np.array(ev.fingerprint))
        # A matching synoptic regime is meaningful extra evidence.
        if ev.regime == regime:
            sim = min(1.0, sim + 0.09)
        scored.append((sim, ev))

    scored.sort(key=lambda t: t[0], reverse=True)
    out: list[dict[str, object]] = []
    for rank, (sim, ev) in enumerate(scored[:top_k], start=1):
        out.append(
            {
                "rank": rank,
                "id": ev.id,
                "date": ev.event_date,
                "region": ev.region,
                "regime": ev.regime,
                "pattern": ev.pattern,
                "similarity": round(sim, 4),
                "bust_occurred": ev.bust_occurred,
                "outcome": ev.outcome,
                "verified_error": ev.verified_error,
            }
        )
    return out


def analogue_mismatch(analogue_list: list[dict[str, object]]) -> float:
    """Convert analogue results into the 0-1 'mismatch' risk feature.

    Two things raise the feature:
      * the best analogue is a poor match (we have no precedent), and
      * the analogues we *do* match busted historically.
    """
    if not analogue_list:
        return 0.8

    best = float(analogue_list[0]["similarity"])
    novelty = 1.0 - best

    weights = np.array([float(a["similarity"]) for a in analogue_list])
    busts = np.array([1.0 if a["bust_occurred"] else 0.0 for a in analogue_list])
    bust_rate = float(np.average(busts, weights=weights)) if weights.sum() > 0 else 0.5

    return float(np.clip(0.55 * novelty + 0.45 * bust_rate, 0.0, 1.0))
