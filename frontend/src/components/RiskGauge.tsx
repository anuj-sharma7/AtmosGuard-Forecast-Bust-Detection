/**
 * The bust-risk gauge - the single most important number in the product.
 *
 * Form: a hero number with a supporting arc. The reader's job here is to take
 * one value in at a glance, so the number is the mark and the arc is context;
 * the band scale beneath shows where the value sits without making the reader
 * decode an angle.
 */

import type { RiskCategory } from '../api/types';
import { RISK_COLORS, riskColor } from '../lib/risk';

const BANDS: { name: RiskCategory; from: number; to: number }[] = [
  { name: 'LOW', from: 0, to: 30 },
  { name: 'MODERATE', from: 30, to: 60 },
  { name: 'HIGH', from: 60, to: 80 },
  { name: 'SEVERE', from: 80, to: 100 },
];

const SIZE = 210;
const CENTER = SIZE / 2;
const RADIUS = 84;
const STROKE = 13;
/** 270-degree sweep: -225deg to +45deg, leaving the gap at the bottom. */
const START = -225;
const SWEEP = 270;

function polar(angleDeg: number, radius: number) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: CENTER + radius * Math.cos(rad), y: CENTER + radius * Math.sin(rad) };
}

function arcPath(fromPct: number, toPct: number, radius: number) {
  const a0 = START + (fromPct / 100) * SWEEP;
  const a1 = START + (toPct / 100) * SWEEP;
  const p0 = polar(a0, radius);
  const p1 = polar(a1, radius);
  const largeArc = a1 - a0 > 180 ? 1 : 0;
  return `M ${p0.x} ${p0.y} A ${radius} ${radius} 0 ${largeArc} 1 ${p1.x} ${p1.y}`;
}

export function RiskGauge({
  score,
  category,
  forecastConfidence,
  horizon,
}: {
  score: number;
  category: RiskCategory;
  forecastConfidence: number;
  horizon: number;
}) {
  const color = riskColor(category);
  const needle = polar(START + (score / 100) * SWEEP, RADIUS + STROKE / 2 + 5);

  return (
    <figure className="flex flex-col items-center">
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="w-full max-w-[210px]"
        role="img"
        aria-label={`Forecast bust risk ${score.toFixed(0)} percent, ${category} risk, Day ${horizon}`}
      >
        {/* Band track. Each band is drawn with a 1.2% gap so the boundaries are
            legible without a separate legend. */}
        {BANDS.map((band) => (
          <path
            key={band.name}
            d={arcPath(band.from + (band.from > 0 ? 0.9 : 0), band.to - 0.9, RADIUS)}
            fill="none"
            stroke={RISK_COLORS[band.name]}
            strokeOpacity={category === band.name ? 0.4 : 0.14}
            strokeWidth={STROKE}
            strokeLinecap="butt"
          />
        ))}

        {/* Value arc. */}
        <path
          d={arcPath(0.4, Math.max(score, 1), RADIUS)}
          fill="none"
          stroke={color}
          strokeWidth={STROKE}
          strokeLinecap="round"
          style={{ transition: 'stroke 300ms ease, d 400ms ease' }}
        />

        {/* Needle tick at the value. */}
        <circle cx={needle.x} cy={needle.y} r="3.2" fill={color} />

        <text
          x={CENTER}
          y={CENTER - 22}
          textAnchor="middle"
          className="fill-ink-muted text-[9px] font-semibold uppercase"
          style={{ letterSpacing: '0.14em' }}
        >
          Bust Risk
        </text>
        <text
          x={CENTER}
          y={CENTER + 20}
          textAnchor="middle"
          fill={color}
          style={{ fontSize: 46, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}
        >
          {score.toFixed(0)}
          <tspan style={{ fontSize: 20, fontWeight: 600 }}>%</tspan>
        </text>
        <text
          x={CENTER}
          y={CENTER + 42}
          textAnchor="middle"
          fill={color}
          style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.1em' }}
        >
          {category} RISK
        </text>
      </svg>

      <figcaption className="mt-1 grid w-full grid-cols-2 gap-2 text-center">
        <div className="rounded border border-edge bg-surface-2 px-2 py-1.5">
          <p className="text-2xs text-ink-muted">Forecast confidence</p>
          <p className="text-sm font-semibold tabular text-ink-primary">
            {forecastConfidence.toFixed(0)}%
          </p>
        </div>
        <div className="rounded border border-edge bg-surface-2 px-2 py-1.5">
          <p className="text-2xs text-ink-muted">Forecast horizon</p>
          <p className="text-sm font-semibold tabular text-ink-primary">Day {horizon}</p>
        </div>
      </figcaption>
    </figure>
  );
}
