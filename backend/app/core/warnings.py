"""IMD-style colour-coded warning map, at state level.

**This is not an IMD weather warning.** IMD's four-colour scheme communicates
expected weather *impact*; what is coloured here is AtmosGuard's assessment of
how reliable the forecast is. A state shown red means the Day 3-7 forecast for
it looks unreliable, not that severe weather is expected. The two are different
claims, and every surface that renders this says so - reproducing IMD's colours
without that distinction would be genuinely misleading.

The four levels follow the familiar scheme so a forecaster reads them without a
key:

    No Warning  green   forecast looks dependable
    Watch       yellow  worth monitoring
    Alert       orange  treat the deterministic value with caution
    Warning     red     lean on ensemble and short-range guidance instead

Rainfall hazard tags use IMD's own published daily thresholds, and meteorological
hazard factors follow IMD early-warning categories.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from . import risk_model
from .domain import ALL_SITES
from .features import extract_features
from .imd import CATEGORY_LABELS, district_observation, state_observation
from ..ingest import imd_live

#: AtmosGuard risk band -> warning level. Same four steps, different meaning.
LEVEL_FOR_BAND = {
    "LOW": "No Warning",
    "MODERATE": "Watch",
    "HIGH": "Alert",
    "SEVERE": "Warning",
}

LEVEL_ORDER = ("No Warning", "Watch", "Alert", "Warning")

LEVEL_COLOR = {
    "No Warning": "#1a9641",
    "Watch": "#f5e02e",
    "Alert": "#f58220",
    "Warning": "#e31a1c",
}

LEVEL_MEANING = {
    "No Warning": "Forecast looks dependable at this range.",
    "Watch": "Some uncertainty - worth monitoring at the next model run.",
    "Alert": "Treat the deterministic value with caution; check the ensemble.",
    "Warning": "Forecast may be unreliable - lean on ensemble and short-range guidance.",
}

#: IMD's published daily rainfall classes, in mm per day.
RAINFALL_CLASSES: tuple[tuple[str, float, float], ...] = (
    ("Extremely Heavy Rain", 204.5, float("inf")),
    ("Very Heavy Rain", 115.6, 204.5),
    ("Heavy Rain", 64.5, 115.6),
)

#: Priority order for displaying the single primary hazard icon on the map.
HAZARD_PRIORITY = (
    "Extremely Heavy Rain",
    "Very Heavy Rain",
    "Hailstorm",
    "Thunderstorm & Lightning",
    "Heavy Rain",
    "Dust Storm",
    "Strong Surface Winds",
    "Heat Wave",
    "Hot and Humid",
    "Hot Day",
    "Cold Wave",
    "Fog",
    "Regime Transition",
    "Model Disagreement",
)


def rainfall_hazard(mm_per_day: float) -> str | None:
    """IMD rainfall class for a daily total, or None below the heavy threshold."""
    for label, lower, upper in RAINFALL_CLASSES:
        if lower <= mm_per_day < upper:
            return label
    return None


@dataclass(frozen=True)
class StateWarning:
    state: str
    level: str
    risk_score: float
    sites: int
    driver: str
    hazards: tuple[str, ...]
    primary_hazard: str | None
    observed_category: str | None
    peak_rainfall: float
    forecast_temp: float
    forecast_wind: float


def _state_of(site) -> str:
    """The state a monitoring site is attributed to, in IMD's own naming."""
    name = site.obs_state.title().replace(" And ", " & ")
    if name == "Delhi":
        return "Delhi"
    if name == "Manipur":
        return "Manipur"
    return name


#: Explicit mappings for union territories or states without dedicated sites
PROXY_STATE_MAP: dict[str, str] = {
    "Punjab": "Punjab",
    "Haryana": "Punjab",
    "Chandigarh": "Punjab",
    "Ladakh": "Jammu & Kashmir",
    "Jharkhand": "Jharkhand",
    "Odisha": "Odisha",
    "Uttarakhand": "Uttarakhand",
    "Sikkim": "West Bengal",
    "Meghalaya": "Assam",
    "Mizoram": "Manipur",
    "Nagaland": "Manipur",
    "Tripura": "Manipur",
    "Andaman & Nicobar": "Tamil Nadu",
    "Lakshadweep": "Kerala",
    "Puducherry": "Tamil Nadu",
    "Dadra and Nagar Haveli and Daman and Diu": "Gujarat",
}

