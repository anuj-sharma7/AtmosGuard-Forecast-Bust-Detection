/**
 * Command centre.
 *
 * The whole product in one screen: what the network looks like right now, the
 * assessment for the selected forecast, why it is at risk, and what the
 * ensemble is doing. On first load this is the Jaipur Day 5 rainfall case.
 */

import { useEffect, useState } from 'react';
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
  const { meta, risk, network, selection, setLocation, reload } = useAppState();
  const navigate = useNavigate();
  const [reportOpen, setReportOpen] = useState(false);
  const [alerts, setAlerts] = useState<AlertsResponse | null>(null);
  const [warnings, setWarnings] = useState<WarningsResponse | null>(null);
  const [warningsLoading, setWarningsLoading] = useState(false);
  const [imdBust, setImdBust] = useState<ImdBustResponse | null>(null);
  const [imdBustLoading, setImdBustLoading] = useState(false);

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
    api
      .warnings(selection)
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
      {/* Positioning statement - the product explained in two lines. */}
      <section className="panel px-4 py-3.5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="max-w-2xl">
            <h2 className="text-lg font-bold tracking-tight text-ink-primary">
              Reads the forecast before it fails.
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-ink-secondary">
              AtmosGuard detects medium-range forecast bust risk before the weather event occurs -
              helping forecasters identify uncertainty, understand its causes, and act earlier.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => navigate('/analysis')}
              className="rounded border border-accent/50 bg-accent/12 px-3 py-1.5 text-xs
                         font-semibold text-accent transition-colors hover:bg-accent/20"
            >
              Analyze Forecast
            </button>
            <button
              type="button"
              onClick={() => navigate('/map')}
              className="rounded border border-edge-strong px-3 py-1.5 text-xs font-medium
                         text-ink-secondary transition-colors hover:text-ink-primary"
            >
              View Risk Map
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

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        {/* Map */}
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
          className="min-h-[580px]"
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
                height={520}
                horizon={selection?.horizon}
                baseDate={selection?.base_date}
              />
            )}
          </div>
        </Panel>

        {/* Risk panel */}
        <div className="space-y-4">
          <Panel
            title="Forecast Bust Risk"
            subtitle={
              imdBust
                ? `${imdBust.location_name} · IMD Live: ${imdBust.matched_station}`
                : r
                ? `${r.location.name}, ${r.location.state}`
                : undefined
            }
            tip={RISK_DEFINITION}
            actions={
              r && (
                <button
                  type="button"
                  onClick={() => setReportOpen(true)}
                  className="rounded border border-edge-strong px-2 py-1 text-2xs font-medium
                             text-ink-secondary transition-colors hover:border-accent hover:text-accent"
                >
                  Report
                </button>
              )
            }
          >
            <div className="mb-3 space-y-3">
              <LocationSearch />
              <DemoScenarios />
            </div>

            {/* ── IMD LIVE ANALYSIS CARD ── */}
            {imdBustLoading ? (
              <LoadingState label="Fetching live IMD data…" rows={3} />
            ) : imdBust ? (
              <div className="mb-4 rounded-lg border border-edge overflow-hidden">
                {/* Header bar */}
                <div
                  className="flex items-center justify-between px-3 py-2"
                  style={{ backgroundColor: (WARNING_COLOR[imdBust.day_1_warning_color] ?? '#22c55e') + '22', borderBottom: `2px solid ${WARNING_COLOR[imdBust.day_1_warning_color] ?? '#22c55e'}` }}
                >
                  <div className="flex items-center gap-2">
                    <span className="relative flex h-2.5 w-2.5">
                      <span
                        className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-75"
                        style={{ backgroundColor: WARNING_COLOR[imdBust.day_1_warning_color] ?? '#22c55e' }}
                      />
                      <span
                        className="relative inline-flex h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: WARNING_COLOR[imdBust.day_1_warning_color] ?? '#22c55e' }}
                      />
                    </span>
                    <span className="text-xs font-bold uppercase tracking-wide text-ink-primary">
                      IMD Live Analysis
                    </span>
                  </div>
                  <span className="text-2xs text-ink-muted">
                    {imdBust.matched_station} · {imdBust.distance_km} km
                  </span>
                </div>

                {/* Live Bust Score — big number */}
                <div className="px-3 pt-3">
                  <div className="flex items-end justify-between mb-1">
                    <span className="text-2xs font-medium uppercase tracking-wider text-ink-muted">AI Bust Probability</span>
                    <span
                      className="text-2xl font-black tabular-nums"
                      style={{ color: BUST_COLOR[imdBust.bust_category] ?? '#22c55e' }}
                    >
                      {imdBust.bust_risk_score}%
                    </span>
                  </div>
                  {/* Animated progress bar */}
                  <div className="relative h-3 w-full overflow-hidden rounded-full bg-surface-2 mb-1">
                    <div
                      className="absolute inset-y-0 left-0 rounded-full transition-all duration-700"
                      style={{
                        width: `${imdBust.bust_risk_score}%`,
                        backgroundColor: BUST_COLOR[imdBust.bust_category] ?? '#22c55e',
                      }}
                    />
                  </div>
                  <div className="flex justify-between text-2xs text-ink-muted mb-3">
                    <span>LOW</span><span>MODERATE</span><span>HIGH</span><span>SEVERE</span>
                  </div>

                  {/* Risk category badge & dynamic bulletin date info */}
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span
                        className="rounded px-2 py-0.5 text-xs font-bold uppercase tracking-wide text-white"
                        style={{ backgroundColor: BUST_COLOR[imdBust.bust_category] ?? '#22c55e' }}
                      >
                        {imdBust.bust_category} RISK
                      </span>
                      <span className="text-2xs font-medium text-emerald-400">
                        ● IMD Bulletin {formatDate(imdBust.bulletin_date || imdBust.date)} (Today)
                      </span>
                    </div>
                    <span className="text-[11px] text-ink-muted">
                      {imdBust.last_updated ? `Synced: ${imdBust.last_updated}` : 'Live feed'}
                    </span>
                  </div>

                  {/* Forecast window banner */}
                  <div className="mb-3 rounded border border-edge/60 bg-surface-2/70 px-2.5 py-1.5 text-[11px] text-ink-secondary flex items-center justify-between">
                    <span>
                      <strong className="text-ink-primary">Forecast Window:</strong> Day 1 to Day 7
                      {imdBust.forecast_valid_to ? ` (${formatDate(imdBust.bulletin_date || imdBust.date)} – ${formatDate(imdBust.forecast_valid_to)})` : ''}
                    </span>
                    <span className="text-accent text-[10px] uppercase font-semibold">Live Operational</span>
                  </div>

                  {/* Current conditions grid */}
                  <div className="grid grid-cols-2 gap-2 mb-3">
                    <div className="rounded bg-surface-2 px-2 py-1.5">
                      <p className="text-2xs text-ink-muted">24-hr Rainfall</p>
                      <p className="text-sm font-semibold text-ink-primary">
                        {imdBust.past_24_hrs_rainfall === 'NIL' || !imdBust.past_24_hrs_rainfall
                          ? '0 mm'
                          : `${imdBust.past_24_hrs_rainfall} mm`}
                      </p>
                    </div>
                    <div className="rounded bg-surface-2 px-2 py-1.5">
                      <p className="text-2xs text-ink-muted">IMD Warning</p>
                      <p
                        className="text-sm font-semibold capitalize"
                        style={{ color: WARNING_COLOR[imdBust.day_1_warning_color] ?? '#22c55e' }}
                      >
                        {imdBust.day_1_warning_color.toUpperCase()}
                      </p>
                    </div>
                    {imdBust.today_max_temp && (
                      <div className="rounded bg-surface-2 px-2 py-1.5">
                        <p className="text-2xs text-ink-muted">Max Temp</p>
                        <p className="text-sm font-semibold text-ink-primary">{imdBust.today_max_temp}&deg;C</p>
                      </div>
                    )}
                    {imdBust.humidity_0830 && (
                      <div className="rounded bg-surface-2 px-2 py-1.5">
                        <p className="text-2xs text-ink-muted">Humidity 0830</p>
                        <p className="text-sm font-semibold text-ink-primary">{imdBust.humidity_0830}%</p>
                      </div>
                    )}
                  </div>

                  {/* Today's official forecast */}
                  {imdBust.todays_forecast && (
                    <div className="mb-3 rounded bg-surface-2 px-2.5 py-2">
                      <p className="text-2xs text-ink-muted mb-0.5">IMD Official Forecast</p>
                      <p className="text-xs text-ink-secondary leading-snug">{imdBust.todays_forecast}</p>
                    </div>
                  )}

                  {/* Bust drivers */}
                  {imdBust.bust_drivers.length > 0 && (
                    <div className="mb-3">
                      <p className="text-2xs font-medium uppercase tracking-wider text-ink-muted mb-1.5">Risk Drivers</p>
                      <ul className="space-y-1">
                        {imdBust.bust_drivers.map((d, i) => (
                          <li key={i} className="flex items-start gap-1.5 text-2xs text-ink-secondary">
                            <span style={{ color: BUST_COLOR[imdBust.bust_category] }}>▶</span>
                            <span>{d}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Recommendation */}
                  {imdBust.recommendation && (
                    <div
                      className="mb-3 rounded px-2.5 py-2 text-2xs"
                      style={{
                        backgroundColor: (BUST_COLOR[imdBust.bust_category] ?? '#22c55e') + '18',
                        borderLeft: `3px solid ${BUST_COLOR[imdBust.bust_category] ?? '#22c55e'}`,
                        color: BUST_COLOR[imdBust.bust_category] ?? '#22c55e',
                      }}
                    >
                      {imdBust.recommendation}
                    </div>
                  )}

                  {/* Day-1 warning text */}
                  {imdBust.day_1_warning && (
                    <p className="text-2xs text-ink-muted mb-2">
                      <span className="font-medium">Day 1 Warning:</span> {imdBust.day_1_warning}
                    </p>
                  )}
                </div>
              </div>
            ) : null}

            {/* ── Original model gauge (kept) ── */}
            {risk.error ? (
              <ErrorState message={risk.error} onRetry={reload} />
            ) : r ? (
              <>
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-2xs font-semibold uppercase tracking-wider text-ink-muted">
                    ECMWF Ensemble Hindcast
                  </p>
                  <span className="text-[10px] text-ink-muted" title="Historical baseline scenario for NWP ensemble spread and SHAP attributions">
                    Scenario: {formatDate(r.valid_date)}
                  </span>
                </div>
                <RiskGauge
                  score={imdBust ? imdBust.bust_risk_score : r.risk_score}
                  category={imdBust ? imdBust.bust_category : r.risk_category}
                  forecastConfidence={r.forecast_confidence}
                  horizon={r.forecast_horizon}
                />
                <dl className="mt-3 space-y-1.5 border-t border-edge pt-3 text-2xs">
                  <Row term="Risk category" value={<RiskChip category={imdBust ? imdBust.bust_category : r.risk_category} size="sm" />} />
                  <Row
                    term="Confidence in assessment"
                    value={<span className="tabular">{r.model_confidence.toFixed(0)}%</span>}
                  />
                  <Row term="Synoptic regime" value={<span className="text-right">{r.synoptic.regime}</span>} />
                  <Row term="Valid date" value={formatDate(r.valid_date)} />
                </dl>
              </>
            ) : (
              <LoadingState label="Assessing forecast" rows={4} />
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

      {/* Explanation + ensemble */}
      <div className="grid gap-4 xl:grid-cols-2">
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

      {/* Analogues */}
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

function Row({ term, value }: { term: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-ink-muted">{term}</dt>
      <dd className="font-medium text-ink-primary">{value}</dd>
    </div>
  );
}
