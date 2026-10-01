"""Archived-forecast (hindcast) interface - Mode A.

A genuine *forecast bust* validation needs the forecast that busted. That means
an archived NWP run initialised on or before the origin date, valid across the
replay window: ECMWF/TIGGE ensemble fields, an NCMRWF NEPS archive, or an
agency reforecast set.

**No such archive is present in this repository.** Rather than approximate one,
this module defines the interface that would consume it and reports precisely
what is missing, so Mode A stays visibly unavailable instead of quietly
becoming something else.

Dropping a conforming file into ``data/hindcast/`` is all that is required to
make Mode A reachable; nothing downstream changes shape. Until then every
Mode A request returns ``available: false`` together with the exact list of
files it looked for.

Expected layout::

    data/hindcast/
        manifest.json                 # source, model, member count, licence
        <model>_<YYYYMMDD>.nc         # or .grib2 / .parquet - one per init

`manifest.json` schema::

    {
      "source": "TIGGE",                     # archive the data came from
      "model": "ecmwf-ens",                  # NWP model identifier
      "members": 51,                         # ensemble size (1 = deterministic)
      "variable": "rainfall",
      "unit": "mm/day",
      "initialisations": ["2016-09-04", ...],# init dates present
      "lead_days": 7,
      "reference": "https://apps.ecmwf.int/datasets/data/tigge/",
      "licence": "..."
    }

The reader itself is intentionally unimplemented. Writing a GRIB decoder
against a file format nobody has seen produces code that cannot be tested and
will be wrong; the honest deliverable is the contract plus a clear error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

HINDCAST_DIR = Path(__file__).resolve().parents[3] / "data" / "hindcast"
MANIFEST = HINDCAST_DIR / "manifest.json"

#: Archives that actually contain what Mode A needs, with the real access route.
#: These are documented routes, not live connections - see /api/sources.
CANDIDATE_ARCHIVES: tuple[dict[str, str], ...] = (
    {
        "id": "tigge",
        "name": "TIGGE multi-model ensemble archive",
        "covers": "2006 to present, ECMWF / NCEP / UKMO / JMA and others",
        "why": "The only free archive that actually holds historical ensemble "
        "members at medium range, which is what a bust label needs.",
        "reference": "https://apps.ecmwf.int/datasets/data/tigge/",
        "access": "Free registration, then MARS retrieval.",
    },
    {
        "id": "ecmwf-reforecast",
        "name": "ECMWF reforecast / ERA5 ensemble",
        "covers": "1940 to present (ERA5); reforecasts back 20 years",
        "why": "Reanalysis for the verifying fields, reforecasts for the runs.",
        "reference": "https://cds.climate.copernicus.eu/",
        "access": "CDS API key.",
    },
    {
        "id": "ncmrwf-ncum",
        "name": "NCMRWF NCUM / NEPS archive",
        "covers": "Indian domain, operational archive",
        "why": "The operational Indian model, so busts are the ones IMD forecasters saw.",
        "reference": "https://www.ncmrwf.gov.in/",
        "access": "Institutional request.",
    },
)


@dataclass(frozen=True)
class HindcastManifest:
    source: str
    model: str
    members: int
    variable: str
    unit: str
    initialisations: tuple[date, ...]
    lead_days: int
    reference: str
    licence: str


@dataclass(frozen=True)
class HindcastAvailability:
    """What Mode A has, and precisely what it is missing."""

    available: bool
    reason: str
    manifest: HindcastManifest | None = None
    #: Initialisation dates the request needed but the archive does not hold.
    missing_initialisations: tuple[str, ...] = ()
    #: Files the loader looked for and did not find.
    looked_for: tuple[str, ...] = ()
    candidates: tuple[dict[str, str], ...] = field(default=CANDIDATE_ARCHIVES)


class HindcastUnavailable(RuntimeError):
    """Raised when Mode A is requested and no archived forecast exists."""


def load_manifest() -> HindcastManifest | None:
    if not MANIFEST.is_file():
        return None
    try:
        raw = json.loads(MANIFEST.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return HindcastManifest(
            source=str(raw["source"]),
            model=str(raw["model"]),
            members=int(raw["members"]),
            variable=str(raw.get("variable", "rainfall")),
            unit=str(raw.get("unit", "mm/day")),
            initialisations=tuple(
                date.fromisoformat(d) for d in raw.get("initialisations", [])
            ),
            lead_days=int(raw.get("lead_days", 7)),
            reference=str(raw.get("reference", "")),
            licence=str(raw.get("licence", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def availability(origin: date | None = None) -> HindcastAvailability:
    """Whether Mode A can run, and if not, exactly what is missing."""
    manifest = load_manifest()
    if manifest is None:
        return HindcastAvailability(
            available=False,
            reason=(
                "No archived NWP forecast is present. Mode A validates a real "
                "forecast against what was observed, so it needs the forecast "
                "itself - an ensemble or deterministic run initialised on or "
                "before the origin date. None exists in this repository, and "
                "none can be reconstructed from observations without inventing "
                "it. Mode A is therefore unavailable, not approximated."
            ),
            looked_for=(str(MANIFEST.relative_to(MANIFEST.parents[2])),),
        )

    if origin is None:
        return HindcastAvailability(available=True, reason="Archive present.", manifest=manifest)

    if origin not in manifest.initialisations:
        return HindcastAvailability(
            available=False,
            reason=(
                f"The archive holds no run initialised {origin.isoformat()}. "
                "Mode A cannot verify a forecast that was never archived."
            ),
            manifest=manifest,
            missing_initialisations=(origin.isoformat(),),
        )
    return HindcastAvailability(available=True, reason="Archive covers this origin.", manifest=manifest)


def ensemble(origin: date, location_id: str, lead_days: int = 7):
    """Archived ensemble members for one site and initialisation.

    Unimplemented by design: there is no file to read. When an archive is
    supplied this returns an (n_members, lead_days) array and the replay engine
    switches to Mode A with no other change.
    """
    state = availability(origin)
    if not state.available:
        raise HindcastUnavailable(state.reason)
    raise NotImplementedError(
        "A hindcast manifest is present but the decoder for its file format has "
        "not been written. Implement it here against the manifest's `source` "
        "and `model`; the replay engine expects an (n_members, lead_days) array "
        "in the manifest's `unit`."
    )


def requirements(origin: date, lead_days: int = 7) -> dict[str, object]:
    """A plain statement of what Mode A needs for one specific origin."""
    valid = [(origin + timedelta(days=d)).isoformat() for d in range(1, lead_days + 1)]
    return {
        "origin": origin.isoformat(),
        "valid_days": valid,
        "needs": [
            {
                "item": "Archived NWP forecast",
                "detail": f"Ensemble or deterministic run initialised on or before "
                f"{origin.isoformat()}, valid through {valid[-1]}.",
                "present": load_manifest() is not None,
                "path": "data/hindcast/",
            },
            {
                "item": "Daily observed rainfall",
                "detail": f"Observations for {valid[0]} to {valid[-1]} to verify against.",
                "present": None,  # answered by the replay engine against the real archive
                "path": "data/imd_district_daily_rainfall.csv",
            },
        ],
        "candidates": list(CANDIDATE_ARCHIVES),
    }
