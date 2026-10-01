/**
 * 7-day station replay, 2010-2017.
 *
 * The question this answers is the one people actually arrive with: "if I pick
 * a date that has already happened, does the forecast for the following week
 * match what then happened?" So the page is laid out as that experiment: what
 * the model saw, what it forecast, what then occurred, and the verdict - with
 * the rows the reader can check for themselves on any public archive.
 *
 * Every observed number is a NOAA GHCN-Daily station observation. A day the
 * station did not report shows a dash, and is not scored.
 */

import { useMemo } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { StationReplay, StationsMeta } from '../api/types';
import { Badge } from './Primitives';
import { OutcomeChip } from './ReplayPanels';
import { SERIES } from '../lib/risk';
import { formatShortDate } from '../lib/format';

/** Validated pair (dark surface): forecast blue, observation orange. */
const FORECAST = SERIES.primary;
const OBSERVED = SERIES.tertiary;

const TOOLTIP_STYLE = {
  background: '#1a273c',
  border: '1px solid #2b3d5c',
  borderRadius: 6,
  fontSize: 11,
};

function fmt(value: number | null | undefined, digits = 1, unit = ''): string {
  return value === null || value === undefined ? '—' : `${value.toFixed(digits)}${unit}`;
}

function Check({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="text-ink-muted">—</span>;
  return ok ? (
    <span className="font-medium text-risk-low">✓</span>
  ) : (
    <span className="font-medium text-risk-severe">✗</span>
  );
}

export function StationReplayPanel({
  meta,
  data,
  date,
  station,
  onDateChange,
  onStationChange,
  busy,
  error,
}: {
  meta: StationsMeta | null;
  data: StationReplay | null;
  date: string;
  station: string;
  onDateChange: (value: string) => void;
  onStationChange: (value: string) => void;
  busy: boolean;
  error: string | null;
}) {
  const rows = useMemo(() => {
    if (!data) return [];
    const byDate = new Map(data.validation.rows.map((r) => [r.date, r]));
    return data.forecast.map((f) => ({ f, v: byDate.get(f.date)! }));
  }, [data]);

  const tempChart = useMemo(() => {
    if (!data) return [];
    const history = data.history.map((h) => ({
      label: formatShortDate(h.date),
      observed: h.tmax_c,
      forecast: null as number | null,
    }));
    // The origin day carries both series so the forecast line visibly starts
    // from what was known at T.
    if (history.length) history[history.length - 1].forecast = history[history.length - 1].observed;
    return [
      ...history,
      ...rows.map(({ f, v }) => ({
        label: formatShortDate(f.date),
        observed: v.observed_tmax_c,
        forecast: f.tmax_c,
      })),
    ];
  }, [data, rows]);

  const bustChart = useMemo(
    () =>
      rows.map(({ f, v }) => ({
        label: `D${f.lead}`,
        probability: Number((f.bust_probability * 100).toFixed(1)),
        actual: v.actual_bust,
        verdict: v.verdict,
      })),
    [rows],
  );

  const summary = data?.validation.summary;
  const threshold = data?.thresholds.bust_any ?? meta?.thresholds.bust_any ?? 0.28;
  const selectedStation = meta?.stations.find((s) => s.station_id === station);

  return (
    <div className="space-y-4">
      {/* ------------------------------ Framing ------------------------------ */}
      <section className="panel border-l-2 border-l-accent px-4 py-3">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h3 className="text-[13px] font-semibold text-ink-primary">
            Pick a date that already happened. See the next 7 days forecast — then what actually
            happened.
          </h3>
          <Badge tone="accent">Held-out {meta ? `${meta.test_period[0].slice(0, 4)}–${meta.test_period[1].slice(0, 4)}` : '2010–2021'}</Badge>
        </div>
        <p className="mt-1.5 text-[11px] leading-relaxed text-ink-secondary">
          The model was fitted on <strong className="text-ink-primary">1995–2009 only</strong>.
          Every date from 2010 to 2021 is one it has never seen, and it forecasts using nothing
          after the date you pick. The observations it is then checked against are real NOAA
          GHCN-Daily station records.
        </p>
        {meta && (
          <p className="mt-2 border-t border-edge pt-2 text-2xs leading-relaxed text-ink-muted">
            {meta.forecast_note} A day is a <strong className="text-ink-secondary">bust</strong>{' '}
            when {meta.bust_definition.temperature.charAt(0).toLowerCase()}
            {meta.bust_definition.temperature.slice(1, -1)}, or when{' '}
            {meta.bust_definition.rain.charAt(0).toLowerCase()}
            {meta.bust_definition.rain.slice(1)}
          </p>
        )}
      </section>

      {/* ------------------------------ Controls ----------------------------- */}
      <section className="panel px-4 py-3">
        <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
          <div>
            <label htmlFor="station-date" className="block text-2xs uppercase tracking-[0.08em] text-ink-muted">
              Forecast date (T)
            </label>
            <input
              id="station-date"
              type="date"
              value={date}
              min={meta?.first_date}
              max={meta?.last_date}
              onChange={(e) => e.target.value && onDateChange(e.target.value)}
              className="mt-1 rounded border border-edge-strong bg-surface-2 px-2.5 py-1.5 text-[13px]
                         tabular text-ink-primary focus:border-accent focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor="station-id" className="block text-2xs uppercase tracking-[0.08em] text-ink-muted">
              Station
            </label>
            <select
              id="station-id"
              value={station}
              onChange={(e) => onStationChange(e.target.value)}
              className="mt-1 rounded border border-edge-strong bg-surface-2 px-2.5 py-1.5 text-[13px]
                         text-ink-primary focus:border-accent focus:outline-none"
            >
              {[...(meta?.stations ?? [])]
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((s) => (
                  <option key={s.station_id} value={s.station_id}>
                    {s.name}
                  </option>
                ))}
            </select>
          </div>
          {data && (
            <div className="text-[11px]">
              <p className="text-2xs uppercase tracking-[0.08em] text-ink-muted">Model saw data through</p>
              <p className="mt-1 text-[13px] font-semibold tabular text-ink-primary">{data.evidence_through}</p>
            </div>
          )}
          {data && (
            <a
              href={data.validation.station_page}
              target="_blank"
              rel="noreferrer noopener"
              className="ml-auto text-[11px] text-accent hover:underline"
            >
              Check this station on NOAA ↗
            </a>
          )}
        </div>
        {meta?.preview_dates && (
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-edge pt-2.5">
            <span className="text-2xs text-ink-muted">
              Any day from {meta.first_date} to {meta.last_date} works. Quick picks:
            </span>
            {meta.preview_dates.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => onDateChange(d)}
                className={`rounded border px-1.5 py-0.5 text-2xs tabular transition-colors ${
                  d === date
                    ? 'border-accent/55 bg-accent/12 text-accent'
                    : 'border-edge-strong text-ink-secondary hover:border-accent hover:text-accent'
                }`}
              >
                {d}
              </button>
            ))}
          </div>
        )}
        {error && <p className="mt-2 text-[11px] text-risk-severe">{error}</p>}
      </section>

      {/* ------------------------------ Scorecard ---------------------------- */}
      {summary && (
        <section className="panel overflow-hidden">
          <div className="grid grid-cols-2 gap-px bg-edge sm:grid-cols-4">
            {[
              ['Max temp within ±2 °C', `${summary.tmax_within_2c} / ${summary.tmax_checked}`, 'IMD counts ±2 °C as a correct temperature forecast'],
              ['Max temp error', fmt(summary.tmax_mae_c, 2, ' °C'), 'Mean absolute error over the verified days'],
              ['Rain / no-rain correct', `${summary.rain_correct} / ${summary.rain_checked}`, 'Days the station reported rainfall'],
              ['Bust calls correct', `${summary.bust_correct} / ${summary.days_verified}`, 'Hits plus correct negatives'],
            ].map(([label, value, hint]) => (
              <div key={label} className="bg-surface-1 px-4 py-3">
                <p className="text-[10px] font-medium uppercase tracking-[0.09em] text-ink-muted">{label}</p>
                <p className="mt-1.5 text-2xl font-semibold leading-none tabular text-ink-primary">{value}</p>
                <p className="mt-1 text-2xs text-ink-muted">{hint}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {busy && !data && (
        <section className="panel px-4 py-8 text-center text-[11px] text-ink-muted">Running replay…</section>
      )}

      {/* ------------------------------ Day table ---------------------------- */}
      {data && (
        <section className="panel">
          <header className="px-4 pb-2.5 pt-3.5">
            <h2 className="text-[13px] font-semibold tracking-tight text-ink-primary">
              {data.station.name} — forecast on {formatShortDate(data.origin)}, checked against what happened
            </h2>
            <p className="mt-1 text-[11px] leading-snug text-ink-muted">
              Forecast columns were produced before any of these days were read. Observed columns are
              the station's published records. A dash means the station did not report — that day is
              not scored.
            </p>
          </header>
          <div className="overflow-x-auto px-4 pb-4">
            <table className="w-full min-w-[980px] border-collapse text-[11px]">
              <thead>
                <tr className="border-b border-edge-strong text-left text-2xs uppercase tracking-[0.08em] text-ink-muted">
                  <th className="py-2 pr-3 font-medium">Day</th>
                  <th className="py-2 pr-3 text-right font-medium">Max °C<br />forecast</th>
                  <th className="py-2 pr-3 text-right font-medium">Max °C<br />observed</th>
                  <th className="py-2 pr-3 text-center font-medium">±2 °C</th>
                  <th className="py-2 pr-3 text-right font-medium">Min °C<br />fc / obs</th>
                  <th className="py-2 pr-3 text-right font-medium">Rain<br />chance</th>
                  <th className="py-2 pr-3 text-right font-medium">Rain mm<br />observed</th>
                  <th className="py-2 pr-3 text-right font-medium">Bust<br />probability</th>
                  <th className="py-2 pr-3 font-medium">Actually<br />busted?</th>
                  <th className="py-2 font-medium">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ f, v }) => (
                  <tr key={f.date} className="border-b border-edge">
                    <td className="py-2 pr-3">
                      <span className="font-semibold text-ink-primary tabular">D{f.lead}</span>{' '}
                      <span className="text-ink-muted tabular">{formatShortDate(f.date)}</span>
                    </td>
                    <td className="py-2 pr-3 text-right tabular font-medium text-ink-primary">{fmt(f.tmax_c)}</td>
                    <td className="py-2 pr-3 text-right tabular text-ink-secondary">{fmt(v.observed_tmax_c)}</td>
                    <td className="py-2 pr-3 text-center"><Check ok={v.tmax_within_2c} /></td>
                    <td className="py-2 pr-3 text-right tabular text-ink-muted">
                      {fmt(f.tmin_c)} / {fmt(v.observed_tmin_c)}
                    </td>
                    <td className="py-2 pr-3 text-right tabular text-ink-secondary">
                      {(f.rain_probability * 100).toFixed(0)}%
                    </td>
                    <td className="py-2 pr-3 text-right tabular text-ink-secondary">
                      {v.observed_rain_mm === null ? '—' : (
                        <>
                          {v.observed_rain_mm.toFixed(1)}
                          {v.observed_rain_class && v.observed_rain_mm >= 2.5 && (
                            <span className="ml-1 text-2xs text-ink-muted">{v.observed_rain_class}</span>
                          )}
                        </>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-right tabular">
                      <span className={f.bust_probability >= threshold ? 'font-semibold text-risk-high' : 'text-ink-secondary'}>
                        {(f.bust_probability * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-ink-secondary">
                      {v.actual_bust === null ? '—' : v.actual_bust ? 'Yes' : 'No'}
                    </td>
                    <td className="py-2"><OutcomeChip outcome={v.verdict} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-2xs leading-snug text-ink-muted">
              A bust is called when its probability reaches {(threshold * 100).toFixed(0)}% — the
              point matching the bust rate in the training years, fixed before 2010 was scored.
              Rain chance is shown rather than a single amount: a week out, "38% chance of rain" is the
              honest statement, and rounding it to "no rain" would hide that.
            </p>
          </div>
        </section>
      )}

      {/* -------------------------------- Charts ----------------------------- */}
      {data && (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="panel px-4 pb-4 pt-3.5">
            <h2 className="text-[13px] font-semibold text-ink-primary">Max temperature: forecast vs observed</h2>
            <p className="mt-1 text-[11px] text-ink-muted">
              Seven days the model saw, then seven it forecast. °C.
            </p>
            <div className="mt-2 h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={tempChart} margin={{ top: 8, right: 12, bottom: 4, left: -14 }}>
                  <CartesianGrid strokeDasharray="2 4" stroke="#1e2c44" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#66768f' }} tickLine={false} interval={1} />
                  <YAxis
                    domain={[(min: number) => Math.floor(min - 1), (max: number) => Math.ceil(max + 1)]}
                    tick={{ fontSize: 10, fill: '#66768f' }}
                    tickLine={false}
                    axisLine={false}
                    allowDecimals={false}
                  />
                  <Tooltip
                    contentStyle={TOOLTIP_STYLE}
                    formatter={(value, name) => [
                      typeof value === 'number' ? `${value.toFixed(1)} °C` : 'not reported',
                      name === 'forecast' ? 'Forecast' : 'Observed',
                    ]}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: 11, color: '#9aa9bf' }}
                    formatter={(value) => (value === 'forecast' ? 'Forecast' : 'Observed')}
                  />
                  <ReferenceLine
                    x={formatShortDate(data.origin)}
                    stroke="#2b3d5c"
                    strokeDasharray="4 3"
                    label={{ value: 'T', fontSize: 10, fill: '#9aa9bf', position: 'insideTopLeft' }}
                  />
                  <Line type="monotone" dataKey="observed" stroke={OBSERVED} strokeWidth={2}
                        strokeDasharray="5 3" dot={{ r: 4, strokeWidth: 0, fill: OBSERVED }} connectNulls={false} />
                  <Line type="monotone" dataKey="forecast" stroke={FORECAST} strokeWidth={2}
                        dot={{ r: 4, strokeWidth: 0, fill: FORECAST }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="panel px-4 pb-4 pt-3.5">
            <h2 className="text-[13px] font-semibold text-ink-primary">Bust probability, day by day</h2>
            <p className="mt-1 text-[11px] text-ink-muted">
              Dashed line: the call threshold. Bars are labelled with what actually happened.
            </p>
            <div className="mt-2 h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={bustChart} margin={{ top: 18, right: 12, bottom: 4, left: -14 }}>
                  <CartesianGrid strokeDasharray="2 4" stroke="#1e2c44" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#66768f' }} tickLine={false} />
                  <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 10, fill: '#66768f' }} tickLine={false} axisLine={false} />
                  <Tooltip
                    contentStyle={TOOLTIP_STYLE}
                    cursor={{ fill: 'rgba(154,169,191,0.08)' }}
                    formatter={(value: number, _n, item) => [
                      `${value}% — actually busted: ${
                        item?.payload?.actual === null ? 'not verifiable' : item?.payload?.actual ? 'yes' : 'no'
                      }`,
                      'Bust probability',
                    ]}
                  />
                  <ReferenceLine y={threshold * 100} stroke="#9aa9bf" strokeDasharray="4 3" />
                  <Bar
                    dataKey="probability"
                    radius={[4, 4, 0, 0]}
                    barSize={26}
                  >
                    {bustChart.map((d) => (
                      <Cell key={d.label} fill={FORECAST} fillOpacity={d.probability >= threshold * 100 ? 1 : 0.55} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {bustChart.map((d) => (
                <span key={d.label} className="inline-flex items-center gap-1 text-2xs text-ink-muted">
                  {d.label} <OutcomeChip outcome={d.verdict} />
                </span>
              ))}
            </div>
          </section>
        </div>
      )}

      {/* --------------------------- Track record ---------------------------- */}
      {meta && (
        <section className="panel">
          <header className="px-4 pb-2.5 pt-3.5">
            <h2 className="text-[13px] font-semibold text-ink-primary">
              Track record across every day of 2010–2021
            </h2>
            <p className="mt-1 text-[11px] text-ink-muted">
              {meta.overall.rows.toLocaleString()} forecasts at {meta.stations.length} stations, none
              of them seen in fitting. One week can go well or badly by luck — this is the number to
              judge the model on.
            </p>
          </header>
          <div className="grid grid-cols-2 gap-px border-y border-edge bg-edge sm:grid-cols-4">
            {[
              ['Max temp within ±2 °C', `${(meta.overall.tmax_within_2c * 100).toFixed(1)}%`],
              ['Max temp error', `${meta.overall.tmax_mae_c} °C`, `normal-only forecast: ${meta.overall.tmax_mae_climatology_c} °C`],
              ['Rain / no-rain correct', `${(meta.overall.rain_day_accuracy * 100).toFixed(1)}%`, `normal-only forecast: ${(meta.overall.rain_day_accuracy_climatology * 100).toFixed(1)}%`],
              ['Bust ROC-AUC', meta.bust_any.roc_auc?.toFixed(3) ?? '—', '0.5 = no skill, 1.0 = perfect'],
            ].map(([label, value, hint]) => (
              <div key={label} className="bg-surface-1 px-4 py-3">
                <p className="text-[10px] font-medium uppercase tracking-[0.09em] text-ink-muted">{label}</p>
                <p className="mt-1.5 text-xl font-semibold leading-none tabular text-ink-primary">{value}</p>
                {hint && <p className="mt-1 text-2xs text-ink-muted">{hint}</p>}
              </div>
            ))}
          </div>
          <div className="overflow-x-auto px-4 pb-4 pt-3">
            <table className="w-full min-w-[640px] border-collapse text-[11px]">
              <thead>
                <tr className="border-b border-edge-strong text-left text-2xs uppercase tracking-[0.08em] text-ink-muted">
                  <th className="py-1.5 pr-3 font-medium">Lead</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Max temp error</th>
                  <th className="py-1.5 pr-3 text-right font-medium">"Same as today"</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Normal only</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Within ±2 °C</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Rain correct</th>
                  <th className="py-1.5 text-right font-medium">Bust AUC</th>
                </tr>
              </thead>
              <tbody>
                {meta.by_lead.map((r) => (
                  <tr key={r.lead} className="border-b border-edge">
                    <td className="py-1.5 pr-3 font-semibold text-ink-primary">Day {r.lead}</td>
                    <td className="py-1.5 pr-3 text-right tabular font-medium text-ink-primary">
                      {r.tmax_mae_same_rows_as_persistence_c.toFixed(2)} °C
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular text-ink-muted">{r.tmax_mae_persistence_c.toFixed(2)} °C</td>
                    <td className="py-1.5 pr-3 text-right tabular text-ink-muted">{r.tmax_mae_climatology_c.toFixed(2)} °C</td>
                    <td className="py-1.5 pr-3 text-right tabular text-ink-secondary">{(r.tmax_within_2c * 100).toFixed(0)}%</td>
                    <td className="py-1.5 pr-3 text-right tabular text-ink-secondary">{(r.rain_day_accuracy * 100).toFixed(0)}%</td>
                    <td className="py-1.5 text-right tabular text-ink-secondary">{r.bust_auc?.toFixed(3) ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-2xs leading-relaxed text-ink-muted">
              "Same as today" is the forecast that tomorrow repeats today; "normal only" forecasts the
              long-term average for the date. At Day 1 the model ties "same as today" — temperature is
              that persistent — and from Day 2 it beats both. Rain is the weak spot: a week out, from
              station records alone, rain/no-rain is only a point or so better than the calendar.
              {selectedStation && ` Station ${selectedStation.station_id}, ${selectedStation.lat.toFixed(2)}°N ${selectedStation.lon.toFixed(2)}°E.`}
              {' '}Source: {meta.source}
            </p>
          </div>

          <div className="border-t border-edge px-4 pb-4 pt-3">
            <h3 className="text-[12px] font-semibold text-ink-primary">Year by year</h3>
            <p className="mt-0.5 text-2xs text-ink-muted">
              Every year is held out. 2018–2021 are as far from the training data as the model gets,
              and they score the same as 2010 — the skill does not fade.
            </p>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[560px] border-collapse text-[11px]">
                <thead>
                  <tr className="border-b border-edge-strong text-left text-2xs uppercase tracking-[0.08em] text-ink-muted">
                    <th className="py-1.5 pr-3 font-medium">Year</th>
                    <th className="py-1.5 pr-3 text-right font-medium">Forecasts</th>
                    <th className="py-1.5 pr-3 text-right font-medium">Within ±2 °C</th>
                    <th className="py-1.5 pr-3 text-right font-medium">Max temp error</th>
                    <th className="py-1.5 pr-3 text-right font-medium">Bust rate</th>
                    <th className="py-1.5 text-right font-medium">Bust AUC</th>
                  </tr>
                </thead>
                <tbody>
                  {meta.by_year.map((r) => (
                    <tr key={r.year} className="border-b border-edge">
                      <td className="py-1.5 pr-3 font-semibold text-ink-primary tabular">{r.year}</td>
                      <td className="py-1.5 pr-3 text-right tabular text-ink-muted">{r.forecasts.toLocaleString()}</td>
                      <td className="py-1.5 pr-3 text-right tabular text-ink-secondary">{(r.tmax_within_2c * 100).toFixed(0)}%</td>
                      <td className="py-1.5 pr-3 text-right tabular text-ink-secondary">{r.tmax_mae_c.toFixed(2)} °C</td>
                      <td className="py-1.5 pr-3 text-right tabular text-ink-muted">{(r.bust_rate * 100).toFixed(0)}%</td>
                      <td className="py-1.5 text-right tabular text-ink-secondary">{r.bust_auc?.toFixed(3) ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="border-t border-edge px-4 pb-4 pt-3">
            <h3 className="text-[12px] font-semibold text-ink-primary">Why this page does not headline "accuracy"</h3>
            <p className="mt-1 text-[11px] leading-relaxed text-ink-secondary">
              Only {((1 - meta.bust_any.call_accuracy_always_no) * 100).toFixed(0)}% of days bust. A
              rule that <em>always</em> says "no bust" is therefore right{' '}
              <strong className="text-ink-primary">{(meta.bust_any.call_accuracy_always_no * 100).toFixed(1)}%</strong>{' '}
              of the time while being useless — it never warns of anything. This model's calls are
              right {(meta.bust_any.call_accuracy_operating * 100).toFixed(1)}% of the time because it
              deliberately trades some of that for catching busts. So a high accuracy figure — 90%
              or any other — says almost nothing here. ROC-AUC ({meta.bust_any.roc_auc?.toFixed(3)})
              measures what matters: whether days that bust get higher probabilities than days that
              don't.
            </p>
          </div>
        </section>
      )}
    </div>
  );
}
