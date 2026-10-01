/**
 * Historical analogue analysis - "we have seen this pattern before, and here is
 * how the forecast performed".
 */

import type { Analogue } from '../api/types';
import { Badge } from './Primitives';

export function AnaloguePanel({
  analogues,
  note,
  bestSimilarity,
  bustCount,
}: {
  analogues: Analogue[];
  note: string;
  bestSimilarity: number;
  bustCount: number;
}) {
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-2xs">
        <Badge tone="accent">Best match {bestSimilarity.toFixed(0)}%</Badge>
        <Badge tone={bustCount >= analogues.length / 2 ? 'warn' : 'neutral'}>
          {bustCount} of {analogues.length} analogues busted
        </Badge>
      </div>

      <ol className="space-y-2">
        {analogues.map((a) => (
          <li key={a.id} className="rounded-md border border-edge bg-surface-2/55 p-2.5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-xs font-semibold text-ink-primary">
                  {a.date} - {a.region}
                </p>
                <p className="mt-0.5 text-2xs text-ink-muted">{a.regime}</p>
              </div>
              <div className="shrink-0 text-right">
                <p className="text-2xs text-ink-muted">Similarity</p>
                <p className="text-sm font-bold tabular text-accent">
                  {(a.similarity * 100).toFixed(0)}%
                </p>
              </div>
            </div>

            {/* Similarity bar: magnitude on one sequential hue. */}
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-3" aria-hidden>
              <div
                className="h-full rounded-full bg-accent transition-all duration-300"
                style={{ width: `${(a.similarity * 100).toFixed(1)}%` }}
              />
            </div>

            <p className="mt-2 text-2xs leading-relaxed text-ink-secondary">{a.pattern}</p>

            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs
                            font-semibold ${
                              a.bust_occurred
                                ? 'border-risk-severe/45 bg-risk-severe/10 text-risk-severe'
                                : 'border-risk-low/45 bg-risk-low/10 text-risk-low'
                            }`}
              >
                {a.bust_occurred ? 'BUST: YES' : 'BUST: NO'}
              </span>
              <span className="text-2xs text-ink-muted">{a.outcome}</span>
              <span className="text-2xs text-ink-muted tabular">- {a.verified_error}</span>
            </div>
          </li>
        ))}
      </ol>

      <p className="mt-3 text-2xs leading-relaxed text-ink-muted">{note}</p>
    </div>
  );
}
