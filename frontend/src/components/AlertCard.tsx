/**
 * Early-warning alert card.
 *
 * Deliberate wording: these are *forecast bust risk* notices, never weather
 * warnings. The card says what may be unreliable and what to do about it, and
 * never asserts what the weather will do.
 */

import { useState } from 'react';

import type { Alert } from '../api/types';
import { RiskChip } from './Primitives';
import { formatDate } from '../lib/format';
import { riskColor } from '../lib/risk';

export function AlertCard({
  alert,
  onAnalyse,
  onExport,
}: {
  alert: Alert;
  onAnalyse: (alert: Alert) => void;
  onExport?: (alert: Alert) => void;
}) {
  const [acknowledged, setAcknowledged] = useState(false);
  const color = riskColor(alert.severity);

  return (
    <article
      className="panel overflow-hidden animate-rise"
      style={{ borderLeft: `3px solid ${color}` }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 px-3.5 pt-3">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <RiskChip category={alert.severity} size="sm" />
            <span className="text-2xs uppercase tracking-wider text-ink-muted">
              Forecast bust risk
            </span>
            {alert.source ? (
              <span className="inline-flex items-center gap-1 rounded bg-accent/15 px-1.5 py-0.5 text-3xs font-semibold text-accent border border-accent/30">
                <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                {alert.source}
              </span>
            ) : null}
            {alert.imd_warning_color && (
              <span
                className="rounded px-1.5 py-0.2 text-3xs font-bold uppercase text-white"
                style={{
                  backgroundColor:
                    alert.imd_warning_color === 'red'
                      ? '#ef4444'
                      : alert.imd_warning_color === 'orange'
                      ? '#f97316'
                      : alert.imd_warning_color === 'yellow'
                      ? '#eab308'
                      : '#22c55e',
                }}
              >
                IMD {alert.imd_warning_color}
              </span>
            )}
            {alert.severity === 'SEVERE' && !acknowledged && (
              <span
                className="h-1.5 w-1.5 rounded-full bg-risk-severe animate-pulse-ring"
                aria-hidden
              />
            )}
          </div>
          <h3 className="truncate text-sm font-semibold text-ink-primary">
            {alert.location_name}
            <span className="font-normal text-ink-muted"> - {alert.state}</span>
          </h3>
          <p className="mt-0.5 text-2xs text-ink-secondary">
            Day {alert.horizon} {alert.variable_label.toLowerCase()} forecast - valid{' '}
            {formatDate(alert.valid_date)}
          </p>
        </div>

        <div className="shrink-0 text-right">
          <p className="text-2xs text-ink-muted">Bust risk</p>
          <p className="text-2xl font-bold leading-none tabular" style={{ color }}>
            {alert.risk_score.toFixed(0)}%
          </p>
          <p className="mt-0.5 text-2xs text-ink-muted tabular">
            p(bust) {(alert.bust_probability * 100).toFixed(0)}% - confidence{' '}
            {alert.model_confidence.toFixed(0)}%
          </p>
        </div>
      </div>

      {alert.past_24_hrs_rainfall && alert.past_24_hrs_rainfall !== 'NIL' && (
        <div className="mt-2 mx-3.5 flex items-center gap-2 rounded bg-surface-2 px-2.5 py-1 text-2xs">
          <span className="font-semibold text-accent">🌧️ 24h Rain Observed:</span>
          <span className="font-mono text-ink-primary font-bold">{alert.past_24_hrs_rainfall} mm</span>
          {alert.todays_forecast && (
            <span className="truncate text-ink-muted border-l border-edge pl-2">
              {alert.todays_forecast}
            </span>
          )}
        </div>
      )}

      <div className="mt-2.5 px-3.5">
        <p className="text-2xs text-ink-muted">Reason</p>
        <p className="text-xs text-ink-secondary">{alert.reason}</p>
      </div>

      <div className="mt-2 px-3.5">
        <p className="text-2xs text-ink-muted">Recommended action</p>
        <p className="text-xs leading-relaxed text-ink-secondary">{alert.recommended_action}</p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-edge px-3.5 py-2.5">
        <button
          type="button"
          onClick={() => onAnalyse(alert)}
          className="rounded border border-accent/50 bg-accent/10 px-2.5 py-1 text-2xs font-semibold
                     text-accent transition-colors hover:bg-accent/18"
        >
          View analysis
        </button>
        <button
          type="button"
          onClick={() => setAcknowledged(true)}
          disabled={acknowledged}
          className="rounded border border-edge px-2.5 py-1 text-2xs font-medium text-ink-secondary
                     transition-colors hover:border-edge-strong hover:text-ink-primary
                     disabled:cursor-default disabled:opacity-50"
        >
          {acknowledged ? 'Acknowledged' : 'Acknowledge'}
        </button>
        {onExport && (
          <button
            type="button"
            onClick={() => onExport(alert)}
            className="rounded border border-edge px-2.5 py-1 text-2xs font-medium text-ink-secondary
                       transition-colors hover:border-edge-strong hover:text-ink-primary"
          >
            Export report
          </button>
        )}
        <span className="ml-auto text-2xs text-ink-muted">
          Status: {acknowledged ? 'Acknowledged' : alert.status}
        </span>
      </div>
    </article>
  );
}
