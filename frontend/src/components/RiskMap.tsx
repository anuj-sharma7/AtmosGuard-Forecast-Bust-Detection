/**
 * Interactive risk map.
 *
 * Risk is encoded twice on purpose: by the status colour *and* by marker
 * radius. The green-to-red severity scale is not colour-vision-safe (green and
 * red are ~4 Delta E apart under deuteranopia), so size carries the same
 * ordering, and every popup and list entry names the category in words.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet';
import type { Layer, PathOptions } from 'leaflet';
import type { Feature, Geometry } from 'geojson';

import type { NetworkSite, RiskCategory } from '../api/types';
import indiaStates from '../lib/india-basemap.json';
import { RISK_ORDER, markerRadius, riskColor } from '../lib/risk';
import { RiskChip } from './Primitives';

/**
 * Base layers.
 *
 * "vector" is the default and draws India from geometry bundled with the app -
 * 36 states and union territories, simplified from DataMeet's CC BY 4.0
 * boundary shapefile. It needs no network, which matters for an operations room
 * behind a restrictive policy, and at national scale it reads better than raster
 * tiles: street detail is noise when the marks are sub-divisional risk scores.
 *
 * The tile layers remain for when a forecaster wants terrain or place-name
 * context, and degrade to the vector base if the CDN is unreachable.
 */
export const BASEMAPS = {
  vector: {
    label: 'Vector',
    url: null,
    attribution:
      'Boundaries: <a href="https://github.com/datameet/maps">DataMeet</a> (CC BY 4.0)',
  },
  dark: {
    label: 'Dark tiles',
    url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
  },
  terrain: {
    label: 'Terrain',
    url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
  },
} as const;

export type BasemapKey = keyof typeof BASEMAPS;

/** Land and boundary styling for the bundled vector base. */
const LAND_STYLE: PathOptions = {
  color: '#31415a',
  weight: 0.9,
  fillColor: '#111b28',
  fillOpacity: 1,
};

const LAND_STYLE_OVER_TILES: PathOptions = {
  color: '#4a5f80',
  weight: 1,
  fill: false,
};

/** Which quantity the marker colour represents. */
export type MapLayer = 'risk' | 'spread' | 'confidence' | 'regime';

export const MAP_LAYERS: { id: MapLayer; label: string; tip: string }[] = [
  { id: 'risk', label: 'Bust Risk', tip: 'Assessed probability that this forecast busts.' },
  {
    id: 'spread',
    label: 'Ensemble Spread',
    tip: 'Disagreement between ensemble members, relative to what is normal for this lead time.',
  },
  {
    id: 'confidence',
    label: 'Forecast Confidence',
    tip: 'Confidence in the forecast itself - the complement of bust risk.',
  },
  {
    id: 'regime',
    label: 'Regime Change',
    tip: 'Strength of the large-scale pattern transition inside the forecast window.',
  },
];

/** Bounds fitted on load so the whole country is visible at any panel size. */
const INDIA_BOUNDS: [[number, number], [number, number]] = [
  [6.5, 67.0],
  [36.5, 97.5],
];

function layerValue(site: NetworkSite, layer: MapLayer): number {
  switch (layer) {
    case 'risk':
      return site.risk_score;
    case 'spread':
      return site.ensemble_spread * 100;
    case 'confidence':
      return site.forecast_confidence;
    case 'regime':
      return site.regime_change * 100;
  }
}

/** Colour for the non-risk layers: a single-hue sequential ramp (blue). */
const BLUE_RAMP = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95'];

function layerColor(site: NetworkSite, layer: MapLayer): string {
  if (layer === 'risk') return riskColor(site.risk_category);
  const value = layerValue(site, layer);
  const index = Math.min(BLUE_RAMP.length - 1, Math.floor((value / 100) * BLUE_RAMP.length));
  return BLUE_RAMP[index];
}

/**
 * Fits the country on first paint and on every container resize.
 *
 * Leaflet measures its container when the map is constructed, which in a
 * responsive grid happens before layout has settled - so an initial `bounds`
 * prop alone lands on the wrong zoom. Re-fitting after `invalidateSize` is what
 * makes the view correct at any panel size.
 */
function FitCountry({ enabled }: { enabled: boolean }) {
  const map = useMap();

  useEffect(() => {
    if (!enabled) return;
    const fit = () => {
      map.invalidateSize({ animate: false });
      map.fitBounds(INDIA_BOUNDS, { padding: [14, 14], animate: false });
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [enabled, map]);

  return null;
}

/**
 * Pans to the selected site when the selection *changes* - never on mount,
 * where it would immediately undo the initial country fit.
 */
function FlyToSelected({ site }: { site: NetworkSite | undefined }) {
  const map = useMap();
  const previous = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!site) return;
    if (previous.current === undefined) {
      previous.current = site.id;
      return;
    }
    if (previous.current === site.id) return;
    previous.current = site.id;
    map.flyTo([site.lat, site.lon], Math.max(map.getZoom(), 5.5), { duration: 0.65 });
  }, [site, map]);

  return null;
}

