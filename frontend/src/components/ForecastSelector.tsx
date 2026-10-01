/**
 * The selection controls. Every control here drives the single shared
 * selection, so changing any one of them re-derives the whole application.
 */

import { useAppState } from '../state/AppState';
import { InfoTip } from './Primitives';

function Segmented<T extends string | number>({
  label,
  tip,
  options,
  value,
  onChange,
}: {
  label: string;
  tip?: string;
  options: { value: T; label: string; hint?: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div>
      <p className="mb-1.5 flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wider text-ink-muted">
        {label}
        {tip && <InfoTip text={tip} label={label} />}
      </p>
      <div className="flex flex-wrap gap-1" role="group" aria-label={label}>
        {options.map((option) => (
          <button
            key={String(option.value)}
            type="button"
            title={option.hint}
            aria-pressed={option.value === value}
            onClick={() => onChange(option.value)}
            className={`segment ${option.value === value ? 'segment-active' : ''}`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function ForecastSelector({ compact = false }: { compact?: boolean }) {
  const { meta, selection, setHorizon, setVariable, setModel } = useAppState();
  if (!meta.data || !selection) return null;

  return (
    <div className={compact ? 'grid gap-3 sm:grid-cols-3' : 'space-y-4'}>
      <Segmented
        label="Forecast horizon"
        tip="How many days ahead the forecast is valid. Medium-range forecasts (Day 3-7) are where bust risk matters most."
        value={selection.horizon}
        onChange={setHorizon}
        options={meta.data.horizons.map((h) => ({ value: h, label: `Day ${h}` }))}
      />
      <Segmented
        label="Weather variable"
        tip="The forecast field being assessed. Rainfall is the hardest to predict at medium range and busts most often."
        value={selection.variable_id}
        onChange={setVariable}
        options={meta.data.variables.map((v) => ({ value: v.id, label: v.label }))}
      />
      <Segmented
        label="NWP model"
        tip="Which numerical weather prediction system supplies the forecast and its ensemble."
        value={selection.model_id}
        onChange={setModel}
        options={meta.data.models.map((m) => ({ value: m.id, label: m.label, hint: m.centre }))}
      />
    </div>
  );
}
