/**
 * Verification charts.
 *
 * `ForecastVsObservation` answers "how did the weather forecast do?"
 * `ReliabilityChart` and `RocChart` answer "how did the *risk model* do?"
 * They are separate questions and the UI never mixes them in one plot.
 */

import {
  CartesianGrid,
  Cell,
  ComposedChart,
  Bar,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { ForecastVerification, ModelPerformance } from '../api/types';
import { RISK_COLORS, SERIES } from '../lib/risk';
import { displayUnit, formatShortDate } from '../lib/format';

const AXIS = { fill: '#66768f', fontSize: 10 };
const GRID = { stroke: '#1e2c44', strokeDasharray: '2 4' } as const;

function TooltipBox({ title, rows }: { title: string; rows: [string, string, string?][] }) {
  return (
    <div className="rounded-md border border-edge-strong bg-surface-3 px-2.5 py-2 shadow-2xl">
      <p className="mb-1 text-2xs font-semibold text-ink-primary">{title}</p>
      <dl className="space-y-0.5 text-2xs tabular">
        {rows.map(([term, value, color]) => (
          <div key={term} className="flex items-center justify-between gap-4">
            <dt className="flex items-center gap-1.5 text-ink-muted">
              {color && (
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} aria-hidden />
              )}
              {term}
            </dt>
            <dd className="font-medium text-ink-primary">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function ForecastVsObservation({
  verification,
  height = 240,
}: {
  verification: ForecastVerification;
  height?: number;
}) {
  const unit = displayUnit(verification.unit);
  const rows = verification.series.map((p) => ({ ...p, label: formatShortDate(p.date) }));

  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 10, bottom: 4, left: 0 }}>
          <CartesianGrid {...GRID} vertical={false} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={{ stroke: '#1e2c44' }}
            tick={AXIS}
            interval="preserveStartEnd"
            minTickGap={18}
          />
          <YAxis tickLine={false} axisLine={false} tick={AXIS} width={40} />
          <Line
            type="monotone"
            dataKey="forecast"
            name="Day 5 forecast"
            stroke={SERIES.primary}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="observed"
            name="Observed"
            stroke={SERIES.observed}
            strokeWidth={2}
            strokeDasharray="5 3"
            dot={false}
            isAnimationActive={false}
          />
          <Tooltip
            cursor={{ stroke: '#38bdf8', strokeDasharray: '3 3' }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as (typeof rows)[number];
              return (
                <TooltipBox
                  title={`${label}${row.bust ? ' - forecast bust' : ''}`}
                  rows={[
                    ['Forecast', `${row.forecast.toFixed(1)} ${unit}`, SERIES.primary],
                    ['Observed', `${row.observed.toFixed(1)} ${unit}`, SERIES.observed],
                    ['Error', `${row.error > 0 ? '+' : ''}${row.error.toFixed(1)} ${unit}`],
                  ]}
                />
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-ink-secondary">
        <span className="flex items-center gap-1.5">
          <svg width="18" height="4" aria-hidden>
            <line x1="0" y1="2" x2="18" y2="2" stroke={SERIES.primary} strokeWidth="2.5" />
          </svg>
          Day 5 forecast
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="18" height="4" aria-hidden>
            <line
              x1="0"
              y1="2"
              x2="18"
              y2="2"
              stroke={SERIES.observed}
              strokeWidth="2.5"
              strokeDasharray="4 3"
            />
          </svg>
          Observed / reanalysis
        </span>
      </div>
    </div>
  );
}

export function ReliabilityChart({
  reliability,
  height = 260,
}: {
  reliability: ModelPerformance['reliability'];
  height?: number;
}) {
  const rows = reliability
    .filter((b) => b.count > 0)
    .map((b) => ({ ...b, predicted: b.predicted * 100, observed: b.observed * 100 }));

  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 16, left: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis
            type="number"
            dataKey="predicted"
            domain={[0, 100]}
            tickLine={false}
            axisLine={{ stroke: '#1e2c44' }}
            tick={AXIS}
            unit="%"
            label={{ value: 'Predicted bust risk', position: 'insideBottom', offset: -8, style: { fill: '#66768f', fontSize: 10 } }}
          />
          <YAxis
            type="number"
            domain={[0, 100]}
            tickLine={false}
            axisLine={false}
            tick={AXIS}
            width={40}
            unit="%"
            label={{ value: 'Observed bust rate', angle: -90, position: 'insideLeft', style: { fill: '#66768f', fontSize: 10, textAnchor: 'middle' } }}
          />
          {/* Perfect calibration. A model on this line is honest about itself. */}
          <ReferenceLine
            segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]}
            stroke="#66768f"
            strokeDasharray="4 4"
            ifOverflow="extendDomain"
          />
          <Line
            type="monotone"
            dataKey="observed"
            stroke={SERIES.primary}
            strokeWidth={2}
            dot={{ r: 4, fill: SERIES.primary, stroke: '#0d1524', strokeWidth: 1.5 }}
            isAnimationActive={false}
          />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as (typeof rows)[number];
              return (
                <TooltipBox
                  title={`Predicted ${row.bin}`}
                  rows={[
                    ['Mean predicted', `${row.predicted.toFixed(1)}%`, SERIES.primary],
                    ['Observed bust rate', `${row.observed.toFixed(1)}%`],
                    ['Forecasts in bin', String(row.count)],
                  ]}
                />
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="mt-1.5 text-2xs leading-relaxed text-ink-muted">
        The dashed diagonal is where a literal probability forecast would sit. This curve runs below
        it because the score is a risk <em>index</em>, not a frequency estimate - a score of 80 means
        "among the riskiest forecasts", not "80% of these bust". What the product depends on is that
        the curve rises monotonically: a higher index really does mean a higher bust rate.
      </p>
    </div>
  );
}

export function RocChart({
  roc,
  auc,
  height = 260,
}: {
  roc: ModelPerformance['roc_curve'];
  auc: number;
  height?: number;
}) {
  const rows = roc.map((p) => ({ fpr: p.fpr * 100, tpr: p.tpr * 100, threshold: p.threshold }));

  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 16, left: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis
            type="number"
            dataKey="fpr"
            domain={[0, 100]}
            tickLine={false}
            axisLine={{ stroke: '#1e2c44' }}
            tick={AXIS}
            unit="%"
            label={{ value: 'False positive rate', position: 'insideBottom', offset: -8, style: { fill: '#66768f', fontSize: 10 } }}
          />
          <YAxis
            type="number"
            domain={[0, 100]}
            tickLine={false}
            axisLine={false}
            tick={AXIS}
            width={40}
            unit="%"
            label={{ value: 'True positive rate', angle: -90, position: 'insideLeft', style: { fill: '#66768f', fontSize: 10, textAnchor: 'middle' } }}
          />
          <ReferenceLine
            segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]}
            stroke="#66768f"
            strokeDasharray="4 4"
            ifOverflow="extendDomain"
          />
          <Line
            type="monotone"
            dataKey="tpr"
            stroke={SERIES.secondary}
            strokeWidth={2.5}
            dot={false}
            isAnimationActive={false}
          />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as (typeof rows)[number];
              return (
                <TooltipBox
                  title={`Threshold ${(row.threshold * 100).toFixed(0)}%`}
                  rows={[
                    ['True positive rate', `${row.tpr.toFixed(1)}%`, SERIES.secondary],
                    ['False positive rate', `${row.fpr.toFixed(1)}%`],
                  ]}
                />
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="mt-1.5 text-2xs leading-relaxed text-ink-muted">
        Area under the curve <span className="font-semibold tabular text-ink-primary">{auc.toFixed(3)}</span>.
        The dashed diagonal is a coin flip; further above it is better separation between forecasts
        that busted and those that did not.
      </p>
    </div>
  );
}

