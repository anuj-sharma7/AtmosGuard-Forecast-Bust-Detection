"""Feature extraction: turns raw NWP/ensemble fields into model inputs.

This is the seam between "data" and "model".  A production deployment swaps
`synthetic` for a real NetCDF/GRIB reader and this module is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from ..config import settings
from . import analogues, synthetic
from .domain import ALL_SITES_BY_ID
from .risk_model import location_skill


@dataclass(frozen=True)
class FeatureBundle:
    """Model inputs plus the supporting evidence the UI needs to explain them."""

    values: dict[str, float]
    historical_skill: float
    #: Full predictor vector for the trained models. Attached lazily so this
    #: module does not import `predictors`, which imports this one.
    vector: dict[str, float]
    forecast: synthetic.EnsembleForecast
    state: synthetic.SynopticState
    model_values: dict[str, float]
    persistence_history: list[dict[str, float | str]]
    analogues: list[dict[str, object]]


def extract_features(
    location_id: str,
    variable_id: str,
    model_id: str,
    base_date: date,
    horizon: int,
    n_members: int | None = None,
) -> FeatureBundle:
    if not settings.is_demo:  # pragma: no cover - guarded future path
        raise NotImplementedError(
            "Live NWP ingestion is not implemented in the MVP. Set ATMOSGUARD_DATA_MODE=demo."
        )

    members = n_members or settings.ensemble_members
    loc = ALL_SITES_BY_ID[location_id]

    fc = synthetic.ensemble_forecast(location_id, variable_id, model_id, base_date, members)
    state = fc.state

    spread = synthetic.normalised_spread(fc, horizon)
    disagreement, model_values = synthetic.model_disagreement(
        location_id, variable_id, base_date, horizon, members
    )
    pressure = synthetic.pressure_tendency(location_id, base_date, horizon, members)
    persistence, history = synthetic.run_to_run_persistence(
        location_id, variable_id, model_id, base_date, horizon, members
    )

    analogue_list = analogues.find_analogues(state, loc.convective_index, state.regime)
    mismatch = analogues.analogue_mismatch(analogue_list)

    values = {
        "ensemble_spread": spread,
        "regime_change": synthetic.effective_regime_change(state, horizon),
        "analogue_mismatch": mismatch,
        "pressure_change": pressure,
        "forecast_persistence": persistence,
        "model_disagreement": disagreement,
    }

    bundle = FeatureBundle(
        values=values,
        vector={},
        historical_skill=location_skill(location_id, variable_id),
        forecast=fc,
        state=state,
        model_values=model_values,
        persistence_history=history,
        analogues=analogue_list,
    )

    from .predictors import build_vector  # local: avoids an import cycle

    return replace(
        bundle,
        vector=build_vector(bundle, location_id, variable_id, model_id, base_date, horizon),
    )
