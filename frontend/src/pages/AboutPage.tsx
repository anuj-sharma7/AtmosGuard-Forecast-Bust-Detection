/** What AtmosGuard is, how it works, and - just as importantly - what it is not. */

import { Panel } from '../components/Primitives';
import { useAppState } from '../state/AppState';

export function AboutPage() {
  const { meta } = useAppState();

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <section className="panel px-5 py-5">
        <h2 className="text-xl font-bold tracking-tight text-ink-primary">
          Reads the forecast before it fails.
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-secondary">
          Medium-range forecasts for Day 3 to Day 7 can become unreliable because of atmospheric
          uncertainty, ensemble spread, changing weather regimes and rapidly evolving systems. The
          problem is that forecast failures are usually recognised only after the event. AtmosGuard
          identifies forecasts with a high probability of busting <em>before</em> the event occurs.
        </p>
      </section>

      <Panel title="What the system does">
        <ol className="space-y-2.5 text-xs leading-relaxed text-ink-secondary">
          {[
            ['Ingests forecast fields', 'Deterministic and ensemble output from multiple NWP centres.'],
            ['Extracts predictors', 'Ensemble spread anomaly, regime change, analogue mismatch, pressure tendency, run-to-run persistence and model disagreement.'],
            ['Scores bust risk', 'A calibrated 0-100 score with LOW / MODERATE / HIGH / SEVERE bands.'],
            ['Explains the score', 'Additive per-feature contributions, so a forecaster can see which driver is responsible.'],
            ['Compares with history', 'Retrieves past situations with similar patterns and known forecast outcomes.'],
            ['Raises early warnings', 'Alerts when risk crosses the HIGH band, with the escalation history for that valid date.'],
          ].map(([title, detail], index) => (
            <li key={title} className="flex gap-3">
              <span
                className="grid h-5 w-5 shrink-0 place-items-center rounded-full border border-edge-strong
                           bg-surface-2 text-2xs font-bold tabular text-ink-muted"
              >
                {index + 1}
              </span>
              <span>
                <span className="font-semibold text-ink-primary">{title}.</span> {detail}
              </span>
            </li>
          ))}
        </ol>
      </Panel>

      <Panel title="How the risk score is built">
        <p className="text-xs leading-relaxed text-ink-secondary">
          The MVP uses an interpretable linear baseline whose weights encode the physical priors a
          forecaster would recognise: ensemble spread dominates, then regime change, then analogue
          mismatch. For a linear model the Shapley value of a predictor is exactly its weight times
          its deviation from the dataset mean, so the contributions shown in the explanation panel
          are genuine additive attributions rather than a SHAP-shaped decoration. The score is then
          passed through a logistic calibration so it spreads sensibly across the four bands.
        </p>
        <p className="mt-2.5 text-xs leading-relaxed text-ink-secondary">
          This baseline is deliberately the floor, not the ceiling. The service boundary already has
          the shape a trained, calibrated XGBoost model with a real SHAP explainer will satisfy, so
          replacing the estimator does not change the API or the interface.
        </p>
      </Panel>

      <Panel title="What AtmosGuard is not">
        <ul className="space-y-2 text-xs leading-relaxed text-ink-secondary">
          <li>
            <span className="font-semibold text-ink-primary">Not a weather warning service.</span>{' '}
            A high bust risk says the forecast may be wrong. It says nothing about whether the
            weather will be severe.
          </li>
          <li>
            <span className="font-semibold text-ink-primary">Not a forecast.</span> AtmosGuard does
            not produce its own prediction of rainfall, temperature, wind or pressure.
          </li>
          <li>
            <span className="font-semibold text-ink-primary">Not a replacement for an agency.</span>{' '}
            It is decision support for the people who issue official forecasts and warnings.
          </li>
          <li>
            <span className="font-semibold text-emerald-400">Integrated with IMD Live Networks.</span>{' '}
            Real-time warnings, 24-hr observed rainfall, and 7-day city forecasts are pulled directly from official
            IMD operational services (api.imd.gov.in & GeoServer WFS), augmented with medium-range ensemble guidance.
          </li>
        </ul>
      </Panel>

      <Panel title="Authoritative Datasets & Reference Sources">
        <div className="space-y-3 text-xs leading-relaxed text-ink-secondary">
          <div className="rounded border border-edge bg-surface-2/60 p-3">
            <h4 className="font-semibold text-ink-primary flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              India Meteorological Department (IMD) — Ministry of Earth Sciences
            </h4>
            <p className="mt-1 text-2xs text-ink-secondary">
              National Weather Forecasting Centre (NWFC), Hydromet Division, and GeoServer WFS operational feeds.
              Provides official colour-coded warnings (Red/Orange/Yellow/Green), 113-station daily observations, and sub-divisional rainfall normals (1901–2017).
            </p>
          </div>
          <div className="rounded border border-edge bg-surface-2/60 p-3">
            <h4 className="font-semibold text-ink-primary">
              European Centre for Medium-Range Weather Forecasts (ECMWF)
            </h4>
            <p className="mt-1 text-2xs text-ink-secondary">
              51-member Integrated Forecasting System (IFS) ensemble open data, geopotential height spread, and convective precipitation dispersion.
            </p>
          </div>
          <div className="rounded border border-edge bg-surface-2/60 p-3">
            <h4 className="font-semibold text-ink-primary">
              NCMRWF &amp; NOAA Global Historical Climatology Network (GHCN-D)
            </h4>
            <p className="mt-1 text-2xs text-ink-secondary">
              Indian regional numerical weather models (NEPS) and 28-station long-term synoptic observation benchmarks (1995–2021).
            </p>
          </div>
        </div>
      </Panel>

      <Panel title="Intended users">
        <div className="grid gap-2.5 sm:grid-cols-2">
          {[
            ['Meteorologist / forecaster', 'Primary user. Decides how much weight to give a medium-range forecast.'],
            ['Disaster management authority', 'Judges how firm the guidance behind a planning decision is.'],
            ['Emergency response team', 'Understands when a forecast may change materially.'],
            ['Government decision-maker', 'Sees where confidence is thin before committing resources.'],
          ].map(([role, detail]) => (
            <div key={role} className="rounded-md border border-edge bg-surface-2/55 p-3">
              <p className="text-xs font-semibold text-ink-primary">{role}</p>
              <p className="mt-0.5 text-2xs leading-relaxed text-ink-muted">{detail}</p>
            </div>
          ))}
        </div>
      </Panel>

      {meta.data && (
        <Panel title="Build">
          <dl className="space-y-1.5 text-2xs">
            <div className="flex justify-between gap-3">
              <dt className="text-ink-muted">Version</dt>
              <dd className="font-medium tabular text-ink-primary">{meta.data.version}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-ink-muted">Data mode</dt>
              <dd className="font-medium capitalize text-ink-primary">{meta.data.data_mode}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-ink-muted">Monitored sites</dt>
              <dd className="font-medium tabular text-ink-primary">
                {meta.data.locations.length + meta.data.regions.length}
              </dd>
            </div>
          </dl>
        </Panel>
      )}
    </div>
  );
}
