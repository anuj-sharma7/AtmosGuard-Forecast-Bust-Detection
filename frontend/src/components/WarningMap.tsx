/**
 * State warning map, in the four-colour scheme Indian forecasters read without
 * a key. Powered by the enhanced ImdWeatherMap.
 */

import type { StateWarning, WarningsResponse } from '../api/types';
import { ImdWeatherMap } from './ImdWeatherMap';

export function WarningMap({
  data,
  height = 520,
  onSelectState,
}: {
  data: WarningsResponse;
  height?: number | string;
  onSelectState?: (state: StateWarning) => void;
}) {
  return (
    <div>
      <div className="mb-2.5 flex items-start gap-2 rounded-md border border-risk-moderate/45 bg-risk-moderate/10 px-3 py-2">
        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-risk-moderate" aria-hidden />
        <p className="text-2xs leading-relaxed text-ink-secondary">
          <span className="font-semibold text-risk-moderate">
            Official IMD-style Warning Map & Forecast Reliability Factors.
          </span>{' '}
          Colours indicate early-warning severity levels. Icons highlight primary meteorological
          hazards (Thunderstorm, Heavy Rain, Winds, Heat Wave, etc.) and synoptic transition risks.
        </p>
      </div>

      <ImdWeatherMap
        warnings={data}
        height={height}
        horizon={data.horizon}
        baseDate={data.base_date}
        onSelectState={onSelectState}
      />
    </div>
  );
}
