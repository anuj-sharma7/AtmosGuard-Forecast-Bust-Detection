"""Build the bundled India basemap from DataMeet's boundary shapefile.

    python -m scripts.build_basemap

Why a bundled basemap at all: the map's tile layer needs an external CDN, and an
operations room may not have one - or may be behind a policy that blocks it. A
map that degrades to markers floating on an empty background is useless exactly
when it matters, so the country is drawn from geometry shipped with the app.

Source
------
DataMeet's ``States/Admin2`` shapefile - 36 states and union territories in
WGS84, about 1.07 million vertices. Licensed CC BY 4.0, which is why it is used
here in preference to the several unlicensed India GeoJSON repositories doing
the rounds: those carry no rights grant at all, and a couple explicitly disclaim
accuracy.

    India boundaries by the DataMeet India community, CC BY 4.0
    https://github.com/datameet/maps

Simplification
--------------
A million vertices is three orders of magnitude more than a national-scale
dashboard can show. Ramer-Douglas-Peucker reduces each ring to the points that
carry its shape, then coordinates are rounded to three decimals - about 110 m,
which is far finer than a 0.25 degree forecast grid and invisible at any zoom
this map opens at.

Small rings are dropped, with one exception that matters: the largest ring of
every state is always kept. Without that, island territories - Lakshadweep,
parts of Andaman and Nicobar - vanish from the map entirely, which would be both
wrong and, for a map of India, unacceptable.

A boundary note
---------------
This is a cartographic aid for locating forecast points, not an authoritative
boundary. Official boundaries of India are published by the Survey of India, and
anything with legal or official standing must come from there.
"""

from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

try:
    import shapefile  # pyshp
except ImportError:  # pragma: no cover - build-time only
    raise SystemExit("pyshp is required: pip install pyshp")

SOURCE_DIR = Path(__file__).resolve().parents[2] / "data" / "boundaries"
OUTPUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "india-basemap.json"

#: The shapefile is ~17 MB, so it is fetched on demand rather than committed.
#: Only the 126 KB simplified result belongs in the repository.
SOURCE_BASE = "https://raw.githubusercontent.com/datameet/maps/master/States/Admin2"
SOURCE_EXTENSIONS = ("shp", "dbf", "shx", "prj")


def ensure_source() -> None:
    """Download the DataMeet shapefile if it is not already present."""
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    for extension in SOURCE_EXTENSIONS:
        target = SOURCE_DIR / f"Admin2.{extension}"
        if target.exists():
            continue
        url = f"{SOURCE_BASE}.{extension}"
        print(f"  fetching {url}")
        with urllib.request.urlopen(url, timeout=300) as response:
            target.write_bytes(response.read())

#: Douglas-Peucker tolerance in degrees. 0.02 is roughly 2 km - the coastline
#: stays recognisable while the vertex count falls by about 99%.
TOLERANCE = 0.02

#: Rings whose bounding box is smaller than this (square degrees) are dropped,
#: unless they are the largest ring of their state.
MIN_RING_EXTENT = 0.02

#: Three decimals is about 110 m. The forecast grid is 0.25 degrees.
PRECISION = 3


