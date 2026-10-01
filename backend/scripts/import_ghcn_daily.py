"""Build the daily station archive from NOAA GHCN-Daily.

    python -m scripts.import_ghcn_daily            # download + build
    python -m scripts.import_ghcn_daily --cached DIR   # build from files already on disk

**Why this dataset.** The 7-day replay needs real daily observations for
2010-2017 - maximum and minimum temperature and rainfall, day by day. Nothing
in the IMD files here provides that: the district file covers 22 days of 2026
and the sub-division file is monthly. The IMD gridded daily archive would, but
every IMD host is denied by this environment's network policy.

NOAA's Global Historical Climatology Network - Daily is the official archive
that Indian synoptic stations report into through the WMO exchange. It is
public domain, it is mirrored on the AWS Open Data registry (which *is*
reachable), and it is quality-controlled: every value that failed one of
NOAA's checks carries a Q_FLAG, and those values are dropped here, not kept.

    Source   https://registry.opendata.aws/noaa-ghcn/
    Docs     https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily
    Licence  Public domain (U.S. Government work)
    Citation Menne, M.J., et al. (2012). An overview of the Global Historical
             Climatology Network-Daily Database. J. Atmos. Oceanic Technol.

**Station selection is a fixed rule, stated up front, not a hand-picked list:**
a station is kept when it has at least `MIN_TEST_DAYS` quality-passed TMAX
reports in 2010-2017 *and* at least `MIN_TRAIN_DAYS` in 1995-2009. The archive
itself runs to 2021. The first
condition makes the held-out years verifiable; the second gives the model
enough history to learn from. Every Indian station meeting both is kept.

**What is never done:** a missing day is never filled. GHCN's Indian stations
report precipitation mostly on days when it rains - in the dry season large
stretches are simply absent - and treating "absent" as "0 mm" would quietly
manufacture dry days. Missing stays missing, all the way to the model (which
handles it natively) and the verification (which skips it and says so).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "ghcn"
DAILY_OUT = OUT_DIR / "india_daily_1995_2021.csv.gz"
STATIONS_OUT = OUT_DIR / "stations.csv"

BUCKET = "https://noaa-ghcn-pds.s3.amazonaws.com"

FIRST_YEAR, LAST_YEAR = 1995, 2021
TRAIN_END = 2009

#: The selection rule is evaluated on a fixed window, 2010-2017, and was set
#: before the archive was extended to 2021. Re-evaluating it over 2010-2021
#: would admit more stations, change the network features, and retrain the
#: model - so the extension adds years to the same 28 stations instead.
SELECTION_WINDOW = (2010, 2017)
MIN_TEST_DAYS = 2300   # of 2,922 days in 2010-2017  (~79%)
MIN_TRAIN_DAYS = 3000  # of 5,479 days in 1995-2009  (~55%)

ELEMENTS = ("TMAX", "TMIN", "PRCP")


def fetch(path: str) -> bytes:
    with urllib.request.urlopen(f"{BUCKET}/{path}", timeout=180) as response:
        return response.read()


def read_stations(raw: str) -> dict[str, dict]:
    """Fixed-width ghcnd-stations.txt -> {id: metadata} for India only."""
    out: dict[str, dict] = {}
    for line in raw.splitlines():
        sid = line[0:11]
        if not sid.startswith("IN"):
            continue
        out[sid] = {
            "station_id": sid,
            "lat": float(line[12:20]),
            "lon": float(line[21:30]),
            "elevation_m": float(line[31:37]),
            "name": line[41:71].strip().title(),
        }
    return out


def candidates(inventory: str) -> list[str]:
    """Indian stations whose inventory claims PRCP or TMAX across 1995-2017."""
    out = set()
    for line in inventory.splitlines():
        parts = line.split()
        if len(parts) < 6 or not parts[0].startswith("IN"):
            continue
        sid, element, first, last = parts[0], parts[3], int(parts[4]), int(parts[5])
        if element in ("TMAX", "PRCP") and first <= FIRST_YEAR and last >= SELECTION_WINDOW[1]:
            out.add(sid)
    return sorted(out)


def parse_station(raw: str) -> dict[date, dict[str, float]]:
    """One station's by_station CSV -> {day: {element: value}}, QC-passed only.

    GHCN stores temperature in tenths of a degree C and precipitation in tenths
    of a millimetre. Any value carrying a Q_FLAG failed a NOAA quality check and
    is dropped.
    """
    out: dict[date, dict[str, float]] = defaultdict(dict)
    for row in csv.reader(io.StringIO(raw)):
        if len(row) < 6 or row[0] == "ID":
            continue
        element = row[2]
        if element not in ELEMENTS:
            continue
        stamp = row[1]
        year = int(stamp[:4])
        if not FIRST_YEAR <= year <= LAST_YEAR:
            continue
        if row[5].strip():  # Q_FLAG set: failed quality control
            continue
        try:
            value = int(row[3]) / 10.0
        except ValueError:
            continue
        out[date(year, int(stamp[4:6]), int(stamp[6:8]))][element] = value
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cached", type=Path, help="directory holding ghcnd-*.txt and st/<id>.csv")
    args = parser.parse_args()

    if args.cached:
        stations_raw = (args.cached / "ghcnd-stations.txt").read_text()
        inventory_raw = (args.cached / "ghcnd-inventory.txt").read_text()
    else:
        print("fetching station list and inventory ...")
        stations_raw = fetch("ghcnd-stations.txt").decode()
        inventory_raw = fetch("ghcnd-inventory.txt").decode()

    meta = read_stations(stations_raw)
    ids = candidates(inventory_raw)
    print(f"{len(ids)} Indian candidate stations")

    def load(sid: str) -> tuple[str, dict]:
        if args.cached:
            raw = (args.cached / "st" / f"{sid}.csv").read_text()
        else:
            raw = fetch(f"csv/by_station/{sid}.csv").decode()
        return sid, parse_station(raw)

    with ThreadPoolExecutor(max_workers=12) as pool:
        series = dict(pool.map(load, ids))

    kept: list[str] = []
    for sid in ids:
        days = series[sid]
        train = sum(1 for d, v in days.items() if d.year <= TRAIN_END and "TMAX" in v)
        test = sum(
            1 for d, v in days.items()
            if SELECTION_WINDOW[0] <= d.year <= SELECTION_WINDOW[1] and "TMAX" in v
        )
        if train >= MIN_TRAIN_DAYS and test >= MIN_TEST_DAYS:
            kept.append(sid)
            meta[sid]["train_tmax_days"] = train
            meta[sid]["test_tmax_days"] = test
            meta[sid]["test_prcp_days"] = sum(
                1 for d, v in days.items() if d.year > TRAIN_END and "PRCP" in v
            )
    print(f"{len(kept)} stations pass the coverage rule")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with STATIONS_OUT.open("w", newline="") as handle:
        fields = [
            "station_id", "name", "lat", "lon", "elevation_m",
            "train_tmax_days", "test_tmax_days", "test_prcp_days",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sid in kept:
            writer.writerow({k: meta[sid][k] for k in fields})

    rows = 0
    with gzip.open(DAILY_OUT, "wt", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["station_id", "date", "tmax_c", "tmin_c", "prcp_mm"])
        for sid in kept:
            for day in sorted(series[sid]):
                v = series[sid][day]
                # Empty field = not reported. Never 0, never a guess.
                writer.writerow([
                    sid,
                    day.isoformat(),
                    "" if "TMAX" not in v else f"{v['TMAX']:.1f}",
                    "" if "TMIN" not in v else f"{v['TMIN']:.1f}",
                    "" if "PRCP" not in v else f"{v['PRCP']:.1f}",
                ])
                rows += 1
    size = DAILY_OUT.stat().st_size / 1_048_576
    print(f"wrote {rows:,} station-days -> {DAILY_OUT.relative_to(ROOT)} ({size:.1f} MB)")
    print(f"wrote {len(kept)} stations  -> {STATIONS_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
