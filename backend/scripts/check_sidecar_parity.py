"""Check that the static build's station replays match the live API exactly.

    python -m scripts.check_sidecar_parity [--per-station N]

Samples dates for every station, asks the API route for each replay, compiles
`frontend/src/lib/stationSidecar.ts`, rebuilds the same replays from the
sidecar files, and compares them field by field. Exits non-zero on any
difference. Run it after `scripts.export_station_sidecar`.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes import stations_replay  # noqa: E402
from app.core import station_replay as S  # noqa: E402

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
EDGES = ("2010-01-01", "2021-12-24", "2012-02-29", "2016-02-29", "2020-02-29", "2015-08-17")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-station", type=int, default=40)
    args = parser.parse_args()

    rng = random.Random(2021)
    first = S.TEST_START
    span = (S.LAST_DAY - timedelta(days=max(S.LEADS)) - first).days + 1
    dump: dict[str, object] = {}
    for station in S.stations():
        days = {(first + timedelta(days=rng.randrange(span))).isoformat() for _ in range(args.per_station)}
        for day in sorted(days | set(EDGES)):
            dump[f"{station.station_id}|{day}"] = stations_replay(on=day, station=station.station_id)

    with tempfile.TemporaryDirectory() as tmp:
        dump_path = Path(tmp) / "api.json"
        dump_path.write_text(json.dumps(dump))
        out = Path(tmp) / "js"
        subprocess.run(
            ["npx", "tsc", "src/lib/stationSidecar.ts", "--outDir", str(out),
             "--module", "es2020", "--target", "es2020", "--moduleResolution", "node", "--skipLibCheck"],
            cwd=FRONTEND, check=True,
        )
        (out / "package.json").write_text('{"type":"module"}')
        result = subprocess.run(
            ["node", "scripts/check-sidecar-parity.mjs", str(dump_path), str(out / "lib" / "stationSidecar.js")],
            cwd=FRONTEND,
        )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
