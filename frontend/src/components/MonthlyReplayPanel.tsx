/**
 * Monthly replay over the 1901-2017 sub-division record.
 *
 * Type a date anywhere in that span and this answers for the month containing
 * it, using nothing later than the month before, then sets the answer against
 * what IMD actually recorded.
 *
 * The one thing this panel has to communicate before anything else is its
 * resolution. The sub-division file holds one figure per month; a reader who
 * types 5 August 2015 expecting seven daily values has to learn, immediately
 * and without hunting for it, that the answer covers August 1st to 31st as a
 * single unit. So the resolution notice sits at the top, not in a footnote.
 */

import { useMemo, useState } from 'react';

import type { MonthlyMeta, MonthlyReplay, MonthlyRow } from '../api/types';
import { Badge } from './Primitives';
import { RISK_COLORS } from '../lib/risk';

const VERDICT_STYLE: Record<string, string> = {
  hit: 'border-risk-low/45 bg-risk-low/12 text-risk-low',
  miss: 'border-risk-severe/45 bg-risk-severe/12 text-risk-severe',
  'false alarm': 'border-risk-high/45 bg-risk-high/12 text-risk-high',
  'correct negative': 'border-edge-strong bg-surface-3 text-ink-secondary',
};

const VERDICT_LABEL: Record<string, string> = {
  hit: 'Hit',
  miss: 'Miss',
  'false alarm': 'False alarm',
  'correct negative': 'Correct negative',
};

