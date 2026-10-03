/**
 * Command centre.
 *
 * The whole product in one screen: what the network looks like right now, the
 * assessment for the selected forecast, why it is at risk, and what the
 * ensemble is doing. On first load this is the Jaipur Day 5 rainfall case.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { AlertsResponse, WarningsResponse, ImdBustResponse } from '../api/types';

import { EnsembleSpreadChart } from '../components/EnsembleSpreadChart';
import { AlertTimeline } from '../components/AlertTimeline';
import { AnaloguePanel } from '../components/AnaloguePanel';
import { DemoScenarios } from '../components/DemoScenarios';
import { ForecastSelector } from '../components/ForecastSelector';
import { LocationSearch } from '../components/LocationSearch';
import { Metric, MetricStrip } from '../components/RiskCard';
import { RiskGauge } from '../components/RiskGauge';
import { ImdWeatherMap } from '../components/ImdWeatherMap';
import { ReportExport } from '../components/ReportExport';
import { ShapExplanation } from '../components/ShapExplanation';
import {
  DemoNotice,
  ErrorState,
  LoadingState,
  Panel,
  RiskChip,
} from '../components/Primitives';
import { useAppState } from '../state/AppState';
import { formatDate } from '../lib/format';
import { RISK_DEFINITION, riskColor } from '../lib/risk';

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

export function Dashboard() {
  const { meta, risk, network, selection, setLocation, setHorizon, reload } = useAppState();
  const navigate = useNavigate();
  const [reportOpen, setReportOpen] = useState(false);
  const [alerts, setAlerts] = useState<AlertsResponse | null>(null);
  const [warnings, setWarnings] = useState<WarningsResponse | null>(null);
  const [warningsLoading, setWarningsLoading] = useState(false);
  const [imdBust, setImdBust] = useState<ImdBustResponse | null>(null);
  const [imdBustLoading, setImdBustLoading] = useState(false);
  const [countdown, setCountdown] = useState(60);
  const [isSyncing, setIsSyncing] = useState(false);
  const [siteFilter, setSiteFilter] = useState<'ALL' | 'ALERT' | 'NORMAL'>('ALL');

  const sortedSites = useMemo(() => {
    if (!network.data?.sites) return [];
    const list = [...network.data.sites].sort((a, b) => b.risk_score - a.risk_score);
    if (siteFilter === 'ALERT') {
      return list.filter((s) => s.risk_category === 'HIGH' || s.risk_category === 'SEVERE');
    }
    if (siteFilter === 'NORMAL') {
      return list.filter((s) => s.risk_category === 'LOW' || s.risk_category === 'MODERATE');
    }
    return list;
  }, [network.data?.sites, siteFilter]);

  // Manual or timer-triggered live telemetry sync
  const handleSync = useCallback(
    async (force = true) => {
      if (!selection?.location_id) return;
      setIsSyncing(true);
      try {
        const data = await api.imdBust(selection.location_id, force);
        setImdBust(data);
        reload();
      } catch {
        // preserve current state on network error
      } finally {
        setIsSyncing(false);
        setCountdown(60);
      }
    },
    [selection?.location_id, reload]
  );

  // Real-time 60-second polling heartbeat
  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          handleSync(true);
          return 60;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [handleSync]);

  // The alert count is not the same thing as the high-risk-area count: the
  // alert engine scans every monitored variable and lead time, while the map
  // shows one variable at one lead time. Showing the map's number twice would
  // be misleading, so this comes from the alert scan itself.
  useEffect(() => {
    if (!selection) return;
    let cancelled = false;
    api
      .alerts(selection.base_date)
      .then((data) => {
        if (!cancelled) setAlerts(data);
      })
      .catch(() => {
        if (!cancelled) setAlerts(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selection?.base_date]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load IMD-style state warnings & weather hazard factors
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

  // Fetch live IMD bust prediction for the selected location
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
    return () => { cancelled = true; };
  }, [selection?.location_id]);

  if (meta.error) return <ErrorState message={meta.error} onRetry={reload} />;

  const r = risk.data;
  const net = network.data;

  return (
    <div className="space-y-4">
      {/* Top Cockpit Header & Telemetry Status Bar */}
      <section className="panel px-4 py-3 border border-edge/80 bg-gradient-to-r from-surface-1 via-surface-1 to-surface-2/60">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-accent/40 bg-accent/15 text-accent shadow-sm">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 00-9.78 2.096A4.001 4.001 0 003 15z" />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold tracking-tight text-ink-primary">
                  AtmosGuard Meteorological Early-Warning Operations
                </h1>
                <span className="flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  LIVE GROUND TELEMETRY
                </span>
              </div>
              <p className="mt-0.5 text-xs text-ink-secondary">
                Medium-range numerical forecast bust risk detection powered by live ground telemetry divergence, ensemble dispersion, and IMD early-warning protocols.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="hidden lg:flex items-center gap-3 rounded border border-edge/60 bg-surface-2/80 px-3 py-1.5 text-2xs text-ink-secondary">
              <div>
                <span className="text-ink-muted">Monitored: </span>
                <strong className="text-ink-primary">{net ? `${net.network_size} Synoptic Sites` : '10 Sites'}</strong>
              </div>
              <span className="text-edge">|</span>
              <div>
                <span className="text-ink-muted">Active Alerts: </span>
                <strong className="text-amber-400">{alerts ? alerts.alerts.length : '--'}</strong>
              </div>
              <span className="text-edge">|</span>
              <div>
                <span className="text-ink-muted">Confidence: </span>
                <strong className="text-cyan-400">{net ? `${net.mean_model_confidence.toFixed(0)}%` : '--'}</strong>
              </div>
            </div>

            <button
              type="button"
              onClick={() => navigate('/analysis')}
              className="rounded border border-accent/50 bg-accent/15 px-3 py-1.5 text-xs font-semibold text-accent transition-colors hover:bg-accent/25"
            >
              Deep Analysis
            </button>
            <button
              type="button"
              onClick={() => navigate('/map')}
              className="rounded border border-edge-strong bg-surface-2 px-3 py-1.5 text-xs font-medium text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary"
            >
              Interactive Map
            </button>
            <button
              type="button"
              onClick={() => setReportOpen(true)}
              className="rounded border border-edge-strong bg-surface-2 px-3 py-1.5 text-xs font-medium text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary"
            >
              Export Report
            </button>
          </div>
        </div>
      </section>

      {/* KPI row */}
      <MetricStrip>
        <Metric
          label="Active high-risk areas"
          value={net ? net.high_risk_areas : '--'}
          detail={net ? `of ${net.network_size} monitored sites` : undefined}
          tip="Sites currently assessed at HIGH or SEVERE bust risk for the selected variable and lead time."
          accent="#ec835a"
          loading={network.loading && !net}
        />
        <Metric
          label="Highest bust risk"
          value={net?.highest_risk ? `${net.highest_risk.risk_score.toFixed(0)}%` : '--'}
          detail={net?.highest_risk?.name}
          tip={RISK_DEFINITION}
          accent={net?.highest_risk ? riskColor(net.highest_risk.risk_category) : undefined}
          loading={network.loading && !net}
        />
        <Metric
          label="Forecast horizon"
          value={selection ? `Day ${selection.horizon}` : '--'}
          detail={r ? `valid ${formatDate(r.valid_date)}` : undefined}
          tip="The lead time currently selected. All panels on this page describe this lead time."
        />
        <Metric
          label="Active alerts"
          value={alerts ? alerts.alerts.length : '--'}
          detail={alerts ? `${alerts.counts.SEVERE} severe - rainfall` : undefined}
          tip="Rainfall alerts across every monitored site and lead time. Raised on the fitted bust probability, not the index, so the alert rate reflects how unsettled the atmosphere actually is."
          accent="#fab219"
          loading={!alerts}
        />
        <Metric
          label="Model confidence"
          value={net ? `${net.mean_model_confidence.toFixed(0)}%` : '--'}
          detail="mean across network"
          tip="Confidence in the risk assessment itself - distinct from confidence in the weather forecast."
          accent="#38bdf8"
          trend={r?.horizon_profile.map((h) => h.model_confidence)}
          loading={network.loading && !net}
        />
      </MetricStrip>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.25fr)_420px]">
        {/* Left Column: National Map + Early Warning Station Watchlist */}
        <div className="space-y-4">
          <Panel
            title="National Weather Warning & Forecast Bust Risk"
            subtitle={
              r
                ? `Day ${r.forecast_horizon} ${r.variable.label.toLowerCase()} · ${r.model.label} · Official IMD Early-Warning Factors`
                : 'Loading network'
            }
            tip="Official IMD four-colour warning map (Green/Yellow/Orange/Red) with complete meteorological hazard factors (Thunderstorm, Heavy Rain, Winds, Heat Wave, etc.). Click any state or marker to inspect."
            updated={selection ? formatDate(selection.base_date) : undefined}
            bodyClassName="p-0"
          >
            <div className="w-full p-1">
              {network.error ? (
                <div className="p-3">
                  <ErrorState message={network.error} onRetry={reload} />
                </div>
              ) : warningsLoading && !warnings ? (
                <div className="p-3">
                  <LoadingState label="Loading IMD warning map and meteorological factors" rows={5} />
                </div>
              ) : (
                <ImdWeatherMap
                  warnings={warnings}
                  sites={net?.sites}
                  selectedLocationId={selection?.location_id}
                  onSelectSite={setLocation}
                  height={500}
                  horizon={selection?.horizon}
                  baseDate={selection?.base_date}
                />
              )}
            </div>
          </Panel>

          {/* National Early Warning Watchlist */}
          <Panel
            title="National Early-Warning Station Watchlist & Live Telemetry"
            subtitle={`${sortedSites.length} synoptic stations ranked by AI bust probability · Lead Time: Day ${selection?.horizon ?? 5}`}
            tip="Operational overview of forecast reliability across all monitored Indian cities. Click any station to focus its forecast and live telemetry."
          >
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2 pb-1 text-2xs">
                <div className="flex items-center gap-1 rounded bg-surface-2 p-0.5">
                  {(['ALL', 'ALERT', 'NORMAL'] as const).map((filter) => (
                    <button
                      key={filter}
                      type="button"
                      onClick={() => setSiteFilter(filter)}
                      className={`rounded px-2.5 py-0.5 font-medium transition-colors ${
                        siteFilter === filter
                          ? 'bg-accent text-surface-0 font-bold'
                          : 'text-ink-secondary hover:text-ink-primary'
                      }`}
                    >
                      {filter === 'ALL' ? 'All Stations (10)' : filter === 'ALERT' ? 'Alerts (High/Severe)' : 'Normal (Low/Mod)'}
                    </button>
                  ))}
                </div>
                <span className="text-[10px] text-ink-muted">
                  Click any station to focus
                </span>
              </div>

              <div className="grid gap-1.5 max-h-[380px] overflow-y-auto pr-1">
                {sortedSites.map((site) => {
                  const isCurrent = selection?.location_id === site.id;
                  const color = riskColor(site.risk_category);
                  return (
                    <div
                      key={site.id}
                      onClick={() => setLocation(site.id)}
                      className={`flex cursor-pointer items-center justify-between rounded-md border p-2.5 text-2xs transition-all ${
                        isCurrent
                          ? 'border-accent bg-accent/15 ring-1 ring-accent/60 shadow-sm'
                          : 'border-edge/70 bg-surface-2/60 hover:border-edge-strong hover:bg-surface-2'
                      }`}
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <span
                          className="h-2.5 w-2.5 shrink-0 rounded-full shadow-sm"
                          style={{ backgroundColor: color }}
                        />
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className={`text-xs font-bold truncate ${isCurrent ? 'text-accent' : 'text-ink-primary'}`}>
                              {site.name}
                            </span>
                            <span className="text-[10px] text-ink-muted truncate">
                              · {site.state}
                            </span>
                          </div>
                          <div className="mt-0.5 text-[10px] text-ink-muted truncate">
                            Regime: <span className="text-ink-secondary">{site.regime}</span> · Driver: <span className="text-ink-secondary">{site.top_driver}</span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-3 shrink-0">
                        <div className="text-right">
                          <div className="text-xs font-black tabular-nums" style={{ color }}>
                            {site.risk_score.toFixed(0)}%
                          </div>
                          <div className="text-[9px] text-ink-muted">
                            Confidence: {site.model_confidence.toFixed(0)}%
                          </div>
                        </div>
                        <RiskChip category={site.risk_category} size="sm" />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </Panel>
        </div>

        {/* Risk panel */}
        <div className="space-y-4">
          <Panel
            title="Meteorological Command Center & AI Bust Assessment"
            subtitle={
              imdBust
                ? `${imdBust.location_name} · IMD Station: ${imdBust.matched_station} (${imdBust.distance_km} km)`
                : r
                ? `${r.location.name}, ${r.location.state}`
                : undefined
            }
            tip={RISK_DEFINITION}
            actions={
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleSync(true)}
                  disabled={isSyncing}
                  className="inline-flex items-center gap-1.5 rounded border border-edge-strong bg-surface-2 px-2.5 py-1 text-2xs font-semibold
                             text-ink-primary transition-all hover:border-accent hover:text-accent disabled:opacity-60"
                  title="Force refresh real-time ground telemetry from OpenWeatherMap and IMD"
                >
                  <svg
                    className={`h-3 w-3 ${isSyncing ? 'animate-spin text-accent' : 'text-cyan-400'}`}
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
                  <span className="text-[10px] text-ink-muted">({countdown}s)</span>
                </button>
                {r && (
                  <button
                    type="button"
                    onClick={() => setReportOpen(true)}
                    className="rounded border border-edge-strong px-2 py-1 text-2xs font-medium
                               text-ink-secondary transition-colors hover:border-accent hover:text-accent"
                  >
                    Report
                  </button>
                )}
              </div>
            }
          >
            <div className="mb-3 space-y-3">
              <LocationSearch />
              <DemoScenarios />
            </div>

            {imdBustLoading && !imdBust ? (
              <LoadingState label="Fetching live multi-source telemetry…" rows={5} />
            ) : (
              <div className="space-y-3">
                {/* ── LIVE TELEMETRY & STATION BAR ── */}
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-edge/60 bg-surface-2/80 px-2.5 py-1.5">
                  <div className="flex items-center gap-2">
                    <span className="relative flex h-2.5 w-2.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400 opacity-75" />
                      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-cyan-500" />
                    </span>
                    <span className="text-2xs font-bold uppercase tracking-wider text-cyan-400">
                      Live Telemetry Stream
                    </span>
                    <span className="text-2xs text-ink-muted hidden sm:inline">
                      · {imdBust ? `${imdBust.matched_station} (${imdBust.distance_km} km)` : r?.location.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-[10px]">
                    <span className="rounded border border-edge/60 bg-surface-1 px-1.5 py-0.5 font-medium text-ink-secondary">
                      OWM + MSN Gateway
                    </span>
                    <span className="rounded border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 font-semibold text-emerald-400">
                      ● IMD Ground Truth
                    </span>
                  </div>
                </div>

                {/* ── HERO AI BUST ASSESSMENT GAUGE ── */}
                {risk.error ? (
                  <ErrorState message={risk.error} onRetry={reload} />
                ) : r ? (
                  <div
                    className="relative overflow-hidden rounded-lg border border-edge/80 p-3"
                    style={{
                      background: `radial-gradient(ellipse at top, ${(BUST_COLOR[imdBust?.bust_category ?? r.risk_category] ?? '#22c55e')}16 0%, transparent 70%)`,
                    }}
                  >
                    <div className="flex flex-col items-center">
                      <RiskGauge
                        score={imdBust?.bust_risk_score ?? r.risk_score}
                        category={imdBust?.bust_category ?? r.risk_category}
                        forecastConfidence={r.forecast_confidence}
                        horizon={selection?.horizon ?? r.forecast_horizon}
                      />
                      {/* Risk Category Pill & Validity Window */}
                      <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
                        <span
                          className="rounded-full px-3 py-0.5 text-xs font-black uppercase tracking-wider text-white shadow-sm"
                          style={{
                            backgroundColor: BUST_COLOR[imdBust?.bust_category ?? r.risk_category] ?? '#22c55e',
                            boxShadow: `0 0 14px ${(BUST_COLOR[imdBust?.bust_category ?? r.risk_category] ?? '#22c55e')}55`,
                          }}
                        >
                          {imdBust?.bust_category ?? r.risk_category} BUST RISK
                        </span>
                        <span className="rounded border border-edge bg-surface-2 px-2 py-0.5 text-2xs font-semibold text-ink-secondary">
                          {selection?.horizon === 1
                            ? 'Day 1 · Live Nowcast (Today)'
                            : selection?.horizon === 2
                            ? 'Day 2 · Short-Range Outlook (Tomorrow)'
                            : `Day ${selection?.horizon ?? r.forecast_horizon} · Valid ${formatDate(r.valid_date)}`}
                        </span>
                      </div>
                    </div>

                    {/* Operational Telemetry Summary Bar */}
                    <div className="mt-3 grid grid-cols-3 gap-1.5 border-t border-edge/60 pt-2.5 text-center text-2xs">
                      <div className="rounded bg-surface-2/70 p-1.5">
                        <p className="text-[10px] text-ink-muted">Model Confidence</p>
                        <p className="font-bold text-ink-primary">{r.model_confidence.toFixed(0)}%</p>
                      </div>
                      <div className="rounded bg-surface-2/70 p-1.5">
                        <p className="text-[10px] text-ink-muted">Synoptic Regime</p>
                        <p className="font-bold text-ink-primary truncate">{r.synoptic.regime}</p>
                      </div>
                      <div className="rounded bg-surface-2/70 p-1.5">
                        <p className="text-[10px] text-ink-muted">IMD Warning</p>
                        <p
                          className="font-bold uppercase"
                          style={{ color: WARNING_COLOR[imdBust?.day_1_warning_color ?? 'green'] ?? '#22c55e' }}
                        >
                          {imdBust?.day_1_warning_color?.toUpperCase() ?? 'GREEN'}
                        </p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <LoadingState label="Computing AI bust probability…" rows={4} />
                )}

                {/* ── 7-DAY HORIZON OUTLOOK SEGMENTED STRIP ── */}
                <div className="rounded-lg border border-edge/70 bg-surface-2/60 p-2.5">
                  <div className="mb-2 flex items-center justify-between text-2xs font-medium">
                    <span className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-ink-primary">
                      <span>📅</span> 7-Day Horizon Trajectory
                    </span>
                    <span className="text-[10px] font-semibold text-accent">Select Lead Time</span>
                  </div>
                  <div className="grid grid-cols-7 gap-1">
                    {(imdBust?.forecast_7days && imdBust.forecast_7days.length > 0
                      ? imdBust.forecast_7days
                      : [1, 2, 3, 4, 5, 6, 7].map((d) => ({
                          day: d,
                          max_temp: null,
                          min_temp: null,
                          forecast: '',
                          warning: '',
                          warning_color: 'green',
                        }))
                    ).map((day) => {
                      const isSelected = selection?.horizon === day.day;
                      const warnCol = WARNING_COLOR[day.warning_color?.toLowerCase() ?? 'green'] ?? '#22c55e';
                      return (
                        <button
                          key={day.day}
                          type="button"
                          onClick={() => setHorizon(day.day)}
                          className={`flex flex-col items-center justify-between rounded p-1.5 text-center transition-all ${
                            isSelected
                              ? 'border-2 border-accent bg-accent/20 shadow-sm ring-1 ring-accent/60'
                              : 'border border-edge bg-surface-1/70 hover:border-edge-strong hover:bg-surface-2'
                          }`}
                          title={`Day ${day.day}: ${day.forecast || 'Official Forecast'} (Warning: ${day.warning || day.warning_color || 'Green'})`}
                        >
                          <div className="flex w-full items-center justify-between">
                            <span className={`text-[10px] font-bold ${isSelected ? 'text-accent' : 'text-ink-secondary'}`}>
                              D{day.day}
                            </span>
                            <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: warnCol }} />
                          </div>
                          <span className="my-0.5 text-xs font-black text-ink-primary">
                            {day.max_temp !== null && day.max_temp !== undefined ? `${Math.round(day.max_temp)}°` : '--'}
                          </span>
                          <span className="text-[9px] text-ink-muted">
                            {day.min_temp !== null && day.min_temp !== undefined ? `${Math.round(day.min_temp)}°` : ''}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* ── GROUND TRUTH VS NWP MODEL DIVERGENCE MATRIX ── */}
                <div className="rounded-lg border border-cyan-500/30 bg-surface-2/70 p-2.5">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-cyan-400">
                      <span>⚡</span> Ground Truth vs NWP Divergence
                    </span>
                    <span className="rounded border border-cyan-500/20 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] font-medium text-cyan-300">
                      OpenWeatherMap + MSN
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-2xs">
                    {/* Temperature Tile */}
                    <div className="rounded-md border border-edge/60 bg-surface-1/80 p-2">
                      <div className="flex items-center justify-between text-ink-muted">
                        <span className="font-semibold text-ink-secondary">Surface Temp</span>
                        <span className="text-[10px]">ΔT Anomaly</span>
                      </div>
                      <div className="mt-1 flex items-baseline gap-1.5">
                        <span className="text-sm font-black text-ink-primary">
                          {imdBust?.live_current?.temperature !== null && imdBust?.live_current?.temperature !== undefined
                            ? `${imdBust.live_current.temperature.toFixed(1)}°C`
                            : imdBust?.today_max_temp
                            ? `${imdBust.today_max_temp}°C`
                            : 'N/A'}
                        </span>
                        {imdBust?.live_current?.feels_like !== null && imdBust?.live_current?.feels_like !== undefined && (
                          <span className="text-[10px] text-ink-muted">
                            (Feels {imdBust.live_current.feels_like.toFixed(1)}°)
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 flex items-center justify-between text-[10px] text-ink-muted">
                        <span>
                          NWP:{' '}
                          {imdBust?.today_max_temp
                            ? `${imdBust.today_max_temp}°C`
                            : r?.base_value !== undefined
                            ? `${r.base_value.toFixed(1)}${r.variable.unit}`
                            : '--'}
                        </span>
                        {imdBust?.live_current?.temperature !== null &&
                          imdBust?.live_current?.temperature !== undefined &&
                          imdBust?.today_max_temp && (
                            <span
                              className={`rounded px-1 text-[9px] font-bold ${
                                Math.abs(imdBust.live_current.temperature - parseFloat(imdBust.today_max_temp)) >= 2.5
                                  ? 'bg-rose-500/20 text-rose-400'
                                  : 'bg-emerald-500/20 text-emerald-400'
                              }`}
                            >
                              {(imdBust.live_current.temperature - parseFloat(imdBust.today_max_temp)) > 0 ? '+' : ''}
                              {(imdBust.live_current.temperature - parseFloat(imdBust.today_max_temp)).toFixed(1)}°C
                            </span>
                          )}
                      </div>
                    </div>

                    {/* Moisture & Rain Tile */}
                    <div className="rounded-md border border-edge/60 bg-surface-1/80 p-2">
                      <div className="flex items-center justify-between text-ink-muted">
                        <span className="font-semibold text-ink-secondary">Moisture & Rain</span>
                        <span className="text-[10px]">
                          {imdBust?.live_current?.dew_point !== null && imdBust?.live_current?.dew_point !== undefined
                            ? `Dew ${imdBust.live_current.dew_point.toFixed(0)}°`
                            : 'RH'}
                        </span>
                      </div>
                      <div className="mt-1 flex items-baseline gap-1.5">
                        <span className="text-sm font-black text-ink-primary">
                          {imdBust?.live_current?.relative_humidity !== null && imdBust?.live_current?.relative_humidity !== undefined
                            ? `${imdBust.live_current.relative_humidity}%`
                            : imdBust?.humidity_0830
                            ? `${imdBust.humidity_0830}%`
                            : 'N/A'}
                        </span>
                        <span className="text-[10px] text-ink-muted">
                          Live: {imdBust?.live_current?.precipitation_mm ?? '0.0'} mm
                        </span>
                      </div>
                      <div className="mt-0.5 flex items-center justify-between text-[10px] text-ink-muted">
                        <span>Past 24h: {imdBust?.past_24_hrs_rainfall || '0 mm'}</span>
                        <span className="font-medium text-cyan-400">
                          {(imdBust?.live_current?.relative_humidity ?? 50) > 75 ? 'High Vapor Inflow' : 'Standard Moisture'}
                        </span>
                      </div>
                    </div>

                    {/* Barometric Pressure Tile */}
                    <div className="rounded-md border border-edge/60 bg-surface-1/80 p-2">
                      <div className="flex items-center justify-between text-ink-muted">
                        <span className="font-semibold text-ink-secondary">Surface Pressure</span>
                        <span className="text-[10px]">Tendency</span>
                      </div>
                      <div className="mt-1 flex items-baseline gap-1.5">
                        <span className="text-sm font-black text-ink-primary">
                          {imdBust?.live_current?.pressure_hpa ? `${imdBust.live_current.pressure_hpa} hPa` : '1010 hPa'}
                        </span>
                      </div>
                      <div className="mt-0.5 flex items-center justify-between text-[10px] text-ink-muted">
                        <span>
                          {(imdBust?.live_current?.pressure_hpa ?? 1010) < 1006 ? 'Depression Flow' : 'Equilibrium Field'}
                        </span>
                        <span
                          className={`font-semibold ${
                            (imdBust?.live_current?.pressure_hpa ?? 1010) < 1006 ? 'text-amber-400' : 'text-emerald-400'
                          }`}
                        >
                          {(imdBust?.live_current?.pressure_hpa ?? 1010) < 1006 ? 'Convective' : 'Stable'}
                        </span>
                      </div>
                    </div>

                    {/* Boundary Layer Wind & Sky Tile */}
                    <div className="rounded-md border border-edge/60 bg-surface-1/80 p-2">
                      <div className="flex items-center justify-between text-ink-muted">
                        <span className="font-semibold text-ink-secondary">Wind & Sky</span>
                        <span className="text-[10px]">Cloud {imdBust?.live_current?.cloud_cover ?? '--'}%</span>
                      </div>
                      <div className="mt-1 flex items-baseline gap-1.5">
                        <span className="text-sm font-black text-ink-primary">
                          {imdBust?.live_current?.wind_speed_kmh !== null && imdBust?.live_current?.wind_speed_kmh !== undefined
                            ? `${imdBust.live_current.wind_speed_kmh} km/h`
                            : 'N/A'}
                        </span>
                        <span className="text-[10px] text-ink-muted truncate max-w-[80px]">
                          {imdBust?.live_current?.wind_deg ? `${imdBust.live_current.wind_deg}°` : ''}
                        </span>
                      </div>
                      <div className="mt-0.5 truncate text-[10px] text-ink-secondary">
                        {imdBust?.live_current?.weather_description || imdBust?.todays_forecast || 'Clear Sky'}
                      </div>
                    </div>
                  </div>
                </div>

                {/* ── PHYSICAL BUST DRIVERS ── */}
                {imdBust?.bust_drivers && imdBust.bust_drivers.length > 0 && (
                  <div>
                    <p className="mb-1 text-2xs font-bold uppercase tracking-wider text-ink-muted">
                      Telemetry & Anomaly Risk Drivers
                    </p>
                    <ul className="space-y-1">
                      {imdBust.bust_drivers.map((d, i) => (
                        <li key={i} className="flex items-start gap-1.5 text-2xs text-ink-secondary">
                          <span style={{ color: BUST_COLOR[imdBust.bust_category ?? 'LOW'] }}>▶</span>
                          <span>{d}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* ── OPERATIONAL DIRECTIVE & RECOMMENDATION ── */}
                {imdBust?.recommendation && (
                  <div
                    className="rounded-md px-3 py-2 text-2xs leading-relaxed"
                    style={{
                      backgroundColor: (BUST_COLOR[imdBust.bust_category ?? 'LOW'] ?? '#22c55e') + '18',
                      borderLeft: `3px solid ${BUST_COLOR[imdBust.bust_category ?? 'LOW'] ?? '#22c55e'}`,
                      color: BUST_COLOR[imdBust.bust_category ?? 'LOW'] ?? '#22c55e',
                    }}
                  >
                    <strong className="mb-0.5 block font-bold uppercase tracking-wider">
                      IMD Operational Directive:
                    </strong>
                    {imdBust.recommendation}
                  </div>
                )}
              </div>
            )}
          </Panel>

          <Panel
            title="Forecast selection"
            subtitle="Every panel on this page follows this selection"
          >
            <ForecastSelector />
          </Panel>
        </div>
      </div>

      {/* Explanation + Multi-Model Comparison on Left | Ensemble + Timeline on Right */}
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="space-y-4">
          <Panel
            title="Why is this forecast at risk?"
            subtitle="Contribution of each monitored driver to the assessed risk"
            tip="Each bar shows how far this driver sits from its dataset average, weighted by its importance in the model. Red raises the assessed risk; blue lowers it."
          >
            {r ? (
              <ShapExplanation
                contributions={r.feature_contributions}
                explanation={r.explanation}
                method={r.explanation_method}
                label={r.explanation_label}
              />
            ) : (
              <LoadingState label="Computing contributions" rows={6} />
            )}
          </Panel>

          {/* Numerical Weather Prediction Multi-Model Consensus */}
          {r && (
            <Panel
              title="Numerical Weather Prediction Multi-Model Consensus"
              subtitle={`ECMWF vs NCMRWF-NCUM vs GFS · Day ${r.forecast_horizon} ${r.variable.label}`}
              tip="Comparison of major global and regional NWP centres. Large disagreement between deterministic models signals elevated atmospheric unpredictability."
            >
              <div className="space-y-3">
                {/* Disagreement / Agreement Banner */}
                <div
                  className={`flex items-center justify-between rounded-md border px-3 py-2 text-2xs ${
                    r.model_comparison.disagreement
                      ? 'border-amber-500/40 bg-amber-500/10 text-amber-300'
                      : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  }`}
                >
                  <span className="font-semibold flex items-center gap-1.5">
                    <span>{r.model_comparison.disagreement ? '⚠️' : '✓'}</span>
                    {r.model_comparison.message}
                  </span>
                  <span className="font-mono text-[11px] text-ink-secondary">
                    Inter-Model Spread: <strong>{r.model_comparison.spread_between_models} {r.variable.unit}</strong>
                  </span>
                </div>

                {/* Model Rows */}
                <div className="grid gap-2">
                  {r.model_comparison.rows.map((row) => (
                    <div
                      key={row.model_id}
                      className={`flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-2xs transition-colors ${
                        selection?.model_id === row.model_id
                          ? 'border-accent bg-accent/10 ring-1 ring-accent/50'
                          : 'border-edge bg-surface-2/60 hover:bg-surface-2'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-ink-primary">{row.model}</span>
                        <span className="text-[10px] text-ink-muted hidden sm:inline">({row.centre})</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="font-mono font-bold text-ink-primary">
                          {row.forecast_value} {row.unit}
                        </span>
                        <span className="text-[10px] text-ink-secondary">
                          Spread: <strong className="text-ink-primary">{row.ensemble_spread}</strong> ({row.spread_label})
                        </span>
                        <RiskChip category={row.risk_category} size="sm" />
                        <span className="text-[10px] text-ink-muted">
                          Skill: {row.historical_skill}%
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </Panel>
          )}
        </div>

        <div className="space-y-4">
          <Panel
            title="Ensemble spread"
            subtitle={r ? `${r.ensemble.member_count} members - ${r.model.label}` : undefined}
            tip="Measures disagreement between ensemble forecast members. Higher spread generally indicates greater forecast uncertainty."
            unit={r?.variable.unit}
          >
            {r ? (
              <EnsembleSpreadChart ensemble={r.ensemble} horizon={r.forecast_horizon} />
            ) : (
              <LoadingState label="Loading ensemble" rows={4} />
            )}
          </Panel>

          <Panel
            title="Risk escalation timeline"
            subtitle={r ? `Successive model runs verifying on ${formatDate(r.valid_date)}` : undefined}
            tip="Each point is a different model initialisation for the same valid date, from Day 7 down to Day 3."
          >
            {r ? <AlertTimeline rows={r.risk_timeline} /> : <LoadingState rows={3} />}
          </Panel>
        </div>
      </div>

      {/* Analogues + Horizon Profile with Operational Verification */}
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel
          title="Historical analogue analysis"
          subtitle="Similar past atmospheric patterns and how their forecasts performed"
          tip="How closely the current pattern matches historical situations for which the forecast outcome is known."
        >
          {r ? (
            <AnaloguePanel
              analogues={r.analogues}
              note={r.analogue_summary.note}
              bestSimilarity={r.analogue_summary.best_similarity}
              bustCount={r.analogue_summary.bust_count}
            />
          ) : (
            <LoadingState rows={5} />
          )}
        </Panel>

        <Panel
          title="Risk across the forecast horizon"
          subtitle="How bust risk varies with lead time from this initialisation"
          tip="Risk generally grows with lead time, but a pattern transition inside the window can make one specific lead time far riskier than its neighbours."
        >
          {r ? (
            <div className="space-y-4">
              <ul className="space-y-2">
                {r.horizon_profile.map((row) => (
                  <li key={row.horizon} className="flex items-center gap-3">
                    <span className="w-12 shrink-0 text-2xs font-medium text-ink-secondary">
                      {row.label}
                    </span>
                    <span className="h-5 flex-1 overflow-hidden rounded-sm bg-surface-2">
                      <span
                        className="flex h-full items-center justify-end rounded-sm px-1.5
                                   text-[10px] font-bold text-surface-0 transition-all duration-300"
                        style={{
                          width: `${Math.max(row.risk_score, 8)}%`,
                          background: riskColor(row.risk_category),
                        }}
                      >
                        {row.risk_score.toFixed(0)}%
                      </span>
                    </span>
                    <span className="w-20 shrink-0 text-right">
                      <RiskChip category={row.risk_category} size="sm" />
                    </span>
                  </li>
                ))}
              </ul>

              {/* Operational Verification Scorecard */}
              <div className="rounded-lg border border-edge/80 bg-surface-2/70 p-3 text-2xs">
                <div className="flex items-center justify-between pb-2 border-b border-edge/60">
                  <span className="font-bold uppercase tracking-wider text-ink-primary flex items-center gap-1.5">
                    <span>📊</span> Operational Verification Scorecard
                  </span>
                  <span className="text-[10px] text-ink-muted">
                    {r.observation_source.verified_against}
                  </span>
                </div>

                <div className="mt-2.5 grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
                  <div className="rounded bg-surface-1/80 p-2 border border-edge/50">
                    <p className="text-[10px] text-ink-muted">RMSE</p>
                    <p className="text-xs font-black text-ink-primary">
                      {r.verification.metrics.rmse} {r.variable.unit}
                    </p>
                    <p className="text-[9px] text-ink-muted mt-0.5">MAE: {r.verification.metrics.mae}</p>
                  </div>

                  <div className="rounded bg-surface-1/80 p-2 border border-edge/50">
                    <p className="text-[10px] text-ink-muted">Accuracy (ACC)</p>
                    <p className="text-xs font-black text-emerald-400">
                      {(r.verification.metrics.acc * 100).toFixed(1)}%
                    </p>
                    <p className="text-[9px] text-ink-muted mt-0.5">Anomaly Corr</p>
                  </div>

                  <div className="rounded bg-surface-1/80 p-2 border border-edge/50">
                    <p className="text-[10px] text-ink-muted">Forecast Skill</p>
                    <p className="text-xs font-black text-cyan-400">
                      {(r.verification.metrics.skill * 100).toFixed(1)}%
                    </p>
                    <p className="text-[9px] text-ink-muted mt-0.5">vs Climatology</p>
                  </div>

                  <div className="rounded bg-surface-1/80 p-2 border border-edge/50">
                    <p className="text-[10px] text-ink-muted">Verified Busts</p>
                    <p className="text-xs font-black text-amber-400">
                      {r.verification.metrics.bust_count} / {r.verification.metrics.sample_size}
                    </p>
                    <p className="text-[9px] text-ink-muted mt-0.5">Obs Window</p>
                  </div>
                </div>

                <div className="mt-2 text-[10px] text-ink-muted flex flex-wrap items-center justify-between gap-1">
                  <span>Window: {formatDate(r.observation_source.window[0])} – {formatDate(r.observation_source.window[1])}</span>
                  <span>Reference: {r.verification.metrics.reference || 'IMD published daily normal'}</span>
                </div>
              </div>
            </div>
          ) : (
            <LoadingState rows={5} />
          )}
          <DemoNotice notice={meta.data?.demo_notice ?? null} className="mt-3" />
        </Panel>
      </div>

      {reportOpen && r && <ReportExport risk={r} onClose={() => setReportOpen(false)} />}
    </div>
  );
}
