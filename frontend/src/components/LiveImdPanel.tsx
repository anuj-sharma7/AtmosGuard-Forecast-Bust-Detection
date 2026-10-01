/**
 * Live IMD city-forecast feed.
 *
 * Answers one question on sight: is real IMD data flowing right now, and if
 * not, what exactly needs fixing? Every state but "connected" shows an empty
 * table and the reason - never stand-in numbers - because a panel that quietly
 * filled itself with demonstration data would look connected when it was not.
 */

import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { ImdLiveState, ImdLiveStatus } from '../api/types';
import { Badge, Panel } from './Primitives';

const STATE_LABEL: Record<ImdLiveState, { label: string; tone: 'accent' | 'warn' | 'neutral' }> = {
  connected: { label: 'Connected — live IMD data', tone: 'accent' },
  not_configured: { label: 'Not configured', tone: 'neutral' },
  needs_probe: { label: 'Key set — run --probe', tone: 'warn' },
  unreachable: { label: 'IMD unreachable', tone: 'warn' },
  rejected: { label: 'Refused by IMD', tone: 'warn' },
  error: { label: 'IMD error', tone: 'warn' },
  unrecognised: { label: 'Response not recognised', tone: 'warn' },
  static: { label: 'Static preview — no live calls', tone: 'neutral' },
};

function fmt(value: number | null, unit: string): string {
  return value === null || value === undefined ? '—' : `${value}${unit}`;
}

export function LiveImdPanel() {
  const [data, setData] = useState<ImdLiveStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load(refresh: boolean) {
    setBusy(true);
    setError(null);
    api
      .imdLive(refresh)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load the IMD status'))
      .finally(() => setBusy(false));
  }

  useEffect(() => load(false), []);

  const meta = data ? STATE_LABEL[data.state] ?? STATE_LABEL.error : null;
  const matched = data ? Object.values(data.matched) : [];

  return (
    <Panel
      title="Live IMD feed"
      subtitle="Real-time city forecasts from api.imd.gov.in, when this server is authorised to fetch them."
      tip="IMD API keys are bound to one static public IP. Only the server registered with the key can connect; everywhere else this panel says why it cannot, and shows no numbers."
      actions={
        data?.state !== 'static' ? (
          <button
            type="button"
            onClick={() => load(true)}
            disabled={busy}
            className="rounded border border-edge-strong px-2 py-1 text-2xs font-medium text-ink-secondary
                       transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
          >
            {busy ? 'Checking…' : 'Check now'}
          </button>
        ) : undefined
      }
    >
      {error && <p className="text-[11px] text-risk-severe">{error}</p>}
      {data && meta && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={meta.tone}>{meta.label}</Badge>
            {data.http_status ? (
              <span className="text-2xs tabular text-ink-muted">HTTP {data.http_status}</span>
            ) : null}
            {data.state !== 'static' && (
              <span className="text-2xs tabular text-ink-muted">checked {data.checked_at.replace('T', ' ').slice(0, 19)} UTC</span>
            )}
          </div>
          <p className="text-[11px] leading-relaxed text-ink-secondary">{data.message}</p>

          {data.fields_seen && data.fields_seen.length > 0 && (
            <p className="text-2xs leading-relaxed text-ink-muted">
              Fields IMD sent: <code className="text-ink-secondary">{data.fields_seen.join(', ')}</code>
            </p>
          )}

          {data.state === 'connected' && (
            <>
              {matched.length > 0 && (
                <div className="overflow-x-auto">
                  <p className="mb-1 text-2xs uppercase tracking-[0.08em] text-ink-muted">
                    Monitored cities in today's IMD forecast
                  </p>
                  <table className="w-full min-w-[520px] border-collapse text-[11px]">
                    <thead>
                      <tr className="border-b border-edge-strong text-left text-2xs uppercase tracking-[0.08em] text-ink-muted">
                        <th className="py-1.5 pr-3 font-medium">City</th>
                        <th className="py-1.5 pr-3 text-right font-medium">Max</th>
                        <th className="py-1.5 pr-3 text-right font-medium">Min</th>
                        <th className="py-1.5 pr-3 text-right font-medium">Rain</th>
                        <th className="py-1.5 font-medium">Warning</th>
                      </tr>
                    </thead>
                    <tbody>
                      {matched.map((m) => (
                        <tr key={m.location_id} className="border-b border-edge">
                          <td className="py-1.5 pr-3 font-medium text-ink-primary">{m.location_name}</td>
                          <td className="py-1.5 pr-3 text-right tabular text-ink-secondary">{fmt(m.max_temp, ' °C')}</td>
                          <td className="py-1.5 pr-3 text-right tabular text-ink-secondary">{fmt(m.min_temp, ' °C')}</td>
                          <td className="py-1.5 pr-3 text-right tabular text-ink-secondary">{fmt(m.rainfall, ' mm')}</td>
                          <td className="py-1.5 text-ink-secondary">{m.warning || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="text-2xs text-ink-muted">
                {data.cities.length} IMD cities received in total. Source: {data.endpoint}
              </p>
            </>
          )}
        </div>
      )}
    </Panel>
  );
}
