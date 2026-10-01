/**
 * IMD Weather Warning Map — Satellite Edition
 *
 * Features:
 * - Esri World Imagery satellite basemap (free, no API key)
 * - OpenStreetMap labels overlay on satellite
 * - Full scroll-wheel zoom to subdivision / district level (zoom 4–16)
 * - Real-time IMD subdivision choropleth from live API data
 * - 4 warning levels: No Warning (Green) → Watch (Yellow) → Alert (Orange) → Warning (Red)
 * - All 17+ IMD hazard factor icons with rich tooltips
 * - Fullscreen toggle, print, home reset
 * - Live-data chip on each state popup showing real IMD bulletin
 * - Andaman & Nicobar inset panel
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  Tooltip,
  ZoomControl,
  useMap,
} from 'react-leaflet';

import L, { type Layer, type PathOptions } from 'leaflet';
import type { Feature, Geometry } from 'geojson';

import indiaStates from '../lib/india-basemap.json';
import type { NetworkSite, StateWarning, WarningsResponse, ImdStationForecast, LiveWeatherResponse } from '../api/types';
import { api } from '../api/client';
import { formatDate } from '../lib/format';

// ─── Constants ───────────────────────────────────────────────────────────────

const INDIA_BOUNDS: [[number, number], [number, number]] = [
  [6.0, 67.0],
  [37.5, 98.0],
];

const INDIA_CENTER: [number, number] = [22.5, 82.5];

// ─── Tile Layers ─────────────────────────────────────────────────────────────

const TILES = {
  satellite: {
    label: '🛰 Satellite',
    layers: [
      {
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attribution: 'Tiles &copy; Esri &mdash; Source: Esri, USGS, NOAA',
        maxZoom: 18,
        opacity: 1,
      },
      // Hybrid labels on top
      {
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        attribution: '',
        maxZoom: 18,
        opacity: 1,
        pane: 'overlayPane',
      },
    ],
  },
  terrain: {
    label: '🗺 Terrain',
    layers: [
      {
        url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
        attribution: '&copy; OpenStreetMap &copy; CARTO',
        maxZoom: 19,
        opacity: 1,
      },
    ],
  },
  dark: {
    label: '🌑 Dark',
    layers: [
      {
        url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
        attribution: '&copy; OpenStreetMap &copy; CARTO',
        maxZoom: 19,
        opacity: 1,
      },
    ],
  },
  osm: {
    label: '🗾 Street Map',
    layers: [
      {
        url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19,
        opacity: 1,
      },
    ],
  },
} as const;

type TileKey = keyof typeof TILES;

// ─── Warning Colours ──────────────────────────────────────────────────────────

const WARNING_LEVELS = [
  { level: 'No Warning', fill: '#22c55e', border: '#16a34a', text: '#fff', meaning: 'Forecast looks dependable' },
  { level: 'Watch',      fill: '#eab308', border: '#a16207', text: '#1e293b', meaning: 'Some uncertainty — monitor updates' },
  { level: 'Alert',      fill: '#f97316', border: '#c2410c', text: '#fff', meaning: 'Treat deterministic forecast with caution' },
  { level: 'Warning',    fill: '#ef4444', border: '#b91c1c', text: '#fff', meaning: 'High bust risk — lean on ensemble' },
] as const;


// ─── Hazard Icons ─────────────────────────────────────────────────────────────

export const HAZARD_DEFINITIONS: Record<string, { label: string; emoji: string; color: string; iconSvg: string }> = {
  'Heavy Rain': {
    label: 'Heavy Rain', emoji: '🌧', color: '#3b82f6',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M4 14a4 4 0 0 1 3.6-4 5 5 0 0 1 9 1.4A3.5 3.5 0 0 1 18 16H5a3 3 0 0 1-1-2z" fill="#93c5fd" stroke="#1d4ed8" stroke-width="1.6"/><path d="M8 18l-1.5 3.5M12 18l-1.5 3.5M16 18l-1.5 3.5" stroke="#2563eb" stroke-width="2"/></svg>`,
  },
  'Very Heavy Rain': {
    label: 'Very Heavy Rain', emoji: '⛈', color: '#2563eb',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M4 13a4 4 0 0 1 3.6-4 5 5 0 0 1 9 1.4A3.5 3.5 0 0 1 18 15H5a3 3 0 0 1-1-2z" fill="#60a5fa" stroke="#1d4ed8" stroke-width="1.6"/><path d="M7 16l-2 4M11 16l-2 4M15 16l-2 4M18 16l-2 4" stroke="#1e40af" stroke-width="2"/></svg>`,
  },
  'Extremely Heavy Rain': {
    label: 'Extremely Heavy Rain', emoji: '🌊', color: '#1d4ed8',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M3 13a4 4 0 0 1 3.6-4 5 5 0 0 1 9 1.4A3.5 3.5 0 0 1 18 15H5a3 3 0 0 1-2-2z" fill="#3b82f6" stroke="#1e3a8a" stroke-width="1.8"/><path d="M6 16l-2.5 5M10 16l-2.5 5M14 16l-2.5 5M18 16l-2.5 5" stroke="#1e40af" stroke-width="2.2"/><path d="M8 7l1-3h3l-2 3h3" stroke="#facc15" stroke-width="1.5" fill="#facc15"/></svg>`,
  },
  'Heavy Snow': {
    label: 'Heavy Snow', emoji: '❄️', color: '#7dd3fc',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#38bdf8" stroke-width="1.8" stroke-linecap="round"><path d="M4 13a4 4 0 0 1 3.6-4 5 5 0 0 1 9 1.4A3.5 3.5 0 0 1 18 15H5a3 3 0 0 1-1-2z" fill="#e0f2fe" stroke="#0284c7" stroke-width="1.5"/><path d="M8 18v3M6.5 19.5l3-1.5M6.5 19.5l3 1.5M14 18v3M12.5 19.5l3-1.5M12.5 19.5l3 1.5" stroke="#0284c7" stroke-width="1.5"/></svg>`,
  },
  'Thunderstorm & Lightning': {
    label: 'Thunderstorm & Lightning', emoji: '⚡', color: '#facc15',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M4 11a4 4 0 0 1 3.6-4 5 5 0 0 1 9 1.4A3.5 3.5 0 0 1 18 13H5a3 3 0 0 1-1-2z" fill="#475569" stroke="#1e293b" stroke-width="1.6"/><path d="M12 12l-3 4.5h3.5l-1.5 5 5-6h-3.5l2-3.5z" fill="#facc15" stroke="#ca8a04" stroke-width="1.3"/></svg>`,
  },
  Hailstorm: {
    label: 'Hailstorm', emoji: '🌨', color: '#38bdf8',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M4 12a4 4 0 0 1 3.6-4 5 5 0 0 1 9 1.4A3.5 3.5 0 0 1 18 14H5a3 3 0 0 1-1-2z" fill="#475569" stroke="#1e293b" stroke-width="1.6"/><circle cx="8" cy="18" r="1.6" fill="#38bdf8" stroke="#0284c7" stroke-width="1.1"/><circle cx="12" cy="19.5" r="1.6" fill="#38bdf8" stroke="#0284c7" stroke-width="1.1"/><circle cx="16" cy="18" r="1.6" fill="#38bdf8" stroke="#0284c7" stroke-width="1.1"/></svg>`,
  },
  'Dust Storm': {
    label: 'Dust Storm', emoji: '🌪', color: '#d97706',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#d97706" stroke-width="2" stroke-linecap="round"><path d="M4 8h13a3 3 0 1 0-3-3M3 12h16a3 3 0 1 1-3 3M5 16h11a2.5 2.5 0 1 0-2-2.5"/></svg>`,
  },
  'Strong Surface Winds': {
    label: 'Strong Surface Winds', emoji: '💨', color: '#6366f1',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M5 12H3M8 6H3M8 18H3M13 6a3 3 0 0 1 3 3 3 3 0 0 1-3 3H3M17 18a3 3 0 0 1-3-3 3 3 0 0 1 3-3h4" stroke="#6366f1" stroke-width="2" stroke-linecap="round"/></svg>`,
  },
  'Heat Wave': {
    label: 'Heat Wave', emoji: '🌡', color: '#ef4444',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M10 14.5a3.5 3.5 0 1 0 5 0V5a2.5 2.5 0 0 0-5 0v9.5z" fill="#fca5a5" stroke="#dc2626" stroke-width="1.6"/><circle cx="12.5" cy="16.5" r="2.2" fill="#ef4444"/><path d="M19 6l-1 2 1 2M21 7l-1 2 1 2" stroke="#ea580c" stroke-width="1.6"/></svg>`,
  },
  'Hot Day': {
    label: 'Hot Day', emoji: '☀️', color: '#f59e0b',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><circle cx="12" cy="12" r="4.5" fill="#fde68a" stroke="#d97706" stroke-width="1.5"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" stroke="#d97706" stroke-width="2"/></svg>`,
  },
  'Hot and Humid': {
    label: 'Hot and Humid', emoji: '🌫', color: '#fb923c',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><circle cx="9" cy="11" r="3.8" fill="#fde68a" stroke="#d97706" stroke-width="1.5"/><path d="M9 3v2M9 17v2M3 11h2M15 11h2" stroke="#d97706" stroke-width="1.6"/><path d="M17 13a3 3 0 0 1 3 3c0 2-3 5-3 5s-3-3-3-5a3 3 0 0 1 3-3z" fill="#38bdf8" stroke="#0284c7" stroke-width="1.4"/></svg>`,
  },
  'Warm Night': {
    label: 'Warm Night', emoji: '🌙', color: '#fbbf24',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M12 3a8 8 0 1 0 9 9 7 7 0 0 1-9-9z" fill="#fef08a" stroke="#ca8a04" stroke-width="1.6"/><path d="M18 5v3M19.5 6.5h-3" stroke="#ef4444" stroke-width="1.6"/></svg>`,
  },
  'Cold Wave': {
    label: 'Cold Wave', emoji: '🥶', color: '#0ea5e9',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M10 14.5a3.5 3.5 0 1 0 5 0V5a2.5 2.5 0 0 0-5 0v9.5z" fill="#bae6fd" stroke="#0284c7" stroke-width="1.6"/><circle cx="12.5" cy="16.5" r="2.2" fill="#0284c7"/><path d="M19 8l-1 2 1 2M21 9l-1 2 1 2" stroke="#0284c7" stroke-width="1.6"/></svg>`,
  },
  'Cold Day': {
    label: 'Cold Day', emoji: '❄', color: '#0284c7',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><circle cx="11" cy="11" r="3.5" stroke="#0284c7" stroke-width="1.5"/><path d="M11 3v2M11 17v2M3 11h2M17 11h2M5.6 5.6l1.4 1.4M14 14l1.4 1.4" stroke="#0284c7" stroke-width="1.5"/><path d="M18 16h4" stroke="#0284c7" stroke-width="2"/></svg>`,
  },
  Fog: {
    label: 'Fog', emoji: '🌁', color: '#94a3b8',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#94a3b8" stroke-width="2" stroke-linecap="round"><path d="M4 8h16M6 12h12M4 16h16M7 20h10"/></svg>`,
  },
  'Ground Frost': {
    label: 'Ground Frost', emoji: '🧊', color: '#38bdf8',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#0ea5e9" stroke-width="1.8" stroke-linecap="round"><path d="M4 20h16M7 20l3-6M12 20v-8M17 20l-3-6M10 10l2 2 2-2M12 6v6"/></svg>`,
  },
  'Regime Transition': {
    label: 'Regime Transition', emoji: '🔄', color: '#818cf8',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#6366f1" stroke-width="1.8" stroke-linecap="round"><path d="M4 8h11a3 3 0 1 0-3-3M20 16H9a3 3 0 1 0 3 3"/><path d="M13 3l3 2-3 2M11 21l-3-2 3-2"/></svg>`,
  },
  'Model Disagreement': {
    label: 'Model Disagreement', emoji: '❓', color: '#f472b6',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#ec4899" stroke-width="1.8" stroke-linecap="round"><path d="M6 18l6-12 6 12M6 12h12"/><path d="M3 8l3-4 3 4M15 8l3-4 3 4"/></svg>`,
  },
  'Thunderstorms with Lightning': {
    label: 'Thunderstorms with Lightning', emoji: '⛈', color: '#facc15',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M4 11a4 4 0 0 1 3.6-4 5 5 0 0 1 9 1.4A3.5 3.5 0 0 1 18 13H5a3 3 0 0 1-1-2z" fill="#475569" stroke="#1e293b" stroke-width="1.6"/><path d="M12 12l-3 4.5h3.5l-1.5 5 5-6h-3.5l2-3.5z" fill="#facc15" stroke="#ca8a04" stroke-width="1.3"/></svg>`,
  },
  'Thunderstorm & Lightning with Gusty Winds': {
    label: 'Thunderstorm & Gusty Winds', emoji: '🌩', color: '#a78bfa',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M4 10a4 4 0 0 1 3.6-4 5 5 0 0 1 9 1.4A3.5 3.5 0 0 1 18 12H5a3 3 0 0 1-1-2z" fill="#475569" stroke="#1e293b" stroke-width="1.6"/><path d="M11 12l-2.5 4h3l-1 4 4-5h-3l1.5-3z" fill="#facc15" stroke="#ca8a04" stroke-width="1.2"/><path d="M16 16h4M17 19h3" stroke="#a78bfa" stroke-width="1.8"/></svg>`,
  },
  'Heavy Rain & Thunderstorm': {
    label: 'Heavy Rain & Thunderstorm', emoji: '🌧⚡', color: '#60a5fa',
    iconSvg: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke-linecap="round"><path d="M4 12a4 4 0 0 1 3.6-4 5 5 0 0 1 9 1.4A3.5 3.5 0 0 1 18 14H5a3 3 0 0 1-1-2z" fill="#60a5fa" stroke="#1d4ed8" stroke-width="1.5"/><path d="M10 14l-2 3h2.5l-1 4 3.5-4.5H10.5l1.5-2.5z" fill="#facc15" stroke="#ca8a04" stroke-width="1.1"/></svg>`,
  },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function norm(name: string): string {
  return name.toLowerCase().replace(/&/g, 'and').replace(/[^a-z]/g, '');
}

function createHazardIcon(hazardName: string): L.DivIcon {
  const def = HAZARD_DEFINITIONS[hazardName];
  const svg = def?.iconSvg ?? HAZARD_DEFINITIONS['Thunderstorm & Lightning'].iconSvg;
  return L.divIcon({
    className: '',
    iconSize: [32, 32],
    iconAnchor: [16, 16],
    html: `<div style="
      width:32px;height:32px;display:flex;align-items:center;justify-content:center;
      background:rgba(255,255,255,0.95);border:1.5px solid rgba(0,0,0,0.5);
      border-radius:7px;box-shadow:0 2px 8px rgba(0,0,0,0.45);
      cursor:pointer;transition:transform .12s;
    ">${svg}</div>`,
  });
}

// ─── Map sub-components ───────────────────────────────────────────────────────

function FitIndia({ token }: { token: number }) {
  const map = useMap();
  useEffect(() => {
    map.invalidateSize({ animate: false });
    map.fitBounds(INDIA_BOUNDS, { padding: [16, 16], animate: true });
  }, [map, token]);
  return null;
}

function ScrollZoomEnabler() {
  const map = useMap();
  useEffect(() => {
    map.scrollWheelZoom.enable();
  }, [map]);
  return null;
}

// ─── Props ────────────────────────────────────────────────────────────────────

export interface ImdWeatherMapProps {
  warnings: WarningsResponse | null;
  sites?: NetworkSite[];
  selectedLocationId?: string;
  onSelectSite?: (siteId: string) => void;
  onSelectState?: (state: StateWarning) => void;
  height?: number | string;
  horizon?: number;
  baseDate?: string;
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function ImdWeatherMap({
  warnings,
  sites = [],
  selectedLocationId,
  onSelectSite,
  onSelectState,
  height = 600,
  horizon = 5,
  baseDate,
}: ImdWeatherMapProps) {
  const [tileKey, setTileKey] = useState<TileKey>('satellite');
  const [transparent, setTransparent] = useState(false);
  const [showHazards, setShowHazards] = useState(true);
  const [showSites, setShowSites] = useState(false);
  const [showImdStations, setShowImdStations] = useState(true);
  const [imdStations, setImdStations] = useState<ImdStationForecast[]>([]);
  const [selectedStation, setSelectedStation] = useState<ImdStationForecast | null>(null);
  const [activeFilter, setActiveFilter] = useState<string | null>(null);
  const [resetToken, setResetToken] = useState(0);
  const [selectedState, setSelectedState] = useState<StateWarning | null>(null);
  const [layerOpen, setLayerOpen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSubdivision, setSelectedSubdivision] = useState<string>('ALL');
  const [liveObs, setLiveObs] = useState<LiveWeatherResponse | null>(null);
  const [liveObsLoading, setLiveObsLoading] = useState(false);
  const mapRef = useRef<L.Map | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.cityForecast()
      .then((res) => {
        if (res?.stations) {
          setImdStations(res.stations);
        }
      })
      .catch(() => {});
  }, []);

  // Fetch real-time live weather when a station is clicked
  useEffect(() => {
    if (!selectedStation) {
      setLiveObs(null);
      return;
    }
    setLiveObsLoading(true);
    api.liveWeather(selectedStation.lat, selectedStation.lon)
      .then((data) => setLiveObs(data))
      .catch(() => setLiveObs(null))
      .finally(() => setLiveObsLoading(false));
  }, [selectedStation]);

  // Unique subdivisions sorted alphabetically
  const subdivisions = useMemo(() => {
    const set = new Set<string>();
    for (const st of imdStations) {
      if (st.subdivision) set.add(st.subdivision);
    }
    return Array.from(set).sort();
  }, [imdStations]);

  // Filtered stations based on search query, subdivision, and warning filter
  const filteredStations = useMemo(() => {
    return imdStations.filter((st) => {
      if (selectedSubdivision !== 'ALL' && st.subdivision !== selectedSubdivision) {
        return false;
      }
      if (activeFilter) {
        const warnColor = (st.day_1_warning_color || 'green').toLowerCase();
        if (activeFilter === 'Red Alert' && warnColor !== 'red') return false;
        if (activeFilter === 'Orange Alert' && warnColor !== 'orange') return false;
        if (activeFilter === 'Yellow Watch' && warnColor !== 'yellow') return false;
        if (activeFilter === 'Green Normal' && warnColor !== 'green') return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchName = st.station_name.toLowerCase().includes(q);
        const matchState = st.state.toLowerCase().includes(q);
        const matchSub = (st.subdivision || '').toLowerCase().includes(q);
        if (!matchName && !matchState && !matchSub) return false;
      }
      return true;
    });
  }, [imdStations, selectedSubdivision, activeFilter, searchQuery]);

  // Build lookup from warning data
  const stateMap = useMemo(() => {
    const m = new Map<string, StateWarning>();
    for (const s of warnings?.states ?? []) m.set(norm(s.state), s);
    return m;
  }, [warnings?.states]);

  const lookup = useCallback(
    (feature?: Feature<Geometry, { st_nm?: string }>) =>
      feature?.properties?.st_nm ? stateMap.get(norm(feature.properties.st_nm)) : undefined,
    [stateMap],
  );

  // Hazard glyph positions
  const stateGlyphs = useMemo(() => {
    if (!showHazards || !warnings?.states) return [];
    const features = (
      indiaStates as unknown as {
        features: Feature<Geometry, { st_nm?: string; label_point?: [number, number] }>[];
      }
    ).features;

    return features.flatMap((f) => {
      const sw = lookup(f);
      const pt = f.properties?.label_point;
      if (!sw || !pt) return [];
      const hazard = sw.primary_hazard ?? sw.hazards?.[0] ?? null;
      if (!hazard) return [];
      if (activeFilter) {
        if (sw.level !== activeFilter && !sw.hazards.includes(activeFilter) && sw.primary_hazard !== activeFilter) return [];
      }
      return [{ state: sw.state, hazard, warning: sw, pos: [pt[1], pt[0]] as [number, number] }];
    });
  }, [showHazards, warnings?.states, lookup, activeFilter]);

  const andaman = useMemo(
    () => warnings?.states.find((s) => s.state.toLowerCase().includes('andaman')),
    [warnings?.states],
  );

  // Fullscreen
  const toggleFullscreen = useCallback(() => {
    if (!wrapRef.current) return;
    if (!document.fullscreenElement) {
      wrapRef.current.requestFullscreen?.();
      setIsFullscreen(true);
    } else {
      document.exitFullscreen?.();
      setIsFullscreen(false);
    }
  }, []);

  useEffect(() => {
    const onFsChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

  const mapHeight = isFullscreen ? '100vh' : height;

  return (
    <div ref={wrapRef} className="flex flex-col bg-[#0f172a] rounded-xl border border-slate-700/60 overflow-hidden shadow-2xl">
      {/* ── Top Legend Bar ────────────────────────────────────────────────── */}
      <div className="bg-gradient-to-r from-[#0f172a] via-[#1e293b] to-[#0f172a] border-b border-slate-700 select-none px-3 py-2">
        {/* Warning level pills */}
        <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-700/50">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mr-1">
              Warning Levels:
            </span>
            {WARNING_LEVELS.map((w) => {
              const count = (warnings?.counts as Record<string, number>)?.[w.level] ?? 0;
              const sel = activeFilter === w.level;
              return (
                <button
                  key={w.level}
                  type="button"
                  onClick={() => setActiveFilter(sel ? null : w.level)}
                  title={w.meaning}
                  className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-bold transition-all border ${
                    sel ? 'ring-2 ring-white/80 scale-105' : 'hover:scale-105'
                  }`}
                  style={{ backgroundColor: w.fill, color: w.text, borderColor: w.border }}
                >
                  {w.level}
                  <span className="bg-black/25 px-1 rounded-full text-[10px]">{count}</span>
                </button>
              );
            })}
          </div>
          {activeFilter && (
            <button
              type="button"
              onClick={() => setActiveFilter(null)}
              className="text-[11px] text-amber-300 hover:text-white underline font-medium"
            >
              ✕ Clear "{activeFilter}"
            </button>
          )}
        </div>

        {/* Hazard factor row */}
        <div className="pt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] overflow-x-auto max-h-20 pr-1">
          {Object.entries(HAZARD_DEFINITIONS).map(([name, def]) => {
            const sel = activeFilter === name;
            return (
              <button
                key={name}
                type="button"
                onClick={() => setActiveFilter(sel ? null : name)}
                className={`flex items-center gap-1 px-1.5 py-0.5 rounded transition-all whitespace-nowrap ${
                  sel
                    ? 'bg-amber-400/20 ring-1 ring-amber-400 text-amber-200'
                    : 'text-slate-300 hover:text-white hover:bg-white/5'
                }`}
              >
                <span className="shrink-0 w-5 h-5 flex items-center justify-center"
                  dangerouslySetInnerHTML={{ __html: def.iconSvg }}
                />
                <span className="font-medium">{def.label}</span>
              </button>
            );
          })}
        </div>

        {/* Search & Subdivision Selector Bar */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-700/60 pt-2 text-xs">
          <div className="flex items-center gap-2 flex-1 min-w-[240px]">
            <div className="relative flex-1">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="🔍 Search 270+ cities / districts (e.g. Pune, Dehradun, Siliguri, Surat, Srinagar)..."
                className="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-400 focus:outline-none focus:border-sky-500"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Subdivision Filter Dropdown */}
            <select
              value={selectedSubdivision}
              onChange={(e) => setSelectedSubdivision(e.target.value)}
              className="bg-slate-900/90 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500 cursor-pointer max-w-[220px]"
            >
              <option value="ALL">All Subdivisions ({subdivisions.length})</option>
              {subdivisions.map((sub) => (
                <option key={sub} value={sub}>{sub}</option>
              ))}
            </select>
          </div>

          <div className="text-[11px] text-slate-400 font-medium">
            Showing <strong className="text-sky-400 font-bold">{filteredStations.length}</strong> of {imdStations.length} IMD observatories
          </div>
        </div>
      </div>

      {/* ── Map Container ─────────────────────────────────────────────────── */}
      <div className="relative w-full" style={{ height: mapHeight }}>

        {/* Floating top-left: Home + Print + Fullscreen */}
        <div className="absolute top-3 left-3 z-[1000] flex flex-col gap-1.5">
          <div className="bg-slate-900/90 backdrop-blur-sm border border-slate-600 rounded-lg p-1 flex flex-col gap-1 shadow-xl">
            {/* Home */}
            <button
              type="button"
              onClick={() => setResetToken((n) => n + 1)}
              title="Reset to India view"
              className="w-8 h-8 flex items-center justify-center rounded-md text-slate-200 hover:bg-slate-700 hover:text-white transition-colors"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                <path d="M9 22V12h6v10"/>
              </svg>
            </button>
            {/* Print */}
            <button
              type="button"
              onClick={() => window.print()}
              title="Print / Export"
              className="w-8 h-8 flex items-center justify-center rounded-md text-slate-200 hover:bg-slate-700 hover:text-white transition-colors"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>
                <path d="M6 14h12v8H6z"/>
              </svg>
            </button>
            {/* Fullscreen */}
            <button
              type="button"
              onClick={toggleFullscreen}
              title={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
              className="w-8 h-8 flex items-center justify-center rounded-md text-slate-200 hover:bg-slate-700 hover:text-white transition-colors"
            >
              {isFullscreen ? (
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"/></svg>
              ) : (
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
              )}
            </button>
          </div>
        </div>

        {/* Floating top-right: layers + overlays */}
        <div className="absolute top-3 right-3 z-[1000] flex items-center gap-2">
          {/* Transparent toggle */}
          <button
            type="button"
            onClick={() => setTransparent(!transparent)}
            title="Toggle transparent overlay"
            className={`px-2.5 py-1.5 rounded-lg text-[11px] font-semibold border backdrop-blur-sm shadow-lg transition-all ${
              transparent
                ? 'bg-sky-500 border-sky-400 text-white'
                : 'bg-slate-900/90 border-slate-600 text-slate-300 hover:text-white'
            }`}
          >
            Transparent
          </button>

          {/* Layer switcher */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setLayerOpen(!layerOpen)}
              title="Map Layers"
              className="bg-slate-900/90 backdrop-blur-sm border border-slate-600 rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-slate-200 hover:text-white shadow-lg flex items-center gap-1.5 transition-colors"
            >
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <polygon points="12 2 2 7 12 12 22 7 12 2"/>
                <polyline points="2 17 12 22 22 17"/>
                <polyline points="2 12 12 17 22 12"/>
              </svg>
              Layers
            </button>

            {layerOpen && (
              <div className="absolute right-0 mt-2 w-56 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl p-3 z-[1001] space-y-3 text-[11px] text-slate-200">
                <div className="font-bold text-slate-400 uppercase tracking-wider text-[9px]">Basemap</div>
                <div className="space-y-1.5">
                  {(Object.keys(TILES) as TileKey[]).map((k) => (
                    <label key={k} className="flex items-center gap-2 cursor-pointer hover:text-white">
                      <input
                        type="radio"
                        name="tile"
                        checked={tileKey === k}
                        onChange={() => { setTileKey(k); setLayerOpen(false); }}
                        className="accent-sky-500"
                      />
                      {TILES[k].label}
                    </label>
                  ))}
                </div>
                <div className="border-t border-slate-700 pt-2">
                  <div className="font-bold text-slate-400 uppercase tracking-wider text-[9px] mb-1.5">Overlays</div>
                  <label className="flex items-center gap-2 cursor-pointer hover:text-white mb-1">
                    <input type="checkbox" checked={showImdStations} onChange={(e) => setShowImdStations(e.target.checked)} className="accent-sky-500" />
                    <span className="flex items-center gap-1">
                      <span>IMD Stations</span>
                      <span className="bg-emerald-500/20 text-emerald-300 text-[9px] px-1 rounded font-bold">
                        {imdStations.length || 113}
                      </span>
                    </span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer hover:text-white mb-1">
                    <input type="checkbox" checked={showHazards} onChange={(e) => setShowHazards(e.target.checked)} className="accent-sky-500" />
                    Hazard Icons
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer hover:text-white">
                    <input type="checkbox" checked={showSites} onChange={(e) => setShowSites(e.target.checked)} className="accent-sky-500" />
                    Bust Network Sites
                  </label>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Zoom hint */}
        <div className="absolute bottom-10 left-1/2 -translate-x-1/2 z-[999] pointer-events-none">
          <div className="bg-slate-900/70 text-slate-400 text-[10px] px-2 py-0.5 rounded-full backdrop-blur-sm border border-slate-700">
            Scroll to zoom · Click state for details
          </div>
        </div>

        {/* Andaman Inset */}
        {andaman && (
          <div className="absolute bottom-3 right-3 z-[1000] bg-slate-900/95 border border-slate-700 rounded-xl p-2.5 shadow-2xl backdrop-blur-sm max-w-[160px]">
            <div className="text-[9px] uppercase tracking-widest font-bold text-slate-500 mb-1.5 border-b border-slate-700 pb-1">
              A &amp; N Islands
            </div>
            <div className="flex items-center gap-2">
              <div
                className="w-6 h-8 rounded border border-black/30 shadow-inner flex items-center justify-center"
                style={{ backgroundColor: andaman.color }}
              >
                {andaman.primary_hazard && (
                  <span
                    className="w-5 h-5 scale-75"
                    dangerouslySetInnerHTML={{ __html: HAZARD_DEFINITIONS[andaman.primary_hazard]?.iconSvg ?? '' }}
                  />
                )}
              </div>
              <div>
                <div className="text-[11px] font-bold text-white">{andaman.level}</div>
                <div className="text-[10px] text-amber-300 font-semibold">Risk {andaman.risk_score.toFixed(0)}%</div>
                {andaman.primary_hazard && (
                  <div className="text-[9px] text-slate-400 leading-tight">{andaman.primary_hazard}</div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Leaflet Map ─────────────────────────────────────────────────── */}
        <MapContainer
          center={INDIA_CENTER}
          zoom={5}
          minZoom={4}
          maxZoom={16}
          zoomSnap={0.5}
          zoomDelta={0.5}
          scrollWheelZoom={true}
          doubleClickZoom={true}
          attributionControl={true}
          zoomControl={false}
          className="h-full w-full"
          style={{ height: '100%', width: '100%', background: '#0f172a' }}
          ref={mapRef}
          whenReady={() => {}}
        >
          <FitIndia token={resetToken} />
          <ScrollZoomEnabler />
          <ZoomControl position="bottomleft" />

          {/* Tile layers */}
          {TILES[tileKey].layers.map((layer, i) => (
            <TileLayer key={`${tileKey}-${i}`} url={layer.url} attribution={layer.attribution} maxZoom={layer.maxZoom} opacity={layer.opacity} />
          ))}

          {/* State choropleth */}
          <GeoJSON
            key={`choropleth-${tileKey}-${transparent}-${activeFilter}-${warnings?.counts ? JSON.stringify(warnings.counts) : 'none'}`}
            data={indiaStates as never}
            style={(feature): PathOptions => {
              const sw = lookup(feature as Feature<Geometry, { st_nm?: string }>);
              const inFilter = activeFilter
                ? sw?.level === activeFilter || sw?.hazards.includes(activeFilter) || sw?.primary_hazard === activeFilter
                : true;
              const fill = sw ? sw.color : '#1e293b';
              const opacity = transparent ? 0.28 : inFilter ? 0.78 : 0.12;
              return {
                fillColor: fill,
                fillOpacity: opacity,
                color: transparent ? 'rgba(255,255,255,0.4)' : '#fff',
                weight: transparent ? 0.8 : 1.2,
              };
            }}
            onEachFeature={(feature: Feature<Geometry, { st_nm?: string }>, layer: Layer) => {
              const name = feature.properties?.st_nm ?? 'State';
              const sw = lookup(feature);
              if (sw) {
                const prim = sw.primary_hazard ?? sw.hazards?.[0] ?? 'Standard Guidance';
                const hazIconHtml = HAZARD_DEFINITIONS[prim]?.iconSvg ?? '';
                const liveChip = (sw as unknown as Record<string, unknown>).live_updated_at
                  ? `<span style="background:#22c55e;color:#fff;font-size:9px;padding:1px 5px;border-radius:99px;font-weight:700;letter-spacing:.5px;vertical-align:middle">● LIVE</span>`
                  : '';
                layer.bindTooltip(
                  `<div style="font-family:system-ui,sans-serif;min-width:160px;padding:2px 0">
                    <div style="font-size:13px;font-weight:700;color:#0f172a;margin-bottom:3px">${name} ${liveChip}</div>
                    <div style="display:flex;align-items:center;gap:5px">
                      <span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${sw.color};border:1px solid rgba(0,0,0,.3)"></span>
                      <strong style="color:#0f172a">${sw.level}</strong>
                      <span style="color:#64748b;font-size:11px">· ${sw.risk_score.toFixed(0)}% risk</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:4px;margin-top:4px;font-size:11px;color:#334155">
                      <span style="width:18px;height:18px">${hazIconHtml}</span>
                      ${prim}
                    </div>
                    ${sw.peak_rainfall > 5 ? `<div style="font-size:10px;color:#1d4ed8;margin-top:2px">🌧 ${sw.peak_rainfall.toFixed(1)} mm peak rain</div>` : ''}
                    ${sw.forecast_temp ? `<div style="font-size:10px;color:#dc2626;margin-top:1px">🌡 ${sw.forecast_temp}°C forecast</div>` : ''}
                   </div>`,
                  { sticky: true, direction: 'top', opacity: 0.97, className: 'imd-tooltip' },
                );
                layer.on('click', () => {
                  setSelectedState(sw);
                  onSelectState?.(sw);
                });
              } else {
                layer.bindTooltip(`<strong>${name}</strong><br/><span style="opacity:.6;font-size:11px">No active data</span>`, {
                  sticky: true,
                });
              }
            }}
          />

          {/* Hazard glyphs */}
          {showHazards &&
            stateGlyphs.map((g) => (
              <Marker
                key={g.state}
                position={g.pos}
                icon={createHazardIcon(g.hazard)}
                eventHandlers={{ click: () => setSelectedState(g.warning) }}
              />
            ))}

          {/* IMD Official Weather Stations */}
          {showImdStations &&
            filteredStations.map((st) => {
              const warningColorLower = st.day_1_warning_color?.toLowerCase() || 'green';
              const color =
                warningColorLower === 'red'
                  ? '#ef4444'
                  : warningColorLower === 'orange'
                  ? '#f97316'
                  : warningColorLower === 'yellow'
                  ? '#eab308'
                  : '#22c55e';
              const isSevere = warningColorLower === 'red' || warningColorLower === 'orange';
              const isSelected = selectedStation?.station_code === st.station_code;
              return (
                <CircleMarker
                  key={st.station_code + st.station_name}
                  center={[st.lat, st.lon]}
                  radius={isSelected ? 10 : isSevere ? 7.5 : 5.5}
                  pathOptions={{
                    fillColor: color,
                    fillOpacity: 0.95,
                    color: isSevere ? '#ffffff' : '#0f172a',
                    weight: isSelected ? 3 : isSevere ? 2 : 1.2,
                  }}
                  eventHandlers={{
                    click: () => {
                      setSelectedStation(st);
                      setSelectedState(null);
                    },
                  }}
                >
                  <Tooltip direction="top" opacity={0.97} className="imd-tooltip">
                    <div style={{ fontFamily: 'system-ui,sans-serif', minWidth: 170 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                        <span>{st.station_name}</span>
                        <span
                          style={{
                            fontSize: 9,
                            background: color,
                            color: color === '#eab308' ? '#0f172a' : '#fff',
                            padding: '1px 5px',
                            borderRadius: 99,
                            fontWeight: 700,
                            textTransform: 'uppercase',
                          }}
                        >
                          {st.day_1_warning_color || 'green'}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: '#0369a1', fontWeight: 600, marginTop: 1 }}>
                        📍 {st.subdivision ? `${st.subdivision} · ` : ''}{st.state}
                      </div>
                      <div style={{ fontSize: 10, color: '#64748b' }}>
                        Station #{st.station_code}
                      </div>
                      <div style={{ fontSize: 11, fontWeight: 600, color: '#1e293b', marginTop: 4 }}>
                        {st.todays_forecast || st.day_1_warning}
                      </div>
                      {st.past_24_hrs_rainfall && st.past_24_hrs_rainfall !== 'NIL' && st.past_24_hrs_rainfall !== 'NA' && (
                        <div style={{ fontSize: 11, color: '#1d4ed8', fontWeight: 700, marginTop: 2 }}>
                          🌧 Past 24h Rain: {st.past_24_hrs_rainfall} mm
                        </div>
                      )}
                      {st.today_max_temp && (
                        <div style={{ fontSize: 11, color: '#dc2626', marginTop: 1 }}>
                          🌡 {st.today_max_temp}°C max {st.today_min_temp ? `/ ${st.today_min_temp}°C min` : ''}
                        </div>
                      )}
                      {st.bust_risk_score !== undefined && (
                        <div style={{ fontSize: 11, fontWeight: 700, marginTop: 4, display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid rgba(0,0,0,0.1)', paddingTop: 3 }}>
                          <span style={{ color: '#475569' }}>Forecast Bust Risk:</span>
                          <span
                            style={{
                              color:
                                st.bust_category === 'SEVERE'
                                  ? '#dc2626'
                                  : st.bust_category === 'HIGH'
                                  ? '#ea580c'
                                  : st.bust_category === 'MODERATE'
                                  ? '#d97706'
                                  : '#16a34a',
                            }}
                          >
                            {st.bust_risk_score}% ({st.bust_category})
                          </span>
                        </div>
                      )}
                      <div style={{ fontSize: 9, color: '#0284c7', marginTop: 4, fontWeight: 600 }}>
                        Click to view 7-Day Forecast & Warnings →
                      </div>
                    </div>
                  </Tooltip>

                </CircleMarker>
              );
            })}

          {/* Station pins */}
          {showSites &&
            sites.map((site) => {
              const sel = site.id === selectedLocationId;
              return (
                <CircleMarker
                  key={site.id}
                  center={[site.lat, site.lon]}
                  radius={sel ? 8 : 5}
                  pathOptions={{ fillColor: '#38bdf8', fillOpacity: 1, color: '#0f172a', weight: 2 }}
                  eventHandlers={{ click: () => onSelectSite?.(site.id) }}
                >
                  <Popup>
                    <div className="p-1 space-y-1 text-sm">
                      <div className="font-bold">{site.name}</div>
                      <div>Risk: <strong>{site.risk_score.toFixed(0)}%</strong></div>
                      <div>Category: <strong>{site.risk_category}</strong></div>
                      {onSelectSite && (
                        <button
                          type="button"
                          onClick={() => onSelectSite(site.id)}
                          className="mt-1 w-full px-2 py-1 bg-sky-600 text-white rounded text-xs font-semibold hover:bg-sky-500"
                        >
                          Select
                        </button>
                      )}
                    </div>
                  </Popup>
                </CircleMarker>
              );
            })}
        </MapContainer>


        {/* ── Selected State Panel ──────────────────────────────────────── */}
        {selectedState && (
          <div className="absolute top-3 left-14 z-[1001] bg-slate-950/97 border border-slate-700 rounded-2xl p-4 shadow-2xl text-slate-100 w-72 animate-in fade-in slide-in-from-left-2 backdrop-blur-sm">
            {/* Header */}
            <div className="flex items-start justify-between gap-2 mb-3">
              <div>
                <h4 className="font-black text-base leading-tight text-white">{selectedState.state}</h4>
                <div className="flex items-center gap-2 mt-1">
                  <span
                    className="px-2 py-0.5 rounded-full text-xs font-bold border"
                    style={{
                      backgroundColor: selectedState.color,
                      borderColor: selectedState.color,
                      color: selectedState.level === 'Watch' ? '#1e293b' : '#fff',
                    }}
                  >
                    {selectedState.level}
                  </span>
                  <span className="text-slate-400 text-xs">Bust Risk {selectedState.risk_score.toFixed(0)}%</span>
                  {(selectedState as unknown as Record<string,unknown>).live_updated_at ? (
                    <span className="text-[9px] bg-emerald-500 text-white px-1.5 py-0.5 rounded-full font-bold">● LIVE</span>
                  ) : null}

                </div>
              </div>
              <button type="button" onClick={() => setSelectedState(null)} className="text-slate-500 hover:text-white text-xl leading-none">×</button>
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-3 gap-2 mb-3">
              <div className="bg-slate-800/80 rounded-lg p-2 text-center">
                <div className="text-[9px] text-slate-500 uppercase tracking-wider">Rain</div>
                <div className="text-sm font-black text-blue-300">{selectedState.peak_rainfall.toFixed(1)}<span className="text-[9px] font-normal">mm</span></div>
              </div>
              <div className="bg-slate-800/80 rounded-lg p-2 text-center">
                <div className="text-[9px] text-slate-500 uppercase tracking-wider">Temp</div>
                <div className="text-sm font-black text-orange-300">
                  {selectedState.forecast_temp ? `${selectedState.forecast_temp}°` : '--'}
                </div>
              </div>
              <div className="bg-slate-800/80 rounded-lg p-2 text-center">
                <div className="text-[9px] text-slate-500 uppercase tracking-wider">Wind</div>
                <div className="text-sm font-black text-indigo-300">
                  {selectedState.forecast_wind ? `${selectedState.forecast_wind}` : '--'}<span className="text-[9px] font-normal">km/h</span>
                </div>
              </div>
            </div>

            {/* Primary hazard */}
            {selectedState.primary_hazard && (
              <div className="flex items-center gap-2 bg-amber-400/10 border border-amber-500/30 rounded-lg px-3 py-2 mb-2">
                <span
                  className="w-6 h-6 shrink-0"
                  dangerouslySetInnerHTML={{ __html: HAZARD_DEFINITIONS[selectedState.primary_hazard]?.iconSvg ?? '' }}
                />
                <div>
                  <div className="text-[9px] text-amber-500 uppercase tracking-wider font-bold">Primary Hazard</div>
                  <div className="text-xs font-semibold text-amber-200">{selectedState.primary_hazard}</div>
                </div>
              </div>
            )}

            {/* Active factors */}
            {selectedState.hazards.length > 0 && (
              <div className="mb-2">
                <div className="text-[9px] text-slate-500 uppercase tracking-wider font-bold mb-1.5">Active Factors</div>
                <div className="flex flex-wrap gap-1">
                  {selectedState.hazards.map((h) => (
                    <span key={h} className="flex items-center gap-1 bg-slate-800 px-1.5 py-0.5 rounded-md text-[10px] text-slate-300 border border-slate-700">
                      <span dangerouslySetInnerHTML={{ __html: HAZARD_DEFINITIONS[h]?.iconSvg ?? '' }} className="w-3.5 h-3.5" />
                      {h}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Driver */}
            <div className="text-[11px] text-slate-400 italic leading-tight border-t border-slate-800 pt-2">
              {selectedState.driver}
            </div>
          </div>
        )}

        {/* ── Selected IMD Station 7-Day Forecast Panel ────────────────────── */}
        {selectedStation && (
          <div className="absolute top-3 left-14 z-[1001] bg-slate-950/97 border border-slate-700 rounded-2xl p-4 shadow-2xl text-slate-100 w-80 max-w-[90vw] animate-in fade-in slide-in-from-left-2 backdrop-blur-sm max-h-[85vh] overflow-y-auto">
            {/* Header */}
            <div className="flex items-start justify-between gap-2 mb-3">
              <div>
                <div className="flex items-center gap-1.5">
                  <h4 className="font-black text-base leading-tight text-white">{selectedStation.station_name}</h4>
                  <span className="text-[9px] bg-sky-500/20 text-sky-300 border border-sky-500/40 px-1.5 py-0.5 rounded-full font-bold">
                    #{selectedStation.station_code}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-slate-400 text-xs">{selectedStation.state}</span>
                  <span
                    className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border"
                    style={{
                      backgroundColor:
                        selectedStation.day_1_warning_color === 'red'
                          ? '#ef4444'
                          : selectedStation.day_1_warning_color === 'orange'
                          ? '#f97316'
                          : selectedStation.day_1_warning_color === 'yellow'
                          ? '#eab308'
                          : '#22c55e',
                      borderColor: 'transparent',
                      color: selectedStation.day_1_warning_color === 'yellow' ? '#1e293b' : '#fff',
                    }}
                  >
                    {selectedStation.day_1_warning_color || 'green'} Warning
                  </span>
                </div>
                {selectedStation.subdivision && (
                  <div className="mt-1 text-[11px] text-sky-300 font-semibold flex items-center gap-1">
                    <span className="text-[9px] uppercase tracking-wider text-slate-400 font-normal">Sub-division:</span>
                    <span>{selectedStation.subdivision}</span>
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => setSelectedStation(null)}
                className="text-slate-500 hover:text-white text-xl leading-none"
              >
                ×
              </button>
            </div>

            {/* Live Atmospheric Telemetry (Open-Meteo & WMO Realtime Telemetry) */}
            <div className="bg-slate-900/90 border border-slate-700/80 rounded-xl p-2.5 mb-3 shadow-md">
              <div className="flex items-center justify-between text-[9px] uppercase tracking-wider font-bold text-emerald-400 mb-1.5">
                <span className="flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Live Atmospheric Telemetry
                </span>
                <span className="text-slate-400 text-[8px] font-normal">Realtime Sensors</span>
              </div>
              {liveObsLoading ? (
                <div className="text-[10px] text-slate-400 animate-pulse py-1">Fetching live weather telemetry…</div>
              ) : liveObs && liveObs.temperature !== null ? (
                <div>
                  <div className="grid grid-cols-4 gap-1 text-center mb-1.5">
                    <div className="bg-slate-800/90 rounded p-1">
                      <div className="text-[8px] text-slate-400 uppercase">Live Temp</div>
                      <div className="text-xs font-bold text-amber-300">{liveObs.temperature}°C</div>
                    </div>
                    <div className="bg-slate-800/90 rounded p-1">
                      <div className="text-[8px] text-slate-400 uppercase">Humidity</div>
                      <div className="text-xs font-bold text-sky-300">{liveObs.relative_humidity}%</div>
                    </div>
                    <div className="bg-slate-800/90 rounded p-1">
                      <div className="text-[8px] text-slate-400 uppercase">Rain Now</div>
                      <div className="text-xs font-bold text-blue-300">{liveObs.precipitation_mm ?? 0} mm</div>
                    </div>
                    <div className="bg-slate-800/90 rounded p-1">
                      <div className="text-[8px] text-slate-400 uppercase">Wind</div>
                      <div className="text-xs font-bold text-indigo-300">{liveObs.wind_speed_kmh ?? 0} km/h</div>
                    </div>
                  </div>
                  <div className="text-[10px] text-slate-300 font-medium flex items-center justify-between">
                    <span>Condition: <strong>{liveObs.weather_description}</strong></span>
                    <span className="text-[8px] text-slate-400">Open-Meteo / WMO Grid</span>
                  </div>
                </div>
              ) : (
                <div className="text-[10px] text-slate-400 py-0.5">Telemetry synced with IMD bulletin</div>
              )}
            </div>

            {/* Current Weather Grid */}
            <div className="grid grid-cols-3 gap-2 mb-3">
              <div className="bg-slate-800/80 rounded-lg p-2 text-center">
                <div className="text-[9px] text-slate-500 uppercase tracking-wider">Past 24h Rain</div>
                <div className="text-sm font-black text-blue-300">
                  {selectedStation.past_24_hrs_rainfall || 'NIL'}
                  <span className="text-[9px] font-normal">{selectedStation.past_24_hrs_rainfall && selectedStation.past_24_hrs_rainfall !== 'NIL' && selectedStation.past_24_hrs_rainfall !== 'NA' ? 'mm' : ''}</span>
                </div>
              </div>
              <div className="bg-slate-800/80 rounded-lg p-2 text-center">
                <div className="text-[9px] text-slate-500 uppercase tracking-wider">Max / Min</div>
                <div className="text-sm font-black text-orange-300">
                  {selectedStation.today_max_temp ? `${selectedStation.today_max_temp}°` : '--'} / {selectedStation.today_min_temp ? `${selectedStation.today_min_temp}°` : '--'}
                </div>
              </div>
              <div className="bg-slate-800/80 rounded-lg p-2 text-center">
                <div className="text-[9px] text-slate-500 uppercase tracking-wider">Humidity</div>
                <div className="text-sm font-black text-indigo-300">
                  {selectedStation.humidity_0830 ? `${selectedStation.humidity_0830}%` : '--'}
                </div>
              </div>
            </div>

            {/* Today's Forecast Bulletin */}
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-2.5 mb-3 text-xs">
              <div className="text-[9px] text-slate-500 uppercase tracking-wider font-bold mb-1">Official IMD Bulletin</div>
              <div className="font-semibold text-slate-200">{selectedStation.todays_forecast || 'No current remarks'}</div>
              {selectedStation.day_1_warning && selectedStation.day_1_warning !== 'No warning' && selectedStation.day_1_warning !== 'No Warning' && (
                <div className="mt-2 text-amber-300 font-medium text-[11px] bg-amber-500/10 border border-amber-500/20 rounded p-1.5">
                  ⚠️ <strong>Warning:</strong> {selectedStation.day_1_warning}
                </div>
              )}
            </div>

            {/* AtmosGuard AI Bust Prediction Card */}
            {selectedStation.bust_risk_score !== undefined && (
              <div className="bg-gradient-to-br from-slate-900 via-slate-900/90 to-slate-950 border border-slate-700/80 rounded-xl p-3 mb-3 shadow-lg">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-sky-400 flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
                    AI Bust Prediction
                  </span>
                  <span
                    className="text-[10px] font-black px-2 py-0.5 rounded-full border"
                    style={{
                      backgroundColor:
                        selectedStation.bust_category === 'SEVERE'
                          ? '#ef4444'
                          : selectedStation.bust_category === 'HIGH'
                          ? '#f97316'
                          : selectedStation.bust_category === 'MODERATE'
                          ? '#eab308'
                          : '#22c55e',
                      color: selectedStation.bust_category === 'MODERATE' ? '#0f172a' : '#fff',
                      borderColor: 'transparent',
                    }}
                  >
                    {selectedStation.bust_category} RISK · {selectedStation.bust_risk_score}%
                  </span>
                </div>

                {/* Progress bar */}
                <div className="w-full bg-slate-800 rounded-full h-1.5 mb-2 overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${selectedStation.bust_risk_score}%`,
                      backgroundColor:
                        selectedStation.bust_category === 'SEVERE'
                          ? '#ef4444'
                          : selectedStation.bust_category === 'HIGH'
                          ? '#f97316'
                          : selectedStation.bust_category === 'MODERATE'
                          ? '#eab308'
                          : '#22c55e',
                    }}
                  />
                </div>

                {/* Drivers list */}
                {selectedStation.bust_drivers && selectedStation.bust_drivers.length > 0 && (
                  <div className="space-y-1 mb-2">
                    <div className="text-[9px] uppercase tracking-wider font-bold text-slate-400">Risk Drivers</div>
                    {selectedStation.bust_drivers.map((d, i) => (
                      <div key={i} className="text-[10px] text-slate-300 flex items-start gap-1.5">
                        <span className="text-amber-400 shrink-0 mt-0.5">•</span>
                        <span>{d}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Actionable recommendation */}
                {selectedStation.recommendation && (
                  <div className="text-[10px] text-slate-300 bg-black/40 border border-slate-700/50 rounded p-2 italic leading-relaxed">
                    💡 {selectedStation.recommendation}
                  </div>
                )}
              </div>
            )}

            {/* 7-Day Outlook */}
            {selectedStation.forecast_7days && selectedStation.forecast_7days.length > 0 && (

              <div>
                <div className="text-[9px] text-slate-500 uppercase tracking-wider font-bold mb-2">7-Day IMD Forecast & Warnings</div>
                <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                  {selectedStation.forecast_7days.map((df) => {
                    const dfColor =
                      df.warning_color === 'red'
                        ? '#ef4444'
                        : df.warning_color === 'orange'
                        ? '#f97316'
                        : df.warning_color === 'yellow'
                        ? '#eab308'
                        : '#22c55e';
                    return (
                      <div key={df.day} className="bg-slate-900/90 border border-slate-800 rounded-lg p-2 text-[11px] flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-slate-400 w-10 shrink-0">Day {df.day}</span>
                          <span
                            className="w-2.5 h-2.5 rounded-full shrink-0"
                            style={{ backgroundColor: dfColor }}
                            title={df.warning || 'No warning'}
                          />
                          <span className="text-slate-300 truncate max-w-[140px]" title={df.forecast || ''}>
                            {df.forecast || '--'}
                          </span>
                        </div>
                        <div className="text-right shrink-0">
                          <span className="font-semibold text-white">{df.max_temp ? `${df.max_temp}°` : '--'}</span>
                          <span className="text-slate-500 ml-1">/ {df.min_temp ? `${df.min_temp}°` : '--'}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>


      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <div className="px-4 py-2 bg-slate-950 border-t border-slate-800 text-[11px] flex flex-wrap items-center justify-between text-slate-500 gap-2">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span>IMD Live GeoServer · Day {horizon} Bust Early-Warning · Scroll to zoom · All 36 states</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-emerald-400 font-medium">
            Bulletin: {baseDate ? `${formatDate(baseDate)} (Today)` : 'Today'}
          </span>
          <span>· Valid 7-Day Window</span>
        </div>
      </div>
    </div>
  );
}
