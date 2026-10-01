/**
 * Metric strip.
 *
 * One divided strip rather than a row of bordered cards. A grid of identical
 * boxes gives every number the same weight and reads as a template; an
 * operational console separates readings with hairlines and lets the values
 * themselves carry the hierarchy. It also removes four borders per metric from
 * a screen that already has a lot of edges.
 */

import type { ReactNode } from 'react';

import { InfoTip } from './Primitives';

export function Metric({
  label,
  value,
  unit,
  detail,
  tip,
  accent,
  trend,
  loading = false,
}: {
  label: string;
  value: string | number;
  unit?: string;
  detail?: string;
  tip?: string;
  /** Colour applied to the value only; labels stay in ink. */
  accent?: string;
  trend?: number[];
  loading?: boolean;
}) {
  return (
    <div className="min-w-0 px-4 py-3 first:pl-0 last:pr-0">
      <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.09em] text-ink-muted">
        <span className="truncate">{label}</span>
        {tip && <InfoTip text={tip} label={label} />}
      </p>

      {loading ? (
        <div className="mt-2 h-7 w-16 animate-pulse rounded bg-surface-2" />
      ) : (
        <p className="mt-1.5 flex items-baseline gap-1.5">
          <span
            className="text-[28px] font-semibold leading-none tracking-tight tabular"
            style={accent ? { color: accent } : undefined}
          >
            {value}
          </span>
          {unit && <span className="text-xs font-medium text-ink-muted">{unit}</span>}
          {trend && trend.length > 1 && <Sparkline values={trend} color={accent ?? '#3987e5'} />}
        </p>
      )}

      {detail && <p className="mt-1.5 truncate text-[11px] leading-tight text-ink-muted">{detail}</p>}
    </div>
  );
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const width = 60;
  const height = 16;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - min) / span) * (height - 3) - 1.5;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="ml-1 h-4 w-[60px] self-end opacity-80" aria-hidden>
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.75" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * The strip itself. Scrolls sideways on narrow screens instead of reflowing
 * into a ragged grid, which keeps the reading order intact on a phone.
 */
export function MetricStrip({ children }: { children: ReactNode }) {
  return (
    <section className="panel overflow-hidden">
      <div
        className="flex divide-x divide-edge overflow-x-auto
                   [&>*]:flex-1 [&>*]:shrink-0 [&>*]:basis-[168px] px-4"
      >
        {children}
      </div>
    </section>
  );
}
