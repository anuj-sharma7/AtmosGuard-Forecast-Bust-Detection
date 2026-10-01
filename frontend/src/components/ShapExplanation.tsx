/**
 * "Why is this forecast at risk?" - the feature-contribution panel.
 *
 * Form: a diverging bar chart. Contributions carry polarity (a driver either
 * pushes risk up or pulls it down), so the encoding is a two-hue diverging
 * pair around a neutral zero baseline - red for drivers that raise the risk,
 * blue for those that lower it. Bars are sorted by absolute magnitude, and
 * every bar is directly labelled, so the ranking never depends on colour.
 *
 * Honesty note: for the linear baseline model these are the *exact* Shapley
 * values (phi_i = w_i * (x_i - E[x_i])). They are still labelled
 * "Feature Contribution - MVP" because the estimator behind them is the
 * interpretable baseline, not a trained model with a real SHAP explainer.
 */

import type { FeatureContribution } from '../api/types';
import { InfoTip } from './Primitives';

const POSITIVE = '#d03b3b';
const NEGATIVE = '#3987e5';

export function ShapExplanation({
  contributions,
  explanation,
  method,
  label,
}: {
  contributions: FeatureContribution[];
  explanation: string;
  method: string;
  label: string;
}) {
  const max = Math.max(...contributions.map((c) => Math.abs(c.contribution)), 0.01);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span
          className="rounded border border-edge bg-surface-2 px-1.5 py-0.5 text-2xs
                     font-medium tracking-wide text-ink-muted"
        >
          {label}
        </span>
        <InfoTip label="How this is calculated" text={method} />
        <span className="ml-auto flex items-center gap-3 text-2xs text-ink-muted">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm" style={{ background: POSITIVE }} aria-hidden />
            raises risk
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm" style={{ background: NEGATIVE }} aria-hidden />
            lowers risk
          </span>
        </span>
      </div>

      <ul className="space-y-2">
        {contributions.map((c) => {
          const magnitude = Math.abs(c.contribution) / max;
          const positive = c.contribution >= 0;
          return (
            <li key={c.feature}>
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="flex items-center gap-1.5 truncate text-xs text-ink-primary">
                  <span className="truncate">{c.label}</span>
                  <InfoTip text={c.description} label={c.label} />
                </span>
                <span
                  className="shrink-0 text-xs font-semibold tabular"
                  style={{ color: positive ? POSITIVE : NEGATIVE }}
                >
                  {positive ? '+' : '-'}
                  {Math.abs(c.contribution).toFixed(3)}
                </span>
              </div>

              {/* Diverging bar: zero sits at the centre, bars grow outward. */}
              <div className="relative h-3.5 rounded-sm bg-surface-2" aria-hidden>
                <div className="absolute inset-y-0 left-1/2 w-px bg-edge-strong" />
                <div
                  className="absolute inset-y-0 transition-all duration-300"
                  style={{
                    width: `${(magnitude * 50).toFixed(2)}%`,
                    left: positive ? '50%' : undefined,
                    right: positive ? undefined : '50%',
                    background: positive ? POSITIVE : NEGATIVE,
                    borderRadius: positive ? '0 4px 4px 0' : '4px 0 0 4px',
                  }}
                />
              </div>

              <p className="mt-0.5 text-2xs text-ink-muted tabular">
                value {c.value.toFixed(2)} - {c.direction} assessed risk
              </p>
            </li>
          );
        })}
      </ul>

      <div className="mt-4 rounded-md border border-edge bg-surface-2/60 p-3">
        <p className="text-2xs font-semibold uppercase tracking-wider text-ink-muted">
          Model explanation - demonstration
        </p>
        <p className="mt-1.5 text-xs leading-relaxed text-ink-secondary">{explanation}</p>
      </div>
    </div>
  );
}
