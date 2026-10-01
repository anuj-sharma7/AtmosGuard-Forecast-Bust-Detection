/**
 * Rebuild a 7-day station replay from its static sidecar file.
 *
 * The static build carries every forecast from 2010-01-01 to 2021-12-24 - far
 * too many to embed as ready-made payloads - so each station's are packed into
 * integers by `backend/scripts/export_station_sidecar.py` and unpacked here.
 *
 * This module makes **no scoring decision of its own**. Every forecast value
 * was produced by the same Python function the live API uses, and every
 * bust/verdict flag by the same scoring function; they arrive here as packed
 * integers. What is computed here is only what cannot drift: dates, unit
 * scaling, and the verdict read off those flags. A Node parity check compares
 * the result with the live API field by field.
 */

import type {
  ReplayOutcome,
  StationForecastDay,
  StationReplay,
  StationValidationRow,
} from '../api/types';

export interface StationSidecar {
  v: number;
  station: StationReplay['station'];
  origin0: string;
  n: number;
  obs0: string;
  obs: { tmax: (number | null)[]; tmin: (number | null)[]; prcp: (number | null)[] };
  normals: { tmax: number[]; tmin: number[]; rain_prob: (number | null)[] };
  thresholds: StationReplay['thresholds'];
  forecast_note: string;
  fc: {
    tmax: number[];
    tmin: number[];
    rain_mm: number[];
    p_rain: number[];
    bust: number[];
    bust_t: number[];
    bust_r: number[];
  };
  flags: number[];
  station_page: string;
}

/** IMD daily rainfall classes, lower bounds in integer tenths of a mm. */
const RAIN_CLASSES: [string, number][] = [
  ['No / very light', 0],
  ['Light', 25],
  ['Moderate', 156],
  ['Heavy', 645],
  ['Very heavy', 1156],
  ['Extremely heavy', 2045],
];

const DAY_MS = 86_400_000;
const LEADS = [1, 2, 3, 4, 5, 6, 7];

function utc(iso: string): number {
  const [y, m, d] = iso.split('-').map(Number);
  return Date.UTC(y, m - 1, d);
}

