/**
 * Forecast analysis workbench.
 *
 * Three columns: what you are looking at (left), the forecast itself (centre),
 * and the risk assessment with its reasoning (right).
 */

import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { ClimateProfile } from '../api/types';

import { AnaloguePanel } from '../components/AnaloguePanel';
import { ClimatePanel } from '../components/ClimatePanel';
import { DemoScenarios } from '../components/DemoScenarios';
import { EnsembleSpreadChart } from '../components/EnsembleSpreadChart';
import { ForecastSelector } from '../components/ForecastSelector';
import { LocationSearch } from '../components/LocationSearch';
import { ModelComparison } from '../components/ModelComparison';
import { ReportExport } from '../components/ReportExport';
import { RiskGauge } from '../components/RiskGauge';
import { ShapExplanation } from '../components/ShapExplanation';
import { ForecastVsObservation } from '../components/VerificationChart';
import { ErrorState, LoadingState, Panel, RiskChip } from '../components/Primitives';
import { useAppState } from '../state/AppState';
import { formatDate, formatValue } from '../lib/format';
import { RISK_DEFINITION } from '../lib/risk';

export function ForecastAnalysis() {
  const { risk, selection, reload } = useAppState();
  const [reportOpen, setReportOpen] = useState(false);
  const [climate, setClimate] = useState<ClimateProfile | null>(null);
  const r = risk.data;

  // Climate context follows the selected location, not the forecast, so it is
  // fetched separately and keyed on the site rather than the whole selection.
  useEffect(() => {
    if (!selection?.location_id) return;
    let cancelled = false;
    setClimate(null);
    api
      .climate(selection.location_id)
      .then((data) => {
        if (!cancelled) setClimate(data);
      })
      .catch(() => {
        if (!cancelled) setClimate(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selection?.location_id]);

  return (
    <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)_380px]">
      {/* Left: selection */}
      <div className="space-y-4">
        <Panel title="Location" subtitle="Search or pick from the map">
          <LocationSearch />
        </Panel>
        <Panel title="Forecast parameters">
          <ForecastSelector />
        </Panel>
        <Panel title="Demo scenarios" subtitle="Curated cases covering each risk band">
          <DemoScenarios />
        </Panel>
        {r && (
          <Panel title="Initialisation">
            <dl className="space-y-1.5 text-2xs">
              <Row term="Base date" value={formatDate(r.base_date)} />
              <Row term="Valid date" value={formatDate(r.valid_date)} />
              <Row term="Model" value={r.model.label} />
              <Row term="Centre" value={r.model.centre} />
              <Row term="Members" value={String(r.ensemble.member_count)} />
            </dl>
          </Panel>
        )}
      </div>

      {/* Centre: the forecast */}
      <div className="space-y-4">
        {risk.error ? (
          <ErrorState message={risk.error} onRetry={reload} />
        ) : !r ? (
          <Panel title="Forecast">
            <LoadingState label="Loading forecast" rows={6} />
          </Panel>
        ) : (
          <>
            <Panel
              title="Ensemble forecast"
              subtitle={`${r.location.name} - Day 1 to Day 7 - ${r.variable.label}`}
              tip="Every ensemble member is a plausible evolution of the atmosphere. Where they agree, the forecast is trustworthy; where they fan apart, it is not."
              unit={r.variable.unit}
              updated={formatDate(r.base_date)}
            >
              <EnsembleSpreadChart ensemble={r.ensemble} horizon={r.forecast_horizon} height={340} />
            </Panel>

            <Panel
              title="NWP model comparison"
              subtitle={`Deterministic runs at Day ${r.forecast_horizon}`}
              tip="When independent modelling centres disagree, the atmosphere is in a state that is genuinely hard to predict - not just one model having a bad run."
            >
              <ModelComparison
                rows={r.model_comparison.rows}
                disagreement={r.model_comparison.disagreement}
                message={r.model_comparison.message}
                spreadBetweenModels={r.model_comparison.spread_between_models}
                unit={r.variable.unit}
              />
            </Panel>

            <Panel
              title="Run-to-run consistency"
              subtitle={`Successive initialisations forecasting ${formatDate(r.valid_date)}`}
              tip="A forecast that keeps changing between model runs has not settled. Persistence is one of the strongest bust precursors."
            >
              <ul className="grid gap-2 sm:grid-cols-4">
                {r.persistence_history.map((h) => (
                  <li key={h.init_date} className="rounded-md border border-edge bg-surface-2/55 p-2.5">
                    <p className="text-2xs text-ink-muted">Run of {formatDate(h.init_date)}</p>
                    <p className="mt-0.5 text-sm font-bold tabular text-ink-primary">
                      {formatValue(h.value, r.variable.unit)}
                    </p>
                    <p className="text-2xs text-ink-muted">at Day {h.lead_time}</p>
                  </li>
                ))}
              </ul>
            </Panel>

            <Panel
              title="Climate context"
              subtitle={
                climate
                  ? `${climate.subdivision} - ${climate.record.start} to ${climate.record.end}`
                  : 'Loading the long record'
              }
              tip="What normal looks like here across 117 years of IMD records, and whether it is shifting. A forecast is only unusual relative to this."
              unit="mm"
            >
              {climate ? <ClimatePanel profile={climate} /> : <LoadingState rows={5} />}
            </Panel>

            <Panel
              title="Forecast verification"
              subtitle="Rolling Day 5 forecast against observed / reanalysis"
              tip="How this location's Day 5 forecasts have performed against the observed record."
              unit={r.variable.unit}
              actions={
                <span
                  className={`rounded border px-1.5 py-0.5 text-2xs font-medium ${
                    r.observation_source.real
                      ? 'border-risk-low/45 bg-risk-low/10 text-risk-low'
                      : 'border-risk-moderate/45 bg-risk-moderate/10 text-risk-moderate'
                  }`}
                  title={r.observation_source.verified_against}
                >
                  {r.observation_source.real ? 'Real IMD observations' : 'Reconstructed truth'}
                </span>
              }
            >
              <ForecastVsObservation verification={r.verification} />
              <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                <Metric label="RMSE" value={`${r.verification.metrics.rmse.toFixed(1)} ${r.variable.unit}`} />
                <Metric label="MAE" value={`${r.verification.metrics.mae.toFixed(1)} ${r.variable.unit}`} />
                <Metric label="Bias" value={`${r.verification.metrics.bias > 0 ? '+' : ''}${r.verification.metrics.bias.toFixed(1)}`} />
                <Metric label="ACC" value={r.verification.metrics.acc.toFixed(2)} />
                <Metric label="Skill vs climatology" value={`${(r.verification.metrics.skill * 100).toFixed(0)}%`} />
              </dl>
              {r.verification.metrics.reference && (
                <p className="mt-2 text-2xs text-ink-muted">
                  Skill and anomaly correlation are measured against the{' '}
                  {r.verification.metrics.reference}.
                </p>
              )}
            </Panel>
          </>
        )}
      </div>

      {/* Right: the assessment */}
      <div className="space-y-4">
        <Panel
          title="Bust risk"
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
          {r ? (
            <>
              <RiskGauge
                score={r.risk_score}
                category={r.risk_category}
                forecastConfidence={r.forecast_confidence}
                horizon={r.forecast_horizon}
              />
              <dl className="mt-3 space-y-1.5 border-t border-edge pt-3 text-2xs">
                <Row term="Category" value={<RiskChip category={r.risk_category} size="sm" />} />
                <Row term="Confidence in assessment" value={`${r.model_confidence.toFixed(0)}%`} />
                <Row term="Regime now" value={r.synoptic.regime} />
                <Row term="Transitioning to" value={r.synoptic.next_regime} />
              </dl>
            </>
          ) : (
            <LoadingState rows={4} />
          )}
        </Panel>

        <Panel
          title="Why is this forecast at risk?"
          tip="Each bar shows how far a driver sits from its dataset average, weighted by its importance in the model."
        >
          {r ? (
            <ShapExplanation
              contributions={r.feature_contributions}
              explanation={r.explanation}
              method={r.explanation_method}
              label={r.explanation_label}
            />
          ) : (
            <LoadingState rows={6} />
          )}
        </Panel>

        <Panel title="Historical analogues" subtitle="Similar patterns, known outcomes">
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
      </div>

      {reportOpen && r && <ReportExport risk={r} onClose={() => setReportOpen(false)} />}
      {!selection && null}
    </div>
  );
}

function Row({ term, value }: { term: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-ink-muted">{term}</dt>
      <dd className="text-right font-medium text-ink-primary">{value}</dd>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-edge bg-surface-2/55 px-2.5 py-2">
      <dt className="text-2xs text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-sm font-bold tabular text-ink-primary">{value}</dd>
    </div>
  );
}
