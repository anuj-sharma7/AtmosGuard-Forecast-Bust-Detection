"""Export a static snapshot of the API for a backend-free deployment.

    python -m scripts.export_snapshot            # writes frontend/snapshot.json

Fetches every combination the shared preview should support and writes them
under canonical keys (path + alphabetically sorted query), which is what
`frontend/src/api/client.ts` looks up when a snapshot is embedded.

Scope is deliberate rather than exhaustive: every site for rainfall (the
variable the model is actually fitted on), plus the other variables and models
for the ten featured cities. A full cross-product would be 3,000 payloads and
tens of megabytes to serve a preview.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from app.config import settings
from app.core import service, verification
from app.core.alerts import ALERT_PROBABILITY, ALERT_THRESHOLD, network_summary, scan
from app.core.domain import ALL_SITES, DETERMINISTIC_MODEL_IDS, LOCATIONS, VARIABLES
from app.core.scenarios import SCENARIOS
from app.api.routes import (
    HORIZONS,
    data_sources,
    meta,
    monthly_meta,
    monthly_model_card,
    monthly_replay,
    replay_model_card,
    stations_meta,
    stations_model_card,
    stations_replay,
    replay_origins,
)
from app.core import monthly as monthly_core
from app.core import replay
from app.core import climate
from app.core import warnings as warnings_core

#: Replay origins embedded in the static preview. Each one costs a run
#: payload per site, which dominates the snapshot size.
SNAPSHOT_ORIGINS = 3

#: Months embedded for the monthly replay. Every held-out monsoon month of
#: 2015 and the years around it, plus the dates people tend to ask about -
#: each is one payload covering all 36 sub-divisions.
SNAPSHOT_MONTHS = tuple(
    f"{year}-{month:02d}-01"
    for year in range(monthly_core.TEST_FROM_YEAR, 2018)
    for month in range(6, 10)
)

#: Origins embedded for the 7-day station replay, for every station. The
#: dates asked about, plus one monsoon date per held-out year - including the
#: weeks before the June 2013 Uttarakhand and September 2014 Kashmir floods.
#: The live API serves every day from 2010-01-01 to 2017-12-24.
SNAPSHOT_STATION_DATES = (
    "2015-08-17", "2015-08-05", "2010-07-15", "2011-08-01", "2012-09-01",
    "2013-06-14", "2014-09-01", "2016-07-20", "2017-08-10",
    "2018-08-15", "2019-07-01", "2020-08-17", "2021-06-10",
)

OUTPUT = Path(__file__).resolve().parents[2] / "frontend" / "snapshot.json"

#: Grouped payload files served next to a published build. The page finds them
#: through the "__sidecar__" manifest embedded in the snapshot. A single-file
#: build has none and falls back to the dates embedded below.
SIDECAR_DIR = OUTPUT.parent / "sidecar"

OTHER_MODELS = (*DETERMINISTIC_MODEL_IDS, "ensemble")


def key(path: str, params: dict[str, object]) -> str:
    items = sorted((k, str(v)) for k, v in params.items() if v not in (None, ""))
    query = "&".join(f"{k}={v}" for k, v in items)
    return f"{path}?{query}" if query else path


def main() -> None:
    base_iso = settings.demo_reference_date
    base = date.fromisoformat(base_iso)
    snap: dict[str, object] = {}

    snap["/meta"] = meta()
    snap["/sources"] = data_sources()

    # Climate context is per site and independent of the forecast selection.
    for site in ALL_SITES:
        profile = climate.profile(site.subdivision)
        if profile is not None:
            snap[f"/climate/{site.id}"] = {
                **profile,
                "location_id": site.id,
                "location_name": site.name,
            }

    def add_risk(location: str, variable: str, model: str, horizon: int) -> None:
        snap[
            key(
                "/risk",
                {
                    "location": location,
                    "variable": variable,
                    "model": model,
                    "horizon": horizon,
                    "forecast_date": base_iso,
                },
            )
        ] = service.risk_bundle(location, variable, model, base, horizon)

    # Every monitored site, for rainfall - the variable the model is fitted on.
    for site in ALL_SITES:
        for horizon in HORIZONS:
            add_risk(site.id, "rainfall", "ecmwf", horizon)

    # Featured cities: the other variables, and the other models.
    for site in LOCATIONS:
        for variable in VARIABLES:
            if variable.id != "rainfall":
                for horizon in HORIZONS:
                    add_risk(site.id, variable.id, "ecmwf", horizon)
        for model in OTHER_MODELS:
            if model != "ecmwf":
                for horizon in HORIZONS:
                    add_risk(site.id, "rainfall", model, horizon)

    # Curated scenarios may sit on other dates.
    for scenario in SCENARIOS:
        scenario_date = date.fromisoformat(scenario.base_date)
        snap[f"/scenario/{scenario.id}"] = service.resolve_scenario(scenario.id)
        snap[
            key(
                "/risk",
                {
                    "location": scenario.location_id,
                    "variable": scenario.variable_id,
                    "model": scenario.model_id,
                    "horizon": scenario.horizon,
                    "forecast_date": scenario.base_date,
                },
            )
        ] = service.risk_bundle(
            scenario.location_id,
            scenario.variable_id,
            scenario.model_id,
            scenario_date,
            scenario.horizon,
        )

    # Network views behind the map and the KPI strip.
    def add_network(variable: str, model: str, horizon: int, when: str) -> None:
        summary = network_summary(when, variable, horizon, model)
        snap[
            key(
                "/network",
                {"variable": variable, "model": model, "horizon": horizon, "forecast_date": when},
            )
        ] = {
            **summary,
            "variable_id": variable,
            "horizon": horizon,
            "model_id": model,
            "base_date": when,
            "data_mode": settings.data_mode,
            "demo_notice": service.DEMO_NOTICE if settings.is_demo else None,
        }

    dates = {base_iso, *(s.base_date for s in SCENARIOS)}
    for when in dates:
        for horizon in HORIZONS:
            for variable in VARIABLES:
                add_network(variable.id, "ecmwf", horizon, when)
            for model in OTHER_MODELS:
                if model != "ecmwf":
                    add_network("rainfall", model, horizon, when)

    # Warning map, per lead time.
    for when in dates:
        when_date = date.fromisoformat(when)
        for horizon in HORIZONS:
            states = warnings_core.state_warnings(when_date, horizon, "ecmwf")
            snap[
                key("/warnings", {"model": "ecmwf", "horizon": horizon, "forecast_date": when})
            ] = {
                "states": states,
                **warnings_core.summary(states),
                "base_date": when,
                "valid_date": (when_date + timedelta(days=horizon)).isoformat(),
                "horizon": horizon,
                "model_id": "ecmwf",
                "data_mode": settings.data_mode,
                "demo_notice": service.DEMO_NOTICE if settings.is_demo else None,
            }

    # Alerts, verification and system status.
    for when in dates:
        items = list(scan(when, "ecmwf"))
        counts = {"LOW": 0, "MODERATE": 0, "HIGH": 0, "SEVERE": 0}
        for item in items:
            counts[str(item["severity"])] += 1
        payload = {
            "alerts": items,
            "counts": counts,
            "threshold": ALERT_THRESHOLD,
            "probability_threshold": ALERT_PROBABILITY,
            "base_date": when,
            "data_mode": settings.data_mode,
            "demo_notice": service.DEMO_NOTICE if settings.is_demo else None,
            "disclaimer": service.DISCLAIMER,
        }
        snap[key("/alerts", {"forecast_date": when})] = payload
        for severity in ("SEVERE", "HIGH"):
            snap[key("/alerts", {"forecast_date": when, "severity": severity})] = {
                **payload,
                "alerts": [a for a in items if a["severity"] == severity],
            }

        when_date = date.fromisoformat(when)
        snap[key("/verification/model", {"forecast_date": when})] = {
            "model_performance": verification.model_performance(when_date),
            "label": "Fitted on real IMD observations",
            "data_mode": settings.data_mode,
            "demo_notice": service.DEMO_NOTICE if settings.is_demo else None,
            "disclaimer": service.DISCLAIMER,
        }
        snap[key("/system/status", {"forecast_date": when})] = service.system_status(when_date)

    # Historical replay. The backtest and the model card are selection-
    # independent; the per-origin runs are exported for every usable origin so
    # the static build can walk the whole archive, not just one date.
    snap["/replay/backtest"] = replay.backtest()
    snap["/replay/model"] = replay_model_card()

    # A run payload per origin per site is the largest thing in this file, so
    # the static preview carries the most recent SNAPSHOT_ORIGINS of them and
    # says so in the origins listing. The live API serves the whole archive.
    all_origins = replay.usable_origins()
    listing = replay_origins()
    # Export a block ending at the default origin, so the static preview opens
    # on a window that can actually be verified end to end rather than on six
    # empty rows.
    default_iso = listing["default"]
    cutoff = (
        all_origins.index(date.fromisoformat(str(default_iso))) + 1
        if default_iso
        else len(all_origins)
    )
    exported = all_origins[max(0, cutoff - SNAPSHOT_ORIGINS) : cutoff]
    listing["origins"] = [d.isoformat() for d in exported]
    listing["count"] = len(exported)
    listing["note"] = (
        f"Static preview: {len(exported)} of {len(all_origins)} usable origins "
        f"are embedded ({exported[0]} to {exported[-1]}), chosen so the whole "
        "7-day window can be verified. Run the full application for the rest. "
        + str(listing["note"])
    )
    snap["/replay/origins"] = listing

    for origin in exported:
        iso = origin.isoformat()
        snap[key("/replay/availability", {"origin": iso})] = replay.availability(origin)
        for site in ALL_SITES:
            snap[
                key("/replay/run", {"location_id": site.id, "origin": iso})
            ] = replay.replay_window(origin, site.id)

    # Monthly replay. One payload per exported month covers all 36
    # sub-divisions, so a handful of well-known months is cheap and lets the
    # static preview answer the question people actually arrive with.
    snap["/monthly/meta"] = monthly_meta()
    snap["/monthly/model"] = monthly_model_card()
    for iso in SNAPSHOT_MONTHS:
        snap[key("/monthly/replay", {"on": iso})] = monthly_replay(on=iso, subdivision=None)

    # 7-day station replay. The preview dates are advertised in the meta so
    # the static page can offer them, rather than letting a reader pick a date
    # this file does not carry.
    station_meta = stations_meta()
    station_meta["preview_dates"] = list(SNAPSHOT_STATION_DATES)
    snap["/stations/meta"] = station_meta
    snap["/stations/model"] = stations_model_card()
    # Embedded as a fallback for a single-file copy, which has no sidecars:
    # the headline date for every station, and every quick pick for the
    # default station. A published build rebuilds any date from its sidecars.
    embedded = {(SNAPSHOT_STATION_DATES[0], st["station_id"]) for st in station_meta["stations"]}
    embedded |= {(iso, station_meta["default_station"]) for iso in SNAPSHOT_STATION_DATES}
    for iso, sid in sorted(embedded):
        snap[key("/stations/replay", {"on": iso, "station": sid})] = stations_replay(on=iso, station=sid)

    # ---------------------------------------------------------------- sidecars
    # Every date the embedded snapshot leaves out, grouped into files the
    # published page fetches on demand.
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}

    def write_group(name: str, payloads: dict[str, object]) -> None:
        (SIDECAR_DIR / name).write_text(json.dumps(payloads, separators=(",", ":")))
        for k in payloads:
            manifest[k] = name

    # Monthly replay: all twelve months of every held-out year.
    for year in range(monthly_core.TEST_FROM_YEAR, monthly_core.record_span()[1] + 1):
        write_group(
            f"monthly-{year}.json",
            {
                key("/monthly/replay", {"on": f"{year}-{m:02d}-01"}): monthly_replay(
                    on=f"{year}-{m:02d}-01", subdivision=None
                )
                for m in range(1, 13)
            },
        )

    # 2026 validation: every usable origin, every site.
    for origin in all_origins:
        iso = origin.isoformat()
        group = {key("/replay/availability", {"origin": iso}): replay.availability(origin)}
        for site in ALL_SITES:
            group[key("/replay/run", {"location_id": site.id, "origin": iso})] = replay.replay_window(
                origin, site.id
            )
        write_group(f"replay-{iso}.json", group)

    # With sidecars, every origin is reachable, so the listing offers them all.
    full_listing = replay_origins()
    full_listing["note"] = (
        f"{len(all_origins)} usable origins. A single-file copy embeds "
        f"{len(exported)} of them ({exported[0]} to {exported[-1]}); the published "
        "preview loads the rest from its data files. " + str(replay_origins()["note"])
    )
    snap["/replay/origins"] = full_listing

    # A static page cannot call IMD, and must not look as if it had.
    snap["/imd/live"] = {
        "state": "static",
        "message": "This is a static preview: it makes no live calls. Run the backend on the "
        "server whose public IP is registered with the IMD key, and this panel shows real "
        "IMD city forecasts - or exactly why it cannot.",
        "checked_at": "",
        "endpoint": "https://api.imd.gov.in/api/v1/cityforecast",
        "cities": [],
        "matched": {},
    }

    snap["__sidecar__"] = {"files": manifest}
    print(f"sidecar manifest: {len(manifest):,} payloads in {len(set(manifest.values()))} files")

    OUTPUT.write_text(json.dumps(snap, separators=(",", ":")))
    size = OUTPUT.stat().st_size
    print(f"{len(snap):,} endpoints -> {OUTPUT.name}  ({size / 1_048_576:.1f} MB)")


if __name__ == "__main__":
    main()
