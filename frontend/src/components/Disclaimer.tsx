/** Standing trust-and-safety footer. Present on every page, never dismissible. */

export function Disclaimer({ text }: { text?: string }) {
  return (
    <footer className="mt-8 border-t border-edge px-4 py-4">
      <div className="mx-auto max-w-[1800px]">
        <p className="text-2xs leading-relaxed text-ink-muted">
          {text ??
            'AtmosGuard is an experimental AI-based decision-support system. It does not replace official forecasts or warnings issued by authorized meteorological agencies.'}
        </p>
        <p className="mt-1 text-2xs text-ink-muted/70">
          AtmosGuard - Reads the forecast before it fails. Forecast bust risk is a measure of
          forecast reliability, not a prediction of weather severity.
        </p>
      </div>
    </footer>
  );
}
