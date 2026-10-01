"""Import additional IMD daily rainfall observations into the archive.

    python -m scripts.import_imd_daily_rainfall --file downloaded.csv
    python -m scripts.import_imd_daily_rainfall --file a.csv --dry-run
    python -m scripts.import_imd_daily_rainfall --describe

**Why this exists.** The daily observational record in this repository spans
22 days (2026-08-19 to 2026-09-09). Every historical replay outside that window
- including 05-Sep-2016 - is unverifiable, because the observations simply are
not here. The sub-division series that covers 1901-2017 holds *monthly* totals;
a monthly total cannot be turned into daily values, and any attempt to spread
one across 30 days manufactures weather that never happened.

So this script is the interface for the missing data, not a substitute for it.
Point it at a real published daily file and the archive extends; run it against
nothing and it tells you exactly what to fetch and from where.

**What it will not do:** interpolate, distribute a monthly total, forward-fill,
infer a missing day from its neighbours, or accept a row whose date it cannot
parse. Gaps stay gaps.

Accepted input: a CSV carrying, at minimum, a state, a district, a date, the
observed daily rainfall and IMD's published daily normal. Column names are
matched case-insensitively against the aliases below, so the published file
does not have to be renamed first - including IMD's own long-standing typos
('Departue', 'Acutual'), which are matched literally because that is what the
published file contains.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import imd  # noqa: E402

TARGET = imd.DISTRICT_DAILY_FILE

#: Canonical column -> accepted header spellings, lowercased.
ALIASES: dict[str, tuple[str, ...]] = {
    "State": ("state", "state_name", "statename", "state/ut", "subdivision_state"),
    "District": ("district", "district_name", "districtname", "dist"),
    "Date": ("date", "obs_date", "observation_date", "day", "date_of_observation"),
    "Daily Actual": (
        "daily actual", "actual", "rainfall", "rainfall_mm", "actual_rainfall",
        "daily_actual", "daily rainfall", "observed", "daily acutual",
    ),
    "Daily Normal": (
        "daily normal", "normal", "normal_mm", "daily_normal", "normal_rainfall",
        "climatological_normal",
    ),
    "Daily Departure Per": (
        "daily departure per", "departure", "departure_pct", "departure %",
        "daily_departure", "daily departue per", "dep%",
    ),
    "Daily Category": (
        "daily category", "category", "departure_category", "daily_category", "cat",
    ),
}

REQUIRED = ("State", "District", "Date", "Daily Actual", "Daily Normal")

#: Where real daily observations actually come from. Documented routes, not
#: live connections - this environment's network policy denies all of them.
SOURCES: tuple[dict[str, str], ...] = (
    {
        "name": "IMD gridded daily rainfall, 0.25 degree",
        "covers": "1901 to present, daily, national grid",
        "reference": "https://www.imdpune.gov.in/cmpg/Griddata/Rainfall_25_NetCDF.html",
        "note": "The authoritative daily series. NetCDF; needs gridding onto "
                "districts or sub-divisions before import.",
    },
    {
        "name": "IMD district-wise daily rainfall (data.gov.in)",
        "covers": "Rolling recent period, district level",
        "reference": "https://data.gov.in/catalog/rainfall-india",
        "note": "Same shape as the file already in data/. Drops straight in.",
    },
    {
        "name": "India-WRIS daily rainfall",
        "covers": "District and basin level, multi-year",
        "reference": "https://indiawris.gov.in/wris/",
        "note": "Useful for filling historical district gaps.",
    },
    {
        "name": "IMD Pune Hydromet / DDGM(H) archives",
        "covers": "Long historical daily records on request",
        "reference": "https://www.imdpune.gov.in/",
        "note": "Institutional request; the route for a specific past episode "
                "such as September 2016.",
    },
)


@dataclass
class ImportReport:
    read: int = 0
    accepted: int = 0
    rejected_no_date: int = 0
    rejected_no_value: int = 0
    duplicates: int = 0
    new_days: tuple[str, ...] = ()
    existing_days: int = 0

    def render(self) -> str:
        lines = [
            f"rows read            {self.read}",
            f"accepted             {self.accepted}",
            f"rejected, bad date   {self.rejected_no_date}",
            f"rejected, no value   {self.rejected_no_value}",
            f"duplicate site-days  {self.duplicates}",
            f"days already held    {self.existing_days}",
            f"new days             {len(self.new_days)}",
        ]
        if self.new_days:
            shown = ", ".join(self.new_days[:8])
            more = f" (+{len(self.new_days) - 8} more)" if len(self.new_days) > 8 else ""
            lines.append(f"  {shown}{more}")
        return "\n".join(lines)


def resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    """Map canonical names onto the file's actual headers."""
    lowered = {name.strip().lower(): name for name in fieldnames}
    mapping: dict[str, str] = {}
    for canonical, options in ALIASES.items():
        for option in options:
            if option in lowered:
                mapping[canonical] = lowered[option]
                break
    return mapping


