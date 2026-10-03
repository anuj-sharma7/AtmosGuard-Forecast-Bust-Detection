/**
 * National Weather Warning & Numerical Forecast Bust Risk Map
 *
 * Full-screen interactive meteorological GIS command map featuring:
 * - Esri high-resolution World Imagery satellite basemap + OSM labels
 * - Official IMD 4-colour warning choropleth across 36 subdivisions / states
 * - 17+ meteorological hazard factors (Thunderstorm, Heavy Rain, Gale Winds, Heat Wave, etc.)
 * - Multi-source live ground observation telemetry (OWM + MSN + WMO)
 * - Calibrated AI bust risk probabilities per synoptic station
 * - Live inspector card for selected location with direct forecast analysis
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { ImdBustResponse, RiskCategory, WarningsResponse } from '../api/types';
import { ImdWeatherMap } from '../components/ImdWeatherMap';
import { ErrorState, LoadingState, Panel, RiskChip } from '../components/Primitives';
import { useAppState } from '../state/AppState';
import { formatDate } from '../lib/format';
import { RISK_ORDER, riskColor } from '../lib/risk';

type SeverityFilter = 'ALL' | RiskCategory;

const WARNING_COLOR: Record<string, string> = {
  red: '#ef4444',
  orange: '#f97316',
  yellow: '#eab308',
  green: '#22c55e',
};

const BUST_COLOR: Record<string, string> = {
  SEVERE: '#ef4444',
  HIGH: '#f97316',
  MODERATE: '#eab308',
  LOW: '#22c55e',
};

export function RiskMapPage() {
  const { meta, network, selection, setLocation, setVariable, setHorizon, setModel, reload } =
    useAppState();
  const navigate = useNavigate();

  const [warnings, setWarnings] = useState<WarningsResponse | null>(null);
  const [warningsLoading, setWarningsLoading] = useState(false);
  const [imdBust, setImdBust] = useState<ImdBustResponse | null>(null);
  const [imdBustLoading, setImdBustLoading] = useState(false);
  const [severity, setSeverity] = useState<SeverityFilter>('ALL');
  const [isSyncing, setIsSyncing] = useState(false);

  // Fetch official IMD warnings with hazard factors for current horizon/model
  useEffect(() => {
    if (!selection) return;
    let cancelled = false;
    setWarningsLoading(true);
    const effectiveHorizon = Math.max(3, Math.min(7, selection.horizon));
    api
      .warnings({ ...selection, horizon: effectiveHorizon })
      .then((data) => {
        if (!cancelled) setWarnings(data);
      })
      .catch(() => {
        if (!cancelled) setWarnings(null);
      })
      .finally(() => {
        if (!cancelled) setWarningsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selection?.horizon, selection?.model_id, selection?.base_date]);

  // Fetch live IMD bust and ground observation telemetry for currently selected location
  useEffect(() => {
    if (!selection?.location_id) return;
    let cancelled = false;
    setImdBustLoading(true);
    api
      .imdBust(selection.location_id)
      .then((data) => {
        if (!cancelled) setImdBust(data);
      })
      .catch(() => {
        if (!cancelled) setImdBust(null);
      })
      .finally(() => {
        if (!cancelled) setImdBustLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selection?.location_id]);

  // Manual live sync
  const handleSync = useCallback(
    async (force = true) => {
      if (!selection?.location_id) return;
      setIsSyncing(true);
      try {
        const [bustData, warnData] = await Promise.all([
          api.imdBust(selection.location_id, force),
          api.warnings({ ...selection, horizon: Math.max(3, Math.min(7, selection.horizon)) }),
        ]);
        setImdBust(bustData);
        setWarnings(warnData);
        reload();
      } catch {
        // preserve current state on error
      } finally {
        setIsSyncing(false);
      }
    },
    [selection, reload]
  );

  const filteredSites = useMemo(() => {
    const all = network.data?.sites ?? [];
    if (severity === 'ALL') return all;
    return all.filter((s) => s.risk_category === severity);
  }, [network.data?.sites, severity]);

  const activeSite = useMemo(() => {
    return network.data?.sites.find((s) => s.id === selection?.location_id);
  }, [network.data?.sites, selection?.location_id]);

  if (network.error) return <ErrorState message={network.error} onRetry={reload} />;

  return (
    <div className="space-y-4">
      {/* ── Top Header Cockpit ── */}
      <section className="panel px-4 py-3 border border-edge/80 bg-gradient-to-r from-surface-1 via-surface-1 to-surface-2/60">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-accent/40 bg-accent/15 text-accent shadow-sm">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold tracking-tight text-ink-primary">
                  National Weather Warning & Numerical Forecast Bust Risk Map
                </h1>
                <span className="flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  SATELLITE & IMD GIS LIVE
                </span>
              </div>
              <p className="mt-0.5 text-xs text-ink-secondary">
                Official IMD 4-colour meteorological warning choropleths, weather hazard factors, and ground truth telemetry combined with ensemble bust risk predictions.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => handleSync(true)}
              disabled={isSyncing}
              className="inline-flex items-center gap-1.5 rounded border border-edge-strong bg-surface-2 px-3 py-1.5 text-xs font-semibold
                         text-ink-primary transition-all hover:border-accent hover:text-accent disabled:opacity-60"
            >
              <svg
                className={`h-3.5 w-3.5 ${isSyncing ? 'animate-spin text-accent' : 'text-cyan-400'}`}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
              <span>{isSyncing ? 'Syncing…' : 'Sync Telemetry'}</span>
            </button>

            <button
              type="button"
              onClick={() => navigate('/analysis')}
              className="rounded border border-accent/50 bg-accent/15 px-3 py-1.5 text-xs font-semibold text-accent transition-colors hover:bg-accent/25"
            >
              Analyze Forecast
            </button>
            <button
              type="button"
              onClick={() => navigate('/')}
              className="rounded border border-edge-strong bg-surface-2 px-3 py-1.5 text-xs font-medium text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary"
            >
              Command Center
            </button>
          </div>
        </div>
      </section>

      {/* ── Main Map + Inspector Grid ── */}
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        {/* Left: GIS Map */}
        <Panel
          title="National Early-Warning & Meteorological Hazard Map"
          subtitle={
            network.data
              ? `${filteredSites.length} of ${network.data.network_size} synoptic stations plotted · Lead Time: Day ${network.data.horizon} · ${
                  meta.data?.variables.find((v) => v.id === network.data?.variable_id)?.label ?? 'Rainfall'
                } · Model: ${selection?.model_id?.toUpperCase() ?? 'ECMWF'}`
              : undefined
          }
          tip="Official IMD four-colour warning map (Green/Yellow/Orange/Red) with complete meteorological hazard factors (Thunderstorm, Heavy Rain, Winds, Heat Wave, etc.). Click any state or marker to inspect."
          updated={selection ? formatDate(selection.base_date) : undefined}
          bodyClassName="p-0"
          className="min-h-[660px]"
        >
          <div className="w-full p-1">
            {warningsLoading && !warnings ? (
              <div className="p-4">
                <LoadingState label="Loading satellite imagery & official IMD hazard factors…" rows={6} />
              </div>
            ) : (
              <ImdWeatherMap
                warnings={warnings}
                sites={filteredSites}
                selectedLocationId={selection?.location_id}
                onSelectSite={setLocation}
                height={680}
                horizon={selection?.horizon}
                baseDate={selection?.base_date}
              />
            )}
          </div>
        </Panel>

        {/* Right Sidebar: Active Inspector, Filters & Ranked Stations */}
        <div className="space-y-4">
          {/* Active Station Live Inspector */}
          <Panel
            title="Selected Location Inspector"
            subtitle={activeSite ? `${activeSite.name}, ${activeSite.state}` : 'Select a station on the map'}
            tip="Real-time multi-source ground observation telemetry and AI bust probability for the focused site."
          >
            {imdBustLoading && !imdBust ? (
              <LoadingState label="Fetching live ground telemetry…" rows={3} />
            ) : activeSite ? (
              <div className="space-y-3">
                {/* Station header & live badge */}
                <div className="flex items-center justify-between gap-2 rounded border border-edge/60 bg-surface-2/80 p-2 text-2xs">
                  <div className="flex items-center gap-1.5">
                    <span className="relative flex h-2 w-2">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400 opacity-75" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan-500" />
                    </span>
                    <strong className="text-ink-primary font-bold">{activeSite.name}</strong>
                    <span className="text-ink-muted">({activeSite.lat.toFixed(2)}°N, {activeSite.lon.toFixed(2)}°E)</span>
                  </div>
                  <span className="rounded border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-400">
                    ● Live Feed
                  </span>
                </div>

                {/* Score & Warning Row */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-lg border border-edge/80 bg-surface-1 p-2.5 text-center">
                    <span className="text-[10px] uppercase font-semibold text-ink-muted block">AI Bust Risk</span>
                    <span
                      className="text-2xl font-black tabular-nums block my-0.5"
                      style={{ color: BUST_COLOR[imdBust?.bust_category ?? activeSite.risk_category] ?? '#22c55e' }}
                    >
                      {imdBust?.bust_risk_score ?? activeSite.risk_score.toFixed(0)}%
                    </span>
                    <RiskChip category={imdBust?.bust_category ?? activeSite.risk_category} size="sm" />
                  </div>

                  <div className="rounded-lg border border-edge/80 bg-surface-1 p-2.5 text-center">
                    <span className="text-[10px] uppercase font-semibold text-ink-muted block">IMD Warning Level</span>
                    <span
                      className="text-lg font-black uppercase block my-1"
                      style={{ color: WARNING_COLOR[imdBust?.day_1_warning_color ?? 'green'] ?? '#22c55e' }}
                    >
                      {imdBust?.day_1_warning_color?.toUpperCase() ?? 'GREEN'}
                    </span>
                    <span className="text-[10px] text-ink-secondary truncate block">
                      {imdBust?.day_1_warning || 'No active hazard'}
                    </span>
                  </div>
                </div>

                {/* Live Ground Observation Telemetry */}
                {imdBust?.live_current && (
                  <div className="rounded-md border border-cyan-500/30 bg-surface-2/90 p-2.5 text-2xs shadow-sm">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-bold uppercase tracking-wider text-cyan-400 flex items-center gap-1">
                        <span>⚡</span> Ground Observation
                      </span>
                      <span className="text-[9px] text-ink-muted">OWM + MSN Gateway</span>
                    </div>

                    <div className="grid grid-cols-4 gap-1 text-center">
                      <div className="rounded bg-surface-1/80 p-1">
                        <p className="text-[9px] text-ink-muted">Temp</p>
                        <p className="font-bold text-ink-primary">
                          {imdBust.live_current.temperature !== null ? `${imdBust.live_current.temperature}°` : '--'}
                        </p>
                      </div>
                      <div className="rounded bg-surface-1/80 p-1">
                        <p className="text-[9px] text-ink-muted">Humidity</p>
                        <p className="font-bold text-ink-primary">
                          {imdBust.live_current.relative_humidity !== null ? `${imdBust.live_current.relative_humidity}%` : '--'}
                        </p>
                      </div>
                      <div className="rounded bg-surface-1/80 p-1">
                        <p className="text-[9px] text-ink-muted">Rain</p>
                        <p className="font-bold text-ink-primary">
                          {imdBust.live_current.precipitation_mm !== null ? `${imdBust.live_current.precipitation_mm}mm` : '0mm'}
                        </p>
                      </div>
                      <div className="rounded bg-surface-1/80 p-1">
                        <p className="text-[9px] text-ink-muted">Wind</p>
                        <p className="font-bold text-ink-primary">
                          {imdBust.live_current.wind_speed_kmh !== null ? `${imdBust.live_current.wind_speed_kmh}k` : '--'}
                        </p>
                      </div>
                    </div>

                    <div className="mt-2 text-[10px] text-ink-secondary flex items-center justify-between border-t border-edge/40 pt-1">
                      <span className="truncate">Sky: <strong className="text-ink-primary">{imdBust.live_current.weather_description}</strong></span>
                      <span className="text-ink-muted">P: {imdBust.live_current.pressure_hpa ?? '1012'} hPa</span>
                    </div>
                  </div>
                )}

                {/* Action button */}
                <button
                  type="button"
                  onClick={() => navigate('/analysis')}
                  className="w-full rounded border border-accent/50 bg-accent/15 py-2 text-xs font-bold text-accent transition-colors hover:bg-accent/25"
                >
                  Analyze Forecast for {activeSite.name} →
                </button>
              </div>
            ) : (
              <div className="py-6 text-center text-xs text-ink-muted">
                Click any marker on the map to inspect its real-time telemetry and risk drivers.
              </div>
            )}
          </Panel>

          {/* Map Filters Panel */}
          <Panel title="Forecast Filters & Models" subtitle="Drives map observations and predictions">
            <div className="space-y-3.5">
              <Filter label="Forecast Lead Time">
                {(meta.data?.horizons ?? [3, 4, 5, 6, 7]).map((h) => (
                  <button
                    key={h}
                    type="button"
                    onClick={() => setHorizon(h)}
                    aria-pressed={selection?.horizon === h}
                    className={`segment ${selection?.horizon === h ? 'segment-active' : ''}`}
                  >
                    Day {h}
                  </button>
                ))}
              </Filter>

              <Filter label="Weather Variable">
                {(meta.data?.variables ?? []).map((v) => (
                  <button
                    key={v.id}
                    type="button"
                    onClick={() => setVariable(v.id)}
                    aria-pressed={selection?.variable_id === v.id}
                    className={`segment ${selection?.variable_id === v.id ? 'segment-active' : ''}`}
                  >
                    {v.label}
                  </button>
                ))}
              </Filter>

              <Filter label="NWP Centre Model">
                {(meta.data?.models ?? []).map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setModel(m.id)}
                    aria-pressed={selection?.model_id === m.id}
                    className={`segment ${selection?.model_id === m.id ? 'segment-active' : ''}`}
                  >
                    {m.label}
                  </button>
                ))}
              </Filter>

              <Filter label="Risk Band Filter">
                {(['ALL', ...RISK_ORDER] as SeverityFilter[]).map((band) => (
                  <button
                    key={band}
                    type="button"
                    onClick={() => setSeverity(band)}
                    aria-pressed={severity === band}
                    className={`segment ${severity === band ? 'segment-active' : ''}`}
                  >
                    {band === 'ALL' ? 'All Bands' : band}
                  </button>
                ))}
              </Filter>
            </div>
          </Panel>

          {/* National Risk Watchlist (Ranked Sites) */}
          <Panel
            title="National Risk Watchlist"
            subtitle={network.data ? `${filteredSites.length} synoptic stations ranked by AI bust probability` : undefined}
            bodyClassName="px-2 py-2"
          >
            {network.data ? (
              <ul className="max-h-[300px] space-y-1 overflow-auto pr-1">
                {filteredSites.slice(0, 15).map((site) => (
                  <li key={site.id}>
                    <button
                      type="button"
                      onClick={() => setLocation(site.id)}
                      className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1.5
                                  text-left transition-colors hover:bg-surface-2 ${
                                    site.id === selection?.location_id ? 'bg-surface-2 ring-1 ring-accent/60' : ''
                                  }`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-xs font-bold text-ink-primary">{site.name}</span>
                        <span className="block truncate text-2xs text-ink-muted">{site.state} · {site.top_driver}</span>
                      </span>
                      <div className="flex items-center gap-2 shrink-0">
                        <span
                          className="text-xs font-black tabular-nums"
                          style={{ color: riskColor(site.risk_category) }}
                        >
                          {site.risk_score.toFixed(0)}%
                        </span>
                        <RiskChip category={site.risk_category} size="sm" />
                      </div>
                    </button>
                  </li>
                ))}
                {filteredSites.length === 0 && (
                  <li className="px-2 py-4 text-center text-2xs text-ink-muted">
                    No sites in this risk band for the current selection.
                  </li>
                )}
              </ul>
            ) : (
              <LoadingState rows={4} />
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Filter({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-ink-muted">{label}</p>
      <div className="flex flex-wrap gap-1">{children}</div>
    </div>
  );
}
