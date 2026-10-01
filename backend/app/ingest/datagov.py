"""Client for the Open Government Data platform, data.gov.in.

The route by which the two IMD rainfall datasets this project uses are
published, so it is also the route to refreshing them.

    export DATA_GOV_IN_API_KEY=...         # free, from https://data.gov.in/
    python -m app.ingest.download --source imd-district-daily-rainfall

The platform paginates hard - 100 records per call by default - so anything of
useful size needs the offset loop in `fetch_resource`.
"""

from __future__ import annotations

import csv
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

BASE = "https://api.data.gov.in/resource"

#: The platform's ceiling on records per request.
MAX_LIMIT = 1000


class DataGovError(RuntimeError):
    pass


def api_key() -> str:
    key = os.getenv("DATA_GOV_IN_API_KEY", "").strip()
    if not key:
        raise DataGovError(
            "No API key. Register free at https://data.gov.in/, then set "
            "DATA_GOV_IN_API_KEY in the environment."
        )
    return key


Fetcher = Callable[[str], bytes]


def _default_fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:  # pragma: no cover - needs network
        if exc.code in (401, 403):
            raise DataGovError(
                f"data.gov.in rejected the API key ({exc.code}). Check "
                "DATA_GOV_IN_API_KEY is current."
            ) from exc
        raise DataGovError(f"data.gov.in returned {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - needs network
        raise DataGovError(f"Cannot reach data.gov.in: {exc.reason}") from exc


def build_url(resource_id: str, key: str, offset: int, limit: int) -> str:
    """Compose one page request. Separated out so it can be tested offline."""
    params = urllib.parse.urlencode(
        {
            "api-key": key,
            "format": "json",
            "offset": offset,
            "limit": min(limit, MAX_LIMIT),
        }
    )
    return f"{BASE}/{resource_id}?{params}"


def fetch_resource(
    resource_id: str,
    *,
    key: str | None = None,
    page_size: int = MAX_LIMIT,
    max_records: int | None = None,
    fetch: Fetcher = _default_fetch,
) -> Iterator[dict]:
    """Yield every record of a resource, following the platform's pagination."""
    resolved = key or api_key()
    offset = 0

    while True:
        payload = json.loads(fetch(build_url(resource_id, resolved, offset, page_size)))
        records = payload.get("records") or []
        if not records:
            return

        for record in records:
            yield record
            offset += 1
            if max_records is not None and offset >= max_records:
                return

        # A short page means the end of the resource.
        if len(records) < min(page_size, MAX_LIMIT):
            return


def write_csv(records: Iterator[dict], destination: Path) -> int:
    """Write records to CSV, taking the header from the first one."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer: csv.DictWriter | None = None
        for record in records:
            if writer is None:
                writer = csv.DictWriter(handle, fieldnames=list(record.keys()))
                writer.writeheader()
            writer.writerow(record)
            count += 1

    if count == 0:
        destination.unlink(missing_ok=True)
        raise DataGovError("Resource returned no records - check the resource id.")
    return count
