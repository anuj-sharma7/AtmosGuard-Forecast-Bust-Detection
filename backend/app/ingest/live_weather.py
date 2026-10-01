"""Real-time weather observation ingest service.

Fetches live atmospheric parameters (2m temperature, precipitation / rainfall,
relative humidity, 10m wind speed, and WMO weather codes) from open real-time
meteorological feeds (Open-Meteo / WMO Global Grid). Caches responses by rounded
coordinates for fast repeat lookups.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Cache: (rounded_lat, rounded_lon) -> (timestamp, data_dict)
_CACHE: dict[tuple[float, float], tuple[float, dict[str, Any]]] = {}
CACHE_TTL = 900  # 15 minutes

# WMO Weather interpretation codes (WW)
WMO_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm: Slight or moderate",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def fetch_live_weather(lat: float, lon: float, timeout_sec: float = 4.0) -> dict[str, Any]:
    """Fetch current live weather conditions for given coordinates with caching."""
    key = (round(lat, 2), round(lon, 2))
    now = time.monotonic()

    cached = _CACHE.get(key)
    if cached and (now - cached[0] < CACHE_TTL):
        return cached[1]

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat:.4f}&longitude={lon:.4f}&"
        f"current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m&"
        f"timezone=Asia%2FKolkata"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AtmosGuard/1.0 (Bust-Detection Weather Ingest)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            current = data.get("current", {})
            w_code = current.get("weather_code", 0)
            desc = WMO_CODES.get(w_code, "Fair weather")

            result = {
                "lat": lat,
                "lon": lon,
                "temperature": current.get("temperature_2m"),
                "relative_humidity": current.get("relative_humidity_2m"),
                "precipitation_mm": current.get("precipitation"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "weather_code": w_code,
                "weather_description": desc,
                "time": current.get("time"),
                "source": "Open-Meteo Global NWP / WMO Realtime Observations",
                "status": "live",
            }
            _CACHE[key] = (now, result)
            return result
    except Exception as e:
        logger.warning("Could not fetch real-time weather for (%s, %s): %s", lat, lon, e)
        # Return fallback null response
        return {
            "lat": lat,
            "lon": lon,
            "temperature": None,
            "relative_humidity": None,
            "precipitation_mm": None,
            "wind_speed_kmh": None,
            "weather_code": 0,
            "weather_description": "Data unavailable",
            "time": None,
            "source": "Open-Meteo Global NWP (Fallback)",
            "status": "error",
        }
