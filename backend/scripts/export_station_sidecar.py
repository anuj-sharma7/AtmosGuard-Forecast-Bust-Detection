"""Export every 7-day station replay, 2010-2021, for the static build.

    python -m scripts.export_station_sidecar [--out DIR]

The static page cannot call the API, and one payload per station per date is
858,000 of them. So this writes one compact file per station holding every
forecast from 2010-01-01 to 2021-12-24, and the page rebuilds the replay for
whatever date a reader picks.

**Parity is structural, not hoped for.** Every forecast day is produced by
`station_replay.format_day` and every verdict by `station_replay.score_day` -
the same functions the live API calls. The page only unpacks integers; it
makes no scoring decision of its own. `tests/test_station_sidecar.py` rebuilds
payloads from these files and compares them field by field with the API.

Encoding, per station (row = origin_index * 7 + lead - 1):

    fc.tmax, fc.tmin, fc.rain_mm      integer tenths
    fc.p_rain                         integer thousandths
    fc.bust, fc.bust_t, fc.bust_r     integer ten-thousandths
    flags                             2 bits each: temperature bust, rain bust,
                                      within 2 C, rain correct (0 no, 1 yes, 2 n/a)
    obs.tmax, obs.tmin, obs.prcp      integer tenths, null where not reported
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import station_replay as S  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "frontend" / "sidecar"
FIRST_ORIGIN = S.TEST_START
LAST_ORIGIN = S.LAST_DAY - timedelta(days=max(S.LEADS))
HISTORY_DAYS = 6

_TRI = {False: 0, True: 1, None: 2}


def pack_flags(row: dict) -> int:
    return (
        _TRI[row["temperature_bust"]]
        | _TRI[row["rain_bust"]] << 2
        | _TRI[row["tmax_within_2c"]] << 4
        | _TRI[row["rain_correct"]] << 6
    )


def unpack_flags(value: int) -> dict[str, bool | None]:
    """Inverse of pack_flags. Mirrored exactly in frontend/src/lib/stationSidecar.ts."""
    decode = {0: False, 1: True, 2: None}
    return {
        "temperature_bust": decode[value & 3],
        "rain_bust": decode[(value >> 2) & 3],
        "tmax_within_2c": decode[(value >> 4) & 3],
        "rain_correct": decode[(value >> 6) & 3],
    }


def tenths_or_none(values: np.ndarray) -> list[int | None]:
    return [None if np.isnan(v) else int(round(float(v) * 10)) for v in values]


def export_station(station_id: str, models: dict) -> dict:
    origins = np.arange(S.day_index(FIRST_ORIGIN), S.day_index(LAST_ORIGIN) + 1)
    n = len(origins)
    threshold = float(models["card"]["thresholds"]["bust_any"])

    # Batch predictions, one lead at a time.
    per_lead = {}
    for lead in S.LEADS:
        x = S.feature_rows(station_id, origins, lead)
        fc = S.forecast_block(models, x, station_id, origins, lead)
        b = S.bust_inputs(x, fc, station_id, origins, lead)
        per_lead[lead] = {
            **fc,
            "bust": models["bust_any"].predict_proba(b)[:, 1],
            "bust_t": models["bust_temp"].predict_proba(b)[:, 1],
            "bust_r": models["bust_rain"].predict_proba(b)[:, 1],
        }

    arr = S.archive()[station_id]
    keys = ("tmax", "tmin", "rain_mm", "p_rain", "bust", "bust_t", "bust_r")
    fc_out: dict[str, list[int]] = {k: [0] * (n * 7) for k in keys}
    flags = [0] * (n * 7)

    for k, t in enumerate(origins):
        origin = S.index_day(int(t))
        for lead in S.LEADS:
            p = per_lead[lead]
            day = S.format_day(
                origin, lead, station_id,
                p["tmax"][k], p["tmin"][k], p["p_rain"][k], p["rain_mm"][k],
                p["bust"][k], p["bust_t"][k], p["bust_r"][k],
            )
            i = int(t) + lead
            scored = S.score_day(
                day,
                S._observed(arr["tmax"][i]),
                S._observed(arr["tmin"][i]),
                S._observed(arr["prcp"][i]),
                threshold,
            )
            row = k * 7 + lead - 1
            fc_out["tmax"][row] = int(round(day["tmax_c"] * 10))
            fc_out["tmin"][row] = int(round(day["tmin_c"] * 10))
            fc_out["rain_mm"][row] = int(round(day["rain_mm"] * 10))
            fc_out["p_rain"][row] = int(round(day["rain_probability"] * 1000))
            fc_out["bust"][row] = int(round(day["bust_probability"] * 10000))
            fc_out["bust_t"][row] = int(round(day["bust_probability_temperature"] * 10000))
            fc_out["bust_r"][row] = int(round(day["bust_probability_rain"] * 10000))
            flags[row] = pack_flags(scored)

    obs_first = int(origins[0]) - HISTORY_DAYS
    obs_last = S.day_index(S.LAST_DAY)
    clim = S.climatology(station_id)

    return {
        "v": 1,
        "station": S.stations_by_id()[station_id].__dict__,
        "origin0": FIRST_ORIGIN.isoformat(),
        "n": n,
        "obs0": S.index_day(obs_first).isoformat(),
        "obs": {
            "tmax": tenths_or_none(arr["tmax"][obs_first : obs_last + 1]),
            "tmin": tenths_or_none(arr["tmin"][obs_first : obs_last + 1]),
            "prcp": tenths_or_none(arr["prcp"][obs_first : obs_last + 1]),
        },
        "normals": {
            "tmax": [int(round(float(round(float(v), 1)) * 10)) for v in clim["tmax_mean"]],
            "tmin": [int(round(float(round(float(v), 1)) * 10)) for v in clim["tmin_mean"]],
            "rain_prob": [
                None if np.isnan(v) else int(round(float(round(float(v), 3)) * 1000))
                for v in clim["rain_prob"]
            ],
        },
        "thresholds": models["card"]["thresholds"],
        "forecast_note": models["card"]["forecast_note"],
        "fc": fc_out,
        "flags": flags,
        "station_page": S.station_page(station_id),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--station", help="export one station only")
    args = parser.parse_args()

    models = S._models()
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ids = [args.station] if args.station else [s.station_id for s in S.stations()]
    total = 0
    for sid in ids:
        payload = export_station(sid, models)
        path = args.out / f"station-{sid}.json"
        path.write_text(json.dumps(payload, separators=(",", ":")))
        total += path.stat().st_size
        print(f"  {sid}  {payload['n']:,} origins  {path.stat().st_size / 1_048_576:.2f} MB  ({time.time() - t0:.0f}s)")
    print(f"wrote {len(ids)} station files, {total / 1_048_576:.1f} MB, to {args.out}")


if __name__ == "__main__":
    main()
