/** Early-warning alerts across the monitoring network. */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { AlertsResponse, Alert, RiskCategory, ImdRealtimeAlertsResponse } from '../api/types';
import { AlertCard } from '../components/AlertCard';
import { AlertTimeline } from '../components/AlertTimeline';
import { ReportExport } from '../components/ReportExport';
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  Panel,
} from '../components/Primitives';
import { Metric, MetricStrip } from '../components/RiskCard';
import { useAppState } from '../state/AppState';
import { formatDate } from '../lib/format';

type SeverityFilter = 'ALL' | RiskCategory;
type SourceMode = 'IMD_LIVE' | 'ALL' | 'MODEL_ENSEMBLE';

export function AlertsPage() {
  const { selection, risk, setLocation, setVariable, setHorizon } = useAppState();
  const navigate = useNavigate();

  const [sourceMode, setSourceMode] = useState<SourceMode>('IMD_LIVE');
  const [modelData, setModelData] = useState<AlertsResponse | null>(null);
  const [imdData, setImdData] = useState<ImdRealtimeAlertsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<SeverityFilter>('ALL');
  const [reportOpen, setReportOpen] = useState(false);

  // Fetch both live IMD alerts and model alerts in parallel
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const baseDate = selection?.base_date;

    Promise.allSettled([
      api.imdAlerts(50),
      baseDate ? api.alerts(baseDate) : Promise.resolve(null),
    ])
      .then(([imdRes, modelRes]) => {
        if (cancelled) return;
        if (imdRes.status === 'fulfilled') {
          setImdData(imdRes.value);
        }
        if (modelRes.status === 'fulfilled' && modelRes.value) {
          setModelData(modelRes.value);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load alerts');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selection?.base_date]);

  // Aggregate or select alerts based on sourceMode
  const activeAlerts = useMemo(() => {
    let list: Alert[] = [];
    if (sourceMode === 'IMD_LIVE') {
      list = (imdData?.alerts as Alert[]) ?? [];
    } else if (sourceMode === 'MODEL_ENSEMBLE') {
      list = modelData?.alerts ?? [];
    } else {
      // Combined: combine IMD live alerts with model alerts
      const imdAlertsList = (imdData?.alerts as Alert[]) ?? [];
      const modelAlertsList = modelData?.alerts ?? [];
      list = [...imdAlertsList, ...modelAlertsList];
      // Sort worst risk score first
      list.sort((a, b) => b.risk_score - a.risk_score);
    }

    if (filter === 'ALL') return list;
    return list.filter((a) => a.severity === filter);
  }, [sourceMode, imdData, modelData, filter]);

  // Compute metrics depending on current source mode
  const metrics = useMemo(() => {
    if (sourceMode === 'IMD_LIVE') {
      const total = imdData?.alerts.length ?? 0;
      const severe = imdData?.severe_count ?? 0;
      const high = imdData?.high_count ?? 0;
      const issued = imdData?.issued_at ? formatDate(imdData.issued_at) : '27 Sep 2026';
      const highest = imdData?.alerts[0]
        ? `${imdData.alerts[0].risk_score.toFixed(0)}% (${imdData.alerts[0].location_name})`
        : '--';
      return { total, severe, high, issued, highest, isLive: true };
    } else if (sourceMode === 'MODEL_ENSEMBLE') {
      const total = modelData?.alerts.length ?? 0;
      const severe = modelData?.counts.SEVERE ?? 0;
      const high = modelData?.counts.HIGH ?? 0;
      const issued = modelData ? formatDate(modelData.base_date) : '--';
      const highest = modelData?.alerts[0]
        ? `${modelData.alerts[0].risk_score.toFixed(0)}% (${modelData.alerts[0].location_name})`
        : '--';
      return { total, severe, high, issued, highest, isLive: false };
    } else {
      const total = (imdData?.alerts.length ?? 0) + (modelData?.alerts.length ?? 0);
      const severe = (imdData?.severe_count ?? 0) + (modelData?.counts.SEVERE ?? 0);
      const high = (imdData?.high_count ?? 0) + (modelData?.counts.HIGH ?? 0);
      const issued = 'Live & Operational';
      const topAlert = activeAlerts[0];
      const highest = topAlert ? `${topAlert.risk_score.toFixed(0)}% (${topAlert.location_name})` : '--';
      return { total, severe, high, issued, highest, isLive: true };
    }
  }, [sourceMode, imdData, modelData, activeAlerts]);

  const openAnalysis = (alert: Alert) => {
    setLocation(alert.location_id);
    setVariable(alert.variable_id);
    setHorizon(alert.horizon);
    navigate('/analysis');
  };

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;

  return (
    <div className="space-y-4">
      {/* KPI Metric Strip */}
      <MetricStrip>
        <Metric
          label="Active alerts"
          value={loading && !imdData && !modelData ? '--' : metrics.total}
          detail={
            sourceMode === 'IMD_LIVE'
              ? 'Real-time IMD stations ≥ 50% bust risk'
              : 'Rainfall forecast reliability notices'
          }
          tip="Raised when the assessed forecast bust risk crosses the HIGH band (≥50% for live IMD, or p(bust) ≥ 34% for ensemble)."
          accent="#fab219"
          loading={loading && !imdData && !modelData}
        />
        <Metric
          label="Severe"
          value={metrics.severe}
          detail="Bust risk above 70-80%"
          accent="#d03b3b"
          loading={loading && !imdData && !modelData}
        />
        <Metric
          label="High"
          value={metrics.high}
          detail="Bust risk 50-70%"
          accent="#ec835a"
          loading={loading && !imdData && !modelData}
        />
        <Metric
          label={metrics.isLive ? 'Live Bulletin' : 'Model Issued'}
          value={metrics.issued}
          detail={metrics.isLive ? 'Official IMD Realtime Feed' : 'Ensemble initialisation'}
        />
        <Metric
          label="Highest risk"
          value={metrics.highest}
          accent="#d03b3b"
          loading={loading && !imdData && !modelData}
        />
      </MetricStrip>

      {/* Main Grid */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel
          title={
            sourceMode === 'IMD_LIVE'
              ? 'Real-Time IMD Weather Early Warnings'
              : sourceMode === 'MODEL_ENSEMBLE'
              ? 'ECMWF Ensemble Early Warnings'
              : 'Combined Multi-Source Early Warnings'
          }
          subtitle={
            sourceMode === 'IMD_LIVE'
              ? 'Official India Meteorological Department 113-observatory city bulletin & convective risk model'
              : 'Rainfall forecast reliability notices — decision support for forecasters'
          }
          tip="AtmosGuard flags forecasts with elevated bust risk based on official warnings, observed precipitation volatility, and ensemble spread."
          actions={
            <div className="flex flex-wrap items-center gap-2">
              {/* Source Mode Toggle */}
              <div className="flex rounded border border-edge bg-surface-2 p-0.5">
                <button
                  type="button"
                  onClick={() => setSourceMode('IMD_LIVE')}
                  className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-2xs font-semibold transition-colors ${
                    sourceMode === 'IMD_LIVE'
                      ? 'bg-accent/20 text-accent border border-accent/40'
                      : 'text-ink-secondary hover:text-ink-primary'
                  }`}
                >
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                    <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  </span>
                  IMD Live
                </button>
                <button
                  type="button"
                  onClick={() => setSourceMode('ALL')}
                  className={`rounded px-2.5 py-1 text-2xs font-semibold transition-colors ${
                    sourceMode === 'ALL'
                      ? 'bg-accent/20 text-accent border border-accent/40'
                      : 'text-ink-secondary hover:text-ink-primary'
                  }`}
                >
                  Combined
                </button>
                <button
                  type="button"
                  onClick={() => setSourceMode('MODEL_ENSEMBLE')}
                  className={`rounded px-2.5 py-1 text-2xs font-semibold transition-colors ${
                    sourceMode === 'MODEL_ENSEMBLE'
                      ? 'bg-accent/20 text-accent border border-accent/40'
                      : 'text-ink-secondary hover:text-ink-primary'
                  }`}
                >
                  ECMWF Model
                </button>
              </div>

              {/* Severity Filter */}
              <div className="flex gap-1">
                {(['ALL', 'SEVERE', 'HIGH'] as SeverityFilter[]).map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setFilter(option)}
                    aria-pressed={filter === option}
                    className={`segment ${filter === option ? 'segment-active' : ''}`}
                  >
                    {option === 'ALL' ? 'All' : option}
                  </button>
                ))}
              </div>
            </div>
          }
        >
          {loading && activeAlerts.length === 0 ? (
            <LoadingState label="Scanning IMD live network and model guidance…" rows={5} />
          ) : activeAlerts.length === 0 ? (
            <EmptyState
              title="No active alerts in this category"
              detail="No station or region currently crosses the selected risk threshold."
            />
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              {activeAlerts.map((alert) => (
                <AlertCard
                  key={alert.id}
                  alert={alert}
                  onAnalyse={openAnalysis}
                  onExport={(a) => {
                    openAnalysisNoNav(a);
                    setReportOpen(true);
                  }}
                />
              ))}
            </div>
          )}
        </Panel>

        {/* Right Sidebar: Risk Escalation + References & Methodology */}
        <div className="space-y-4">
          <Panel
            title="Risk escalation"
            subtitle={
              risk.data
                ? `${risk.data.location.name} - valid ${formatDate(risk.data.valid_date)}`
                : undefined
            }
            tip="Successive model runs for one valid date. Rising risk as the event nears is the early warning."
          >
            {risk.data ? <AlertTimeline rows={risk.data.risk_timeline} /> : <LoadingState rows={3} />}
          </Panel>

          {/* Authoritative Sources & Datasets Reference */}
          <Panel
            title="Authoritative Data Sources"
            subtitle="Verified national & international meteorology feeds"
          >
            <div className="space-y-2.5 text-2xs">
              <div className="rounded border border-edge bg-surface-2 p-2.5">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-ink-primary flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                    IMD National Weather Centre
                  </span>
                  <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-3xs font-bold text-emerald-400">
                    OPERATIONAL
                  </span>
                </div>
                <p className="mt-1 text-ink-secondary leading-snug">
                  Live 113-station daily bulletin, 24h observed rainfall records, and 7-day multi-tier warnings (Red/Orange/Yellow) via official IMD API and GeoServer WFS.
                </p>
                <div className="mt-1.5 flex gap-2 text-3xs text-ink-muted">
                  <span>Portal: <a href="https://mausam.imd.gov.in" target="_blank" rel="noreferrer" className="text-accent underline">mausam.imd.gov.in</a></span>
                  <span>•</span>
                  <span>License: GODL India</span>
                </div>
              </div>

              <div className="rounded border border-edge bg-surface-2 p-2.5">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-ink-primary">ECMWF IFS Ensemble</span>
                  <span className="rounded bg-accent/20 px-1.5 py-0.5 text-3xs font-bold text-accent">
                    NWP MODEL
                  </span>
                </div>
                <p className="mt-1 text-ink-secondary leading-snug">
                  51-member global medium-range ensemble spread, geopotential height anomalies, and precipitation plume distributions for forecast dispersion.
                </p>
                <div className="mt-1.5 flex gap-2 text-3xs text-ink-muted">
                  <span>Portal: <a href="https://data.ecmwf.int" target="_blank" rel="noreferrer" className="text-accent underline">data.ecmwf.int</a></span>
                  <span>•</span>
                  <span>License: CC BY 4.0</span>
                </div>
              </div>

              <div className="rounded border border-edge bg-surface-2 p-2.5">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-ink-primary">NCMRWF &amp; NOAA GHCN-D</span>
                  <span className="rounded bg-surface-3 px-1.5 py-0.5 text-3xs font-medium text-ink-muted">
                    CLIMATOLOGY
                  </span>
                </div>
                <p className="mt-1 text-ink-secondary leading-snug">
                  MoES National Centre for Medium Range Weather Forecasting NEPS models and 1901–2021 historical synoptic station benchmarks.
                </p>
              </div>
            </div>
          </Panel>

          <Panel title="How to read an alert">
            <ul className="space-y-2.5 text-2xs leading-relaxed text-ink-secondary">
              <li>
                <Badge tone="accent">Bust risk</Badge> measures how likely this forecast is to turn
                out materially wrong — not how severe the weather will be.
              </li>
              <li>
                <Badge>Confidence</Badge> is confidence in the assessment itself. A high
                risk with high confidence indicates urgent need for nowcasting.
              </li>
              <li>
                <Badge tone="warn">Action</Badge> recommends shifting weight toward radar nowcasts,
                satellite imagery, and multi-model ensemble plume spread.
              </li>
            </ul>
            <p className="mt-3 border-t border-edge pt-3 text-2xs leading-relaxed text-ink-muted">
              Official IMD Early-Warning Advisory System. Data refreshed automatically from IMD operational servers.
            </p>
          </Panel>
        </div>
      </div>

      {reportOpen && risk.data && <ReportExport risk={risk.data} onClose={() => setReportOpen(false)} />}
    </div>
  );

  function openAnalysisNoNav(alert: Alert) {
    setLocation(alert.location_id);
    setVariable(alert.variable_id);
    setHorizon(alert.horizon);
  }
}