function Verdict({ verdict }: { verdict?: string }) {
  if (!verdict) return <span className="text-ink-muted">—</span>;
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-2xs font-medium ${
        VERDICT_STYLE[verdict] ?? VERDICT_STYLE['correct negative']
      }`}
    >
      {VERDICT_LABEL[verdict] ?? verdict}
    </span>
  );
}

/** A compact bar showing where the month landed against its own climatology. */
function AnomalyBar({ z }: { z: number }) {
  const clipped = Math.max(-3, Math.min(z, 3));
  const half = (Math.abs(clipped) / 3) * 50;
  const wet = clipped >= 0;
  return (
    <span className="relative inline-block h-2.5 w-24 rounded-sm bg-surface-3 align-middle">
      <span className="absolute left-1/2 top-0 h-full w-px bg-edge-strong" />
      <span
        className="absolute top-0 h-full rounded-sm"
        style={{
          width: `${half}%`,
          left: wet ? '50%' : `${50 - half}%`,
          background: wet ? RISK_COLORS.LOW : RISK_COLORS.SEVERE,
          opacity: Math.abs(clipped) >= 1 ? 0.95 : 0.4,
        }}
      />
    </span>
  );
}

export function MonthlyReplayPanel({
  meta,
  data,
  date,
  onDateChange,
  busy,
  error,
}: {
  meta: MonthlyMeta | null;
  data: MonthlyReplay | null;
  date: string;
  onDateChange: (value: string) => void;
  busy: boolean;
  error: string | null;
}) {
  const [onlyExtremes, setOnlyExtremes] = useState(false);

  const rows = useMemo(() => {
    const all = data?.rows ?? [];
    const filtered = onlyExtremes
      ? all.filter((r) => r.validation.actual_extreme || r.prediction.extreme.flag)
      : all;
    // Biggest departures first: the months worth arguing about go at the top.
    return [...filtered].sort(
      (a, b) => Math.abs(b.validation.z ?? 0) - Math.abs(a.validation.z ?? 0),
    );
  }, [data, onlyExtremes]);

  const summary = data?.summary;

  return (
    <div className="space-y-4">
      {/* --------------------------- Resolution notice -------------------------- */}
      <section className="panel border-l-2 border-l-risk-moderate px-4 py-3">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h3 className="text-[13px] font-semibold text-ink-primary">
            This answer covers a whole month, not seven days
          </h3>
          <Badge tone="warn">Monthly resolution</Badge>
        </div>
        <p className="mt-1.5 text-[11px] leading-relaxed text-ink-secondary">
          The 1901–2017 sub-division file holds{' '}
          <strong className="text-ink-primary">one rainfall figure per sub-division per
          month</strong>. August 2015 in Vidarbha is a single number — 288.9 mm. There is no
          5 August in it. Splitting that total across 31 days would invent weather that never
          happened, so this replay works at the resolution the data actually has: pick a date,
          and it predicts the month containing it from everything known up to the end of the
          month before.
        </p>
        {meta && (
          <p className="mt-2 border-t border-edge pt-2 text-2xs leading-relaxed text-ink-muted">
            A month counts as <strong className="text-ink-secondary">extreme</strong> when it sits
            at least {meta.extreme_z} standard deviation from its own climatology, wet or dry.
            That climatology is an expanding window — for a target in year Y it uses only years
            before Y — so nothing about 2015 informs the judgement of August 2015. Everything from{' '}
            {meta.test_from_year} onward was held out of fitting entirely.
          </p>
        )}
      </section>

      {/* ------------------------------- Controls ------------------------------- */}
      <section className="panel px-4 py-3">
        <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
          <div>
            <label
              htmlFor="monthly-date"
              className="block text-2xs uppercase tracking-[0.08em] text-ink-muted"
            >
              Any date, 2010–2017
            </label>
            <input
              id="monthly-date"
              type="date"
              value={date}
              // Held-out years only: a month the model was fitted on is not a test.
              min={meta ? `${meta.test_from_year}-01-01` : undefined}
              max={meta ? `${meta.record_end}-12-31` : undefined}
              onChange={(event) => onDateChange(event.target.value)}
              className="mt-1 rounded border border-edge-strong bg-surface-2 px-2.5 py-1.5
                         text-[13px] tabular text-ink-primary focus:border-accent focus:outline-none"
            />
          </div>

          {data && (
            <div className="text-[11px]">
              <p className="text-2xs uppercase tracking-[0.08em] text-ink-muted">Replaying</p>
              <p className="mt-1 text-[13px] font-semibold text-ink-primary">
                {data.target_label}
              </p>
              <p className="text-2xs text-ink-muted">
                from everything known through {data.origin_label}
              </p>
            </div>
          )}

          {data && (
            <Badge tone={data.held_out ? 'accent' : 'neutral'}>
              {data.held_out ? 'Held-out year' : 'Training year'}
            </Badge>
          )}

          <label className="ml-auto flex cursor-pointer items-center gap-2 text-[11px] text-ink-secondary">
            <input
              type="checkbox"
              checked={onlyExtremes}
              onChange={(event) => setOnlyExtremes(event.target.checked)}
              className="h-3.5 w-3.5 rounded border-edge-strong bg-surface-2 accent-accent"
            />
            Only extremes and flags
          </label>
        </div>
        {error && <p className="mt-2 text-[11px] text-risk-severe">{error}</p>}
      </section>

      {/* -------------------------------- Summary ------------------------------- */}
      {summary && summary.verified > 0 && (
        <section className="panel overflow-hidden">
          <div className="grid grid-cols-2 gap-px bg-edge sm:grid-cols-3 lg:grid-cols-6">
            {[
              ['Sub-divisions', summary.verified, null],
              ['Actually extreme', summary.actual_extremes, null],
              ['Hits', summary.hit ?? 0, RISK_COLORS.LOW],
              ['Misses', summary.miss ?? 0, RISK_COLORS.SEVERE],
              ['False alarms', summary['false alarm'] ?? 0, RISK_COLORS.HIGH],
              [
                'Accuracy',
                summary.accuracy === null ? '—' : `${(summary.accuracy * 100).toFixed(0)}%`,
                null,
              ],
            ].map(([label, value, color]) => (
              <div key={label as string} className="bg-surface-1 px-4 py-3">
                <p className="text-[10px] font-medium uppercase tracking-[0.09em] text-ink-muted">
                  {label}
                </p>
                <p
                  className="mt-1.5 text-2xl font-semibold leading-none tabular"
                  style={color ? { color: color as string } : { color: '#e8eef7' }}
                >
                  {value}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* --------------------------------- Table -------------------------------- */}
      <section className="panel">
        <header className="px-4 pb-2.5 pt-3.5">
          <h2 className="text-[13px] font-semibold tracking-tight text-ink-primary">
            {data ? `${data.target_label} — predicted, then checked` : 'Monthly replay'}
          </h2>
          <p className="mt-1 text-[11px] leading-snug text-ink-muted">
            Predictions formed from the record through {data?.origin_label ?? 'the previous month'}.
            Observed columns are the published IMD figures for that month — look any of them up.
          </p>
        </header>
        <div className="-mx-0 overflow-x-auto px-4 pb-4">
          {busy && !data ? (
            <p className="py-8 text-center text-[11px] text-ink-muted">Running replay…</p>
          ) : rows.length === 0 ? (
            <p className="py-8 text-center text-[11px] text-ink-muted">
              Nothing to show for this month.
            </p>
          ) : (
            <table className="w-full min-w-[820px] border-collapse text-[11px]">
              <thead>
                <tr className="border-b border-edge-strong text-left text-2xs uppercase tracking-[0.08em] text-ink-muted">
                  <th className="py-2 pr-3 font-medium">Sub-division</th>
                  <th className="py-2 pr-3 text-right font-medium">p(extreme)</th>
                  <th className="py-2 pr-3 text-right font-medium">p(wet)</th>
                  <th className="py-2 pr-3 text-right font-medium">p(dry)</th>
                  <th className="py-2 pr-3 font-medium">Called</th>
                  <th className="py-2 pr-3 text-right font-medium">Observed</th>
                  <th className="py-2 pr-3 text-right font-medium">Normal</th>
                  <th className="py-2 pr-3 text-right font-medium">Departure</th>
                  <th className="py-2 pr-3 font-medium">Anomaly</th>
                  <th className="py-2 pr-3 font-medium">IMD category</th>
                  <th className="py-2 font-medium">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row: MonthlyRow) => {
                  const p = row.prediction;
                  const v = row.validation;
                  const called =
                    p.wet.flag && !p.dry.flag
                      ? 'Wet extreme'
                      : p.dry.flag && !p.wet.flag
                        ? 'Dry extreme'
                        : p.extreme.flag
                          ? 'Extreme'
                          : 'Near normal';
                  return (
                    <tr key={p.subdivision} className="border-b border-edge">
                      <td className="py-2 pr-3 font-medium text-ink-primary">{p.subdivision}</td>
                      <td
                        className={`py-2 pr-3 text-right tabular ${
                          p.extreme.flag ? 'font-semibold text-ink-primary' : 'text-ink-muted'
                        }`}
                      >
                        {(p.extreme.probability * 100).toFixed(0)}%
                      </td>
                      <td className="py-2 pr-3 text-right tabular text-ink-muted">
                        {(p.wet.probability * 100).toFixed(0)}%
                      </td>
                      <td className="py-2 pr-3 text-right tabular text-ink-muted">
                        {(p.dry.probability * 100).toFixed(0)}%
                      </td>
                      <td
                        className={`py-2 pr-3 ${
                          called === 'Near normal' ? 'text-ink-muted' : 'text-ink-secondary'
                        }`}
                      >
                        {called}
                      </td>
                      <td className="py-2 pr-3 text-right tabular text-ink-secondary">
                        {v.rainfall_mm?.toFixed(1) ?? '—'}
                      </td>
                      <td className="py-2 pr-3 text-right tabular text-ink-muted">
                        {v.climatology_mm?.toFixed(1) ?? '—'}
                      </td>
                      <td
                        className={`py-2 pr-3 text-right tabular ${
                          (v.departure_pct ?? 0) >= 0 ? 'text-ink-secondary' : 'text-ink-muted'
                        }`}
                      >
                        {v.departure_pct === undefined
                          ? '—'
                          : `${v.departure_pct > 0 ? '+' : ''}${v.departure_pct.toFixed(0)}%`}
                      </td>
                      <td className="py-2 pr-3">
                        {v.z === undefined ? '—' : <AnomalyBar z={v.z} />}
                      </td>
                      <td className="py-2 pr-3 text-ink-secondary">{v.category ?? '—'}</td>
                      <td className="py-2">
                        <Verdict verdict={v.verdict} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        {meta?.caveat && (
          <footer className="border-t border-edge px-4 py-2.5 text-2xs leading-relaxed text-ink-muted">
            {meta.caveat}
          </footer>
        )}
      </section>
    </div>
  );
}
