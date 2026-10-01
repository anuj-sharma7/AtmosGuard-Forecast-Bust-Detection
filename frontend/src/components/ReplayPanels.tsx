/**
 * Panels for the historical replay.
 *
 * The visual job here is different from the rest of the dashboard. Everywhere
 * else the question is "how risky is this forecast?"; here it is "can this
 * number be trusted?", and that means the page has to show its working - which
 * mode is running, what each phase was allowed to read, which days had no
 * observation, and where the flattering number differs from the honest one.
 *
 * So the caveats are laid out as content, not tucked into a footnote. A panel
 * that cannot be verified says so in the place where its result would be.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type {
  ReplayAvailability,
  ReplayBacktest,
  ReplayContribution,
  ReplayGroupMetric,
  ReplayOutcome,
  ReplayPrediction,
  ReplayReliabilityBin,
  ReplayRun,
  ReplayValidation,
} from '../api/types';
import { Badge } from './Primitives';
import { formatShortDate } from '../lib/format';
import { RISK_COLORS, SERIES } from '../lib/risk';

/* ------------------------------ Outcome chips ----------------------------- */

const OUTCOME_STYLE: Record<ReplayOutcome, { label: string; className: string }> = {
  hit: { label: 'Hit', className: 'border-risk-low/45 bg-risk-low/12 text-risk-low' },
  miss: { label: 'Miss', className: 'border-risk-severe/45 bg-risk-severe/12 text-risk-severe' },
  'false alarm': {
    label: 'False alarm',
    className: 'border-risk-high/45 bg-risk-high/12 text-risk-high',
  },
  'correct negative': {
    label: 'Correct negative',
    className: 'border-edge-strong bg-surface-3 text-ink-secondary',
  },
  'not verifiable': {
    label: 'No observation',
    className: 'border-edge-strong bg-surface-2 text-ink-muted',
  },
};