def parse_day(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def existing_keys() -> set[tuple[str, str, date]]:
    return {(r.state, r.district, r.day) for r in imd._daily_rows()}


def read_source(path: Path) -> tuple[list[dict[str, str]], ImportReport]:
    report = ImportReport()
    have = existing_keys()
    known_days = {d for _, _, d in have}
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, date]] = set()
    new_days: set[date] = set()

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SystemExit(f"{path} has no header row.")
        columns = resolve_columns(list(reader.fieldnames))
        missing = [c for c in REQUIRED if c not in columns]
        if missing:
            raise SystemExit(
                f"{path} is missing required column(s): {', '.join(missing)}.\n"
                f"Headers found: {', '.join(reader.fieldnames)}\n"
                "Add the column or extend ALIASES in this script - do not fill "
                "the value in by hand."
            )

        for row in reader:
            report.read += 1
            day = parse_day(row.get(columns["Date"], ""))
            if day is None:
                report.rejected_no_date += 1
                continue
            actual = imd._float(row.get(columns["Daily Actual"]))
            normal = imd._float(row.get(columns["Daily Normal"]))
            if actual is None or normal is None:
                # A missing measurement is a missing measurement. It is not zero
                # rainfall, and it is not the district's normal.
                report.rejected_no_value += 1
                continue

            state = imd.normalise_state(row.get(columns["State"], ""))
            district = (row.get(columns["District"], "") or "").strip().upper()
            key = (state, district, day)
            if key in have or key in seen:
                report.duplicates += 1
                continue
            seen.add(key)
            if day not in known_days:
                new_days.add(day)

            departure = row.get(columns.get("Daily Departure Per", ""), "") if "Daily Departure Per" in columns else ""
            category = row.get(columns.get("Daily Category", ""), "") if "Daily Category" in columns else ""
            if not (departure or "").strip() and normal > 0:
                departure = f"{(actual - normal) / normal * 100:.1f}"

            out.append(
                {
                    "State": state,
                    "District": district,
                    "Date": day.isoformat(),
                    "Daily Actual": f"{actual}",
                    "Daily Normal": f"{normal}",
                    "Daily Departure Per": (departure or "").strip(),
                    "Daily Category": (category or "").strip().upper(),
                }
            )
            report.accepted += 1

    report.new_days = tuple(sorted(d.isoformat() for d in new_days))
    report.existing_days = len(known_days)
    return out, report


def append(rows: list[dict[str, str]]) -> None:
    """Append accepted rows to the archive, preserving its existing header."""
    with TARGET.open(newline="", encoding="utf-8-sig") as handle:
        header = next(csv.reader(handle))

    with TARGET.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
        for row in rows:
            # Columns the source file did not carry are left empty, never guessed.
            writer.writerow({field: row.get(field, "") for field in header})


def describe() -> None:
    start, end = imd.observation_window()
    span = (end - start).days + 1
    print("AtmosGuard daily observational archive")
    print("=" * 62)
    print(f"file      {TARGET}")
    print(f"covers    {start} to {end}  ({span} days)")
    print(f"rows      {len(imd._daily_rows())}")
    counts = Counter(r.day for r in imd._daily_rows())
    print(f"districts {len({(r.state, r.district) for r in imd._daily_rows()})}")
    print(f"per day   {min(counts.values())}-{max(counts.values())} districts reporting")
    print()
    print("Every replay origin outside this window is unverifiable. The")
    print("1901-2017 sub-division file holds MONTHLY totals and cannot supply")
    print("daily values for any date, including September 2016.")
    print()
    print("Where real daily observations come from:")
    for source in SOURCES:
        print(f"\n  {source['name']}")
        print(f"    covers  {source['covers']}")
        print(f"    ref     {source['reference']}")
        print(f"    note    {source['note']}")
    print()
    print("Download one of these outside the session, then:")
    print("  python -m scripts.import_imd_daily_rainfall --file <path> --dry-run")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, help="CSV of published daily observations")
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("--describe", action="store_true", help="show archive coverage and sources")
    args = parser.parse_args()

    if args.describe or args.file is None:
        describe()
        if args.file is None and not args.describe:
            print("\nNothing imported: pass --file to import a real published file.")
        return

    if not args.file.is_file():
        raise SystemExit(f"No such file: {args.file}")

    rows, report = read_source(args.file)
    print(report.render())

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return
    if not rows:
        print("\nNothing to import.")
        return

    append(rows)
    imd._daily_rows.cache_clear()
    imd.observation_window.cache_clear()
    imd._by_district.cache_clear()
    imd._by_state.cache_clear()
    imd.coverage.cache_clear()
    start, end = imd.observation_window()
    print(f"\nappended {len(rows)} row(s). Archive now covers {start} to {end}.")
    print("Retrain the replay model so it sees the new origins:")
    print("  python -m scripts.train_replay_model")


if __name__ == "__main__":
    main()