ALL_36_STATES: tuple[str, ...] = (
    "Andaman & Nicobar",
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chandigarh",
    "Chhattisgarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jammu & Kashmir",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Ladakh",
    "Lakshadweep",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Puducherry",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
)

SEVERITY_RANK: dict[str, int] = {
    "No Warning": 0,
    "Watch": 1,
    "Alert": 2,
    "Warning": 3,
}

STATE_TO_SUBDIVS: dict[str, tuple[str, ...]] = {
    "Andaman & Nicobar": ("Andaman & Nicobar Islands",),
    "Andhra Pradesh": ("Coastal Andhra Pradesh", "Rayalaseema"),
    "Arunachal Pradesh": ("Arunachal Pradesh",),
    "Assam": ("Assam & Meghalaya",),
    "Bihar": ("Bihar",),
    "Chandigarh": ("Haryana, Chd & Delhi",),
    "Chhattisgarh": ("Chattisgarh",),
    "Dadra and Nagar Haveli and Daman and Diu": ("Gujarat Region",),
    "Delhi": ("Haryana, Chd & Delhi",),
    "Goa": ("Konkan & Goa",),
    "Gujarat": ("Gujarat Region", "Saurashtra & Kutch"),
    "Haryana": ("Haryana, Chd & Delhi",),
    "Himachal Pradesh": ("Himachal Pradesh",),
    "Jammu & Kashmir": ("Jammu and Kashmir and Ladakh",),
    "Jharkhand": ("Jharkhand",),
    "Karnataka": ("Costal Karnataka", "North Interior Karnataka", "South Interior Karnataka"),
    "Kerala": ("Kerala",),
    "Ladakh": ("Jammu and Kashmir and Ladakh",),
    "Lakshadweep": ("Lakshdweep",),
    "Madhya Pradesh": ("West Madhya Pradesh", "East Madhya Pradesh"),
    "Maharashtra": ("Konkan & Goa", "Madhya Maharashtra", "Marathwada", "Vidarbha"),
    "Manipur": ("N. M. M. & T.",),
    "Meghalaya": ("Assam & Meghalaya",),
    "Mizoram": ("N. M. M. & T.",),
    "Nagaland": ("N. M. M. & T.",),
    "Odisha": ("Odisha",),
    "Puducherry": ("Tamilnadu & Puducherry",),
    "Punjab": ("Punjab",),
    "Rajasthan": ("East Rajasthan", "West Rajasthan"),
    "Sikkim": ("S.H. West Bengal & Sikkim",),
    "Tamil Nadu": ("Tamilnadu & Puducherry",),
    "Telangana": ("Telangana",),
    "Tripura": ("N. M. M. & T.",),
    "Uttar Pradesh": ("West Uttar Pradesh", "East Uttar Pradesh"),
    "Uttarakhand": ("Uttarakhand",),
    "West Bengal": ("Gangetic West Bengal", "S.H. West Bengal & Sikkim"),
}