export function OutcomeChip({ outcome }: { outcome: ReplayOutcome }) {
  const style = OUTCOME_STYLE[outcome] ?? OUTCOME_STYLE['not verifiable'];
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-2xs font-medium ${style.className}`}
    >
      {style.label}
    </span>
  );
}

/* -------------------------------- Mode banner ----------------------------- */

/**
 * Which mode is running, and why the other one is not.
 *
 * Mode A is the real thing - an archived forecast checked against what
 * happened - and it is unavailable, because no such archive exists here. That
 * is stated at the top of the page rather than discovered at the bottom of it.
 */
export function ModeBanner({ availability }: { availability: ReplayAvailability }) {
  const a = availability.mode_a;
  const b = availability.mode_b;

  return (
    <section className="panel overflow-hidden">
      <div className="grid gap-px bg-edge md:grid-cols-2">
        <div className="bg-surface-1 p-4">
          <div className="flex items-center gap-2">
            <span className="grid h-5 w-5 place-items-center rounded-full border border-edge-strong text-2xs font-bold text-ink-muted">
              A
            </span>
            <h3 className="text-[13px] font-semibold text-ink-primary">{a.name}</h3>
            <Badge tone={a.available ? 'accent' : 'neutral'}>
              {a.available ? 'Available' : 'Unavailable'}
            </Badge>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-ink-secondary">{a.reason}</p>
          {!a.available && a.candidate_archives && a.candidate_archives.length > 0 && (
            <div className="mt-3 border-t border-edge pt-2.5">
              <p className="text-2xs uppercase tracking-[0.08em] text-ink-muted">
                Archives that hold what this needs
              </p>
              <ul className="mt-1.5 space-y-1.5">
                {a.candidate_archives.map((c) => (
                  <li key={c.id} className="text-[11px] leading-snug">
                    <a
                      className="font-medium text-accent hover:underline"
                      href={c.reference}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      {c.name}
                    </a>
                    <span className="text-ink-muted"> — {c.covers}. {c.access}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="bg-surface-1 p-4">
          <div className="flex items-center gap-2">
            <span className="grid h-5 w-5 place-items-center rounded-full border border-accent/55 bg-accent/12 text-2xs font-bold text-accent">
              B
            </span>
            <h3 className="text-[13px] font-semibold text-ink-primary">{b.name}</h3>
            <Badge tone={b.available ? 'accent' : 'neutral'}>
              {b.available ? 'Running' : 'Unavailable'}
            </Badge>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-ink-secondary">{b.reason}</p>
          <p className="mt-2 border-t border-edge pt-2.5 text-[11px] leading-relaxed text-ink-muted">
            Mode B predicts an <strong className="text-ink-secondary">observed</strong> IMD Large
            Excess rainfall day from information available at the origin. It is a real, verifiable
            prediction about the weather — and it is{' '}
            <strong className="text-ink-secondary">not</strong> a forecast bust, because there is no
            archived forecast here to bust.
          </p>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------- Phase strip ------------------------------ */

/** The two phases, and what each one was permitted to read. */
export function PhaseStrip({ run }: { run: ReplayRun }) {
  const evidence = run.predictions[0]?.evidence_window;
  const validDays = run.validations.map((v) => v.valid_day);

  return (
    <section className="panel overflow-hidden">
      <div className="grid gap-px bg-edge sm:grid-cols-2">
        <div className="bg-surface-1 px-4 py-3">
          <p className="text-2xs uppercase tracking-[0.08em] text-ink-muted">
            Phase 1 — prediction
          </p>
          <p className="mt-1 text-[13px] font-semibold text-ink-primary tabular">
            {evidence ? `${formatShortDate(evidence[0])} → ${formatShortDate(evidence[1])}` : '—'}
          </p>
          <p className="mt-1 text-[11px] leading-snug text-ink-muted">
            Reads observations up to and including the origin. A read past it raises{' '}
            <code className="text-ink-secondary">LeakageError</code> rather than returning a value.
          </p>
        </div>
        <div className="bg-surface-1 px-4 py-3">
          <p className="text-2xs uppercase tracking-[0.08em] text-ink-muted">
            Phase 2 — validation
          </p>
          <p className="mt-1 text-[13px] font-semibold text-ink-primary tabular">
            {validDays.length
              ? `${formatShortDate(validDays[0])} → ${formatShortDate(validDays[validDays.length - 1])}`
              : '—'}
          </p>
          <p className="mt-1 text-[11px] leading-snug text-ink-muted">
            Runs only after every prediction is frozen. Reads the published observation and nothing
            else.
          </p>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------ Replay table ------------------------------ */

export function ReplayTable({
  predictions,
  validations,
  threshold,
  selected,
  onSelect,
}: {
  predictions: ReplayPrediction[];
  validations: ReplayValidation[];
  threshold: number;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const byId = new Map(validations.map((v) => [v.prediction_id, v]));

  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[720px] border-collapse text-[11px]">
        <thead>
          <tr className="border-b border-edge-strong text-left text-2xs uppercase tracking-[0.08em] text-ink-muted">
            <th className="py-2 pr-3 font-medium">Lead</th>
            <th className="py-2 pr-3 font-medium">Valid day</th>
            <th className="py-2 pr-3 text-right font-medium">p(event)</th>
            <th className="py-2 pr-3 font-medium">Predicted</th>
            <th className="py-2 pr-3 text-right font-medium">Observed</th>
            <th className="py-2 pr-3 text-right font-medium">Normal</th>
            <th className="py-2 pr-3 text-right font-medium">Departure</th>
            <th className="py-2 pr-3 font-medium">IMD category</th>
            <th className="py-2 font-medium">Outcome</th>
          </tr>
        </thead>
        <tbody>
          {predictions.map((p) => {
            const v = byId.get(p.prediction_id);
            const active = selected === p.prediction_id;
            return (
              <tr
                key={p.prediction_id}
                onClick={() => onSelect(p.prediction_id)}
                className={`cursor-pointer border-b border-edge transition-colors hover:bg-surface-2 ${
                  active ? 'bg-accent/8' : ''
                }`}
              >
                <td className="py-2 pr-3 font-semibold text-ink-primary tabular">D{p.lead_time}</td>
                <td className="py-2 pr-3 text-ink-secondary tabular">
                  {formatShortDate(p.valid_day)}
                </td>
                <td className="py-2 pr-3 text-right tabular font-medium text-ink-primary">
                  {(p.probability * 100).toFixed(1)}%
                </td>
                <td className="py-2 pr-3">
                  <span
                    className={
                      p.probability >= threshold
                        ? 'font-medium text-risk-high'
                        : 'text-ink-muted'
                    }
                  >
                    {p.probability >= threshold ? 'Event' : 'No event'}
                  </span>
                </td>
                <td className="py-2 pr-3 text-right tabular text-ink-secondary">
                  {v?.observed_available ? `${v.observed_rainfall?.toFixed(1)} mm` : '—'}
                </td>
                <td className="py-2 pr-3 text-right tabular text-ink-muted">
                  {v?.observed_available ? `${v.observed_normal?.toFixed(1)} mm` : '—'}
                </td>
                <td className="py-2 pr-3 text-right tabular text-ink-muted">
                  {v?.observed_available && v.observed_departure_pct !== null
                    ? `${v.observed_departure_pct > 0 ? '+' : ''}${v.observed_departure_pct.toFixed(0)}%`
                    : '—'}
                </td>
                <td className="py-2 pr-3 text-ink-secondary">
                  {v?.observed_available ? v.observed_category : '—'}
                </td>
                <td className="py-2">
                  <OutcomeChip outcome={v?.outcome ?? 'not verifiable'} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* --------------------------- Probability profile -------------------------- */

export function ProbabilityProfile({
  predictions,
  validations,
  threshold,
}: {
  predictions: ReplayPrediction[];
  validations: ReplayValidation[];
  threshold: number;
}) {
  const byId = new Map(validations.map((v) => [v.prediction_id, v]));
  const data = predictions.map((p) => {
    const v = byId.get(p.prediction_id);
    return {
      lead: `D${p.lead_time}`,
      probability: Number((p.probability * 100).toFixed(1)),
      observed: v?.observed_available ? (v.actual_event ? 100 : 0) : null,
      outcome: v?.outcome ?? 'not verifiable',
    };
  });

  return (
    <div className="h-52">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: -18 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="#1e2c44" vertical={false} />
          <XAxis dataKey="lead" tick={{ fontSize: 10, fill: '#66768f' }} tickLine={false} />
          <YAxis
            domain={[0, 100]}
            unit="%"
            tick={{ fontSize: 10, fill: '#66768f' }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              background: '#1a273c',
              border: '1px solid #2b3d5c',
              borderRadius: 6,
              fontSize: 11,
            }}
            formatter={(value: number, name: string) =>
              name === 'observed'
                ? [value === 100 ? 'Large Excess' : 'No event', 'Observed']
                : [`${value}%`, 'Predicted probability']
            }
          />
          <ReferenceLine
            y={threshold * 100}
            stroke={RISK_COLORS.HIGH}
            strokeDasharray="4 3"
            label={{
              value: `threshold ${(threshold * 100).toFixed(0)}%`,
              fontSize: 9,
              fill: RISK_COLORS.HIGH,
              position: 'insideTopRight',
            }}
          />
          <Line
            type="monotone"
            dataKey="probability"
            stroke={SERIES.primary}
            strokeWidth={2}
            dot={{ r: 3 }}
          />
          <Line
            type="stepAfter"
            dataKey="observed"
            stroke="#66768f"
            strokeWidth={1.5}
            strokeDasharray="3 3"
            dot={{ r: 2.5 }}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="mt-1 text-2xs leading-snug text-ink-muted">
        Solid: the model's probability at each lead. Dashed: what was observed — 100% where the day
        recorded an IMD Large Excess, 0% where it did not, absent where the record has no entry.
      </p>
    </div>
  );
}

/* ------------------------------ Attribution ------------------------------- */

export function ReplayAttribution({
  contributions,
  baseValue,
  probability,
}: {
  contributions: ReplayContribution[];
  baseValue: number;
  probability: number;
}) {
  const data = contributions.map((c) => ({
    label: c.label,
    contribution: Number(c.contribution.toFixed(4)),
    value: c.value,
    description: c.description,
  }));

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between text-[11px]">
        <span className="text-ink-muted">
          Base log-odds <span className="tabular text-ink-secondary">{baseValue.toFixed(3)}</span>
        </span>
        <span className="text-ink-muted">
          Probability{' '}
          <span className="tabular font-semibold text-ink-primary">
            {(probability * 100).toFixed(1)}%
          </span>
        </span>
      </div>
      <div style={{ height: Math.max(data.length * 30, 120) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 8 }}>
            <CartesianGrid strokeDasharray="2 4" stroke="#1e2c44" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: '#66768f' }} tickLine={false} />
            <YAxis
              type="category"
              dataKey="label"
              width={130}
              tick={{ fontSize: 10, fill: '#9aa9bf' }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                background: '#1a273c',
                border: '1px solid #2b3d5c',
                borderRadius: 6,
                fontSize: 11,
                maxWidth: 260,
              }}
              formatter={(value: number, _n, item) => [
                `${value > 0 ? '+' : ''}${value.toFixed(3)} log-odds`,
                item?.payload?.description ?? '',
              ]}
            />
            <ReferenceLine x={0} stroke="#2b3d5c" />
            <Bar dataKey="contribution" radius={[0, 3, 3, 0]} barSize={14}>
              {data.map((d, i) => (
                <Cell
                  key={i}
                  fill={d.contribution >= 0 ? RISK_COLORS.HIGH : RISK_COLORS.LOW}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1.5 text-2xs leading-snug text-ink-muted">
        Exact Shapley values. The model is linear in the log-odds, so each attribution has a closed
        form and the six shown plus the rest sum precisely to the log-odds behind the probability —
        no sampling, no approximation.
      </p>
    </div>
  );
}

/* ----------------------------- Confusion matrix --------------------------- */

export function ConfusionMatrix({
  confusion,
  caption,
}: {
  confusion: ReplayBacktest['overall']['confusion'];
  caption?: string;
}) {
  const cells = [
    { label: 'Hit', value: confusion.true_positive, tone: 'text-risk-low', hint: 'predicted, happened' },
    { label: 'False alarm', value: confusion.false_positive, tone: 'text-risk-high', hint: 'predicted, did not happen' },
    { label: 'Miss', value: confusion.false_negative, tone: 'text-risk-severe', hint: 'not predicted, happened' },
    { label: 'Correct negative', value: confusion.true_negative, tone: 'text-ink-secondary', hint: 'not predicted, did not happen' },
  ];

  return (
    <div>
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded border border-edge bg-edge">
        {cells.map((c) => (
          <div key={c.label} className="bg-surface-2 px-3 py-2.5">
            <p className={`text-xl font-semibold tabular ${c.tone}`}>{c.value}</p>
            <p className="mt-0.5 text-[11px] font-medium text-ink-secondary">{c.label}</p>
            <p className="text-2xs text-ink-muted">{c.hint}</p>
          </div>
        ))}
      </div>
      <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-4">
        {[
          ['Precision', confusion.precision],
          ['Recall', confusion.recall],
          ['F1', confusion.f1],
          ['Base rate', confusion.base_rate],
        ].map(([label, value]) => (
          <div key={label as string} className="flex justify-between border-b border-edge pb-1">
            <dt className="text-ink-muted">{label}</dt>
            <dd className="tabular font-medium text-ink-primary">
              {value === null ? '—' : (value as number).toFixed(3)}
            </dd>
          </div>
        ))}
      </dl>
      {caption && <p className="mt-2 text-2xs leading-snug text-ink-muted">{caption}</p>}
    </div>
  );
}

/* --------------------------- Reliability diagram -------------------------- */

export function ReliabilityDiagram({ bins }: { bins: ReplayReliabilityBin[] }) {
  const data = bins
    .filter((b) => b.count > 0)
    .map((b) => ({
      predicted: Number(((b.mean_predicted ?? 0) * 100).toFixed(1)),
      observed: Number(((b.observed_rate ?? 0) * 100).toFixed(1)),
      count: b.count,
      perfect: Number(((b.mean_predicted ?? 0) * 100).toFixed(1)),
    }));

  return (
    <div className="h-52">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 10, bottom: 4, left: -18 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="#1e2c44" />
          <XAxis
            dataKey="predicted"
            type="number"
            domain={[0, 100]}
            unit="%"
            tick={{ fontSize: 10, fill: '#66768f' }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 100]}
            unit="%"
            tick={{ fontSize: 10, fill: '#66768f' }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              background: '#1a273c',
              border: '1px solid #2b3d5c',
              borderRadius: 6,
              fontSize: 11,
            }}
            formatter={(value: number, name: string, item) =>
              name === 'observed'
                ? [`${value}% (n=${item?.payload?.count})`, 'Observed frequency']
                : [`${value}%`, 'Perfect calibration']
            }
          />
          <Line
            type="linear"
            dataKey="perfect"
            stroke="#66768f"
            strokeDasharray="3 3"
            strokeWidth={1}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="observed"
            stroke={SERIES.primary}
            strokeWidth={2}
            dot={{ r: 3.5 }}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="mt-1 text-2xs leading-snug text-ink-muted">
        A calibrated model sits on the dashed diagonal. Bin counts are in the tooltip — a bin
        holding a handful of cases is not evidence of anything.
      </p>
    </div>
  );
}

/* ---------------------------- Skill by lead time -------------------------- */

export function SkillByLead({ rows }: { rows: ReplayGroupMetric[] }) {
  const data = rows.map((r) => ({
    lead: `D${r.lead_time}`,
    auc: r.roc_auc ?? 0,
    count: r.count,
    events: r.events,
  }));

  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: -20 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="#1e2c44" vertical={false} />
          <XAxis dataKey="lead" tick={{ fontSize: 10, fill: '#66768f' }} tickLine={false} />
          <YAxis
            domain={[0.4, 1]}
            tick={{ fontSize: 10, fill: '#66768f' }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              background: '#1a273c',
              border: '1px solid #2b3d5c',
              borderRadius: 6,
              fontSize: 11,
            }}
            formatter={(value: number, _n, item) => [
              `${value.toFixed(3)} (n=${item?.payload?.count}, ${item?.payload?.events} events)`,
              'ROC-AUC',
            ]}
          />
          <ReferenceLine
            y={0.5}
            stroke={RISK_COLORS.SEVERE}
            strokeDasharray="4 3"
            label={{ value: 'no skill', fontSize: 9, fill: RISK_COLORS.SEVERE, position: 'insideTopRight' }}
          />
          <Bar dataKey="auc" fill={SERIES.primary} radius={[3, 3, 0, 0]} barSize={26} />
        </BarChart>
      </ResponsiveContainer>
      <p className="mt-1 text-2xs leading-snug text-ink-muted">
        Skill falling away with lead time is what real predictability does. A flat profile across
        seven days would be the signature of a leak, not of a good model.
      </p>
    </div>
  );
}

/* -------------------------------- Audit log ------------------------------- */

export function AuditLog({ run }: { run: ReplayRun }) {
  return (
    <ol className="space-y-2.5">
      {run.audit_log.map((entry, i) => (
        <li key={i} className="border-l-2 border-edge-strong pl-3">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-[11px] font-semibold text-ink-primary">{entry.step}</span>
            <span className="text-2xs uppercase tracking-[0.08em] text-ink-muted">
              {entry.phase}
            </span>
          </div>
          <p className="mt-0.5 text-[11px] leading-snug text-ink-secondary">{entry.detail}</p>
          <p className="mt-0.5 text-2xs text-ink-muted">
            reads: <code>{entry.reads}</code>
          </p>
        </li>
      ))}
    </ol>
  );
}

/* ------------------------------- Provenance ------------------------------- */

export function Provenance({ run }: { run: ReplayRun }) {
  const rows: [string, string][] = [
    ['Run ID', run.run_id],
    ['Model version', run.model_version],
    ['Mode', `${run.mode} — ${run.mode_name ?? ''}`],
    ['Origin date', run.origin],
    ['Decision threshold', run.threshold !== undefined ? run.threshold.toFixed(2) : '—'],
    ['Event definition', run.event?.definition ?? '—'],
    ['Observation source', run.event?.source ?? '—'],
    [
      'Archive coverage',
      `${run.availability.archive.start} to ${run.availability.archive.end} (${run.availability.archive.days} days)`,
    ],
  ];

  return (
    <dl className="space-y-1.5 text-[11px]">
      {rows.map(([label, value]) => (
        <div key={label} className="flex flex-wrap justify-between gap-x-4 border-b border-edge pb-1.5">
          <dt className="shrink-0 text-ink-muted">{label}</dt>
          <dd className="text-right font-medium text-ink-secondary">
            {label.includes('ID') || label.includes('version') ? (
              <code className="tabular">{value}</code>
            ) : (
              value
            )}
          </dd>
        </div>
      ))}
      <p className="pt-1 text-2xs leading-snug text-ink-muted">
        The run ID is derived from the origin date and the model version, so the same inputs always
        produce the same identifier. Re-running this replay reproduces these numbers exactly.
      </p>
    </dl>
  );
}
