/** Data-source status and the inference pipeline. */

import type { SystemStatus } from '../api/types';

const STATUS_TONE: Record<string, string> = {
  ok: 'bg-risk-low',
  baseline: 'bg-risk-moderate',
  error: 'bg-risk-severe',
};

export function DataSources({ sources }: { sources: SystemStatus['sources'] }) {
  return (
    <ul className="space-y-2">
      {sources.map((source) => {
        const isDemo = source.status.toLowerCase() === 'demo';
        return (
          <li
            key={source.id}
            className="flex items-start justify-between gap-3 rounded-md border border-edge
                       bg-surface-2/55 px-3 py-2"
          >
            <div className="min-w-0">
              <p className="truncate text-xs font-semibold text-ink-primary">{source.name}</p>
              <p className="text-2xs text-ink-muted">{source.role}</p>
              <p className="mt-0.5 text-2xs text-ink-secondary">{source.detail}</p>
            </div>
            <span className="flex shrink-0 items-center gap-1.5 text-2xs font-medium">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  isDemo ? 'bg-risk-moderate' : 'bg-risk-low'
                }`}
                aria-hidden
              />
              <span className={isDemo ? 'text-risk-moderate' : 'text-risk-low'}>
                {source.status}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function Pipeline({ pipeline }: { pipeline: SystemStatus['pipeline'] }) {
  return (
    <ol className="space-y-1">
      {pipeline.map((stage, index) => (
        <li key={stage.stage}>
          <div className="flex items-start gap-3 rounded-md border border-edge bg-surface-2/55 px-3 py-2">
            <span
              className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border
                         border-edge-strong bg-surface-3 text-2xs font-bold tabular text-ink-muted"
            >
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 text-xs font-semibold text-ink-primary">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${STATUS_TONE[stage.status] ?? 'bg-ink-muted'}`}
                  aria-hidden
                />
                {stage.stage}
              </p>
              <p className="mt-0.5 text-2xs text-ink-secondary">{stage.detail}</p>
            </div>
          </div>
          {index < pipeline.length - 1 && (
            <div className="ml-[22px] h-2 w-px bg-edge-strong" aria-hidden />
          )}
        </li>
      ))}
    </ol>
  );
}
