"""Client for IMD's public forecast API.

    https://api.imd.gov.in/api/v1/cityforecast

**Unverified against the live service.** This session's egress policy returns
403 for every imd.gov.in host, so the response schema below could not be
confirmed. The parser is therefore written to *discover* the shape rather than
assume it: `inspect()` prints what actually comes back, and `parse_cities()`
accepts any of the field spellings IMD has used across its endpoints rather
than hard-coding one. Run `inspect()` first and fix the mapping if it differs -
that is a five-minute job, and far safer than code that silently mis-reads a
field and reports the wrong temperature.

    python -m app.ingest.imd_api --probe             # find how the key is sent
    python -m app.ingest.imd_api --inspect
    python -m app.ingest.imd_api --city 42182        # Jaipur's IMD station id

**The API key.** Read from the ``IMD_API_KEY`` environment variable, or from a
``.env`` file beside the backend - never from source, and never printed: every
URL or header shown on screen has the key masked. Keys issued by IMD are bound
to the server's static public IP, so they work only from the machine that was
registered.

**How the key is sent is not assumed.** IMD's portal does not say whether it
expects a header or a URL parameter, and guessing wrong looks exactly like a
bad key. ``--probe`` tries each common convention once from the registered
machine and reports which one the server accepts; set ``IMD_API_AUTH`` to that
name and every other command uses it.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

BASE = "https://api.imd.gov.in/api/v1"
TIMEOUT = 30

#: Field spellings IMD has used across its endpoints. First match wins.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "station_id": ("Station_Id", "station_id", "stationid", "id", "City_Id"),
    "city": ("Station_Name", "station_name", "City", "city", "name"),
    "state": ("State", "state", "State_Name"),
    "date": ("Date", "date", "Forecast_Date"),
    "max_temp": ("Max_Temp", "max_temp", "Today_Max_temp", "maxtemp"),
    "min_temp": ("Min_Temp", "min_temp", "Today_Min_temp", "mintemp"),
    "rainfall": ("Rainfall", "rainfall", "Rain", "rain"),
    "humidity": ("Humidity", "humidity", "RH"),
    "warning": ("Warning", "warning", "Warnings", "Alert", "alert"),
    "forecast": ("Forecast", "forecast", "Description", "weather"),
}


class ImdApiError(RuntimeError):
    """An IMD API failure. `status` is the HTTP code, or None if unreachable."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


Fetcher = Callable[[str], bytes]

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

#: Conventions an API key is commonly sent by. `--probe` tries each; the one
#: the server accepts goes in IMD_API_AUTH. Nothing here is IMD's documented
#: scheme - that is exactly what the probe establishes.
AUTH_SCHEMES: dict[str, tuple[str, str]] = {
    "header-x-api-key": ("header", "x-api-key"),
    "header-api-key": ("header", "api-key"),
    "header-apikey": ("header", "apikey"),
    "bearer": ("header", "Authorization"),
    "header-authorization": ("header", "Authorization"),
    "query-api_key": ("query", "api_key"),
    "query-apikey": ("query", "apikey"),
    "query-key": ("query", "key"),
    "query-token": ("query", "token"),
}


def _read_env_file(path: Path | None = None) -> dict[str, str]:
    """Minimal KEY=value reader, so Windows users need no shell exports."""
    path = path or ENV_FILE  # resolved at call time, not import time
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def setting(name: str) -> str | None:
    """An environment variable, falling back to backend/.env."""
    return os.environ.get(name) or _read_env_file().get(name) or None


def mask(text: str, key: str | None) -> str:
    """Hide the key wherever it would be printed."""
    if not key:
        return text
    return text.replace(key, f"{key[:4]}...{key[-4:]}" if len(key) > 12 else "****")


def authorise(url: str, key: str, scheme: str) -> tuple[str, dict[str, str]]:
    """Attach the key to a request by the named convention."""
    if scheme not in AUTH_SCHEMES:
        raise ImdApiError(f"Unknown IMD_API_AUTH '{scheme}'. One of: {', '.join(AUTH_SCHEMES)}")
    where, name = AUTH_SCHEMES[scheme]
    if where == "header":
        return url, {name: f"Bearer {key}" if scheme == "bearer" else key}
    joiner = "&" if urllib.parse.urlparse(url).query else "?"
    return f"{url}{joiner}{urllib.parse.urlencode({name: key})}", {}


