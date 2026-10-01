/** Data pipeline and system status. */

import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { SourcesResponse, SystemStatus } from '../api/types';
import { DataSources, Pipeline } from '../components/SystemPipeline';
import { LiveImdPanel } from '../components/LiveImdPanel';
import { Badge, ErrorState, LoadingState, Panel } from '../components/Primitives';
import { useAppState } from '../state/AppState';
import { formatDate } from '../lib/format';

export function SystemPage() {
  const { selection } = useAppState();
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [sources, setSources] = useState<SourcesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .sources()
      .then((data) => {
        if (!cancelled) setSources(data);
      })
      .catch(() => {
        if (!cancelled) setSources(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selection) return;
    let cancelled = false;
    api
      .systemStatus(selection.base_date)
      .then((data) => {
        if (!cancelled) setStatus(data);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load system status');
      });
    return () => {
      cancelled = true;
    };
  }, [selection?.base_date]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;

  return (
    <div className="space-y-4">
      <LiveImdPanel />
      {sources && <SourceCatalogue data={sources} />}
      <div className="grid gap-4 xl:grid-cols-2">
      <div className="space-y-4">
        <Panel
          title="Data sources"
          subtitle="Forecast and verification inputs"
          tip="In demonstration mode the NWP feeds are simulated. The reanalysis archive backs verification and the analogue search."
        >
          {status ? <DataSources sources={status.sources} /> : <LoadingState rows={4} />}
        </Panel>

        <Panel title="Runtime" subtitle="Current configuration">
          {status ? (
            <dl className="space-y-2 text-2xs">
              <Field term="Data mode" value={status.data_mode} />
              <Field term="Reference initialisation" value={formatDate(status.reference_date)} />
              <Field term="Ensemble members" value={String(status.ensemble_members)} />
              <Field term="Database engine" value={status.database} />
              <Field term="Risk model" value={`${status.model.name} v${status.model.version}`} />
            </dl>
          ) : (
            <LoadingState rows={4} />
          )}
        </Panel>
      </div>

      <Panel
        title="Inference pipeline"
        subtitle="Data ingestion through to alerting"
        tip="Each stage is a replaceable component. Swapping the simulated provider for real NetCDF/GRIB ingestion changes only the first two stages."
      >
        {status ? (
          <>
            <Pipeline pipeline={status.pipeline} />
            <div className="mt-4 rounded-md border border-risk-moderate/40 bg-risk-moderate/8 p-3">
              <Badge tone="warn">Baseline model in use</Badge>
              <p className="mt-1.5 text-2xs leading-relaxed text-ink-secondary">
                {status.model.notice}
              </p>
            </div>
          </>
        ) : (
          <LoadingState rows={6} />
        )}
      </Panel>
      </div>
    </div>
  );
}

const ACCESS_LABEL: Record<string, string> = {
  open: 'Open',
  key: 'Free API key',
  account: 'Free account',
  restricted: 'By request',
};

/**
 * The data catalogue.
 *
 * Status is the point of this panel: only datasets physically present and read
 * by the system say "in use". Everything else is a documented route, and saying
 * so plainly is the difference between a data pipeline and a wish list.
 */
function SourceCatalogue({ data }: { data: SourcesResponse }) {
  const inUse = new Set(data.in_use);
  const ordered = [...data.sources].sort(
    (a, b) => Number(inUse.has(b.id)) - Number(inUse.has(a.id)),
  );

  return (
    <Panel
      title="Data sources"
      subtitle={`${data.sources.length} catalogued - ${data.in_use.length} in use`}
      tip="Where every dataset comes from, what it licenses, and which part of the system it feeds."
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-edge text-left text-2xs uppercase tracking-wider text-ink-muted">
              <th scope="col" className="pb-2 pr-3 font-medium">Dataset</th>
              <th scope="col" className="pb-2 pr-3 font-medium">Agency</th>
              <th scope="col" className="pb-2 pr-3 font-medium">Coverage</th>
              <th scope="col" className="pb-2 pr-3 font-medium">Access</th>
              <th scope="col" className="pb-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((source) => (
              <tr key={source.id} className="border-b border-edge/60 last:border-0 align-top">
                <td className="py-2.5 pr-3">
                  <a
                    href={source.portal}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="font-medium text-accent hover:underline"
                  >
                    {source.name}
                  </a>
                  <p className="mt-0.5 max-w-md text-2xs leading-snug text-ink-muted">
                    {source.role}
                  </p>
                </td>
                <td className="py-2.5 pr-3 text-2xs text-ink-secondary">
                  {source.agency}
                  <span className="block text-ink-muted">{source.country}</span>
                </td>
                <td className="py-2.5 pr-3 text-2xs text-ink-secondary">
                  {source.resolution}
                  <span className="block text-ink-muted">{source.fmt}</span>
                </td>
                <td className="py-2.5 pr-3 text-2xs text-ink-secondary">
                  {ACCESS_LABEL[source.access] ?? source.access}
                </td>
                <td className="py-2.5">
                  {inUse.has(source.id) ? (
                    <span className="inline-flex items-center gap-1 rounded border border-risk-low/45 bg-risk-low/10 px-1.5 py-0.5 text-2xs font-semibold text-risk-low">
                      in use
                    </span>
                  ) : (
                    <span className="text-2xs text-ink-muted">documented route</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-2xs leading-relaxed text-ink-muted">{data.note}</p>
    </Panel>
  );
}

function Field({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-ink-muted">{term}</dt>
      <dd className="text-right font-medium capitalize text-ink-primary">{value}</dd>
    </div>
  );
}
