/**
 * Risk escalation timeline.
 *
 * This is the product's central claim rendered as a chart: for one valid date,
 * each point is a *different model run*, from Day 7 out down to Day 3. When a
 * forecast is heading for a bust, risk climbs as the event approaches - the
 * warning arrives days before the failure becomes obvious.
 */

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { TimelineRow } from '../api/types';
import { RISK_COLORS, riskColor } from '../lib/risk';
import { formatShortDate } from '../lib/format';

export function AlertTimeline({ rows, height = 210 }: { rows: TimelineRow[]; height?: number }) {
  if (!rows.length) return null;

  const first = rows[0];
  const last = rows[rows.length - 1];
  const change = last.risk_score - first.risk_score;

  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 10, right: 12, bottom: 4, left: 0 }}>
          {/* Band backdrop so a reader can place the line without a legend. */}
          <ReferenceArea y1={0} y2={30} fill={RISK_COLORS.LOW} fillOpacity={0.05} />
          <ReferenceArea y1={30} y2={60} fill={RISK_COLORS.MODERATE} fillOpacity={0.05} />
          <ReferenceArea y1={60} y2={80} fill={RISK_COLORS.HIGH} fillOpacity={0.06} />
          <ReferenceArea y1={80} y2={100} fill={RISK_COLORS.SEVERE} fillOpacity={0.07} />

          <CartesianGrid stroke="#1e2c44" strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={{ stroke: '#1e2c44' }}
            tick={{ fill: '#66768f', fontSize: 10 }}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 30, 60, 80, 100]}
            tickLine={false}
            axisLine={false}
            width={40}
            tick={{ fill: '#66768f', fontSize: 10 }}
            unit="%"
          />

          <Area
            type="monotone"
            dataKey="risk_score"
            stroke="none"
            fill="#38bdf8"
            fillOpacity={0.1}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="risk_score"
            stroke="#38bdf8"
            strokeWidth={2.5}
            isAnimationActive={false}
            dot={({ cx, cy, payload }) => (
              <circle
                key={payload.lead_time}
                cx={cx}
                cy={cy}
                r={5}
                fill={riskColor(payload.risk_category)}
                stroke="#0d1524"
                strokeWidth={2}
              />
            )}
          />

          <Tooltip
            cursor={{ stroke: '#38bdf8', strokeDasharray: '3 3' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as TimelineRow;
              return (
                <div className="rounded-md border border-edge-strong bg-surface-3 px-2.5 py-2 shadow-2xl">
                  <p className="text-2xs font-semibold text-ink-primary">
                    {row.label} forecast - run of {formatShortDate(row.init_date)}
                  </p>
                  <p className="mt-1 text-2xs tabular text-ink-secondary">
                    Bust risk{' '}
                    <span className="font-semibold" style={{ color: riskColor(row.risk_category) }}>
                      {row.risk_score.toFixed(1)}% {row.risk_category}
                    </span>
                  </p>
                  <p className="text-2xs tabular text-ink-muted">
                    Forecast confidence {row.forecast_confidence.toFixed(0)}%
                  </p>
                </div>
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <p className="mt-2 text-2xs leading-relaxed text-ink-muted">
        Each point is a separate model run verifying on the same date.{' '}
        {change > 4 ? (
          <span className="text-ink-secondary">
            Risk rose{' '}
            <span className="font-semibold text-risk-high tabular">
              {change.toFixed(0)} points
            </span>{' '}
            between the Day {first.lead_time} and Day {last.lead_time} runs - the early warning
            AtmosGuard exists to give.
          </span>
        ) : change < -4 ? (
          <span className="text-ink-secondary">
            Risk fell {Math.abs(change).toFixed(0)} points as the lead time shortened - the forecast
            settled as the event approached.
          </span>
        ) : (
          <span className="text-ink-secondary">
            Risk stayed broadly flat across successive runs.
          </span>
        )}
      </p>
    </div>
  );
}
