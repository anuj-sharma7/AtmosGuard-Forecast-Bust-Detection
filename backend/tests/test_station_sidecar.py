"""Tests for the static-build station sidecar.

The full browser-side parity check (every field, 1,000+ replays, compiled
TypeScript) lives in `scripts/check_sidecar_parity.py`, because it needs Node.
These cover the Python half: the packing is lossless, and what is packed is
exactly what the API publishes.
"""

from __future__ import annotations

import itertools
from datetime import date, timedelta

import pytest

from app.api.routes import stations_replay
from app.core import station_replay as S
from scripts import export_station_sidecar as E

DELHI = "IN022021900"


@pytest.mark.parametrize(
    "flags",
    [
        dict(zip(("temperature_bust", "rain_bust", "tmax_within_2c", "rain_correct"), combo))
        for combo in itertools.product((False, True, None), repeat=4)
    ],
)
def test_flag_packing_is_lossless(flags):
    assert E.unpack_flags(E.pack_flags(flags)) == flags


@pytest.fixture(scope="module")
def delhi():
    return E.export_station(DELHI, S._models())


def test_sidecar_covers_every_origin_2010_2021(delhi):
    assert delhi["origin0"] == "2010-01-01"
    last = date.fromisoformat(delhi["origin0"]) + timedelta(days=delhi["n"] - 1)
    assert last == date(2021, 12, 24)
    assert len(delhi["fc"]["tmax"]) == delhi["n"] * 7
    assert len(delhi["flags"]) == delhi["n"] * 7


@pytest.mark.parametrize("day", ["2010-01-01", "2015-08-17", "2016-02-29", "2019-06-30", "2021-12-24"])
def test_packed_values_are_what_the_api_publishes(delhi, day):
    api = stations_replay(on=day, station=DELHI)
    k = (date.fromisoformat(day) - date.fromisoformat(delhi["origin0"])).days
    for f, v in zip(api["forecast"], api["validation"]["rows"]):
        row = k * 7 + f["lead"] - 1
        assert delhi["fc"]["tmax"][row] / 10 == f["tmax_c"]
        assert delhi["fc"]["tmin"][row] / 10 == f["tmin_c"]
        assert delhi["fc"]["rain_mm"][row] / 10 == f["rain_mm"]
        assert delhi["fc"]["p_rain"][row] / 1000 == f["rain_probability"]
        assert delhi["fc"]["bust"][row] / 10000 == f["bust_probability"]
        flags = E.unpack_flags(delhi["flags"][row])
        for name in ("temperature_bust", "rain_bust", "tmax_within_2c", "rain_correct"):
            assert flags[name] == v[name], (day, f["lead"], name)


def test_missing_observations_are_null_not_zero(delhi):
    assert None in delhi["obs"]["prcp"]
    assert 0 in delhi["obs"]["prcp"]
