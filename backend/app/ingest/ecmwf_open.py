"""Fetch real ensemble forecasts from ECMWF open data.

This is the one that matters. AtmosGuard reconstructs its ensemble because no
archive of real members was available; ECMWF publishes its 51-member ensemble
openly, at 0.25 degrees, with no registration. Wiring this in removes the last
modelled component from the system.

    pip install ecmwf-opendata cfgrib xarray
    python -m app.ingest.download --source ecmwf-open-data

Two things to know before relying on it:

* **Only a few days are retained.** Building a training archive means collecting
  daily and keeping your own copy. For history, use TIGGE instead.
* **It is GRIB2.** Reading it needs `cfgrib`, which needs the ECCODES system
  library. On Debian or Ubuntu: `apt-get install libeccodes0`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

#: Total precipitation, 2 m temperature, 10 m winds, mean sea level pressure -
#: the four fields the dashboard works in, in ECMWF's short names.
DEFAULT_PARAMS = ("tp", "2t", "10u", "10v", "msl")

#: Lead times in hours: every 6 h out to ten days, which covers the Day 3-7
#: window with room either side.
DEFAULT_STEPS = tuple(range(0, 241, 6))

#: India and its surrounding seas, as (north, west, south, east).
INDIA_BBOX = (38.0, 66.0, 5.0, 100.0)


@dataclass(frozen=True)
class Request:
    """One ensemble retrieval."""

    run_date: date
    #: Model cycle in UTC. ECMWF runs 00 and 12 for the ensemble.
    cycle: int = 0
    params: tuple[str, ...] = DEFAULT_PARAMS
    steps: tuple[int, ...] = DEFAULT_STEPS
    #: "enfo" is the ensemble; "oper" the deterministic high-resolution run.
    stream: str = "enfo"

    def target(self, directory: Path) -> Path:
        return directory / (
            f"ecmwf_{self.stream}_{self.run_date:%Y%m%d}_{self.cycle:02d}z.grib2"
        )


def describe(request: Request) -> dict[str, object]:
    """The request as a plain dict - useful for logging and for tests."""
    return {
        "stream": request.stream,
        "date": request.run_date.isoformat(),
        "time": request.cycle,
        "params": list(request.params),
        "steps": list(request.steps),
        "type": "pf" if request.stream == "enfo" else "fc",
    }


def download(request: Request, directory: Path) -> Path:
    """Retrieve one cycle into ``directory`` and return the file path.

    Uses ECMWF's own client rather than hand-rolling the index protocol: the
    open-data layout has moved before, and the client tracks it.
    """
    try:
        from ecmwf.opendata import Client
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "ecmwf-opendata is not installed. Run: pip install ecmwf-opendata"
        ) from exc

    directory.mkdir(parents=True, exist_ok=True)
    target = request.target(directory)
    if target.exists():
        return target

    client = Client(source="ecmwf")
    client.retrieve(
        date=request.run_date,
        time=request.cycle,
        stream=request.stream,
        type="pf" if request.stream == "enfo" else "fc",
        param=list(request.params),
        step=list(request.steps),
        target=str(target),
    )
    return target


def to_site_series(
    grib_path: Path,
    sites: list[tuple[str, float, float]],
    param: str = "tp",
) -> dict[str, list[list[float]]]:
    """Read a GRIB file and pull out per-site ensemble series.

    Returns ``{site_id: [[member_0 by step], [member_1 by step], ...]}``, which
    is the shape `app/core/synthetic.EnsembleForecast` expects - so this is the
    seam where real data replaces the reconstruction.

    Nearest-neighbour sampling is used deliberately: at 0.25 degrees a grid box
    is about 28 km, and interpolating precipitation between boxes smooths away
    exactly the convective peaks that cause busts.
    """
    try:
        import xarray as xr
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("xarray and cfgrib are required to read GRIB files.") from exc

    dataset = xr.open_dataset(grib_path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    field = dataset[param]

    out: dict[str, list[list[float]]] = {}
    for site_id, lat, lon in sites:
        point = field.sel(latitude=lat, longitude=lon, method="nearest")
        # Dimension order varies with how the file was written.
        if "number" in point.dims:
            point = point.transpose("number", "step")
            out[site_id] = [[float(v) for v in member] for member in point.values]
        else:
            out[site_id] = [[float(v) for v in point.values]]
    return out
