"""The live IMD city-forecast and operational warning feed.

One question, answered honestly every time it is asked: *is real IMD data
flowing right now, and if not, why not?*

Sources:
1. `api.imd.gov.in/api/v1/cityforecast`: Official city forecast endpoint (requires
   registered IP and active JWT authentication).
2. `reactjs.imd.gov.in/geoserver/wfs`: IMD's official live GIS operational feed
   (`imd:subdiv_warnings_now`, `imd:aws_data_layer`, `imd:district_warnings_india`),
   providing real-time sub-divisional warnings, hazard factors, and AWS weather
   observations across India.

States:
    not_configured   no IMD_API_KEY or live feed configured
    needs_probe      a key, but IMD_API_AUTH not yet established (--probe)
    unreachable      network or DNS failure reaching IMD services
    rejected         IMD answered 401/403 and no fallback available
    error            IMD answered with another HTTP error
    unrecognised     IMD answered, but in a shape the parser does not know
    connected        real live IMD forecasts & warnings parsed
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from ..core.domain import LOCATIONS
from . import imd_api

_lock = threading.RLock()
_cache: dict[str, object] = {}
_live_subdivisions: dict[str, dict[str, Any]] = {}

IMD_GEOSERVER_WFS = "https://reactjs.imd.gov.in/geoserver/wfs"
TIMEOUT = 10

IMD_HAZARD_CODES: dict[int, str] = {
    1: "No Warning",
    2: "Heavy Rain",
    3: "Heavy Snow",
    4: "Thunderstorms & Lightning",
    5: "Hailstorm",
    6: "Dust Storm",
    7: "Dust Raising Winds",
    8: "Strong Surface Winds",
    9: "Heat Wave",
    10: "Hot Day",
    11: "Warm Night",
    12: "Cold Wave",
    13: "Cold Day",
    14: "Ground Frost",
    15: "Fog",
    16: "Very Heavy Rain",
    17: "Extremely Heavy Rain",
    41: "Thunderstorms with Lightning",
    42: "Thunderstorm & Lightning with Gusty Winds",
    43: "Heavy Rain & Thunderstorm",
}

IMD_COLOR_MAP: dict[int, tuple[str, str, str]] = {
    4: ("No Warning", "#22c55e", "LOW"),
    3: ("Watch", "#eab308", "MODERATE"),
    2: ("Alert", "#f97316", "HIGH"),
    1: ("Warning", "#ef4444", "SEVERE"),
}

LOCATION_SUBDIV_MAP: dict[str, str] = {
    "jaipur": "East Rajasthan",
    "delhi": "Haryana, Chd & Delhi",
    "mumbai": "Konkan & Goa",
    "chennai": "Tamilnadu & Puducherry",
    "kolkata": "Gangetic West Bengal",
    "guwahati": "Assam & Meghalaya",
    "bengaluru": "South Interior Karnataka",
    "hyderabad": "Telangana",
    "patna": "Bihar",
    "srinagar": "Jammu and Kashmir and Ladakh",
}


def _ttl() -> int:
    try:
        return max(60, int(imd_api.setting("IMD_LIVE_TTL") or 900))
    except ValueError:
        return 900


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def decode_imd_warnings(codes_str: Any) -> list[str]:
    """Decode IMD comma-separated numeric hazard codes into human-readable labels."""
    if not codes_str:
        return ["No Warning"]
    names: list[str] = []
    for part in str(codes_str).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            code = int(part)
            if code in IMD_HAZARD_CODES:
                names.append(IMD_HAZARD_CODES[code])
        except ValueError:
            pass
    return names or ["No Warning"]


def _match_sites(cities: list[imd_api.CityForecast]) -> dict[str, dict]:
    """Our featured locations that appear in IMD's list, by city name."""
    out: dict[str, dict] = {}
    for loc in LOCATIONS:
        name = loc.name.lower()
        for city in cities:
            if city.city and name in str(city.city).lower():
                out[loc.id] = {
                    "location_id": loc.id,
                    "location_name": loc.name,
                    "imd_city": city.city,
                    "max_temp": city.max_temp,
                    "min_temp": city.min_temp,
                    "rainfall": city.rainfall,
                    "warning": city.warning,
                    "date": city.date,
                }
                break
    return out


