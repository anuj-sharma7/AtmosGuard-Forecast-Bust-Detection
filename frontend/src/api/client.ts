/**
 * Thin API abstraction.
 *
 * Every network call in the app goes through `request`, so retries, error
 * shaping and the base URL are defined once. Responses are cached by URL
 * because the demonstration dataset is deterministic - the same selection
 * always yields the same payload, so re-fetching it on every navigation is
 * pure waste.
 */

import type {
  AlertsResponse,
  ClimateProfile,
  ForecastVerification,
  Meta,
  NetworkResponse,
  RiskResponse,
  Selection,
  ImdLiveStatus,
  ImdCityForecastResponse,
  MonthlyMeta,
  StationReplay,
  StationsMeta,
  MonthlyReplay,
  ReplayAvailability,
  ReplayBacktest,
  ReplayModelCard,
  ReplayOrigins,
  ReplayRun,
  SourcesResponse,
  WarningsResponse,
  SystemStatus,
  VerificationResponse,
  ImdBustResponse,
  ImdRealtimeAlertsResponse,
  LiveWeatherResponse,
} from './types';

import { rebuildReplay, type StationSidecar } from '../lib/stationSidecar';

const BASE = '/api';

/**
 * Static snapshot mode.
 *
 * A build can embed pre-fetched API responses on `window`, letting the whole
 * dashboard run with no backend - useful for a shared read-only deployment or
 * an air-gapped review copy. When a snapshot is present the client serves from
 * it and never touches the network; when it is absent, nothing changes.
 *
 * Keys are canonical: path plus alphabetically sorted query parameters, so the
 * exporter and the client agree without depending on argument order.
 */
declare global {
  interface Window {
    __ATMOSGUARD_SNAPSHOT__?: Record<string, unknown>;
  }
}

function snapshot(): Record<string, unknown> | undefined {
  return typeof window === 'undefined' ? undefined : window.__ATMOSGUARD_SNAPSHOT__;
}

export function isSnapshotMode(): boolean {
  return snapshot() !== undefined;
}

function canonicalKey(path: string, params: URLSearchParams): string {
  const sorted = [...params.entries()].sort(([a], [b]) => a.localeCompare(b));
  const qs = sorted.map(([k, v]) => `${k}=${v}`).join('&');
  return qs ? `${path}?${qs}` : path;
}

/**
 * Sidecar files: the part of a static build too large to embed.
 *
 * A published build ships them next to the page. The 7-day station replay is
 * rebuilt from one packed file per station; the monthly and 2026 replays are
 * looked up in grouped payload files through a manifest embedded in the
 * snapshot. A single-file build has no sidecars - `fetch` fails, this returns
 * undefined, and the caller reports the date as not in the preview.
 */
const sidecarFiles = new Map<string, Promise<unknown>>();

function loadSidecar(file: string): Promise<unknown> {
  let pending = sidecarFiles.get(file);
  if (!pending) {
    pending = fetch(`sidecar/${file}`).then((response) => {
      if (!response.ok) throw new Error(`sidecar ${file}: ${response.status}`);
      return response.json();
    });
    // A failed fetch is not cached: a flaky network should not poison the page.
    pending.catch(() => sidecarFiles.delete(file));
    sidecarFiles.set(file, pending);
  }
  return pending;
}

async function sidecar<T>(
  snap: Record<string, unknown>,
  path: string,
  query: URLSearchParams,
  key: string,
): Promise<T | undefined> {
  try {
    if (path === '/stations/replay') {
      const station = query.get('station') ?? '';
      const on = query.get('on') ?? '';
      const side = (await loadSidecar(`station-${station}.json`)) as StationSidecar;
      try {
        return rebuildReplay(side, on) as T;
      } catch (error) {
        throw new ApiError(error instanceof Error ? error.message : 'Invalid date', 422, key);
      }
    }
    const manifest = snap['__sidecar__'] as { files?: Record<string, string> } | undefined;
    const file = manifest?.files?.[key];
    if (!file) return undefined;
    const bundle = (await loadSidecar(file)) as Record<string, unknown>;
    return bundle[key] as T | undefined;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    return undefined;
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly url: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const cache = new Map<string, unknown>();
const inflight = new Map<string, Promise<unknown>>();

async function request<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
  options: { cache?: boolean } = {},
): Promise<T> {
  const query = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  const snap = snapshot();
  if (snap) {
    const key = canonicalKey(path, query);
    if (key in snap) return snap[key] as T;
    const fromSidecar = await sidecar<T>(snap, path, query, key);
    if (fromSidecar !== undefined) return fromSidecar;
    throw new ApiError(
      'This combination is not included in this static copy. The published preview ' +
        'loads every date from its data files, and the full application runs any ' +
        'location, variable and model.',
      404,
      key,
    );
  }

  const qs = query.toString();
  const url = `${BASE}${path}${qs ? `?${qs}` : ''}`;

  const useCache = options.cache !== false;
  if (useCache && cache.has(url)) return cache.get(url) as T;
  // De-duplicate concurrent requests for the same URL: the dashboard mounts
  // several panels at once and they routinely ask for the same payload.
  const pending = inflight.get(url);
  if (pending) return pending as Promise<T>;

  const promise = (async () => {
    let response: Response;
    try {
      response = await fetch(url, { headers: { Accept: 'application/json' } });
    } catch (cause) {
      throw new ApiError(
        'Cannot reach the AtmosGuard API. Is the backend running on port 8000?',
        0,
        url,
      );
    }

    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json();
        if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : detail;
      } catch {
        /* response had no JSON body; the status line is the best we have */
      }
      throw new ApiError(detail, response.status, url);
    }

    const data = (await response.json()) as T;
    if (useCache) cache.set(url, data);
    return data;
  })();

  inflight.set(url, promise);
  try {
    return await promise;
  } finally {
    inflight.delete(url);
  }
}