export function ErrorDistribution({
  verification,
  height = 180,
}: {
  verification: ForecastVerification;
  height?: number;
}) {
  const unit = displayUnit(verification.unit);
  const rows = verification.series.map((p) => ({ ...p, label: formatShortDate(p.date) }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={rows} margin={{ top: 8, right: 10, bottom: 4, left: 0 }}>
        <CartesianGrid {...GRID} vertical={false} />
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={{ stroke: '#1e2c44' }}
          tick={AXIS}
          interval="preserveStartEnd"
          minTickGap={18}
        />
        <YAxis tickLine={false} axisLine={false} tick={AXIS} width={40} />
        <ReferenceLine y={0} stroke="#2b3d5c" />
        <Bar dataKey="error" radius={[3, 3, 0, 0]} isAnimationActive={false}>
          {rows.map((row) => (
            <Cell key={row.date} fill={row.bust ? '#d03b3b' : SERIES.primary} fillOpacity={row.bust ? 0.95 : 0.55} />
          ))}
        </Bar>
        <Tooltip
          cursor={{ fill: 'rgba(56,189,248,0.07)' }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const row = payload[0].payload as (typeof rows)[number];
            return (
              <TooltipBox
                title={String(label)}
                rows={[
                  ['Forecast error', `${row.error > 0 ? '+' : ''}${row.error.toFixed(1)} ${unit}`],
                  ['Classified', row.bust ? 'Bust' : 'Within tolerance'],
                ]}
              />
            );
          }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function ErrorScatter({ perf, height = 200 }: { perf: ModelPerformance; height?: number }) {
  const cm = perf.confusion_matrix;
  const rows = [
    { name: 'Hits', value: cm.true_positive, color: '#0ca30c', hint: 'Bust correctly flagged' },
    { name: 'Misses', value: cm.false_negative, color: '#d03b3b', hint: 'Bust not flagged' },
    { name: 'False alarms', value: cm.false_positive, color: '#fab219', hint: 'Flagged but verified' },
    { name: 'Correct negatives', value: cm.true_negative, color: '#3987e5', hint: 'Correctly not flagged' },
  ];

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={rows} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 0 }}>
        <CartesianGrid {...GRID} horizontal={false} />
        <XAxis type="number" tickLine={false} axisLine={false} tick={AXIS} />
        <YAxis
          type="category"
          dataKey="name"
          tickLine={false}
          axisLine={false}
          tick={{ fill: '#9aa9bf', fontSize: 10 }}
          width={104}
        />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={16} isAnimationActive={false}>
          {rows.map((row) => (
            <Cell key={row.name} fill={row.color} fillOpacity={0.85} />
          ))}
        </Bar>
        <Scatter dataKey="value" shape={() => <g />} />
        <Tooltip
          cursor={{ fill: 'rgba(56,189,248,0.07)' }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const row = payload[0].payload as (typeof rows)[number];
            return <TooltipBox title={row.name} rows={[['Count', String(row.value)], ['Meaning', row.hint]]} />;
          }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/**
 * What a risk band actually means, measured.
 *
 * The bust-risk score is an index, not a probability, so "is it calibrated?"
 * is answered empirically: this is the share of forecasts in each band that
 * went on to bust. A monotonic rise from LOW to SEVERE is the property the
 * product depends on, and it is the number a forecaster should be told.
 */
export function BandReliability({
  bands,
  interpretation,
}: {
  bands: ModelPerformance['band_reliability'];
  interpretation: string;
}) {
  const max = Math.max(...bands.map((b) => b.observed_bust_rate), 0.01);

  return (
    <div>
      <ul className="space-y-2.5">
        {bands.map((band) => (
          <li key={band.band}>
            <div className="mb-1 flex items-baseline justify-between gap-2 text-2xs">
              <span className="flex items-center gap-2">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: RISK_COLORS[band.band] }}
                  aria-hidden
                />
                <span className="font-semibold text-ink-primary">{band.band}</span>
                <span className="text-ink-muted tabular">score {band.range}</span>
              </span>
              <span className="tabular text-ink-muted">
                {band.count.toLocaleString()} forecasts ({(band.share * 100).toFixed(0)}%)
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className="h-4 flex-1 overflow-hidden rounded-sm bg-surface-2">
                <div
                  className="h-full rounded-sm transition-all duration-300"
                  style={{
                    width: `${(band.observed_bust_rate / max) * 100}%`,
                    background: RISK_COLORS[band.band],
                  }}
                />
              </div>
              <span className="w-12 shrink-0 text-right text-xs font-bold tabular text-ink-primary">
                {(band.observed_bust_rate * 100).toFixed(1)}%
              </span>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-2xs leading-relaxed text-ink-muted">{interpretation}</p>
    </div>
  );
}