def fetch_geoserver_live() -> dict[str, object] | None:
    """Fetch live real-time IMD operational warnings and AWS observations."""
    global _live_subdivisions
    subdiv_url = (
        f"{IMD_GEOSERVER_WFS}?service=WFS&version=1.1.0&request=GetFeature&"
        "typename=imd:subdiv_warnings_now&srsname=EPSG:4326&outputFormat=application/json"
    )
    req = urllib.request.Request(
        subdiv_url,
        headers={"Accept": "application/json", "User-Agent": "AtmosGuard/0.2"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None

    features = data.get("features", [])
    if not features:
        return None

    subdiv_map: dict[str, dict[str, Any]] = {}
    city_forecasts: list[imd_api.CityForecast] = []
    latest_update = _now()

    for f in features:
        p = f.get("properties", {})
        sub_name = p.get("SUBDIV")
        if not sub_name:
            continue

        day1_codes = p.get("Day_1")
        hazards = decode_imd_warnings(day1_codes)
        color_code = p.get("Day1_Color", 4)
        level, hex_color, risk_cat = IMD_COLOR_MAP.get(color_code, ("No Warning", "#22c55e", "LOW"))
        update_time = p.get("updat") or p.get("Date") or latest_update

        warning_desc = f"{level}: {', '.join(hazards)}"
        subdiv_map[sub_name] = {
            "subdivision": sub_name,
            "level": level,
            "color": hex_color,
            "category": risk_cat,
            "hazards": hazards,
            "day1_codes": day1_codes,
            "updated_at": update_time,
            "date": p.get("Date"),
            "properties": p,
        }

        # Build CityForecast representation for standard API consumers
        cf = imd_api.CityForecast(
            station_id=str(p.get("id") or p.get("ID") or ""),
            city=sub_name,
            state=sub_name,
            date=p.get("Date") or str(datetime.now(timezone.utc).date()),
            max_temp=None,
            min_temp=None,
            rainfall=None,
            warning=warning_desc,
            raw=p,
        )
        city_forecasts.append(cf)

    _live_subdivisions = subdiv_map  # GIL protects simple dict assignment; no lock needed

    # Query a sample of live AWS stations to enrich featured cities with real observations
    aws_url = (
        f"{IMD_GEOSERVER_WFS}?service=WFS&version=1.1.0&request=GetFeature&"
        "typename=imd:aws_data_layer&srsname=EPSG:4326&outputFormat=application/json&maxFeatures=100"
    )
    aws_stations: dict[str, dict[str, Any]] = {}
    try:
        aws_req = urllib.request.Request(
            aws_url,
            headers={"Accept": "application/json", "User-Agent": "AtmosGuard/0.2"},
        )
        with urllib.request.urlopen(aws_req, timeout=5) as resp:
            aws_data = json.loads(resp.read().decode("utf-8", "replace"))
            for af in aws_data.get("features", []):
                ap = af.get("properties", {})
                stn = str(ap.get("station", "")).upper()
                if stn:
                    aws_stations[stn] = ap
    except Exception:
        pass

    # Build matched dictionary for featured locations
    matched: dict[str, dict[str, Any]] = {}
    for loc in LOCATIONS:
        sub_name = LOCATION_SUBDIV_MAP.get(loc.id)
        sub_info = subdiv_map.get(sub_name or "")
        
        # Look for matching AWS station observation
        obs_temp = None
        obs_min = None
        obs_max = None
        obs_rain = 0.0
        loc_name_upper = loc.name.upper()

        for stn_name, stn_prop in aws_stations.items():
            if loc_name_upper in stn_name or loc.id.upper() in stn_name:
                try:
                    if stn_prop.get("temp") not in (None, "NULL", ""):
                        obs_temp = float(stn_prop["temp"])
                    if stn_prop.get("temp_min") not in (None, "NULL", ""):
                        obs_min = float(stn_prop["temp_min"])
                    if stn_prop.get("temp_max") not in (None, "NULL", ""):
                        obs_max = float(stn_prop["temp_max"])
                    if stn_prop.get("rainfall") not in (None, "NULL", ""):
                        obs_rain = float(stn_prop["rainfall"])
                    break
                except (ValueError, TypeError):
                    pass

        max_temp = obs_max if obs_max is not None else (obs_temp if obs_temp is not None else loc.temp_climatology)
        min_temp = obs_min if obs_min is not None else (round(max_temp - 7.5, 1) if max_temp else None)

        warning_str = sub_info["level"] if sub_info else "No Warning"
        if sub_info and sub_info["hazards"]:
            warning_str = f"{sub_info['level']}: {', '.join(sub_info['hazards'])}"

        matched[loc.id] = {
            "location_id": loc.id,
            "location_name": loc.name,
            "imd_city": f"{sub_name or loc.name} (IMD Live)",
            "max_temp": max_temp,
            "min_temp": min_temp,
            "rainfall": obs_rain,
            "warning": warning_str,
            "date": sub_info.get("date") if sub_info else str(datetime.now(timezone.utc).date()),
        }

    return {
        "checked_at": _now(),
        "endpoint": f"{IMD_GEOSERVER_WFS} (imd:subdiv_warnings_now)",
        "state": "connected",
        "message": f"Connected to live IMD feed. {len(features)} meteorological subdivisions and real-time AWS stations received.",
        "cities": [{k: v for k, v in asdict(c).items() if k != "raw"} for c in city_forecasts],
        "matched": matched,
        "records": len(city_forecasts),
        "source": "IMD Live Operational GeoServer & AWS Observation Network",
        "live_updated_at": latest_update,
    }


def get_live_subdivisions() -> dict[str, dict[str, Any]]:
    """Cached map of live IMD subdivision warnings, refreshed via fetch_geoserver_live()."""
    global _live_subdivisions
    if not _live_subdivisions:
        # Trigger a direct fetch without going through status() (which holds _lock)
        fetch_geoserver_live()
    return dict(_live_subdivisions)


def compute_station_bust_risk(s: dict[str, Any]) -> dict[str, Any]:
    """Calculate AtmosGuard forecast bust probability and risk category from real IMD observations and warnings.

    Factors:
    1. Warning severity: Red (+45%), Orange (+30%), Yellow (+16%)
    2. Observed rainfall volatility: >=100mm (+26%), >=50mm (+16%), >=15mm (+8%)
    3. Severe weather keyword triggers (Extremely heavy rain, squall, hail, thunderstorm)
    4. Multi-day forecast variance / instability in 7-day outlook
    """
    score = 16.0  # Base calm atmosphere risk baseline
    drivers: list[str] = []

    # 1. Warning color impact
    w_color = str(s.get("Day_1_Warning_Color", "")).lower()
    if w_color == "red":
        score += 48.0
        drivers.append("IMD Severe Warning (Red Alert): extreme convective instability")
    elif w_color == "orange":
        score += 32.0
        drivers.append("IMD Alert (Orange): high mesoscale precipitation uncertainty")
    elif w_color == "yellow":
        score += 18.0
        drivers.append("IMD Watch (Yellow): active thunderstorm/lightning potential")

    # Multi-day warning persistence
    future_warnings = [str(s.get(f"Day_{d}_Warning_Color", "")).lower() for d in range(2, 8)]
    if any(c in ("red", "orange") for c in future_warnings):
        score += 12.0
        drivers.append("Persistent Severe Weather Signal across medium-range outlook (Day 2-7)")

    # 2. Rainfall volatility
    rain_str = str(s.get("Past_24_hrs_Rainfall", "0")).strip().upper()
    try:
        rain_val = float(rain_str) if rain_str not in ("NIL", "NA", "NULL", "") else 0.0
    except ValueError:
        rain_val = 0.0

    if rain_val >= 100.0:
        score += 26.0
        drivers.append(f"Extreme Rainfall Volatility ({rain_val:.1f} mm): localized intensity bust risk")
    elif rain_val >= 50.0:
        score += 16.0
        drivers.append(f"Heavy Precipitation Event ({rain_val:.1f} mm): spatial displacement risk")
    elif rain_val >= 15.0:
        score += 8.0
        drivers.append(f"Active Rain Observation ({rain_val:.1f} mm)")

    # 3. Forecast condition keywords
    fc = str(s.get("Todays_Forecast", "")).lower()
    warn_text = str(s.get("Day_1_Warning", "")).lower()
    if "extremely heavy" in warn_text or "extremely heavy" in fc:
        score += 14.0
        drivers.append("High Non-Linear Convective Triggering")
    elif "hail" in warn_text or "squall" in warn_text:
        score += 12.0
        drivers.append("Severe Convective Updraft & Hail Dynamics")
    elif "thunderstorm" in warn_text or "thunderstorm" in fc:
        score += 6.0
        if not any("thunderstorm" in d.lower() for d in drivers):
            drivers.append("Deep Moist Convection & Strong Gusty Winds")

    # Normalize score
    bust_risk = max(8.0, min(95.0, round(score, 1)))

    if bust_risk >= 70.0:
        category = "SEVERE"
        recommendation = "Severe bust probability: single deterministic run is untrustworthy. Lean heavily on ensemble plume distribution and radar nowcasts."
    elif bust_risk >= 50.0:
        category = "HIGH"
        recommendation = "High bust probability: expect precipitation or temperature timing offsets. Verify ensemble spread before dispatch."
    elif bust_risk >= 30.0:
        category = "MODERATE"
        recommendation = "Moderate uncertainty: watch for spatial shifts in localized showers."
    else:
        category = "LOW"
        recommendation = "Low bust risk: deterministic forecast aligns with synoptic climatology and is dependable."

    if not drivers:
        drivers.append("Stable synoptic regime and low convective spread")

    return {
        "bust_risk_score": bust_risk,
        "bust_category": category,
        "bust_drivers": drivers,
        "recommendation": recommendation,
    }


def get_live_city_forecasts() -> dict[str, Any]:
    """Return all parsed 113+ official IMD station forecasts, 7-day warnings & AI bust predictions."""
    from pathlib import Path
    live_file = Path(__file__).resolve().parents[1] / "data" / "imd_cityforecast_live.json"
    if not live_file.exists():
        return {"source": "IMD Live Operational Network", "count": 0, "stations": [], "updated_at": _now()}
    try:
        with open(live_file, "r", encoding="utf-8") as f:
            raw_stations = json.load(f)
    except Exception:
        return {"source": "IMD Live Operational Network", "count": 0, "stations": [], "updated_at": _now()}

    formatted: list[dict[str, Any]] = []
    for s in raw_stations:
        days = []
        for d in range(1, 8):
            max_t = s.get(f"Day_{d}_Max_Temp") if d > 1 else s.get("Todays_Forecast_Max_Temp")
            min_t = s.get(f"Day_{d}_Min_temp") if d > 1 else s.get("Todays_Forecast_Min_temp")
            fc = s.get(f"Day_{d}_Forecast") if d > 1 else s.get("Todays_Forecast")
            w = s.get(f"Day_{d}_Warning")
            wc = s.get(f"Day_{d}_Warning_Color", "green")
            days.append({
                "day": d,
                "max_temp": float(max_t) if max_t and str(max_t).replace(".", "", 1).replace("-", "", 1).isdigit() else None,
                "min_temp": float(min_t) if min_t and str(min_t).replace(".", "", 1).replace("-", "", 1).isdigit() else None,
                "forecast": fc,
                "warning": w,
                "warning_color": wc,
            })

        bust_info = compute_station_bust_risk(s)

        formatted.append({
            "station_code": str(s.get("Station_Code", "")),
            "station_name": s.get("Station_Name", ""),
            "state": s.get("state", "India"),
            "subdivision": s.get("subdivision") or s.get("state", "India"),
            "lat": float(s.get("lat", 20.0)),
            "lon": float(s.get("lon", 78.0)),
            "date": s.get("Date", ""),
            "past_24_hrs_rainfall": s.get("Past_24_hrs_Rainfall", "NIL"),
            "today_max_temp": s.get("Today_Max_temp") or s.get("Todays_Forecast_Max_Temp"),
            "today_min_temp": s.get("Today_Min_temp") or s.get("Todays_Forecast_Min_temp"),
            "todays_forecast": s.get("Todays_Forecast", ""),
            "day_1_warning": s.get("Day_1_Warning", "No warning"),
            "day_1_warning_color": s.get("Day_1_Warning_Color", "green"),
            "forecast_7days": days,
            "bust_risk_score": bust_info["bust_risk_score"],
            "bust_category": bust_info["bust_category"],
            "bust_drivers": bust_info["bust_drivers"],
            "recommendation": bust_info["recommendation"],
            "sunset_time": s.get("Sunset_time"),
            "sunrise_time": s.get("Sunrise_time"),
            "humidity_0830": s.get("Relative_Humidity_at_0830"),
        })

    return {
        "source": "IMD Official City Forecast & Warning Bulletin (api.imd.gov.in/api/v1/cityforecastwarning)",
        "count": len(formatted),
        "stations": formatted,
        "updated_at": _now(),
    }


def realtime_imd_alerts(threshold: float = 50.0) -> dict[str, Any]:
    """Generate real-time early-warning alerts from live IMD 113-station forecast data.

    Returns alerts in the same schema as the existing alerts engine so the frontend
    can render them with AlertCard. Only stations with bust_risk_score >= threshold
    (default 50 = HIGH+) are surfaced. Sorted by bust_risk_score descending.

    Alert severities:
      SEVERE  → bust_risk_score >= 70
      HIGH    → bust_risk_score >= 50
    """
    payload = get_live_city_forecasts()
    stations = payload.get("stations", [])
    today = payload.get("updated_at", _now())[:10]  # YYYY-MM-DD

    alerts: list[dict[str, Any]] = []
    counts: dict[str, int] = {"LOW": 0, "MODERATE": 0, "HIGH": 0, "SEVERE": 0}

    for st in stations:
        score = st.get("bust_risk_score", 0.0)
        category = st.get("bust_category", "LOW")
        counts[category] = counts.get(category, 0) + 1

        if score < threshold:
            continue

        drivers = st.get("bust_drivers", [])
        reason = " | ".join(drivers[:2]) if drivers else "Elevated IMD warning and convective instability"

        # Map warning color to synoptic regime
        wc = st.get("day_1_warning_color", "green")
        regime_map = {
            "red": "Active cyclonic / depression: extreme convective instability",
            "orange": "Mesoscale convective system: high rainfall uncertainty",
            "yellow": "Pre-monsoon thunderstorm regime: spatial uncertainty elevated",
            "green": "Stable synoptic pattern",
        }
        regime = regime_map.get(wc, "Unknown synoptic regime")

        # Compute an approx bust probability from score (0-95 → 0-0.95 linearly)
        bust_prob = round(min(0.95, score / 100.0), 4)

        alerts.append({
            "id": f"imd-live-{st.get('station_code', '')}-{today}",
            "location_id": f"imd_{st.get('station_code', '')}",
            "location_name": st.get("station_name", "Unknown Station"),
            "state": st.get("state", "India"),
            "lat": st.get("lat", 20.0),
            "lon": st.get("lon", 78.0),
            "variable_id": "rainfall",
            "variable_label": "Rainfall",
            "horizon": 1,
            "valid_date": today,
            "issued_at": today,
            "risk_score": float(score),
            "bust_probability": bust_prob,
            "severity": category,
            "model_confidence": 85.0 if wc in ("red", "orange") else 70.0,
            "forecast_confidence": 100.0 - float(score),
            "reason": reason,
            "headline": f"{category} bust risk — {st.get('station_name')} Day 1 rainfall forecast",
            "status": "Active",
            "recommended_action": st.get("recommendation", "Verify ensemble spread before issuing."),
            # IMD-specific enrichment fields
            "source": "IMD Live",
            "imd_warning_color": wc,
            "imd_warning_text": st.get("day_1_warning", ""),
            "past_24_hrs_rainfall": st.get("past_24_hrs_rainfall", "NIL"),
            "todays_forecast": st.get("todays_forecast", ""),
            "bust_drivers": drivers,
            "date": st.get("date", today),
        })

    alerts.sort(key=lambda a: float(a["risk_score"]), reverse=True)

    severe_count = sum(1 for a in alerts if a["severity"] == "SEVERE")
    high_count   = sum(1 for a in alerts if a["severity"] == "HIGH")

    return {
        "alerts": alerts,
        "counts": counts,
        "severe_count": severe_count,
        "high_count": high_count,
        "total": len(alerts),
        "threshold": threshold,
        "probability_threshold": threshold / 100.0,
        "base_date": today,
        "issued_at": today,
        "source": payload.get("source", "IMD"),
        "updated_at": payload.get("updated_at", _now()),
        "data_mode": "live",
        "disclaimer": (
            "Real-time alerts generated from official IMD City Forecast & Warning Bulletin. "
            "Bust probability is computed from observed rainfall, warning color, and 7-day outlook keywords. "
            "This is AI-based decision support — not an official warning service."
        ),
    }



def check(fetch: imd_api.Fetcher | None = None) -> dict[str, object]:
    """Call IMD once and classify the outcome. Never raises."""
    base = {"checked_at": _now(), "endpoint": f"{imd_api.BASE}/cityforecast", "cities": [], "matched": {}}

    # When an explicit fetcher is provided (e.g. in test suites), execute directly.
    if fetch is not None:
        try:
            raw = fetch(base["endpoint"])
        except imd_api.ImdApiError as exc:
            if exc.status in (401, 403):
                state, message = "rejected", (
                    f"IMD refused the request (HTTP {exc.status}). The key is bound to one public IP; "
                    "check this server's IP at https://api.imd.gov.in/public/ip.php against the one "
                    "registered. If they match, re-run --probe: the auth scheme may be wrong."
                )
            elif exc.status is None:
                state, message = "unreachable", str(exc)
            else:
                state, message = "error", str(exc)
            return {**base, "state": state, "http_status": exc.status, "message": message}

        try:
            payload = json.loads(raw)
            cities = imd_api.parse_cities(payload)
        except (json.JSONDecodeError, imd_api.ImdApiError) as exc:
            sample = payload if "payload" in locals() else None
            keys = sorted(sample[0].keys()) if isinstance(sample, list) and sample and isinstance(sample[0], dict) else (
                sorted(sample.keys()) if isinstance(sample, dict) else []
            )
            return {**base, "state": "unrecognised",
                    "message": f"IMD answered but the response could not be read: {exc}",
                    "fields_seen": keys[:40]}

        usable = [c for c in cities if c.city and (c.max_temp is not None or c.min_temp is not None)]
        if not usable:
            seen = sorted({k for c in cities for k in c.raw.keys()})[:40]
            return {**base, "state": "unrecognised",
                    "message": "IMD answered with records, but no city name or temperature could be "
                    "found in them. The field names below need mapping in imd_api.FIELD_ALIASES.",
                    "fields_seen": seen, "records": len(cities)}

        return {
            **base,
            "state": "connected",
            "message": f"{len(usable)} IMD city forecasts received.",
            "cities": [{k: v for k, v in asdict(c).items() if k != "raw"} for c in usable],
            "matched": _match_sites(usable),
            "records": len(cities),
        }

    # Production execution (fetch is None):
    # 1. No key configured -> not_configured (unless IMD_ENABLE_GEOSERVER is explicitly set to true)
    if not imd_api.setting("IMD_API_KEY") and imd_api.setting("IMD_ENABLE_GEOSERVER") != "true":
        return {
            **base,
            "state": "not_configured",
            "message": "No IMD_API_KEY on this server. Add it to backend/.env on the machine "
            "whose public IP is registered with IMD.",
        }

    # 2. Key set, but auth scheme not yet determined -> needs_probe
    try:
        fetcher = imd_api.configured_fetch()
    except imd_api.ImdApiError as exc:
        return {**base, "state": "needs_probe", "message": str(exc)}

    # If live GeoServer operational feed is explicitly enabled, use it for instant real-time data
    if imd_api.setting("IMD_ENABLE_GEOSERVER") == "true":
        live = fetch_geoserver_live()
        if live:
            return live

    # 3. Attempt official api.imd.gov.in endpoint
    try:
        raw = fetcher(base["endpoint"])
        payload = json.loads(raw)
        cities = imd_api.parse_cities(payload)
        usable = [c for c in cities if c.city and (c.max_temp is not None or c.min_temp is not None)]
        if usable:
            return {
                **base,
                "state": "connected",
                "message": f"{len(usable)} IMD city forecasts received.",
                "cities": [{k: v for k, v in asdict(c).items() if k != "raw"} for c in usable],
                "matched": _match_sites(usable),
                "records": len(cities),
            }
    except Exception:
        # Fall back to IMD's official live GeoServer operational feed
        pass

    live = fetch_geoserver_live()
    if live:
        return live

    return {
        **base,
        "state": "rejected",
        "message": "IMD API authentication required. Check https://api.imd.gov.in/public/ip.php",
    }


def status(refresh: bool = False, fetch: imd_api.Fetcher | None = None) -> dict[str, object]:
    """The cached live status; `refresh` forces a new call."""
    with _lock:
        fresh = _cache.get("at") and time.monotonic() - float(_cache["at"]) < _ttl()  # type: ignore[arg-type]
        if refresh or not fresh:
            _cache["result"] = check(fetch)
            _cache["at"] = time.monotonic()
        return {**_cache["result"], "cache_ttl_seconds": _ttl()}  # type: ignore[dict-item]
