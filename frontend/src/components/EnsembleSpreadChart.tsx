/**
 * Ensemble spread chart - the visual heart of AtmosGuard.
 *
 * What the reader must see in one glance: the individual members agree at short
 * lead and fan apart as the forecast goes further out, and the selected lead
 * time is where that fan is widest.
 *
 * Encoding decisions:
 *  - Members are *not* categorical series. Which member is which carries no
 *    meaning, so they share one recessive hue at low opacity and appear in no
 *    legend; their collective shape is the message.
 *  - The 10th-90th percentile band is drawn behind them so the envelope reads
 *    even where the spaghetti is dense.
 *  - Ensemble mean and the deterministic run are the two real series, in the
 *    validated blue/aqua pair.
 *  - Observations are truth rather than a model, so they wear ink and a dashed
 *    stroke instead of a series hue.
 */

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { EnsemblePayload } from '../api/types';
import { SERIES } from '../lib/risk';
import { displayUnit } from '../lib/format';

const AXIS = { stroke: '#66768f', fontSize: 10 };

interface Row {
  label: string;
  lead: number;
  band: [number, number];
  mean: number;
  deterministic: number;
  observed: number | null;
  p25: number;
  p75: number;
  [member: `m${number}`]: number;
}

export function EnsembleSpreadChart({
  ensemble,
  horizon,
  height = 300,
}: {
  ensemble: EnsemblePayload;
  horizon: number;
  height?: number;
}) {
  const unit = displayUnit(ensemble.unit);

  const rows: Row[] = ensemble.days.map((day, i) => {
    const row = {
      label: day.label,
      lead: day.lead,
      band: [ensemble.percentiles.p10[i], ensemble.percentiles.p90[i]] as [number, number],
      mean: ensemble.mean[i],
      deterministic: ensemble.deterministic[i],
      observed: ensemble.observed[i],
      p25: ensemble.percentiles.p25[i],
      p75: ensemble.percentiles.p75[i],
    } as Row;
    ensemble.members.forEach((member, m) => {
      row[`m${m}`] = member.values[i];
    });
    return row;
  });

  const hasObservations = ensemble.observed.some((v) => v !== null);

  return (
    <div>
      {ensemble.high_spread && (
        <div
          className="mb-2.5 flex items-start gap-2 rounded-md border border-risk-moderate/45
                     bg-risk-moderate/10 px-2.5 py-2 animate-fade-in"
        >
          <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-risk-moderate" aria-hidden />
          <p className="text-2xs leading-relaxed text-ink-secondary">
            <span className="font-semibold text-risk-moderate">High Ensemble Spread</span> - spread
            at Day {horizon} is{' '}
            <span className="font-semibold tabular text-ink-primary">
              {ensemble.spread_anomaly.toFixed(2)}x
            </span>{' '}
            the normal level for this lead time.
          </p>
        </div>
      )}

      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 10, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#1e2c44" strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: '#1e2c44' }} tick={AXIS} />
          <YAxis
            tickLine={false}
            axisLine={false}
            tick={AXIS}
            width={44}
            label={{
              value: ensemble.axis_label,
              angle: -90,
              position: 'insideLeft',
              style: { fill: '#66768f', fontSize: 10, textAnchor: 'middle' },
            }}
          />

          {/* The selected lead time, marked so the gauge and the chart agree. */}
          <ReferenceLine
            x={`Day ${horizon}`}
            stroke="#38bdf8"
            strokeDasharray="3 3"
            strokeOpacity={0.7}
            label={{ value: `Day ${horizon}`, fill: '#38bdf8', fontSize: 9, position: 'top' }}
          />

          {/* 10th-90th percentile envelope. */}
          <Area
            type="monotone"
            dataKey="band"
            stroke="none"
            fill={SERIES.primary}
            fillOpacity={0.13}
            isAnimationActive={false}
            activeDot={false}
          />

          {/* Member spaghetti - one recessive hue, no legend entry. */}
          {ensemble.members.map((_, i) => (
            <Line
              key={i}
              type="monotone"
              dataKey={`m${i}`}
              stroke={SERIES.member}
              strokeOpacity={0.26}
              strokeWidth={1}
              dot={false}
              activeDot={false}
              isAnimationActive={false}
              legendType="none"
            />
          ))}

          <Line
            type="monotone"
            dataKey="mean"
            name="Ensemble mean"
            stroke={SERIES.secondary}
            strokeWidth={2.5}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="deterministic"
            name="Deterministic run"
            stroke={SERIES.primary}
            strokeWidth={2.5}
            dot={false}
            isAnimationActive={false}
          />
          {hasObservations && (
            <Line
              type="monotone"
              dataKey="observed"
              name="Observed"
              stroke={SERIES.observed}
              strokeWidth={2}
              strokeDasharray="5 3"
              dot={{ r: 3, fill: SERIES.observed, stroke: '#0d1524', strokeWidth: 1.5 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          )}

          <Tooltip
            cursor={{ stroke: '#38bdf8', strokeWidth: 1, strokeDasharray: '3 3' }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0]?.payload as Row | undefined;
              if (!row) return null;
              const spread = row.band[1] - row.band[0];
              return (
                <div className="rounded-md border border-edge-strong bg-surface-3 px-2.5 py-2 shadow-2xl">
                  <p className="mb-1 text-2xs font-semibold text-ink-primary">{label}</p>
                  <dl className="space-y-0.5 text-2xs tabular">
                    <Row2 color={SERIES.primary} term="Deterministic" value={`${row.deterministic.toFixed(1)} ${unit}`} />
                    <Row2 color={SERIES.secondary} term="Ensemble mean" value={`${row.mean.toFixed(1)} ${unit}`} />
                    {row.observed !== null && (
                      <Row2 color={SERIES.observed} term="Observed" value={`${row.observed.toFixed(1)} ${unit}`} />
                    )}
                    <Row2
                      color="#66768f"
                      term="P10-P90"
                      value={`${row.band[0].toFixed(1)} - ${row.band[1].toFixed(1)} ${unit}`}
                    />
                    <Row2 color="#66768f" term="Spread" value={`${spread.toFixed(1)} ${unit}`} />
                  </dl>
                </div>
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Legend. Members are deliberately described, not colour-keyed. */}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-2xs text-ink-secondary">
        <LegendKey color={SERIES.primary} label="Deterministic run" />
        <LegendKey color={SERIES.secondary} label="Ensemble mean" />
        {hasObservations && <LegendKey color={SERIES.observed} label="Observed" dashed />}
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm" style={{ background: SERIES.primary, opacity: 0.26 }} aria-hidden />
          {ensemble.plotted_member_count} of {ensemble.member_count} ensemble members
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm" style={{ background: SERIES.primary, opacity: 0.13 }} aria-hidden />
          P10-P90 envelope
        </span>
      </div>

      <p className="mt-2 text-2xs leading-relaxed text-ink-muted">{ensemble.explanation}</p>
    </div>
  );
}

function LegendKey({ color, label, dashed = false }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <svg width="18" height="4" aria-hidden>
        <line
          x1="0"
          y1="2"
          x2="18"
          y2="2"
          stroke={color}
          strokeWidth="2.5"
          strokeDasharray={dashed ? '4 3' : undefined}
        />
      </svg>
      {label}
    </span>
  );
}

function Row2({ color, term, value }: { color: string; term: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="flex items-center gap-1.5 text-ink-muted">
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} aria-hidden />
        {term}
      </dt>
      <dd className="font-medium text-ink-primary">{value}</dd>
    </div>
  );
}
