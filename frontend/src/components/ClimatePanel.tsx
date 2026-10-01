/**
 * Climate context from the 117-year IMD record.
 *
 * A single forecast means little without knowing what normal looks like here
 * and how wide the spread of past outcomes has been. This panel supplies that
 * background: the full series, the trend, and how often each IMD rainfall
 * category has actually occurred.
 *
 * Encoding choices:
 *  - The series is a bar-per-year departure chart, not a line. Each year is a
 *    discrete observation, and the reader's question is "how many years ran
 *    dry?" - which counts marks either side of a baseline, something a line
 *    hides.
 *  - Bars take their colour from IMD's own departure categories, so the chart
 *    and the frequency table below it are the same classification.
 *  - The decadal mean rides on top as a line, because a decade *is* a trend.
 */

import {
  Bar,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { ClimateProfile } from '../api/types';
import { InfoTip } from './Primitives';

/** IMD departure categories share the risk scale's semantics, not its meaning. */
const CATEGORY_COLOR: Record<string, string> = {
  'Large Excess': '#1c5cab',
  Excess: '#3987e5',
  Normal: '#8794a6',
  Deficient: '#ec835a',
  Scanty: '#d03b3b',
  'No Rain': '#8a2525',
};

export function ClimatePanel({ profile }: { profile: ClimateProfile }) {
  const normal = profile.monsoon_mean;
  const rows = profile.series.map((point) => {
    const departure = normal ? ((point.monsoon - normal) / normal) * 100 : 0;
    return { ...point, departure, category: categorise(departure) };
  });

  // Decadal means, positioned on the same year axis so the line reads as a
  // smoothed version of the bars rather than a separate series.
  const decadeByYear = new Map<number, number>();
  profile.decades.forEach((d) => decadeByYear.set(d.decade + 5, d.departure_pct));
  const withDecade = rows.map((r) => ({ ...r, decadal: decadeByYear.get(r.year) ?? null }));

  const trend = profile.trend;

  return (
    <div>
      <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        <Stat
          label="Monsoon normal"
          value={`${profile.monsoon_mean.toFixed(0)} mm`}
          detail={`${profile.monsoon_share.toFixed(0)}% of the annual total`}
        />
        <Stat
          label="Variability"
          value={profile.variability.toFixed(2)}
          detail="coefficient of variation"
          tip="Standard deviation of annual rainfall over its mean. High variability is a genuine predictability handicap, and the risk model uses it."
        />
        <Stat
          label="Record"
          value={`${profile.record.years} yr`}
          detail={`${profile.record.start}-${profile.record.end}`}
        />
        <Stat
          label="Trend"
          value={trend ? `${trend.slope_per_decade > 0 ? '+' : ''}${trend.slope_per_decade.toFixed(1)}` : '--'}
          unit="mm/decade"
          detail={trend ? (trend.significant ? `p = ${trend.p_value.toFixed(3)}` : 'not significant') : undefined}
          accent={trend?.significant ? (trend.slope_per_decade < 0 ? '#ec835a' : '#3987e5') : undefined}
          tip="Sen's slope with a Mann-Kendall significance test - rank-based, so a handful of extreme years cannot drag it around the way they would a least-squares fit."
        />
      </dl>

      {trend && (
        <p className="mb-3 text-2xs leading-relaxed text-ink-secondary">
          Monsoon rainfall over {profile.subdivision} shows{' '}
          <span className={trend.significant ? 'font-semibold text-ink-primary' : ''}>
            {trend.direction}
          </span>
          {trend.significant
            ? ` at ${Math.abs(trend.percent_per_decade).toFixed(2)}% per decade (Mann-Kendall p = ${trend.p_value.toFixed(3)}).`
            : ` over the full record (Mann-Kendall p = ${trend.p_value.toFixed(2)}, so the apparent slope is not distinguishable from noise).`}
          {profile.baseline_shift && (
            <>
              {' '}The most recent 30 years ({profile.baseline_shift.late_period}) averaged{' '}
              <span className="tabular">{profile.baseline_shift.late_mean.toFixed(0)} mm</span>{' '}
              against <span className="tabular">{profile.baseline_shift.early_mean.toFixed(0)} mm</span>{' '}
              in {profile.baseline_shift.early_period}.
            </>
          )}
        </p>
      )}

      <ResponsiveContainer width="100%" height={190}>
        <ComposedChart data={withDecade} margin={{ top: 6, right: 8, bottom: 4, left: 0 }}>
          <XAxis
            dataKey="year"
            tickLine={false}
            axisLine={{ stroke: '#1e2c44' }}
            tick={{ fill: '#66768f', fontSize: 10 }}
            interval="preserveStartEnd"
            minTickGap={44}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            tick={{ fill: '#66768f', fontSize: 10 }}
            width={42}
            unit="%"
            label={{
              value: 'Departure from normal',
              angle: -90,
              position: 'insideLeft',
              style: { fill: '#66768f', fontSize: 10, textAnchor: 'middle' },
            }}
          />
          <ReferenceLine y={0} stroke="#2b3d5c" />
          <ReferenceLine y={20} stroke="#3987e5" strokeDasharray="3 3" strokeOpacity={0.5} />
          <ReferenceLine y={-19} stroke="#ec835a" strokeDasharray="3 3" strokeOpacity={0.5} />
          <Bar dataKey="departure" isAnimationActive={false}>
            {withDecade.map((row) => (
              <Cell key={row.year} fill={CATEGORY_COLOR[row.category]} fillOpacity={0.85} />
            ))}
          </Bar>
          <Line
            type="monotone"
            dataKey="decadal"
            stroke="#e8eef7"
            strokeWidth={2}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
          <Tooltip
            cursor={{ fill: 'rgba(56,189,248,0.07)' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as (typeof withDecade)[number];
              return (
                <div className="rounded-md border border-edge-strong bg-surface-3 px-2.5 py-2 shadow-2xl">
                  <p className="mb-1 text-2xs font-semibold tabular text-ink-primary">{row.year}</p>
                  <dl className="space-y-0.5 text-2xs tabular">
                    <Row term="Monsoon" value={`${row.monsoon.toFixed(0)} mm`} />
                    <Row
                      term="Departure"
                      value={`${row.departure > 0 ? '+' : ''}${row.departure.toFixed(1)}%`}
                    />
                    <Row term="IMD category" value={row.category} />
                  </dl>
                </div>
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-ink-muted">
        <span className="flex items-center gap-1.5">
          <svg width="16" height="3" aria-hidden>
            <line x1="0" y1="1.5" x2="16" y2="1.5" stroke="#e8eef7" strokeWidth="2" />
          </svg>
          decadal mean
        </span>
        <span>dashed lines mark IMD's Excess (+20%) and Deficient (-19%) thresholds</span>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <p className="mb-2 flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wider text-ink-muted">
            How often each outcome occurred
            <InfoTip
              label="IMD rainfall categories"
              text="India Meteorological Department's published departure classes: Excess at +20% or more, Normal within ±19%, Deficient -20% to -59%, Scanty -60% to -99%."
            />
          </p>
          <ul className="space-y-1.5">
            {profile.categories
              .filter((c) => c.years > 0)
              .map((c) => (
                <li key={c.category} className="flex items-center gap-2.5 text-2xs">
                  <span className="w-24 shrink-0 text-ink-secondary">{c.category}</span>
                  <span className="h-2.5 flex-1 overflow-hidden rounded-sm bg-surface-2">
                    <span
                      className="block h-full rounded-sm"
                      style={{
                        width: `${c.frequency * 100}%`,
                        background: CATEGORY_COLOR[c.category],
                      }}
                    />
                  </span>
                  <span className="w-20 shrink-0 text-right tabular text-ink-primary">
                    {c.years} yr · {(c.frequency * 100).toFixed(0)}%
                  </span>
                </li>
              ))}
          </ul>
        </div>

        <div>
          <p className="mb-2 text-2xs font-medium uppercase tracking-wider text-ink-muted">
            Extremes on record
          </p>
          <ul className="space-y-1">
            {profile.extremes.wettest.slice(0, 2).map((e) => (
              <Extreme key={e.year} entry={e} />
            ))}
            {profile.extremes.driest.slice(0, 2).map((e) => (
              <Extreme key={e.year} entry={e} />
            ))}
          </ul>
        </div>
      </div>

      <p className="mt-3 border-t border-edge pt-2.5 text-2xs leading-relaxed text-ink-muted">
        {profile.source.name} · {profile.source.publisher}. {profile.source.method}.
      </p>
    </div>
  );
}

function categorise(departure: number): string {
  if (departure >= 60) return 'Large Excess';
  if (departure >= 20) return 'Excess';
  if (departure >= -19) return 'Normal';
  if (departure >= -60) return 'Deficient';
  if (departure >= -99) return 'Scanty';
  return 'No Rain';
}

function Extreme({
  entry,
}: {
  entry: { year: number; monsoon: number; departure_pct: number; category: string };
}) {
  return (
    <li className="flex items-baseline justify-between gap-2 text-2xs">
      <span className="tabular text-ink-primary">{entry.year}</span>
      <span className="flex-1 border-b border-dashed border-edge" aria-hidden />
      <span className="tabular text-ink-secondary">{entry.monsoon.toFixed(0)} mm</span>
      <span
        className="w-14 shrink-0 text-right font-semibold tabular"
        style={{ color: CATEGORY_COLOR[entry.category] }}
      >
        {entry.departure_pct > 0 ? '+' : ''}
        {entry.departure_pct.toFixed(0)}%
      </span>
    </li>
  );
}

function Row({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-ink-muted">{term}</dt>
      <dd className="font-medium text-ink-primary">{value}</dd>
    </div>
  );
}

function Stat({
  label,
  value,
  unit,
  detail,
  tip,
  accent,
}: {
  label: string;
  value: string;
  unit?: string;
  detail?: string;
  tip?: string;
  accent?: string;
}) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-2xs text-ink-muted">
        {label}
        {tip && <InfoTip text={tip} label={label} />}
      </dt>
      <dd>
        <span
          className="text-base font-semibold tabular"
          style={accent ? { color: accent } : undefined}
        >
          {value}
        </span>
        {unit && <span className="ml-1 text-2xs text-ink-muted">{unit}</span>}
        {detail && <span className="block text-2xs text-ink-muted">{detail}</span>}
      </dd>
    </div>
  );
}
