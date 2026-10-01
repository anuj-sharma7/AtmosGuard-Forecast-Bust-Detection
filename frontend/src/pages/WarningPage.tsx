/** IMD-style state warning map for forecast reliability. */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { StateWarning, WarningsResponse } from '../api/types';
import { WarningMap } from '../components/WarningMap';
import { ErrorState, LoadingState, Panel } from '../components/Primitives';
import { Metric, MetricStrip } from '../components/RiskCard';
import { useAppState } from '../state/AppState';
import { formatDate } from '../lib/format';

export function WarningPage() {
  const { selection, meta, setHorizon, setLocation } = useAppState();
  const navigate = useNavigate();
  const [data, setData] = useState<WarningsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selection) return;
    let cancelled = false;
    setError(null);
    api
      .warnings(selection)
      .then((response) => {
        if (!cancelled) setData(response);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load warnings');
      });
    return () => {
      cancelled = true;
    };
  }, [selection?.horizon, selection?.model_id, selection?.base_date]); // eslint-disable-line react-hooks/exhaustive-deps

  const openState = (warning: StateWarning) => {
    const site = [...(meta.data?.locations ?? []), ...(meta.data?.regions ?? [])].find(
      (s) => s.name === warning.worst_site,
    );
    if (site) {
      setLocation(site.id);
      navigate('/analysis');
    }
  };

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;

  return (
    <div className="space-y-4">
      <MetricStrip>
        <Metric
          label="Warning"
          value={data ? data.counts.Warning : '--'}
          detail="states, forecast unreliable"
          accent="#e31a1c"
          loading={!data}
        />
        <Metric
          label="Alert"
          value={data ? data.counts.Alert : '--'}
          detail="treat with caution"
          accent="#f58220"
          loading={!data}
        />
        <Metric
          label="Watch"
          value={data ? data.counts.Watch : '--'}
          detail="worth monitoring"
          accent="#d4bd12"
          loading={!data}
        />
        <Metric
          label="No warning"
          value={data ? data.counts['No Warning'] : '--'}
          detail="forecast dependable"
          accent="#1a9641"
          loading={!data}
        />
        <Metric
          label="Valid"
          value={data ? `Day ${data.horizon}` : '--'}
          detail={data ? formatDate(data.valid_date) : undefined}
        />
      </MetricStrip>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_330px]">
        <Panel
          title="Forecast reliability by state"
          subtitle={
            data
              ? `Day ${data.horizon} rainfall - ${data.state_count} states monitored`
              : 'Loading'
          }
          tip="Each state takes the level of its least reliable monitoring site: an unreliable forecast somewhere in a state should not be averaged away by dependable ones elsewhere."
          actions={
            <div className="flex flex-wrap gap-1">
              {(meta.data?.horizons ?? []).map((h) => (
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
            </div>
          }
        >
          {data ? (
            <WarningMap data={data} height={560} onSelectState={openState} />
          ) : (
            <LoadingState label="Building warning map" rows={5} />
          )}
        </Panel>

        <Panel
          title="States by level"
          subtitle="Worst first"
          bodyClassName="px-2 py-2"
        >
          {data ? (
            <ul className="max-h-[620px] space-y-1 overflow-auto">
              {[...data.states]
                .sort((a, b) => b.risk_score - a.risk_score)
                .map((state) => (
                  <li key={state.state}>
                    <button
                      type="button"
                      onClick={() => openState(state)}
                      className="flex w-full items-start gap-2.5 rounded px-2 py-1.5 text-left transition-colors hover:bg-surface-2"
                    >
                      <span
                        className="mt-1 h-3 w-3 shrink-0 rounded-[2px] border border-black/30"
                        style={{ background: state.color }}
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs text-ink-primary">
                          {state.state}
                        </span>
                        <span className="block truncate text-2xs text-ink-muted">
                          {state.driver}
                          {state.hazards.length > 0 && ` · ${state.hazards.join(' · ')}`}
                        </span>
                      </span>
                      <span className="shrink-0 text-xs font-semibold tabular text-ink-secondary">
                        {state.risk_score.toFixed(0)}%
                      </span>
                    </button>
                  </li>
                ))}
            </ul>
          ) : (
            <LoadingState rows={6} />
          )}
        </Panel>
      </div>
    </div>
  );
}