function iso(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

function daysBetween(fromIso: string, toMs: number): number {
  return Math.round((toMs - utc(fromIso)) / DAY_MS);
}

/** Zero-based day of year, matching Python's `tm_yday - 1`. */
function dayOfYear(ms: number): number {
  const d = new Date(ms);
  return Math.round((ms - Date.UTC(d.getUTCFullYear(), 0, 1)) / DAY_MS);
}

function rainClassLabel(tenths: number): string {
  let label = RAIN_CLASSES[0][0];
  for (const [name, lower] of RAIN_CLASSES) if (tenths >= lower) label = name;
  return label;
}

function tri(bits: number): boolean | null {
  return bits === 0 ? false : bits === 1 ? true : null;
}

function scaled(value: number | null | undefined, by: number): number | null {
  return value === null || value === undefined ? null : value / by;
}

export function lastOrigin(side: StationSidecar): string {
  return iso(utc(side.origin0) + (side.n - 1) * DAY_MS);
}

export function rebuildReplay(side: StationSidecar, origin: string): StationReplay {
  const t = utc(origin);
  const k = daysBetween(side.origin0, t);
  if (k < 0 || k >= side.n) {
    throw new RangeError(
      `Pick a date between ${side.origin0} and ${lastOrigin(side)}: the replay needs seven ` +
        'days of record after the date it forecasts from.',
    );
  }
  const threshold10k = Math.round(side.thresholds.bust_any * 10_000);

  const forecast: StationForecastDay[] = [];
  const rows: StationValidationRow[] = [];

  for (const lead of LEADS) {
    const row = k * 7 + lead - 1;
    const target = t + lead * DAY_MS;
    const doy = dayOfYear(target);
    const fc = side.fc;

    forecast.push({
      lead,
      date: iso(target),
      tmax_c: fc.tmax[row] / 10,
      tmin_c: fc.tmin[row] / 10,
      rain_probability: fc.p_rain[row] / 1000,
      rain_mm: fc.rain_mm[row] / 10,
      rain_class: rainClassLabel(fc.rain_mm[row]),
      normal_tmax_c: side.normals.tmax[doy] / 10,
      normal_tmin_c: side.normals.tmin[doy] / 10,
      normal_rain_probability: scaled(side.normals.rain_prob[doy], 1000),
      bust_probability: fc.bust[row] / 10_000,
      bust_probability_temperature: fc.bust_t[row] / 10_000,
      bust_probability_rain: fc.bust_r[row] / 10_000,
    });

    const i = daysBetween(side.obs0, target);
    const obTmax = side.obs.tmax[i] ?? null;
    const obTmin = side.obs.tmin[i] ?? null;
    const obRain = side.obs.prcp[i] ?? null;
    const f = side.flags[row];
    const temperatureBust = tri(f & 3);
    const rainBust = tri((f >> 2) & 3);
    const actual =
      temperatureBust === null && rainBust === null ? null : temperatureBust === true || rainBust === true;
    const predicted = fc.bust[row] >= threshold10k;
    const verdict: ReplayOutcome =
      actual === null
        ? 'not verifiable'
        : predicted && actual
          ? 'hit'
          : predicted
            ? 'false alarm'
            : actual
              ? 'miss'
              : 'correct negative';

    rows.push({
      lead,
      date: iso(target),
      observed_tmax_c: scaled(obTmax, 10),
      observed_tmin_c: scaled(obTmin, 10),
      observed_rain_mm: scaled(obRain, 10),
      observed_rain_class: obRain === null ? null : rainClassLabel(obRain),
      tmax_error_c: obTmax === null ? null : (fc.tmax[row] - obTmax) / 10,
      tmin_error_c: obTmin === null ? null : (fc.tmin[row] - obTmin) / 10,
      tmax_within_2c: tri((f >> 4) & 3),
      rain_correct: tri((f >> 6) & 3),
      temperature_bust: temperatureBust,
      rain_bust: rainBust,
      actual_bust: actual,
      predicted_bust: predicted,
      verdict,
      rain_reported: obRain !== null,
    });
  }

  const history = [];
  for (let back = 6; back >= 0; back--) {
    const day = t - back * DAY_MS;
    const i = daysBetween(side.obs0, day);
    history.push({
      date: iso(day),
      tmax_c: scaled(side.obs.tmax[i], 10),
      tmin_c: scaled(side.obs.tmin[i], 10),
      rain_mm: scaled(side.obs.prcp[i], 10),
    });
  }

  return {
    station: side.station,
    origin,
    evidence_through: origin,
    history,
    forecast,
    thresholds: side.thresholds,
    held_out: true,
    forecast_note: side.forecast_note,
    validation: {
      rows,
      summary: summarise(rows),
      source: 'NOAA GHCN-Daily, quality-controlled station observations.',
      station_page: side.station_page,
    },
  };
}

/** Mirrors `station_replay.summarise`, including its integer-tenths MAE. */
function summarise(rows: StationValidationRow[]): StationReplay['validation']['summary'] {
  const verified = rows.filter((r) => r.actual_bust !== null);
  const tmaxChecked = rows.filter((r) => r.tmax_within_2c !== null);
  const rainChecked = rows.filter((r) => r.rain_correct !== null);
  const counts: Record<string, number> = {};
  for (const r of verified) counts[r.verdict] = (counts[r.verdict] ?? 0) + 1;
  const tenths = tmaxChecked.map((r) => Math.abs(Math.round((r.tmax_error_c as number) * 10)));
  return {
    days_verified: verified.length,
    ...counts,
    tmax_within_2c: tmaxChecked.filter((r) => r.tmax_within_2c).length,
    tmax_checked: tmaxChecked.length,
    tmax_mae_c: tmaxChecked.length
      ? Math.floor((tenths.reduce((a, b) => a + b, 0) * 10) / tmaxChecked.length + 0.5) / 100
      : null,
    rain_correct: rainChecked.filter((r) => r.rain_correct).length,
    rain_checked: rainChecked.length,
    bust_correct: (counts['hit'] ?? 0) + (counts['correct negative'] ?? 0),
  };
}
