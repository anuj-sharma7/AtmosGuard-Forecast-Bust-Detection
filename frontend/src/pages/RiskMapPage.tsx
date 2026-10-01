/** Full-screen risk map with layer, variable, lead-time and severity filters. */

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import {
  BASEMAPS,
  MAP_LAYERS,
  RiskMap,
  type BasemapKey,
  type MapLayer,
} from '../components/RiskMap';
import { ErrorState, InfoTip, LoadingState, Panel, RiskChip } from '../components/Primitives';
import { useAppState } from '../state/AppState';
import type { RiskCategory } from '../api/types';
import { RISK_ORDER, riskColor } from '../lib/risk';
import { formatDate } from '../lib/format';

type SeverityFilter = 'ALL' | RiskCategory;

export function RiskMapPage() {
  const { meta, network, selection, setLocation, setVariable, setHorizon, setModel, reload } =
    useAppState();
  const navigate = useNavigate();
  const [layer, setLayer] = useState<MapLayer>('risk');
  const [basemap, setBasemap] = useState<BasemapKey>('vector');
  const [severity, setSeverity] = useState<SeverityFilter>('ALL');

  const sites = useMemo(() => {
    const all = network.data?.sites ?? [];
    return severity === 'ALL' ? all : all.filter((s) => s.risk_category === severity);
  }, [network.data, severity]);

  if (network.error) return <ErrorState message={network.error} onRetry={reload} />;

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Panel
        title="Forecast bust risk map"
        subtitle={
          network.data
            ? `${sites.length} of ${network.data.network_size} sites - Day ${network.data.horizon} ${
                meta.data?.variables.find((v) => v.id === network.data?.variable_id)?.label ?? ''
              }`
            : undefined
        }
        tip="Risk is encoded by colour and by marker size together, so the ordering survives for colour-vision-deficient readers and in greyscale."
        updated={selection ? formatDate(selection.base_date) : undefined}
        bodyClassName="p-0"
        className="min-h-[640px]"
      >
        <div className="h-[calc(100vh-240px)] min-h-[520px] w-full p-1">
          {network.data ? (
            <RiskMap
              sites={sites}
              selectedId={selection?.location_id}
              onSelect={setLocation}
              layer={layer}
              basemap={basemap}
            />
          ) : (
            <div className="p-3">
              <LoadingState label="Loading network" rows={5} />
            </div>
          )}
        </div>
      </Panel>

      <div className="space-y-4">
        <Panel title="Map layer" subtitle="What the marker colour represents">
          <div className="space-y-1.5">
            {MAP_LAYERS.map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => setLayer(option.id)}
                aria-pressed={layer === option.id}
                className={`flex w-full items-center justify-between gap-2 rounded border px-2.5 py-2
                            text-left text-xs transition-colors ${
                              layer === option.id
                                ? 'border-accent/60 bg-accent/12 text-accent'
                                : 'border-edge bg-surface-2 text-ink-secondary hover:text-ink-primary'
                            }`}
              >
                {option.label}
                <InfoTip text={option.tip} label={option.label} />
              </button>
            ))}
          </div>
        </Panel>

        <Panel title="Filters">
          <div className="space-y-3.5">
            <Filter label="Forecast day">
              {(meta.data?.horizons ?? []).map((h) => (
                <button
                  key={h}
                  type="button"
                  onClick={() => setHorizon(h)}
                  aria-pressed={selection?.horizon === h}
                  className={`segment ${selection?.horizon === h ? 'segment-active' : ''}`}
                >
                  {h}
                </button>
              ))}
            </Filter>

            <Filter label="Variable">
              {(meta.data?.variables ?? []).map((v) => (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => setVariable(v.id)}
                  aria-pressed={selection?.variable_id === v.id}
                  className={`segment ${selection?.variable_id === v.id ? 'segment-active' : ''}`}
                >
                  {v.label}
                </button>
              ))}
            </Filter>

            <Filter label="Model">
              {(meta.data?.models ?? []).map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setModel(m.id)}
                  aria-pressed={selection?.model_id === m.id}
                  className={`segment ${selection?.model_id === m.id ? 'segment-active' : ''}`}
                >
                  {m.label}
                </button>
              ))}
            </Filter>

            <Filter label="Risk band">
              {(['ALL', ...RISK_ORDER] as SeverityFilter[]).map((band) => (
                <button
                  key={band}
                  type="button"
                  onClick={() => setSeverity(band)}
                  aria-pressed={severity === band}
                  className={`segment ${severity === band ? 'segment-active' : ''}`}
                >
                  {band === 'ALL' ? 'All' : band}
                </button>
              ))}
            </Filter>
          </div>
        </Panel>

        <Panel
          title="Highest risk sites"
          subtitle={network.data ? `${network.data.counts.SEVERE} severe, ${network.data.counts.HIGH} high` : undefined}
          bodyClassName="px-2 py-2"
        >
          {network.data ? (
            <ul className="max-h-[320px] space-y-1 overflow-auto">
              {sites.slice(0, 14).map((site) => (
                <li key={site.id}>
                  <button
                    type="button"
                    onClick={() => setLocation(site.id)}
                    className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1.5
                                text-left transition-colors hover:bg-surface-2 ${
                                  site.id === selection?.location_id ? 'bg-surface-2' : ''
                                }`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-xs text-ink-primary">{site.name}</span>
                      <span className="block truncate text-2xs text-ink-muted">{site.top_driver}</span>
                    </span>
                    <span
                      className="shrink-0 text-sm font-bold tabular"
                      style={{ color: riskColor(site.risk_category) }}
                    >
                      {site.risk_score.toFixed(0)}%
                    </span>
                  </button>
                </li>
              ))}
              {sites.length === 0 && (
                <li className="px-2 py-4 text-center text-2xs text-ink-muted">
                  No sites in this risk band for the current selection.
                </li>
              )}
            </ul>
          ) : (
            <LoadingState rows={4} />
          )}
        </Panel>

        <Panel
          title="Base layer"
          subtitle="Vector needs no network"
          bodyClassName="px-4 py-3"
        >
          <div className="flex gap-1.5">
            {(Object.keys(BASEMAPS) as BasemapKey[]).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setBasemap(key)}
                aria-pressed={basemap === key}
                className={`segment ${basemap === key ? 'segment-active' : ''}`}
              >
                {BASEMAPS[key].label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => navigate('/analysis')}
            className="mt-3 w-full rounded border border-accent/50 bg-accent/12 px-3 py-1.5
                       text-xs font-semibold text-accent hover:bg-accent/20"
          >
            Analyse selected location
          </button>
          {network.data?.highest_risk && (
            <p className="mt-2 flex items-center justify-between text-2xs text-ink-muted">
              Network peak
              <RiskChip
                category={network.data.highest_risk.risk_category}
                score={network.data.highest_risk.risk_score}
                size="sm"
              />
            </p>
          )}
        </Panel>
      </div>
    </div>
  );
}

function Filter({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-ink-muted">{label}</p>
      <div className="flex flex-wrap gap-1">{children}</div>
    </div>
  );
}