export function RiskMap({
  sites,
  selectedId,
  onSelect,
  layer = 'risk',
  basemap = 'vector',
  height = '100%',
  showLegend = true,
}: {
  sites: NetworkSite[];
  selectedId?: string;
  onSelect: (id: string) => void;
  layer?: MapLayer;
  basemap?: BasemapKey;
  height?: string | number;
  showLegend?: boolean;
}) {
  const selected = useMemo(() => sites.find((s) => s.id === selectedId), [sites, selectedId]);
  const tiles = BASEMAPS[basemap];
  // Once the forecaster pans or zooms, the auto-fit stops fighting them.
  const [userMoved, setUserMoved] = useState(false);

  return (
    <div className="relative h-full w-full" style={{ height }}>
      <MapContainer
        bounds={INDIA_BOUNDS}
        minZoom={3}
        zoomSnap={0.25}
        scrollWheelZoom
        className="h-full w-full rounded-md"
        style={{ height }}
      >
        <FitCountry enabled={!userMoved} />
        <UserMoveWatch onMove={() => setUserMoved(true)} />
        {tiles.url && (
          <TileLayer key={basemap} url={tiles.url} attribution={tiles.attribution} />
        )}

        {/* States and union territories, drawn beneath the risk markers. Always
            present: when tiles are unavailable this *is* the map, and when they
            are, it still carries the sub-national boundaries a forecaster reads
            positions against. */}
        <GeoJSON
          key={`states-${basemap}`}
          data={indiaStates as never}
          // CC BY 4.0 requires attribution wherever the geometry is shown, and
          // with no tile layer there is nothing else to carry it.
          attribution={BASEMAPS.vector.attribution}
          style={() => (tiles.url ? LAND_STYLE_OVER_TILES : LAND_STYLE)}
          onEachFeature={(feature: Feature<Geometry, { st_nm?: string }>, layer: Layer) => {
            const name = feature.properties?.st_nm;
            if (name) {
              layer.bindTooltip(name, { sticky: true, direction: 'top', opacity: 0.95 });
            }
          }}
        />

        <FlyToSelected site={selected} />

        {sites.map((site) => {
          const isSelected = site.id === selectedId;
          return (
            <CircleMarker
              key={site.id}
              center={[site.lat, site.lon]}
              radius={markerRadius(layerValue(site, layer), site.featured)}
              pathOptions={{
                color: isSelected ? '#e8eef7' : layerColor(site, layer),
                weight: isSelected ? 2.5 : site.featured ? 1.4 : 1,
                fillColor: layerColor(site, layer),
                fillOpacity: site.featured ? 0.72 : 0.5,
              }}
              eventHandlers={{ click: () => onSelect(site.id) }}
            >
              <Popup>
                <div className="min-w-[190px]">
                  <p className="text-xs font-semibold text-ink-primary">{site.name}</p>
                  <p className="mb-2 text-2xs text-ink-muted">{site.state}</p>
                  <div className="mb-2">
                    <RiskChip category={site.risk_category} score={site.risk_score} size="sm" />
                  </div>
                  <dl className="space-y-0.5 text-2xs tabular">
                    <PopupRow term="Forecast confidence" value={`${site.forecast_confidence.toFixed(0)}%`} />
                    <PopupRow term="Ensemble spread" value={site.ensemble_spread.toFixed(2)} />
                    <PopupRow term="Regime" value={site.regime} />
                    <PopupRow term="Leading driver" value={site.top_driver} />
                  </dl>
                  <button
                    type="button"
                    onClick={() => onSelect(site.id)}
                    className="mt-2 w-full rounded border border-edge-strong px-2 py-1 text-2xs
                               font-medium text-accent hover:bg-surface-3"
                  >
                    Analyse this location
                  </button>
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>

      {showLegend && (
        <div
          className="pointer-events-none absolute bottom-3 left-3 z-[500] rounded-md border
                     border-edge-strong bg-surface-1/92 px-3 py-2 backdrop-blur"
        >
          <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
            {MAP_LAYERS.find((l) => l.id === layer)?.label}
          </p>
          {layer === 'risk' ? (
            <ul className="space-y-1">
              {RISK_ORDER.map((category: RiskCategory) => (
                <li key={category} className="flex items-center gap-2 text-2xs text-ink-secondary">
                  <span
                    className="rounded-full"
                    style={{
                      background: riskColor(category),
                      width: 6 + RISK_ORDER.indexOf(category) * 3,
                      height: 6 + RISK_ORDER.indexOf(category) * 3,
                    }}
                    aria-hidden
                  />
                  {category}
                </li>
              ))}
            </ul>
          ) : (
            <div>
              <div className="flex h-2 w-28 overflow-hidden rounded-sm" aria-hidden>
                {BLUE_RAMP.map((c) => (
                  <span key={c} className="flex-1" style={{ background: c }} />
                ))}
              </div>
              <div className="mt-1 flex justify-between text-2xs text-ink-muted tabular">
                <span>low</span>
                <span>high</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Marks the view as user-controlled after a manual pan or zoom. */
function UserMoveWatch({ onMove }: { onMove: () => void }) {
  const map = useMap();
  useEffect(() => {
    const handler = () => onMove();
    map.on('dragstart', handler);
    map.on('zoomstart', handler);
    return () => {
      map.off('dragstart', handler);
      map.off('zoomstart', handler);
    };
  }, [map, onMove]);
  return null;
}

function PopupRow({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="text-ink-muted">{term}</dt>
      <dd className="text-right font-medium text-ink-primary">{value}</dd>
    </div>
  );
}