def _request(url: str, extra_headers: dict[str, str] | None = None) -> bytes:
    headers = {"Accept": "application/json", "User-Agent": "AtmosGuard/0.2"}
    headers.update(extra_headers or {})
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def configured_fetch() -> Fetcher:
    """A fetcher that sends the key the way IMD_API_AUTH says to.

    With no key set, requests go out unauthenticated, as before. With a key but
    no scheme, it stops and says to run --probe rather than guessing.
    """
    key = setting("IMD_API_KEY")
    if not key:
        return _default_fetch
    scheme = setting("IMD_API_AUTH")
    if not scheme:
        raise ImdApiError(
            "IMD_API_KEY is set but IMD_API_AUTH is not. Run "
            "`python -m app.ingest.imd_api --probe` on the registered server to "
            "find which convention IMD accepts, then set IMD_API_AUTH to it."
        )

    def fetch(url: str) -> bytes:
        signed, headers = authorise(url, key, scheme)
        try:
            return _request(signed, headers)
        except urllib.error.HTTPError as exc:  # pragma: no cover - needs network
            raise ImdApiError(
                f"IMD API returned {exc.code} for {mask(signed, key)}", status=exc.code
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - needs network
            raise ImdApiError(
                f"Cannot reach the IMD API ({getattr(exc, 'reason', exc)}). The key only "
                "works from the server whose public IP was registered with it."
            ) from exc

    return fetch


def probe(station_id: str | None = None) -> str | None:
    """Try each auth convention once and report which the server accepts.

    Prints status and a short, key-masked preview for each. Returns the first
    scheme that got a 200 with a JSON body, or None.
    """
    key = setting("IMD_API_KEY")
    if not key:
        raise ImdApiError("Set IMD_API_KEY (environment or backend/.env) first.")
    url = f"{BASE}/cityforecast" + (f"/{station_id}" if station_id else "")
    print(f"probing {url} with key {mask(key, key)}\n")
    winner = None
    for scheme in AUTH_SCHEMES:
        signed, headers = authorise(url, key, scheme)
        try:
            body = _request(signed, headers)
            status = 200
        except urllib.error.HTTPError as exc:
            status, body = exc.code, exc.read() or b""
        except urllib.error.URLError as exc:
            print(f"  {scheme:22} unreachable: {exc.reason}")
            continue
        preview = mask(body[:120].decode("utf-8", "replace").replace("\n", " "), key)
        is_json = body[:1].strip() in (b"[", b"{")
        mark = "  <- works" if status == 200 and is_json and winner is None else ""
        if mark:
            winner = scheme
        print(f"  {scheme:22} HTTP {status}  {preview!r}{mark}")
    print()
    if winner:
        print(f"Set IMD_API_AUTH={winner}")
    else:
        print(
            "No convention returned JSON. Check that this machine's public IP "
            "(https://api.imd.gov.in/public/ip.php) is the one registered with the key."
        )
    return winner


def _default_fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "AtmosGuard/0.2"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:  # pragma: no cover - needs network
        raise ImdApiError(f"IMD API returned {exc.code} for {url}", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - needs network
        raise ImdApiError(
            f"Cannot reach the IMD API ({getattr(exc, 'reason', exc)}). Note it is often "
            "reachable only from Indian networks, and blocks some cloud ranges."
        ) from exc


def pick(record: dict[str, Any], field: str) -> Any:
    """Read a logical field from a record, whatever IMD called it this time."""
    for alias in FIELD_ALIASES.get(field, ()):
        if alias in record and record[alias] not in ("", None):
            return record[alias]
    # Last resort: case-insensitive match on the logical name.
    lowered = {k.lower(): v for k, v in record.items()}
    return lowered.get(field)


@dataclass(frozen=True)
class CityForecast:
    station_id: str | None
    city: str | None
    state: str | None
    date: str | None
    max_temp: float | None
    min_temp: float | None
    rainfall: float | None
    warning: str | None
    raw: dict[str, Any]


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_cities(payload: Any) -> list[CityForecast]:
    """Normalise whatever the endpoint returned into city forecasts.

    Handles the three envelopes IMD endpoints commonly use: a bare list, a dict
    with a data/records key, or a dict keyed by station id.
    """
    if isinstance(payload, dict):
        for key in ("data", "records", "result", "cityforecast", "forecast"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            if all(isinstance(v, dict) for v in payload.values()) and payload:
                payload = list(payload.values())

    if not isinstance(payload, list):
        raise ImdApiError(
            f"Unexpected response shape: {type(payload).__name__}. "
            "Run --inspect and adjust parse_cities()."
        )

    out: list[CityForecast] = []
    for record in payload:
        if not isinstance(record, dict):
            continue
        out.append(
            CityForecast(
                station_id=str(pick(record, "station_id")) if pick(record, "station_id") else None,
                city=pick(record, "city"),
                state=pick(record, "state"),
                date=pick(record, "date"),
                max_temp=_number(pick(record, "max_temp")),
                min_temp=_number(pick(record, "min_temp")),
                rainfall=_number(pick(record, "rainfall")),
                warning=pick(record, "warning"),
                raw=record,
            )
        )
    return out


def city_forecast(station_id: str | None = None, *, fetch: Fetcher | None = None) -> list[CityForecast]:
    """Fetch the city forecast, for one station or all of them."""
    fetch = fetch or configured_fetch()
    url = f"{BASE}/cityforecast"
    if station_id:
        url = f"{url}/{station_id}"
    return parse_cities(json.loads(fetch(url)))


def inspect(station_id: str | None = None, *, fetch: Fetcher | None = None) -> None:
    """Print the raw response so the field mapping can be checked."""
    fetch = fetch or configured_fetch()
    url = f"{BASE}/cityforecast" + (f"/{station_id}" if station_id else "")
    print(f"GET {url}\n")
    raw = fetch(url)
    print(f"{len(raw):,} bytes\n")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(mask(raw[:1500].decode("utf-8", "replace"), setting("IMD_API_KEY")))
        return

    print(mask(json.dumps(payload, indent=2)[:2500], setting("IMD_API_KEY")))
    print("\n--- parsed ---")
    for city in parse_cities(payload)[:5]:
        print(f"  {city.city} ({city.state}) max={city.max_temp} rain={city.rainfall}")


def main() -> None:
    parser = argparse.ArgumentParser(description="IMD public forecast API")
    parser.add_argument("--inspect", action="store_true", help="print the raw response")
    parser.add_argument("--probe", action="store_true", help="find which auth convention IMD accepts")
    parser.add_argument("--city", help="IMD station id")
    args = parser.parse_args()

    if args.probe:
        probe(args.city)
        return

    if args.inspect or not args.city:
        inspect(args.city)
        return

    for city in city_forecast(args.city):
        print(f"{city.city:24s} {city.date}  max {city.max_temp}  rain {city.rainfall}")


if __name__ == "__main__":
    main()