def perpendicular_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    if start == end:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    cross = abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0])
    return cross / length


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker, iterative so long coastlines cannot blow the stack."""
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        first, last = stack.pop()
        worst, index = 0.0, first
        for i in range(first + 1, last):
            distance = perpendicular_distance(points[i], points[first], points[last])
            if distance > worst:
                worst, index = distance, i
        if worst > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))

    return [p for p, k in zip(points, keep) if k]


def label_point(rings: list[list[list[float]]]) -> list[float]:
    """A point inside the state, for placing its hazard glyph.

    The area centroid of the largest ring, nudged back inside if the state is
    concave enough that its centroid falls outside the polygon - Gujarat and
    Maharashtra both do. Falls back to the vertex mean, which is always inside
    the convex hull.
    """
    biggest = max(rings, key=lambda r: ring_extent([(x, y) for x, y in r]))
    xs = [p[0] for p in biggest]
    ys = [p[1] for p in biggest]

    # Shoelace centroid.
    area = cx = cy = 0.0
    for i in range(len(biggest) - 1):
        cross = xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
        area += cross
        cx += (xs[i] + xs[i + 1]) * cross
        cy += (ys[i] + ys[i + 1]) * cross

    if abs(area) < 1e-9:
        return [round(sum(xs) / len(xs), 3), round(sum(ys) / len(ys), 3)]

    area *= 0.5
    centroid = [cx / (6.0 * area), cy / (6.0 * area)]
    if point_in_ring(centroid, biggest):
        return [round(centroid[0], 3), round(centroid[1], 3)]
    return [round(sum(xs) / len(xs), 3), round(sum(ys) / len(ys), 3)]


def point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    """Ray casting. Used only to sanity-check a centroid."""
    x, y = point
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            inside = not inside
    return inside


def ring_extent(points: list[tuple[float, float]]) -> float:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def rings_of(shape) -> list[list[tuple[float, float]]]:
    """Split a possibly multi-part shapefile shape into its rings."""
    points = [(float(x), float(y)) for x, y in shape.points]
    starts = list(shape.parts) + [len(points)]
    return [points[starts[i] : starts[i + 1]] for i in range(len(starts) - 1)]


def build() -> dict:
    ensure_source()
    reader = shapefile.Reader(str(SOURCE_DIR / "Admin2"))
    fields = [f[0] for f in reader.fields[1:]]
    name_field = fields.index("ST_NM")

    states: list[dict] = []
    raw_points = kept_points = 0

    for record, shape in zip(reader.records(), reader.shapes()):
        name = str(record[name_field]).strip()
        simplified: list[list[list[float]]] = []
        biggest: tuple[float, list[list[float]]] | None = None

        for ring in rings_of(shape):
            raw_points += len(ring)
            extent = ring_extent(ring)
            reduced = simplify(ring, TOLERANCE)
            if len(reduced) < 4:
                continue
            rounded = [[round(x, PRECISION), round(y, PRECISION)] for x, y in reduced]

            if biggest is None or extent > biggest[0]:
                biggest = (extent, rounded)
            if extent >= MIN_RING_EXTENT:
                simplified.append(rounded)

        # Never let a state disappear because all its land is small islands.
        if not simplified and biggest is not None:
            simplified.append(biggest[1])

        kept_points += sum(len(r) for r in simplified)
        if simplified:
            # Emitted as GeoJSON rather than a bespoke shape: it is what Leaflet
            # already reads, so no coordinate order has to be swapped by hand -
            # a classic source of maps that render sideways into the ocean.
            states.append(
                {
                    "type": "Feature",
                    "properties": {"st_nm": name, "label_point": label_point(simplified)},
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [[ring] for ring in simplified],
                    },
                }
            )

    states.sort(key=lambda f: f["properties"]["st_nm"])
    return {
        "type": "FeatureCollection",
        "features": states,
        "meta": {
            "source": "DataMeet India community - States/Admin2",
            "source_url": "https://github.com/datameet/maps",
            "licence": "CC BY 4.0",
            "attribution": "India boundaries by DataMeet India community (CC BY 4.0)",
            "projection": "WGS84",
            "tolerance_degrees": TOLERANCE,
            "precision_decimals": PRECISION,
            "raw_vertices": raw_points,
            "vertices": kept_points,
            "note": "Cartographic aid for locating forecast points. Official boundaries "
            "of India are published by the Survey of India.",
        },
    }


def main() -> None:
    data = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, separators=(",", ":")))
    meta = data["meta"]
    size = OUTPUT.stat().st_size
    print(
        f"{len(data['features'])} states/UTs  "
        f"{meta['raw_vertices']:,} -> {meta['vertices']:,} vertices "
        f"({meta['vertices'] / meta['raw_vertices'] * 100:.1f}%)  "
        f"{size / 1024:.0f} KB"
    )


if __name__ == "__main__":
    main()