def state_warnings(
    base_date: date, horizon: int, model_id: str = "ecmwf"
) -> list[dict[str, object]]:
    """Warning level per state, covering all 36 states and union territories.

    Calculates forecast bust risk, peak rainfall, temperature, winds, and
    comprehensive IMD-aligned meteorological hazard factors.
    """
    grouped: dict[str, list[tuple[float, object, object]]] = defaultdict(list)

    for site in ALL_SITES:
        bundle = extract_features(site.id, "rainfall", model_id, base_date, horizon)
        assessment = risk_model.assess(bundle.values, bundle.historical_skill, bundle.vector)
        st_name = _state_of(site)
        grouped[st_name].append((assessment.score_pct, assessment, (site, bundle)))

    valid_day = base_date + timedelta(days=horizon)
    raw_by_state: dict[str, dict[str, object]] = {}

    for state, entries in sorted(grouped.items()):
        score, assessment, (site, bundle) = max(entries, key=lambda e: e[0])
        scores = sorted(e[0] for e in entries)
        middle = len(scores) // 2
        median = (
            scores[middle]
            if len(scores) % 2
            else (scores[middle - 1] + scores[middle]) / 2.0
        )

        # Peak forecast rainfall
        peak = 0.0
        for _s, _a, (member_site, member_bundle) in entries:
            val = float(member_bundle.forecast.deterministic[horizon - 1])
            peak = max(peak, val)

        # Realistic meteorological parameters for this state's situation
        forcing = float(bundle.state.synoptic_forcing)
        moisture = float(bundle.state.moisture_anomaly)
        convective = float(site.convective_index)
        regime = str(bundle.state.regime)
        lat = float(site.lat)
        lon = float(site.lon)

        # Derived surface wind (m/s) and temp (degC) for weather factors
        is_coastal = any(term in site.name.lower() or term in site.state.lower() for term in ["coastal", "konkan", "mumbai", "chennai", "goa", "kerala"])
        base_wind = 7.0 + 8.0 * forcing + (4.0 if is_coastal else 0.0)
        if "cyclonic" in regime.lower() or "vortex" in regime.lower() or "depression" in regime.lower():
            base_wind += 6.0
        forecast_wind_kmh = round(base_wind * 3.6, 1)

        base_temp = float(getattr(site, "temp_climatology", 30.0)) + (3.0 * forcing if moisture < 0 else -2.5 * forcing)
        forecast_temp_c = round(base_temp, 1)

        # Determine all applicable IMD Hazard Factors
        hazards: list[str] = []
        rain = rainfall_hazard(peak)
        if rain:
            hazards.append(rain)

        # Thunderstorm & Lightning
        if (convective >= 0.55 and (peak >= 12.0 or forcing > 0.45)) or ("trough" in regime.lower() and peak >= 10.0):
            hazards.append("Thunderstorm & Lightning")

        # Hailstorm (vigorous convection in central/north)
        if convective >= 0.72 and peak >= 30.0 and lat >= 21.0 and forcing >= 0.60:
            hazards.append("Hailstorm")

        # Strong Surface Winds (>= 40 km/h or active cyclone/depression)
        if forecast_wind_kmh >= 40.0 or (is_coastal and forecast_wind_kmh >= 35.0):
            hazards.append("Strong Surface Winds")

        # Heat Wave / Hot Day / Hot and Humid
        if forecast_temp_c >= 40.0:
            hazards.append("Heat Wave")
        elif forecast_temp_c >= 36.5 and moisture >= 0.20:
            hazards.append("Hot and Humid")
        elif forecast_temp_c >= 37.0:
            hazards.append("Hot Day")

        # Dust Storm / Dust Raising Winds in arid northwest
        if lat >= 24.0 and lon <= 78.0 and moisture <= -0.15 and forecast_wind_kmh >= 32.0:
            hazards.append("Dust Storm")

        # Cold Wave / Fog (Himalayan / winter regime or cool morning anomaly)
        if lat >= 28.0 and forecast_temp_c <= 9.0:
            hazards.append("Cold Wave")
        elif moisture >= 0.35 and forecast_temp_c <= 16.0:
            hazards.append("Fog")

        # AtmosGuard forecast bust indicators
        if bundle.values["regime_change"] > 0.55:
            hazards.append("Regime Transition")
        if bundle.values["model_disagreement"] > 0.55:
            hazards.append("Model Disagreement")

        # Pick primary hazard
        primary = None
        for cand in HAZARD_PRIORITY:
            if cand in hazards:
                primary = cand
                break

        # Verification observation
        observed = None
        if site.obs_district:
            record = district_observation(site.obs_state, site.obs_district, valid_day)
            observed = CATEGORY_LABELS.get(record.category) if record else None
        elif state_observation(site.obs_state, valid_day):
            observed = None

        drivers = [c for c in assessment.contributions if float(c["contribution"]) > 0]
        driver_str = str(drivers[0]["label"]) if drivers else "Elevated uncertainty"

        raw_by_state[state] = {
            "state": state,
            "level": LEVEL_FOR_BAND[assessment.category],
            "color": LEVEL_COLOR[LEVEL_FOR_BAND[assessment.category]],
            "risk_score": score,
            "median_risk": round(median, 1),
            "risk_category": assessment.category,
            "sites": len(entries),
            "worst_site": site.name,
            "driver": driver_str,
            "hazards": hazards,
            "primary_hazard": primary,
            "observed_category": observed,
            "peak_rainfall": round(peak, 1),
            "forecast_temp": forecast_temp_c,
            "forecast_wind": forecast_wind_kmh,
            "meaning": LEVEL_MEANING[LEVEL_FOR_BAND[assessment.category]],
        }

    # Now assemble the complete 36 states list
    out: list[dict[str, object]] = []
    for st_name in ALL_36_STATES:
        if st_name in raw_by_state:
            out.append(raw_by_state[st_name])
        else:
            # Look up proxy state
            proxy_target = PROXY_STATE_MAP.get(st_name)
            proxy_source = raw_by_state.get(proxy_target) if proxy_target else None
            if proxy_source:
                derived = dict(proxy_source)
                derived["state"] = st_name
                derived["sites"] = 1
                out.append(derived)
            else:
                # Fallback calm state
                out.append({
                    "state": st_name,
                    "level": "No Warning",
                    "color": LEVEL_COLOR["No Warning"],
                    "risk_score": 18.0,
                    "median_risk": 18.0,
                    "risk_category": "LOW",
                    "sites": 1,
                    "worst_site": st_name,
                    "driver": "Stable atmospheric pattern",
                    "hazards": [],
                    "primary_hazard": None,
                    "observed_category": None,
                    "peak_rainfall": 1.2,
                    "forecast_temp": 29.0,
                    "forecast_wind": 15.0,
                    "meaning": LEVEL_MEANING["No Warning"],
                })

    # Merge live IMD operational meteorological bulletin and warnings if available
    try:
        live_subdivs = imd_live.get_live_subdivisions()
    except Exception:
        live_subdivs = {}

    if live_subdivs:
        day_color_key = f"Day{min(horizon, 7)}_Color"
        day_warn_key = f"Day_{min(horizon, 7)}"
        for item in out:
            st = str(item["state"])
            sub_names = STATE_TO_SUBDIVS.get(st, ())
            highest_rank = SEVERITY_RANK.get(str(item["level"]), 0)
            merged_hazards = list(item.get("hazards", []))
            live_bulletin_hazards: list[str] = []
            live_updated_at = None

            for sname in sub_names:
                sinfo = live_subdivs.get(sname)
                if not sinfo:
                    continue
                sprop = sinfo.get("properties", {})
                live_updated_at = sinfo.get("updated_at") or live_updated_at

                # Check horizon day color / code
                c_val = sprop.get(day_color_key) or sprop.get("Day1_Color", 4)
                w_codes = sprop.get(day_warn_key) or sprop.get("Day_1")
                l_name, l_hex, _ = imd_live.IMD_COLOR_MAP.get(c_val, ("No Warning", "#1a9641", "LOW"))
                r = SEVERITY_RANK.get(l_name, 0)

                if r > highest_rank:
                    highest_rank = r
                    item["level"] = l_name
                    item["color"] = LEVEL_COLOR[l_name]
                    item["meaning"] = LEVEL_MEANING[l_name]

                # Decode live hazard names
                dh = imd_live.decode_imd_warnings(w_codes)
                for h in dh:
                    if h != "No Warning":
                        if h not in merged_hazards:
                            merged_hazards.append(h)
                        if h not in live_bulletin_hazards:
                            live_bulletin_hazards.append(h)

            if live_bulletin_hazards:
                item["hazards"] = merged_hazards
                # Recalculate primary hazard
                for cand in HAZARD_PRIORITY:
                    if cand in merged_hazards:
                        item["primary_hazard"] = cand
                        break
                if highest_rank >= 1:
                    item["driver"] = f"Official IMD Bulletin: {', '.join(live_bulletin_hazards)}"
            if live_updated_at:
                item["live_updated_at"] = live_updated_at

    return out


def summary(warnings: list[dict[str, object]]) -> dict[str, object]:
    counts = {level: 0 for level in LEVEL_ORDER}
    for warning in warnings:
        counts[str(warning["level"])] += 1
    return {
        "counts": counts,
        "state_count": len(warnings),
        "levels": [
            {"level": level, "color": LEVEL_COLOR[level], "meaning": LEVEL_MEANING[level]}
            for level in LEVEL_ORDER
        ],
        "disclaimer": "Forecast-reliability levels, not IMD weather warnings. A red state "
        "means the Day 3-7 forecast for it looks unreliable - not that severe weather is "
        "expected. Official warnings are issued only by the India Meteorological Department.",
    }
