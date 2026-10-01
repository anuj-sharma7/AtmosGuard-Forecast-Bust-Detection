/**
 * The small set of primitives every panel in AtmosGuard is built from.
 *
 * Keeping these in one file makes the visual language enforceable: a panel is
 * always titled, it always carries its explanation and units, and every
 * technical term is always defined by a tooltip - the UX requirements from the
 * specification become the default rather than something each page remembers.
 */

import { useId, useState, type ReactNode } from 'react';

import type { RiskCategory } from '../api/types';
import { riskChipClass } from '../lib/risk';

/* --------------------------------- Tooltip -------------------------------- */

export function InfoTip({ text, label }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-label={label ? `About ${label}` : 'More information'}
        aria-describedby={open ? id : undefined}
        className="grid h-4 w-4 place-items-center rounded-full border border-edge-strong
                   text-[9px] font-bold leading-none text-ink-muted transition-colors
                   hover:border-accent hover:text-accent"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(event) => {
          event.preventDefault();
          setOpen((v) => !v);
        }}
      >
        i
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute left-1/2 top-6 z-50 w-64 -translate-x-1/2 rounded-md border
                     border-edge-strong bg-surface-3 p-2.5 text-2xs font-normal leading-relaxed
                     text-ink-secondary shadow-xl animate-fade-in"
        >
          {label && <span className="mb-1 block font-semibold text-ink-primary">{label}</span>}
          {text}
        </span>
      )}
    </span>
  );
}

/* ---------------------------------- Panel --------------------------------- */

interface PanelProps {
  title: string;
  /** One line under the title saying what the reader is looking at. */
  subtitle?: string;
  /** Definition of the technical concept, surfaced as a tooltip. */
  tip?: string;
  unit?: string;
  updated?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}

export function Panel({
  title,
  subtitle,
  tip,
  unit,
  updated,
  actions,
  children,
  className = '',
  bodyClassName = '',
}: PanelProps) {
  return (
    <section className={`panel flex flex-col animate-rise ${className}`}>
      <header className="flex items-start justify-between gap-3 px-4 pb-2.5 pt-3.5">
        <div className="min-w-0">
          <h2 className="flex items-center gap-1.5 text-[13px] font-semibold leading-tight tracking-tight text-ink-primary">
            <span className="truncate">{title}</span>
            {tip && <InfoTip text={tip} label={title} />}
          </h2>
          {subtitle && (
            <p className="mt-1 text-[11px] leading-snug text-ink-muted">{subtitle}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {unit && (
            <span className="rounded border border-edge px-1.5 py-0.5 text-2xs text-ink-muted tabular">
              {unit}
            </span>
          )}
          {actions}
        </div>
      </header>
      <div className={`flex-1 px-4 pb-4 ${bodyClassName}`}>{children}</div>
      {updated && (
        <footer className="px-4 pb-2.5 text-[10px] uppercase tracking-[0.08em] text-ink-muted tabular">
          Updated {updated}
        </footer>
      )}
    </section>
  );
}

/* ---------------------------------- Chips --------------------------------- */

export function RiskChip({
  category,
  score,
  size = 'md',
}: {
  category: RiskCategory;
  score?: number;
  size?: 'sm' | 'md';
}) {
  const pad = size === 'sm' ? 'px-1.5 py-0.5 text-2xs' : 'px-2 py-1 text-xs';
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border font-semibold tracking-wide
                  ${pad} ${riskChipClass(category)}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {category}
      {score !== undefined && <span className="tabular opacity-80">{score.toFixed(0)}%</span>}
    </span>
  );
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'accent' | 'warn';
}) {
  const tones = {
    neutral: 'border-edge bg-surface-2 text-ink-secondary',
    accent: 'border-accent/40 bg-accent/10 text-accent',
    warn: 'border-risk-moderate/45 bg-risk-moderate/10 text-risk-moderate',
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs
                  font-medium tracking-wide ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

/* ------------------------------ Async states ------------------------------ */

export function LoadingState({ label = 'Loading', rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div className="animate-fade-in" role="status" aria-live="polite">
      <div className="mb-3 flex items-center gap-2 text-2xs text-ink-muted">
        <span className="h-3 w-3 animate-spin rounded-full border-2 border-edge-strong border-t-accent" />
        {label}...
      </div>
      <div className="space-y-2">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="h-3 animate-pulse rounded bg-surface-2"
            style={{ width: `${100 - i * 14}%` }}
          />
        ))}
      </div>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-md border border-risk-severe/40 bg-risk-severe/8 p-3.5 animate-fade-in"
    >
      <p className="text-xs font-semibold text-risk-severe">Unable to load data</p>
      <p className="mt-1 text-2xs leading-relaxed text-ink-secondary">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2.5 rounded border border-edge-strong px-2.5 py-1 text-2xs font-medium
                     text-ink-primary transition-colors hover:border-accent hover:text-accent"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="grid place-items-center rounded-md border border-dashed border-edge px-4 py-8 text-center">
      <p className="text-xs font-medium text-ink-secondary">{title}</p>
      {detail && <p className="mt-1 max-w-sm text-2xs leading-relaxed text-ink-muted">{detail}</p>}
    </div>
  );
}

/* ------------------------------- Demo notice ------------------------------ */

export function DemoNotice({ notice, className = '' }: { notice: string | null; className?: string }) {
  if (!notice) return null;
  return (
    <p
      className={`flex items-start gap-1.5 text-2xs leading-relaxed text-ink-muted ${className}`}
    >
      <span
        className="mt-px inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-risk-moderate"
        aria-hidden
      />
      {notice}
    </p>
  );
}
