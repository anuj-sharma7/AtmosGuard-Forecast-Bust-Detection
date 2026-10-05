/**
 * Historical replay and 7-day validation.
 *
 * Pick an origin date, form predictions from everything known up to it, then
 * check them against what the IMD record says actually happened. The page is
 * organised around that sequence rather than around the answer: mode first,
 * then the two phases, then the day-by-day result, then the aggregate skill,
 * then the provenance to reproduce any of it.
 *
 * Nothing on this page is simulated. Every observed value is a published IMD
 * measurement, and days the record does not cover are shown as gaps rather
 * than filled.
 */

import { useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../api/client';
import type {
  MonthlyMeta,
  MonthlyReplay,
  StationReplay,
  StationsMeta,
  ReplayAvailability,
  ReplayBacktest,
  ReplayOrigins,
  ReplayRun,
} from '../api/types';
import {
  AuditLog,
  ConfusionMatrix,
  ModeBanner,
  PhaseStrip,
  ProbabilityProfile,
  Provenance,
  ReliabilityDiagram,
  ReplayAttribution,
  ReplayTable,
  SkillByLead,
} from '../components/ReplayPanels';
import { MonthlyReplayPanel } from '../components/MonthlyReplayPanel';
import { StationReplayPanel } from '../components/StationReplayPanel';
import { Badge, EmptyState, ErrorState, LoadingState, Panel } from '../components/Primitives';
import { Metric, MetricStrip } from '../components/RiskCard';
import { useAppState } from '../state/AppState';
import { formatDate } from '../lib/format';
import { RISK_COLORS } from '../lib/risk';
import { saveFile, type DownloadResult } from '../lib/download';

export function HistoricalReplayPage() {
  const { meta, selection, setLocation } = useAppState();

  const [origins, setOrigins] = useState<ReplayOrigins | null>(null);
  const [origin, setOrigin] = useState<string>('');
  const [run, setRun] = useState<ReplayRun | null>(null);
  const [probe, setProbe] = useState<ReplayAvailability | null>(null);
  const [backtest, setBacktest] = useState<ReplayBacktest | null>(null);
  const [selectedPrediction, setSelectedPrediction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveState, setSaveState] = useState<DownloadResult | null>(null);

  /* The two replays answer different questions at different resolutions, so
     they get tabs rather than being stacked - a reader should never be unsure
     which one a number on screen belongs to. */
  const [tab, setTab] = useState<'station' | 'daily' | 'monthly'>('station');

  const [stationsMeta, setStationsMeta] = useState<StationsMeta | null>(null);
  const [stationRun, setStationRun] = useState<StationReplay | null>(null);
  const [stationDate, setStationDate] = useState('2015-08-17');
  const [stationId, setStationId] = useState('IN022021900');
  const [stationBusy, setStationBusy] = useState(false);
  const [stationError, setStationError] = useState<string | null>(null);
  const [monthlyMeta, setMonthlyMeta] = useState<MonthlyMeta | null>(null);
  const [monthly, setMonthly] = useState<MonthlyReplay | null>(null);
  const [monthlyDate, setMonthlyDate] = useState('2015-08-05');
  const [monthlyBusy, setMonthlyBusy] = useState(false);
  const [monthlyError, setMonthlyError] = useState<string | null>(null);

  const locationId = selection?.location_id ?? 'jaipur';

  /* Origins the archive can actually support. Chosen once. */
  useEffect(() => {
    let cancelled = false;
    api
      .replayOrigins()
      .then((response) => {
        if (cancelled) return;
        setOrigins(response);
        setOrigin((current) => current || response.default || '');
      })
      .catch((e) => !cancelled && setError(describe(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  /* The run itself. Re-fetched whenever the origin or the site changes. */
  useEffect(() => {
    if (!origin) return;
    let cancelled = false;
    setBusy(true);
    setError(null);
    Promise.all([api.replayRun(origin, locationId), api.replayAvailability(origin)])
      .then(([runResponse, availability]) => {
        if (cancelled) return;
        setRun(runResponse);
        setProbe(availability);
        setSelectedPrediction(runResponse.predictions[0]?.prediction_id ?? null);
      })
      .catch((e) => {
        if (cancelled) return;
        setRun(null);
        // An origin outside the archive is not an error - it is the answer.
        // Keep the availability probe so the page can explain the gap.
        api
          .replayAvailability(origin)
          .then((availability) => !cancelled && setProbe(availability))
          .catch(() => undefined);
        setError(describe(e));
      })
      .finally(() => !cancelled && setBusy(false));
    return () => {
      cancelled = true;
    };
  }, [origin, locationId]);

  /* Aggregate skill. Independent of the selected origin, so fetched once. */
  useEffect(() => {
    let cancelled = false;
    api
      .replayBacktest()
      .then((response) => !cancelled && setBacktest(response))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (tab !== 'station' || stationsMeta) return;
    let cancelled = false;
    api
      .stationsMeta()
      .then((response) => !cancelled && setStationsMeta(response))
      .catch((e) => !cancelled && setStationError(describe(e)));
    return () => {
      cancelled = true;
    };
  }, [tab, stationsMeta]);

  useEffect(() => {
    if (tab !== 'station') return;
    let cancelled = false;
    setStationBusy(true);
    setStationError(null);
    api
      .stationReplay(stationDate, stationId)
      .then((response) => !cancelled && setStationRun(response))
      .catch((e) => {
        if (cancelled) return;
        setStationRun(null);
        setStationError(describe(e));
      })
      .finally(() => !cancelled && setStationBusy(false));
    return () => {
      cancelled = true;
    };
  }, [tab, stationDate, stationId]);

  useEffect(() => {
    if (tab !== 'monthly' || monthlyMeta) return;
    let cancelled = false;
    api
      .monthlyMeta()
      .then((response) => !cancelled && setMonthlyMeta(response))
      .catch((e) => !cancelled && setMonthlyError(describe(e)));
    return () => {
      cancelled = true;
    };
  }, [tab, monthlyMeta]);

  useEffect(() => {
    if (tab !== 'monthly' || !monthlyDate) return;
    let cancelled = false;
    setMonthlyBusy(true);
    setMonthlyError(null);
    api
      .monthlyReplay(monthlyDate)
      .then((response) => !cancelled && setMonthly(response))
      .catch((e) => {
        if (cancelled) return;
        setMonthly(null);
        setMonthlyError(describe(e));
      })
      .finally(() => !cancelled && setMonthlyBusy(false));
    return () => {
      cancelled = true;
    };
  }, [tab, monthlyDate]);

  const detail = useMemo(
    () => run?.predictions.find((p) => p.prediction_id === selectedPrediction) ?? null,
    [run, selectedPrediction],
  );

  const availability = probe ?? run?.availability ?? null;
  const summary = run?.summary ?? null;

  async function download(kind: 'json' | 'csv') {
    if (!run) return;
    const stamp = `${run.location_id}_${run.origin}`;
    if (kind === 'json') {
      setSaveState(
        await saveFile(
          `atmosguard_replay_${stamp}.json`,
          JSON.stringify(run, null, 2),
          'application/json',
        ),
      );
      return;
    }
    const byId = new Map(run.validations.map((v) => [v.prediction_id, v]));
    const header = [
      'run_id', 'model_version', 'mode', 'origin', 'location_id', 'lead_time',
      'valid_day', 'probability', 'threshold', 'predicted_event',
      'observed_rainfall_mm', 'observed_normal_mm', 'observed_departure_pct',
      'observed_category', 'actual_event', 'outcome', 'evidence_start', 'evidence_end',
    ];
    const lines = run.predictions.map((p) => {
      const v = byId.get(p.prediction_id);
      return [
        run.run_id, run.model_version, run.mode, run.origin, run.location_id, p.lead_time,
        p.valid_day, p.probability.toFixed(6), p.threshold, p.predicted_event,
        v?.observed_rainfall ?? '', v?.observed_normal ?? '', v?.observed_departure_pct ?? '',
        v?.observed_category ?? '', v?.actual_event ?? '', v?.outcome ?? '',
        p.evidence_window[0], p.evidence_window[1],
      ].join(',');
    });
    setSaveState(
      await saveFile(
        `atmosguard_replay_${stamp}.csv`,
        [header.join(','), ...lines].join('\n'),
        'text/csv',
      ),
    );
  }

  if (error && !availability) {
    return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  }

  const retryStationReplay = () => {
    if (!stationsMeta) {
      api.stationsMeta().then(setStationsMeta).catch((e) => setStationError(describe(e)));
    }
    setStationBusy(true);
    setStationError(null);
    api
      .stationReplay(stationDate, stationId)
      .then((res) => setStationRun(res))
      .catch((e) => {
        setStationRun(null);
        setStationError(describe(e));
      })
      .finally(() => setStationBusy(false));
  };

  return (
    <div className="space-y-4">
      {/* -------------------------------- Tabs -------------------------------- */}
      <nav className="panel flex gap-1 p-1" aria-label="Replay resolution">
        {(
          [
            ['station', '7-day replay, 2010–2017', 'Any past date · NOAA station records'],
            ['daily', 'Validation, 2026', '7 days · IMD district archive'],
            ['monthly', 'Monthly replay', '1901–2017 sub-division record'],
          ] as const
        ).map(([id, label, hint]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            aria-current={tab === id ? 'page' : undefined}
            className={`flex-1 rounded px-3 py-2 text-left transition-colors ${
              tab === id ? 'bg-surface-3 text-ink-primary' : 'text-ink-muted hover:bg-surface-2'
            }`}
          >
            <span className="block text-[12px] font-semibold">{label}</span>
            <span className="block text-2xs text-ink-muted">{hint}</span>
          </button>
        ))}
      </nav>

      {tab === 'station' ? (
        <StationReplayPanel
          meta={stationsMeta}
          data={stationRun}
          date={stationDate}
          station={stationId}
          onDateChange={setStationDate}
          onStationChange={setStationId}
          busy={stationBusy}
          error={stationError}
          onRetry={retryStationReplay}
        />
      ) : tab === 'monthly' ? (
        <MonthlyReplayPanel
          meta={monthlyMeta}
          data={monthly}
          date={monthlyDate}
          onDateChange={setMonthlyDate}
          busy={monthlyBusy}
          error={monthlyError}
        />
      ) : (
        <>
      {/* ------------------------------ Controls ------------------------------ */}
      <section className="panel px-4 py-3">
        <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
          <div>
            <label
              htmlFor="replay-origin"
              className="block text-2xs uppercase tracking-[0.08em] text-ink-muted"
            >
              Origin date (T)
            </label>
            <select
              id="replay-origin"
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
              className="mt-1 rounded border border-edge-strong bg-surface-2 px-2.5 py-1.5
                         text-[13px] tabular text-ink-primary focus:border-accent focus:outline-none"
            >
              {origins?.origins.map((d) => (
                <option key={d} value={d}>
                  {formatDate(d)}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              htmlFor="replay-site"
              className="block text-2xs uppercase tracking-[0.08em] text-ink-muted"
            >
              Site
            </label>
            <select
              id="replay-site"
              value={locationId}
              onChange={(event) => setLocation(event.target.value)}
              className="mt-1 rounded border border-edge-strong bg-surface-2 px-2.5 py-1.5
                         text-[13px] text-ink-primary focus:border-accent focus:outline-none"
            >
              {meta.data?.locations.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.name}
                </option>
              ))}
              {meta.data?.regions?.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.name}
                </option>
              ))}
            </select>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => download('csv')}
              disabled={!run?.predictions.length}
              className="rounded border border-edge-strong px-2.5 py-1.5 text-[11px] font-medium
                         text-ink-secondary transition-colors hover:border-accent hover:text-accent
                         disabled:cursor-not-allowed disabled:opacity-40"
            >
              Export CSV
            </button>
            <button
              type="button"
              onClick={() => download('json')}
              disabled={!run?.predictions.length}
              className="rounded border border-edge-strong px-2.5 py-1.5 text-[11px] font-medium
                         text-ink-secondary transition-colors hover:border-accent hover:text-accent
                         disabled:cursor-not-allowed disabled:opacity-40"
            >
              Export JSON
            </button>
            {saveState && saveState !== 'saved' && (
              <span className="text-2xs text-ink-muted">
                {saveState === 'declined'
                  ? 'Save cancelled.'
                  : 'Downloads are unavailable in this view.'}
              </span>
            )}
          </div>
        </div>
        {origins && (
          <p className="mt-2 border-t border-edge pt-2 text-2xs leading-snug text-ink-muted">
            {origins.count} usable origin{origins.count === 1 ? '' : 's'} between{' '}
            <span className="tabular">{origins.archive_start}</span> and{' '}
            <span className="tabular">{origins.archive_end}</span>. {origins.note}
          </p>
        )}
      </section>

      {/* -------------------------------- Modes ------------------------------- */}
      {availability && <ModeBanner availability={availability} />}

      {/* --------------------------- Nothing to run --------------------------- */}
      {availability && !availability.mode_b.available && (
        <Panel
          title="No replay for this origin"
          subtitle="The observational record does not reach this date."
        >
          <EmptyState
            title="Required daily observations are not present"
            detail={availability.mode_b.reason}
          />
          <p className="mt-3 border-t border-edge pt-3 text-[11px] leading-relaxed text-ink-secondary">
            The 1901–2017 sub-division series does cover this period, but it holds{' '}
            <strong className="text-ink-primary">monthly totals</strong>. A month's total cannot be
            divided into days without inventing weather that never happened, so no prediction is
            formed and nothing is shown. Import a published daily file with{' '}
            <code className="text-ink-muted">scripts/import_imd_daily_rainfall.py</code> and this
            origin becomes available.
          </p>
        </Panel>
      )}

      {/* ------------------------------- The run ------------------------------ */}
      {busy && !run && <LoadingState label="Running replay" rows={4} />}

      {run && run.predictions.length > 0 && (
        <>
          <PhaseStrip run={run} />

          {summary && (
            <MetricStrip>
              <Metric label="Days verified" value={summary.verified_days} detail={`of ${run.predictions.length}`} />
              <Metric label="Hits" value={summary.hit} accent={summary.hit > 0 ? RISK_COLORS.LOW : undefined} />
              <Metric label="Misses" value={summary.miss} />
              <Metric label="False alarms" value={summary['false alarm']} />
              <Metric
                label="Hit rate"
                value={summary.hit_rate === null ? '—' : `${(summary.hit_rate * 100).toFixed(0)}%`}
                tip="Share of the events that actually occurred which the model flagged. Undefined when no event occurred in the window."
              />
            </MetricStrip>
          )}

          <Panel
            title={`7-day replay — ${run.location_name}`}
            subtitle={`Predictions formed on ${formatDate(run.origin)} using data up to that day only, set against the published observation for each valid day.`}
            tip={run.event?.definition}
            actions={<Badge tone="accent">Mode B</Badge>}
          >
            <ReplayTable
              predictions={run.predictions}
              validations={run.validations}
              threshold={run.threshold ?? 0.5}
              selected={selectedPrediction}
              onSelect={setSelectedPrediction}
            />
            {summary && (
              <p className="mt-3 border-t border-edge pt-2.5 text-2xs leading-snug text-ink-muted">
                {summary.note}
              </p>
            )}
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel
              title="Probability against outcome"
              subtitle="How the model's confidence ran across the seven days, and what happened."
              unit="%"
            >
              <ProbabilityProfile
                predictions={run.predictions}
                validations={run.validations}
                threshold={run.threshold ?? 0.5}
              />
            </Panel>

            <Panel
              title={detail ? `Why Day ${detail.lead_time}` : 'Attribution'}
              subtitle="Which predictors pushed this probability up, and which pulled it down. Select a row above to change the day."
              tip="Positive contributions raise the log-odds of an event; negative ones lower it."
            >
              {detail ? (
                <ReplayAttribution
                  contributions={detail.contributions}
                  baseValue={detail.base_value}
                  probability={detail.probability}
                />
              ) : (
                <EmptyState title="Select a day" detail="Pick a row in the replay table." />
              )}
            </Panel>
          </div>
        </>
      )}

      {/* ------------------------------ Backtest ------------------------------ */}
      {backtest && (
        <>
          <Panel
            title="Walk-forward backtest"
            subtitle={`Every usable origin, every site, every lead — ${backtest.counts.prediction_outcome_pairs.toLocaleString()} prediction-outcome pairs across ${backtest.window.origin_count} origins.`}
            tip="The origin advances one day at a time and never looks beyond itself. Each origin's predictions are formed before any of its outcomes are read."
          >
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded border border-edge bg-surface-2 px-3 py-2.5">
                <p className="text-2xs uppercase tracking-[0.08em] text-ink-muted">
                  Out-of-sample ROC-AUC
                </p>
                <p className="mt-1 text-2xl font-semibold tabular text-ink-primary">
                  {backtest.out_of_sample?.roc_auc?.toFixed(3) ?? '—'}
                </p>
                <p className="mt-0.5 text-2xs text-ink-muted">
                  Origins the model never saw. This is the number that means something.
                </p>
              </div>
              <div className="rounded border border-edge bg-surface-2 px-3 py-2.5">
                <p className="text-2xs uppercase tracking-[0.08em] text-ink-muted">
                  All-origins ROC-AUC
                </p>
                <p className="mt-1 text-2xl font-semibold tabular text-ink-secondary">
                  {backtest.overall.roc_auc?.toFixed(3) ?? '—'}
                </p>
                <p className="mt-0.5 text-2xs text-ink-muted">
                  Includes origins used for fitting, so it flatters the model.
                </p>
              </div>
              <div className="rounded border border-edge bg-surface-2 px-3 py-2.5">
                <p className="text-2xs uppercase tracking-[0.08em] text-ink-muted">Brier score</p>
                <p className="mt-1 text-2xl font-semibold tabular text-ink-secondary">
                  {backtest.overall.brier.toFixed(3)}
                </p>
                <p className="mt-0.5 text-2xs text-ink-muted">
                  Base rate {((backtest.overall.confusion.base_rate ?? 0) * 100).toFixed(1)}% — the
                  bar a constant forecast would clear.
                </p>
              </div>
            </div>
            <p className="mt-3 border-t border-edge pt-2.5 text-[11px] leading-relaxed text-ink-secondary">
              {backtest.honesty_note}
            </p>
            <p className="mt-2 text-2xs leading-relaxed text-ink-muted">{backtest.caveat}</p>
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel
              title="Confusion matrix"
              subtitle={`At the fixed 0.50 threshold, across all ${backtest.counts.prediction_outcome_pairs.toLocaleString()} verified pairs.`}
              tip="The threshold was fixed at 0.50 before any evaluation and was never tuned on the held-out origins."
            >
              <ConfusionMatrix
                confusion={backtest.overall.confusion}
                caption={`${backtest.counts.skipped_no_observation.toLocaleString()} further prediction${
                  backtest.counts.skipped_no_observation === 1 ? '' : 's'
                } fell on days the observational record does not cover. They are counted here and scored nowhere.`}
              />
            </Panel>

            <Panel
              title="Calibration"
              subtitle="Does a stated 40% actually happen about 40% of the time?"
              tip="Discrimination and calibration are different properties. A model can rank cases well and still state the wrong probability."
            >
              <ReliabilityDiagram bins={backtest.overall.reliability} />
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel
              title="Skill by lead time"
              subtitle="ROC-AUC at each forecast range."
              tip="Predictability decays with lead time. A profile that does not decay is a warning sign, not a good result."
            >
              <SkillByLead rows={backtest.by_lead} />
            </Panel>

            <Panel
              title="Skill by sub-division"
              subtitle="Where the model works, and where it does not."
              tip="Sub-divisions with fewer than 40 verified pairs are omitted rather than reported on thin evidence."
            >
              {backtest.by_subdivision.length ? (
                <div className="-mx-4 max-h-64 overflow-auto px-4">
                  <table className="w-full border-collapse text-[11px]">
                    <thead className="sticky top-0 bg-surface-1">
                      <tr className="border-b border-edge-strong text-left text-2xs uppercase tracking-[0.08em] text-ink-muted">
                        <th className="py-1.5 pr-3 font-medium">Sub-division</th>
                        <th className="py-1.5 pr-3 text-right font-medium">n</th>
                        <th className="py-1.5 pr-3 text-right font-medium">Events</th>
                        <th className="py-1.5 text-right font-medium">ROC-AUC</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...backtest.by_subdivision]
                        .sort((a, b) => (b.roc_auc ?? 0) - (a.roc_auc ?? 0))
                        .map((row) => (
                          <tr key={row.subdivision} className="border-b border-edge">
                            <td className="py-1.5 pr-3 text-ink-secondary">{row.subdivision}</td>
                            <td className="py-1.5 pr-3 text-right tabular text-ink-muted">
                              {row.count}
                            </td>
                            <td className="py-1.5 pr-3 text-right tabular text-ink-muted">
                              {row.events}
                            </td>
                            <td
                              className={`py-1.5 text-right tabular font-medium ${
                                (row.roc_auc ?? 0) >= 0.5 ? 'text-ink-primary' : 'text-risk-severe'
                              }`}
                            >
                              {row.roc_auc?.toFixed(3) ?? '—'}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState
                  title="Not enough verified pairs per sub-division"
                  detail="Extend the daily record to break skill down by region."
                />
              )}
            </Panel>
          </div>
        </>
      )}

      {/* ---------------------------- Provenance ------------------------------ */}
      {run && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel
            title="Run provenance"
            subtitle="Everything needed to reproduce this run exactly."
          >
            <Provenance run={run} />
          </Panel>
          <Panel
            title="Audit log"
            subtitle="What each phase was permitted to read, in the order it ran."
            tip="The separation is enforced in code: the prediction phase holds an archive that raises on any read past the origin."
          >
            <AuditLog run={run} />
          </Panel>
        </div>
      )}
        </>
      )}
    </div>
  );
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : 'Replay failed';
}

