/** Risk-model verification: how well does the bust-risk score actually work? */

import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { VerificationResponse } from '../api/types';
import {
  BandReliability,
  ErrorScatter,
  ErrorDistribution,
  ForecastVsObservation,
  ReliabilityChart,
  RocChart,
} from '../components/VerificationChart';
import { Badge, ErrorState, LoadingState, Panel } from '../components/Primitives';
import { Metric, MetricStrip } from '../components/RiskCard';
import { useAppState } from '../state/AppState';
import { formatDate } from '../lib/format';

export function VerificationPage() {
  const { selection, risk } = useAppState();
  const [data, setData] = useState<VerificationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selection) return;
    let cancelled = false;
    setError(null);
    api
      .modelVerification(selection.base_date)
      .then((response) => {
        if (!cancelled) setData(response);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load verification');
      });
    return () => {
      cancelled = true;
    };
  }, [selection?.base_date]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;

  const perf = data?.model_performance;

  return (
    <div className="space-y-4">
      <section className="panel px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="accent">Fitted on real IMD observations</Badge>
          <p className="text-2xs leading-relaxed text-ink-muted">
            Every number here is computed at request time - none are hard-coded. The model is a
            logistic regression fitted on real IMD district rainfall observations, and the headline
            score below is <span className="text-ink-secondary">held out</span> on a temporal split:
            earlier dates train, later dates test. A random split would leak, because neighbouring
            days share a weather system.
          </p>
        </div>
      </section>

      <MetricStrip>
        <Metric
          label="ROC-AUC (held out)"
          value={perf ? perf.model.training.roc_auc_holdout.toFixed(3) : '--'}
          detail={
            perf?.model.training.roc_auc_ablated
              ? `${perf.model.training.roc_auc_ablated.toFixed(3)} without ensemble predictors`
              : perf
                ? `${perf.roc_auc.toFixed(3)} in sample - 0.5 is a coin flip`
                : undefined
          }
          tip="Probability that a randomly chosen forecast that busted scored higher than one that did not. The held-out figure is measured on dates the model never saw."
          accent="#3987e5"
          loading={!perf}
        />
        <Metric
          label="Precision"
          value={perf ? perf.precision.toFixed(2) : '--'}
          detail="of alerts raised, share that busted"
          tip="True positives divided by all forecasts flagged. Low precision means false alarms."
          accent="#199e70"
          loading={!perf}
        />
        <Metric
          label="Recall"
          value={perf ? perf.recall.toFixed(2) : '--'}
          detail="of busts, share that was flagged"
          tip="True positives divided by all forecasts that actually busted. Low recall means missed busts."
          accent="#199e70"
          loading={!perf}
        />
        <Metric
          label="F1 score"
          value={perf ? perf.f1.toFixed(2) : '--'}
          detail="harmonic mean of the two"
          accent="#199e70"
          loading={!perf}
        />
        <Metric
          label="Brier score"
          value={perf ? perf.brier_score.toFixed(3) : '--'}
          detail="lower is better"
          tip="Mean squared error of the probability forecast. It rewards being both accurate and honestly calibrated."
          accent="#38bdf8"
          loading={!perf}
        />
      </MetricStrip>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel
          title="What each risk band means"
          subtitle="Share of forecasts in each band that went on to bust"
          tip="The bust-risk score is a 0-100 risk index, not a raw probability. This panel is what the bands mean in practice, measured on the dataset."
        >
          {perf ? (
            <BandReliability
              bands={perf.band_reliability}
              interpretation={perf.score_interpretation}
            />
          ) : (
            <LoadingState rows={4} />
          )}
        </Panel>

        <Panel
          title="ROC curve"
          subtitle="Separation between forecasts that busted and those that did not"
          tip="Each point is a different alert threshold, trading missed busts against false alarms."
        >
          {perf ? <RocChart roc={perf.roc_curve} auc={perf.roc_auc} /> : <LoadingState rows={5} />}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel
          title="Index against observed frequency"
          subtitle="Mean risk index per decile, against the bust rate in that decile"
          tip="The dashed diagonal is where a literal probability would sit. The index runs above it by construction - it ranks risk rather than estimating a frequency - and what matters is that the curve rises monotonically."
        >
          {perf ? <ReliabilityChart reliability={perf.reliability} /> : <LoadingState rows={5} />}
        </Panel>

        <Panel
          title="Contingency at the alert threshold"
          subtitle={perf ? `Operating point ${(perf.operating_threshold * 100).toFixed(0)}% bust risk` : undefined}
          tip="How the alert threshold performs: hits, misses, false alarms and correct negatives."
        >
          {perf ? (
            <>
              <ErrorScatter perf={perf} />
              <dl className="mt-2 grid grid-cols-3 gap-2 text-2xs">
                <Stat label="Sample size" value={perf.sample_size.toLocaleString()} />
                <Stat label="Bust base rate" value={`${(perf.base_rate * 100).toFixed(1)}%`} />
                <Stat label="Accuracy" value={perf.accuracy.toFixed(2)} />
              </dl>
            </>
          ) : (
            <LoadingState rows={4} />
          )}
        </Panel>

        <Panel
          title="Forecast verification"
          subtitle={
            risk.data
              ? `${risk.data.location.name} - Day 5 ${risk.data.variable.label.toLowerCase()}`
              : undefined
          }
          tip="The other kind of verification: how the weather forecast itself performed, independent of the risk model."
          unit={risk.data?.variable.unit}
        >
          {risk.data ? (
            <>
              <ForecastVsObservation verification={risk.data.verification} height={180} />
              <p className="mb-1 mt-3 text-2xs font-medium uppercase tracking-wider text-ink-muted">
                Forecast error - red bars are classified busts
              </p>
              <ErrorDistribution verification={risk.data.verification} height={150} />
            </>
          ) : (
            <LoadingState rows={4} />
          )}
        </Panel>
      </div>

      {perf && (
        <Panel title="Model card" subtitle={`${perf.model.name} v${perf.model.version}`}>
          {perf.model.comparison && perf.model.comparison.length > 1 && (
            <div className="mb-4">
              <p className="mb-2 text-2xs font-medium uppercase tracking-wider text-ink-muted">
                Estimators compared — held out on a temporal split
              </p>
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="border-b border-edge text-left text-2xs uppercase tracking-wider text-ink-muted">
                    <th scope="col" className="pb-1.5 pr-3 font-medium">Model</th>
                    <th scope="col" className="pb-1.5 pr-3 font-medium">Train</th>
                    <th scope="col" className="pb-1.5 pr-3 font-medium">Held out</th>
                    <th scope="col" className="pb-1.5 font-medium">Brier</th>
                  </tr>
                </thead>
                <tbody>
                  {[...perf.model.comparison]
                    .sort((a, b) => b.roc_auc_holdout - a.roc_auc_holdout)
                    .map((row) => {
                      const selected = perf.model.name.endsWith(row.model);
                      return (
                        <tr key={row.model} className="border-b border-edge/60 last:border-0">
                          <td className="py-1.5 pr-3">
                            <span className={selected ? 'font-semibold text-accent' : 'text-ink-secondary'}>
                              {row.model.replace(/_/g, ' ')}
                            </span>
                            {selected && (
                              <span className="ml-1.5 text-2xs text-ink-muted">selected</span>
                            )}
                          </td>
                          <td className="py-1.5 pr-3 tabular text-ink-muted">
                            {row.roc_auc_train.toFixed(3)}
                          </td>
                          <td className="py-1.5 pr-3 tabular font-semibold text-ink-primary">
                            {row.roc_auc_holdout.toFixed(3)}
                          </td>
                          <td className="py-1.5 tabular text-ink-secondary">
                            {row.brier_holdout.toFixed(3)}
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
              <p className="mt-1.5 text-2xs leading-relaxed text-ink-muted">
                A tree ensemble must beat the logistic baseline by a real margin to be
                selected — otherwise the extra opacity is not worth it. The train/held-out
                gap is the honest measure of how much each model memorised.
              </p>
            </div>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="mb-2 text-2xs font-medium uppercase tracking-wider text-ink-muted">
                Predictor influence (fitted)
              </p>
              <ul className="space-y-1.5">
                {Object.entries(perf.model.weights)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 12)
                  .map(([name, weight]) => (
                  <li key={name} className="flex items-center gap-2.5 text-2xs">
                    <span className="w-44 shrink-0 capitalize text-ink-secondary">
                      {name.replace(/_/g, ' ')}
                    </span>
                    <span className="h-2 flex-1 overflow-hidden rounded-sm bg-surface-2">
                      <span
                        className="block h-full rounded-sm bg-series-1"
                        style={{ width: `${Math.min(100, weight * 700)}%` }}
                      />
                    </span>
                    <span className="w-10 shrink-0 text-right font-semibold tabular text-ink-primary">
                      {(weight * 100).toFixed(0)}%
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <dl className="space-y-2 text-2xs">
              <Field term="Estimator" value={perf.model.kind} />
              {perf.model.predictors !== undefined && (
                <Field term="Predictors" value={String(perf.model.predictors)} />
              )}
              {perf.model.contribution_kind && (
                <Field term="Attributions" value={perf.model.contribution_kind} />
              )}
              <Field term="Training data" value={perf.model.training.source} />
              <Field
                term="Train / test"
                value={`${perf.model.training.train_rows.toLocaleString()} / ${perf.model.training.test_rows.toLocaleString()} (temporal)`}
              />
              <Field
                term="ROC-AUC train / held out"
                value={`${perf.model.training.roc_auc_train.toFixed(3)} / ${perf.model.training.roc_auc_holdout.toFixed(3)}`}
              />
              <Field term="Explanation method" value={perf.model.explanation_method} />
              <Field term="Evaluated on" value={selection ? formatDate(selection.base_date) : '--'} />
              {perf.model.ablation_note && (
                <div className="rounded-md border border-risk-moderate/45 bg-risk-moderate/10 p-2.5">
                  <p className="mb-1 font-semibold text-risk-moderate">
                    Read the headline score with this
                  </p>
                  <p className="leading-relaxed text-ink-secondary">{perf.model.ablation_note}</p>
                  {perf.model.training.roc_auc_ablated !== undefined && (
                    <p className="mt-1.5 tabular text-ink-muted">
                      Ceiling {perf.model.training.roc_auc_holdout.toFixed(3)} · floor{' '}
                      {perf.model.training.roc_auc_ablated.toFixed(3)}
                    </p>
                  )}
                </div>
              )}
              <div className="rounded-md border border-risk-moderate/40 bg-risk-moderate/8 p-2.5">
                <p className="leading-relaxed text-ink-secondary">{perf.model.notice}</p>
              </div>
            </dl>
          </div>
        </Panel>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-edge bg-surface-2/55 px-2.5 py-2">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-sm font-bold tabular text-ink-primary">{value}</dd>
    </div>
  );
}

function Field({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-ink-muted">{term}</dt>
      <dd className="text-right font-medium text-ink-primary">{value}</dd>
    </div>
  );
}
