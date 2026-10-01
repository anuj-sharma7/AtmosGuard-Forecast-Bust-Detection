"""Origin-guarded access to the observational archive.

The one rule this module exists to enforce: **a prediction made at origin date
T may read only data dated on or before T.** Anything valid at T+1 or later is
the answer, and reading the answer while forming the question is how backtests
come to report skill they do not have.

Convention is not enough for that. A comment saying "careful, don't read the
future here" survives exactly as long as the person who wrote it. So the guard
is structural: `Archive(origin=T)` physically refuses a read beyond T and
raises `LeakageError`. The validation phase uses a different object,
`Outcomes`, which reads T+1..T+7 and cannot produce features.

    archive  = Archive(origin=T)          # prediction phase   (<= T)
    outcomes = Outcomes(origin=T)         # validation phase   (>  T)

Nothing in this module fabricates a value. Every accessor returns `None` when
the published record does not cover the day asked for, and the caller is
expected to report the gap rather than fill it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

from . import imd
from .domain import ALL_SITES_BY_ID, Location


class LeakageError(RuntimeError):
    """Raised when the prediction phase tries to read beyond its origin date."""


@dataclass(frozen=True)
class SiteDay:
    """One site-day of real observed rainfall, as published by IMD."""

    day: date
    actual: float
    normal: float
    departure_pct: float | None
    #: IMD's own departure category, or the one derived from the published
    #: departure for area-mean (region) sites. Never invented.
    category: str
    #: How many districts the value is averaged over. 1 for a point site.
    districts: int


def _departure(actual: float, normal: float) -> float | None:
    if normal <= 0.0:
        return None
    return (actual - normal) / normal * 100.0


@lru_cache(maxsize=65536)
def _site_day(location_id: str, day: date) -> SiteDay | None:
    """Real observed rainfall for one site on one day, or None if not covered.

    Point sites read their own reporting district. Region sites have no single
    district, so they read the area mean over every district in the state that
    reported that day - which is how a sub-divisional rainfall figure is
    actually constructed.
    """
    site: Location | None = ALL_SITES_BY_ID.get(location_id)
    if site is None:
        return None

    if site.obs_district:
        row = imd.district_observation(site.obs_state, site.obs_district, day)
        if row is None:
            return None
        return SiteDay(
            day=day,
            actual=row.actual,
            normal=row.normal,
            departure_pct=row.departure_pct,
            category=imd.CATEGORY_LABELS.get(row.category, row.category or "No Data"),
            districts=1,
        )

    area = imd.state_observation(site.obs_state, day)
    if area is None:
        return None
    actual, normal, count = area
    departure = _departure(actual, normal)
    # climate.categorise applies IMD's own published category bounds to the
    # departure. Imported lazily: climate imports nothing from here, but the
    # local import keeps the dependency one-directional and obvious.
    from . import climate

    return SiteDay(
        day=day,
        actual=actual,
        normal=normal,
        departure_pct=departure,
        category=climate.categorise(departure) if departure is not None else "No Data",
        districts=count,
    )


@lru_cache(maxsize=4096)
def _state_day(state: str, day: date) -> tuple[float, float, int] | None:
    return imd.state_observation(state, day)


@dataclass(frozen=True)
class Archive:
    """Read-only view of the observational record up to and including `origin`.

    Every accessor checks the requested day against the origin first. A read
    past it is a programming error, not a missing value, so it raises rather
    than returning None - a silent None would be indistinguishable from a real
    coverage gap and would hide the bug it is meant to catch.
    """

    origin: date

    def _check(self, day: date) -> None:
        if day > self.origin:
            raise LeakageError(
                f"prediction phase tried to read {day.isoformat()}, which is after "
                f"origin {self.origin.isoformat()}. Features may use only data <= T."
            )

    def observation(self, location_id: str, day: date) -> SiteDay | None:
        self._check(day)
        return _site_day(location_id, day)

    def history(self, location_id: str, days: int) -> list[SiteDay]:
        """The last `days` observations ending at the origin, oldest first.

        Days the published record does not cover are omitted, not filled. A
        short list means the archive is short; the caller decides what to do
        about it.
        """
        if days < 1:
            return []
        out: list[SiteDay] = []
        for back in range(days - 1, -1, -1):
            row = _site_day(location_id, self.origin - timedelta(days=back))
            if row is not None:
                out.append(row)
        return out

    def state_wet_fraction(self, state: str, day: date) -> float | None:
        """Share of a state's reporting districts running Large Excess that day.

        Spatial context available at the origin: a site sitting inside an
        already-active system is in a different situation from an isolated one.
        """
        self._check(day)
        rows = imd._by_state().get(imd.normalise_state(state), {}).get(day)
        if not rows:
            return None
        wet = sum(1 for r in rows if (r.category or "").upper() == "LE")
        return wet / len(rows)

    def state_anomaly(self, state: str, day: date) -> float | None:
        """State area-mean departure from normal, as a ratio (1.0 = normal)."""
        self._check(day)
        area = _state_day(imd.normalise_state(state), day)
        if area is None:
            return None
        actual, normal, _ = area
        return actual / normal if normal > 0.0 else None


@dataclass(frozen=True)
class Outcomes:
    """Read-only view of what actually happened *after* an origin date.

    Deliberately a separate type with no feature-building methods on it. The
    validation phase holds one of these; the prediction phase never does.
    """

    origin: date

    def actual(self, location_id: str, day: date) -> SiteDay | None:
        if day <= self.origin:
            raise LeakageError(
                f"validation phase asked for {day.isoformat()}, which is not after "
                f"origin {self.origin.isoformat()}. Verify T+1 onward only."
            )
        return _site_day(location_id, day)


@lru_cache(maxsize=1)
def coverage() -> tuple[date, date]:
    """First and last day the daily observational archive actually covers."""
    return imd.observation_window()


def covers(day: date) -> bool:
    start, end = coverage()
    return start <= day <= end


def missing_days(days: list[date]) -> list[date]:
    """Which of these days the archive does not cover. Empty means all present."""
    return [d for d in days if not covers(d)]
