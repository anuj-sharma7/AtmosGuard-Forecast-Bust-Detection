/** NWP model comparison table with inline magnitude bars. */

import type { ModelComparisonRow } from '../api/types';
import { RiskChip } from './Primitives';
import { displayUnit } from '../lib/format';

export function ModelComparison({
  rows,
  disagreement,
  message,
  spreadBetweenModels,
  unit,
}: {
  rows: ModelComparisonRow[];
  disagreement: boolean;
  message: string;
  spreadBetweenModels: number;
  unit: string;
}) {
  const maxValue = Math.max(...rows.map((r) => Math.abs(r.forecast_value)), 1);

  return (
    <div>
      <div
        className={`mb-3 flex items-start gap-2 rounded-md border px-2.5 py-2 ${
          disagreement
            ? 'border-risk-moderate/45 bg-risk-moderate/10'
            : 'border-risk-low/40 bg-risk-low/8'
        }`}
      >
        <span
          className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
            disagreement ? 'bg-risk-moderate' : 'bg-risk-low'
          }`}
          aria-hidden
        />
        <p className="text-2xs leading-relaxed text-ink-secondary">
          <span
            className={`font-semibold ${disagreement ? 'text-risk-moderate' : 'text-risk-low'}`}
          >
            {message}
          </span>{' '}
          - spread between deterministic runs is{' '}
          <span className="font-semibold tabular text-ink-primary">
            {spreadBetweenModels.toFixed(1)} {displayUnit(unit)}
          </span>
          .
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-edge text-left text-2xs uppercase tracking-wider text-ink-muted">
              <th scope="col" className="pb-2 pr-3 font-medium">Model</th>
              <th scope="col" className="pb-2 pr-3 font-medium">Forecast value</th>
              <th scope="col" className="pb-2 pr-3 font-medium">Ensemble spread</th>
              <th scope="col" className="pb-2 pr-3 font-medium">Bust risk</th>
              <th scope="col" className="pb-2 pr-3 font-medium">Confidence</th>
              <th scope="col" className="pb-2 font-medium">Historical skill</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.model_id} className="border-b border-edge/60 last:border-0">
                <td className="py-2.5 pr-3">
                  <p className="font-semibold text-ink-primary">{row.model}</p>
                  <p className="text-2xs text-ink-muted">{row.centre}</p>
                </td>
                <td className="py-2.5 pr-3">
                  <p className="font-semibold tabular text-ink-primary">
                    {row.forecast_value.toFixed(1)}{' '}
                    <span className="text-2xs font-normal text-ink-muted">
                      {displayUnit(row.unit)}
                    </span>
                  </p>
                  <div className="mt-1 h-1 w-20 overflow-hidden rounded-full bg-surface-2" aria-hidden>
                    <div
                      className="h-full rounded-full bg-series-1"
                      style={{ width: `${(Math.abs(row.forecast_value) / maxValue) * 100}%` }}
                    />
                  </div>
                </td>
                <td className="py-2.5 pr-3">
                  <span className="tabular text-ink-secondary">
                    {row.ensemble_spread.toFixed(2)}
                  </span>
                  <span className="ml-1.5 text-2xs text-ink-muted">({row.spread_label})</span>
                </td>
                <td className="py-2.5 pr-3">
                  <RiskChip category={row.risk_category} score={row.risk_score} size="sm" />
                </td>
                <td className="py-2.5 pr-3 tabular text-ink-secondary">
                  {row.forecast_confidence.toFixed(0)}%
                </td>
                <td className="py-2.5 tabular text-ink-secondary">
                  {row.historical_skill.toFixed(0)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
