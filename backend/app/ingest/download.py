"""Download official datasets.

    python -m app.ingest.download --list
    python -m app.ingest.download --source ecmwf-open-data
    python -m app.ingest.download --source imd-district-daily-rainfall --resource-id <id>

Sources needing an account or a signed agreement cannot be automated; for those
this prints the portal and what to look for once you are there.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from .sources import SOURCES, SOURCES_BY_ID

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def list_sources() -> None:
    width = max(len(s.id) for s in SOURCES)
    print(f"{'id'.ljust(width)}  {'access':<11} {'status':<8} name")
    print("-" * (width + 60))
    for source in SOURCES:
        print(f"{source.id.ljust(width)}  {source.access:<11} {source.status:<8} {source.name}")
    print(f"\n{len(SOURCES)} sources. Full references in docs/DATA_SOURCES.md")


def manual(source_id: str) -> None:
    source = SOURCES_BY_ID[source_id]
    print(f"\n{source.name}\n{source.agency} - {source.country}\n")
    print(f"  Portal    {source.portal}")
    print(f"  Access    {source.access}")
    print(f"  Format    {source.fmt}")
    print(f"  Coverage  {source.coverage}")
    print(f"  Licence   {source.licence}\n")
    print(f"  How to get it:\n    {source.how_to_get}\n")
    if source.notes:
        print(f"  Note:\n    {source.notes}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download official datasets for AtmosGuard")
    parser.add_argument("--list", action="store_true", help="list every catalogued source")
    parser.add_argument("--source", help="source id to download")
    parser.add_argument("--resource-id", help="data.gov.in resource id, for OGD sources")
    parser.add_argument("--out", type=Path, default=DATA_DIR, help="destination directory")
    parser.add_argument("--cycle", type=int, default=0, help="ECMWF model cycle, 0 or 12")
    args = parser.parse_args()

    if args.list or not args.source:
        list_sources()
        return

    if args.source not in SOURCES_BY_ID:
        raise SystemExit(f"Unknown source '{args.source}'. Try --list.")

    source = SOURCES_BY_ID[args.source]

    if args.source == "ecmwf-open-data":
        from .ecmwf_open import Request, download

        # Yesterday's 00Z run: today's may not have completed yet.
        run = date.today() - timedelta(days=1)
        request = Request(run_date=run, cycle=args.cycle)
        print(f"Retrieving ECMWF ensemble, {run} {args.cycle:02d}Z ...")
        path = download(request, args.out / "ecmwf")
        print(f"  -> {path}  ({path.stat().st_size / 1_048_576:.1f} MB)")
        return

    if source.access == "key" or args.resource_id:
        from .datagov import fetch_resource, write_csv

        if not args.resource_id:
            print("This source needs --resource-id (find it in the dataset's URL on data.gov.in).")
            manual(args.source)
            return
        destination = args.out / f"{args.source}.csv"
        print(f"Fetching resource {args.resource_id} ...")
        written = write_csv(fetch_resource(args.resource_id), destination)
        print(f"  -> {destination}  ({written:,} records)")
        return

    manual(args.source)


if __name__ == "__main__":
    main()