export const api = {
  meta: () => request<Meta>('/meta'),

  risk: (selection: Selection, refresh = false) =>
    request<RiskResponse>(
      '/risk',
      {
        location: selection.location_id,
        variable: selection.variable_id,
        model: selection.model_id,
        horizon: selection.horizon,
        forecast_date: selection.base_date,
        refresh: refresh ? 'true' : undefined,
      },
      { cache: !refresh }
    ),

  scenario: (id: string) => request<RiskResponse>(`/scenario/${id}`),

  network: (selection: Pick<Selection, 'variable_id' | 'model_id' | 'horizon' | 'base_date'>) =>
    request<NetworkResponse>('/network', {
      variable: selection.variable_id,
      model: selection.model_id,
      horizon: selection.horizon,
      forecast_date: selection.base_date,
    }),

  alerts: (baseDate: string, severity?: string) =>
    request<AlertsResponse>('/alerts', { forecast_date: baseDate, severity }),

  modelVerification: (baseDate: string) =>
    request<VerificationResponse>('/verification/model', { forecast_date: baseDate }),

  forecastVerification: (locationId: string, variableId: string, baseDate: string, lookback = 21) =>
    request<ForecastVerification & { location_id: string; variable_id: string; label: string }>(
      '/verification/forecast',
      { location: locationId, variable: variableId, forecast_date: baseDate, lookback },
    ),

  systemStatus: (baseDate: string) => request<SystemStatus>('/system/status', { forecast_date: baseDate }),

  climate: (locationId: string) => request<ClimateProfile>(`/climate/${locationId}`),

  sources: () => request<SourcesResponse>('/sources'),

  warnings: (selection: Pick<Selection, 'model_id' | 'horizon' | 'base_date'>) =>
    request<WarningsResponse>('/warnings', {
      model: selection.model_id,
      horizon: selection.horizon,
      forecast_date: selection.base_date,
    }),

  /* ---------------------------- Historical replay --------------------------- */

  /** Live feed status: never served from the client cache, it is a live check. */
  imdLive: (refresh = false) =>
    request<ImdLiveStatus>('/imd/live', { refresh: refresh ? 'true' : undefined }, { cache: false }),

  /** Official 7-day city forecasts and warnings across 113+ stations */
  cityForecast: () =>
    request<ImdCityForecastResponse>('/imd/cityforecast', undefined, { cache: false }),

  /** Live IMD bust prediction for the nearest station to a given dashboard location */
  imdBust: (locationId: string, refresh = false) =>
    request<ImdBustResponse>(
      `/imd/bust/${locationId}`,
      { refresh: refresh ? 'true' : undefined },
      { cache: false }
    ),

  /** Real-time early-warning alerts generated from official IMD city forecasts */
  imdAlerts: (threshold = 50, severity?: string) =>
    request<ImdRealtimeAlertsResponse>(
      '/imd/alerts',
      { threshold: String(threshold), severity: severity || undefined },
      { cache: false }
    ),

  /** Fetch real-time current weather observations for coordinates */
  liveWeather: (lat: number, lon: number) =>
    request<LiveWeatherResponse>('/weather/live', { lat: String(lat), lon: String(lon) }),

  replayOrigins: () => request<ReplayOrigins>('/replay/origins'),

  replayAvailability: (origin: string) => request<ReplayAvailability>('/replay/availability', { origin }),

  replayRun: (origin: string, locationId: string) =>
    request<ReplayRun>('/replay/run', { origin, location_id: locationId }),

  replayBacktest: () => request<ReplayBacktest>('/replay/backtest'),

  replayModel: () => request<ReplayModelCard>('/replay/model'),

  /* ----------------------------- Monthly replay ----------------------------- */

  monthlyMeta: () => request<MonthlyMeta>('/monthly/meta'),

  /* ------------------------- 7-day station replay -------------------------- */

  stationsMeta: () => request<StationsMeta>('/stations/meta'),

  stationReplay: (on: string, station: string) =>
    request<StationReplay>('/stations/replay', { on, station }),

  /**
   * The monthly replay answers for the month containing `on`, so the day is
   * not part of the question. Canonicalising to the first of the month keeps
   * one cache entry (and one snapshot key) per month instead of thirty-one,
   * and means a static build does not miss on a date it can actually answer.
   */
  monthlyReplay: (on: string, subdivision?: string) =>
    request<MonthlyReplay>('/monthly/replay', {
      on: `${on.slice(0, 7)}-01`,
      subdivision,
    }),
};
