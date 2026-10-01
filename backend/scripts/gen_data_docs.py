"""Regenerate docs/DATA_SOURCES.md from the source catalogue.

    python -m scripts.gen_data_docs

The document is generated rather than hand-written so it cannot drift from
`app/ingest/sources.py`, which is what the download CLI and the System page
both read. One catalogue, three consumers.
"""

from __future__ import annotations

from pathlib import Path

from app.ingest.sources import ACCESS_ORDER, SOURCES

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "DATA_SOURCES.md"

ACCESS_NOTE = {
    "open": "Direct download, no account needed.",
    "key": "Free API key from a self-service registration.",
    "account": "Free account, usually with a data-use agreement to accept.",
    "restricted": "Request form, institutional affiliation, or a paid licence.",
}

HEADER = """# Data sources

Every dataset AtmosGuard uses or could use, with where it comes from and how to
get it.

## Read this first

Two of these are in the repository and wired in. The rest are **documented
routes, not live connections** - the `status` column says which is which, and
the System page in the running app shows the same thing. Nothing in this project
claims to be fed by a source it is not actually reading.

Portal addresses are stable and are given verbatim. Deep links to individual
files are not: agencies reorganise them, and several portals issue a download
link only after you log in or accept terms. Confirm the exact path at the
source rather than assuming a URL here still resolves.

```bash
python -m app.ingest.download --list            # the catalogue
python -m app.ingest.download --source <id>     # fetch, or print how to
```
"""

FOOTER = """
## Attribution

The two IMD datasets in this repository are published by the **India
Meteorological Department**, Ministry of Earth Sciences, Government of India,
under the Government Open Data Licence - India (GODL). Any work built on them
should say so.

## What is still missing

The one component of AtmosGuard that is not measured is the **ensemble**. No
agency publishes an archive of historical ensemble members as a convenient
download, so the system reconstructs them around the real observed outcome and
labels that plainly throughout.

Two sources would close that gap, in order of effort:

1. **ECMWF open data** - real 51-member ensembles, free, no registration, but
   only a few days are retained. Collect daily to build an archive.
2. **TIGGE** - the proper answer: ten centres' ensembles back to 2006, which is
   what a bust-risk model should really be trained on. Needs a free ECMWF
   account and patience with the retrieval queue.
"""


def render() -> str:
    parts = [HEADER]
    for level in ACCESS_ORDER:
        group = [s for s in SOURCES if s.access == level]
        if not group:
            continue
        parts.append(f"\n## {level.title()} access\n\n_{ACCESS_NOTE[level]}_\n")
        for s in group:
            badge = " **[in use]**" if s.status == "in use" else ""
            parts.append(
                f"""
### {s.name}{badge}

**{s.agency}** - {s.country}

| | |
|---|---|
| Portal | <{s.portal}> |
| Variables | {', '.join(s.variables)} |
| Resolution | {s.resolution} |
| Coverage | {s.coverage} |
| Format | {s.fmt} |
| Licence | {s.licence} |
| Feeds | `{s.feeds}` |

{s.role}

**How to get it.** {s.how_to_get}
"""
            )
            if s.notes:
                parts.append(f"\n**Note.** {s.notes}\n")
            if s.docs:
                parts.append("\n" + "\n".join(f"- <{d}>" for d in s.docs) + "\n")
    parts.append(FOOTER)
    return "".join(parts)


def main() -> None:
    OUTPUT.parent.mkdir(exist_ok=True)
    text = render()
    OUTPUT.write_text(text)
    print(f"wrote {OUTPUT}  ({len(text):,} chars, {text.count(chr(10)) + 1} lines)")


if __name__ == "__main__":
    main()
