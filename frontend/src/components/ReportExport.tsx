/**
 * Forecast risk report.
 *
 * Rendered as a print-optimised document and handed to the browser's own
 * print-to-PDF. That keeps the export dependency-free and produces a file the
 * user's browser has already shown them, rather than a black-box download.
 */

import { useEffect } from 'react';

import type { RiskResponse } from '../api/types';
import { formatDate } from '../lib/format';
import { riskColor } from '../lib/risk';

export function ReportExport({ risk, onClose }: { risk: RiskResponse; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [onClose]);

  const color = riskColor(risk.risk_category);
  const drivers = risk.feature_contributions.filter((c) => c.contribution > 0).slice(0, 4);

  return (
    <div
      className="fixed inset-0 z-[1000] overflow-auto bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Forecast risk report"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="mx-auto max-w-3xl">
        <div className="no-print mb-3 flex items-center justify-between gap-3">
          <p className="text-xs text-ink-secondary">
            Preview - use your browser's print dialog to save as PDF.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => window.print()}
              className="rounded border border-accent/50 bg-accent/12 px-3 py-1.5 text-xs
                         font-semibold text-accent hover:bg-accent/20"
            >
              Print / Save as PDF
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-edge-strong px-3 py-1.5 text-xs font-medium
                         text-ink-secondary hover:text-ink-primary"
            >
              Close
            </button>
          </div>
        </div>

        <article
          id="atmosguard-report"
          className="rounded-lg bg-white p-8 text-[#111] shadow-2xl print:rounded-none print:p-0 print:shadow-none"
        >
          <header className="mb-5 flex items-start justify-between gap-4 border-b-2 border-[#0d1524] pb-3">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-[#0d1524]">AtmosGuard</h1>
              <p className="text-xs text-[#555]">
                Forecast Bust Risk Report - AI-based decision support
              </p>
            </div>
            <div className="text-right text-xs text-[#555]">
              <p>Issued {formatDate(risk.base_date)}</p>
              <p>
                Model {risk.model.label} - {risk.data_mode === 'demo' ? 'Demonstration data' : 'Operational'}
              </p>
            </div>
          </header>

          {risk.demo_notice && (
            <p className="mb-4 rounded border border-[#e2b400] bg-[#fff8e1] px-3 py-2 text-xs text-[#6b5200]">
              {risk.demo_notice}
            </p>
          )}

          <section className="mb-5 grid grid-cols-3 gap-4">
            <Field label="Location" value={`${risk.location.name}, ${risk.location.state}`} />
            <Field label="Forecast horizon" value={`Day ${risk.forecast_horizon}`} />
            <Field label="Valid date" value={formatDate(risk.valid_date)} />
            <Field label="Variable" value={risk.variable.label} />
            <Field label="Synoptic regime" value={risk.synoptic.regime} />
            <Field label="Assessment made" value={formatDate(risk.generated_at)} />
          </section>

          <section className="mb-5 flex items-stretch gap-4">
            <div
              className="flex w-40 flex-col justify-center rounded border-l-4 bg-[#f6f7f9] px-4 py-3"
              style={{ borderColor: color }}
            >
              <p className="text-[10px] uppercase tracking-wider text-[#555]">Forecast bust risk</p>
              <p className="text-4xl font-bold leading-none" style={{ color }}>
                {risk.risk_score.toFixed(0)}%
              </p>
              <p className="mt-1 text-sm font-bold" style={{ color }}>
                {risk.risk_category}
              </p>
            </div>
            <div className="flex-1 rounded bg-[#f6f7f9] px-4 py-3">
              <div className="mb-2 grid grid-cols-2 gap-3">
                <Field label="Forecast confidence" value={`${risk.forecast_confidence.toFixed(0)}%`} />
                <Field label="Confidence in assessment" value={`${risk.model_confidence.toFixed(0)}%`} />
              </div>
              <p className="text-xs leading-relaxed text-[#333]">{risk.explanation}</p>
            </div>
          </section>

          <Section title="Main risk factors">
            <ul className="space-y-1.5">
              {drivers.map((driver) => (
                <li key={driver.feature} className="flex items-center gap-3 text-xs">
                  <span className="w-52 shrink-0 text-[#333]">{driver.label}</span>
                  <span className="h-2.5 flex-1 rounded-sm bg-[#e6e8ec]">
                    <span
                      className="block h-full rounded-sm"
                      style={{
                        width: `${Math.min(100, (driver.contribution / (drivers[0]?.contribution || 1)) * 100)}%`,
                        background: '#d03b3b',
                      }}
                    />
                  </span>
                  <span className="w-14 shrink-0 text-right font-semibold tabular text-[#333]">
                    +{driver.contribution.toFixed(3)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[10px] text-[#777]">
              {risk.explanation_label} - {risk.explanation_method}.
            </p>
          </Section>

          <Section title="Ensemble uncertainty">
            <div className="grid grid-cols-4 gap-3">
              <Field label="Members" value={String(risk.ensemble.member_count)} />
              <Field
                label={`Spread at Day ${risk.forecast_horizon}`}
                value={`${risk.ensemble.spread_at_horizon.toFixed(1)} ${risk.variable.unit}`}
              />
              <Field label="Spread anomaly" value={`${risk.ensemble.spread_anomaly.toFixed(2)}x`} />
              <Field
                label="P10-P90 range"
                value={`${risk.ensemble.range_at_horizon[0].toFixed(0)} - ${risk.ensemble.range_at_horizon[1].toFixed(0)}`}
              />
            </div>
            <p className="mt-2 text-xs leading-relaxed text-[#333]">{risk.ensemble.explanation}</p>
          </Section>

          <Section title="Historical analogues">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-[#ccc] text-left text-[10px] uppercase tracking-wider text-[#666]">
                  <th className="pb-1 pr-2 font-medium">Date</th>
                  <th className="pb-1 pr-2 font-medium">Region</th>
                  <th className="pb-1 pr-2 font-medium">Similarity</th>
                  <th className="pb-1 font-medium">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {risk.analogues.map((a) => (
                  <tr key={a.id} className="border-b border-[#eee]">
                    <td className="py-1 pr-2">{a.date}</td>
                    <td className="py-1 pr-2">{a.region}</td>
                    <td className="py-1 pr-2 tabular">{(a.similarity * 100).toFixed(0)}%</td>
                    <td className="py-1 font-medium" style={{ color: a.bust_occurred ? '#b02a2a' : '#0a7a0a' }}>
                      {a.outcome}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section title="Recommended action">
            <p className="text-xs leading-relaxed text-[#333]">
              Consider increased reliance on ensemble and short-range guidance for this valid time.
              Re-assess at the next model run, and treat the deterministic value as one member of a
              wide distribution rather than a single expected outcome.
            </p>
          </Section>

          <footer className="mt-6 border-t border-[#ccc] pt-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-[#b02a2a]">
              Decision-support information - not an official weather warning
            </p>
            <p className="mt-1 text-[10px] leading-relaxed text-[#666]">{risk.disclaimer}</p>
          </footer>
        </article>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-[#666]">{label}</p>
      <p className="text-xs font-semibold text-[#111]">{value}</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4">
      <h2 className="mb-2 border-b border-[#ddd] pb-1 text-xs font-bold uppercase tracking-wider text-[#0d1524]">
        {title}
      </h2>
      {children}
    </section>
  );
}
