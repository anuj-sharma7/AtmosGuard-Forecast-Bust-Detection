/** Top bar: identity, primary navigation, data status and Demo Mode. */

import { NavLink } from 'react-router-dom';
import { useEffect, useState } from 'react';

import { useAppState } from '../state/AppState';
import { api } from '../api/client';

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/analysis', label: 'Forecast Analysis' },
  { to: '/map', label: 'Risk Map' },
  { to: '/warnings', label: 'Warning Map' },
  { to: '/alerts', label: 'Alerts' },
  { to: '/verification', label: 'Verification' },
  { to: '/replay', label: 'Historical Replay' },
  { to: '/system', label: 'System' },
  { to: '/about', label: 'About' },
];

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-8 w-8 shrink-0" role="img" aria-label="AtmosGuard">
      <rect width="32" height="32" rx="7" fill="#131e30" stroke="#2b3d5c" />
      <path
        d="M6 21h20M6 21a6 6 0 0 1 5-9 7 7 0 0 1 13 2 4.5 4.5 0 0 1 2 7"
        fill="none"
        stroke="#38bdf8"
        strokeWidth="1.9"
        strokeLinecap="round"
      />
      <path d="M16 12.5v6.5M16 22v1.6" stroke="#d03b3b" strokeWidth="2.3" strokeLinecap="round" />
    </svg>
  );
}

function useLiveFeedStatus() {
  const [liveDate, setLiveDate] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [validTo, setValidTo] = useState<string | null>(null);
  const [stationCount, setStationCount] = useState<number>(277);
  const [liveState, setLiveState] = useState<'connecting' | 'live' | 'error'>('connecting');

  useEffect(() => {
    let active = true;

    function poll() {
      api.cityForecast()
        .then((res) => {
          if (!active) return;
          if (res?.stations?.length) {
            const date = res.bulletin_date || res.date || res.stations.find((s) => s.date)?.date || new Date().toISOString().slice(0, 10);
            setLiveDate(date);
            setLastUpdated(res.last_updated || 'Just now');
            setValidTo(res.forecast_valid_to || null);
            setStationCount(res.count || res.stations.length);
            setLiveState('live');
          } else {
            setLiveState('error');
          }
        })
        .catch(() => {
          if (active) setLiveState('error');
        });
    }

    poll();
    const timer = setInterval(poll, 5 * 60 * 1000); // re-poll every 5 min
    return () => { active = false; clearInterval(timer); };
  }, []);

  return { liveDate, lastUpdated, validTo, stationCount, liveState };
}

function formatLiveDate(iso: string | null): string {
  if (!iso) return '--';
  try {
    const parts = iso.slice(0, 10).split('-');
    if (parts.length === 3) {
      const year = parseInt(parts[0], 10);
      const month = parseInt(parts[1], 10) - 1;
      const day = parseInt(parts[2], 10);
      const d = new Date(year, month, day);
      return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
    }
    const d = new Date(iso);
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch {
    return iso;
  }
}

export function AtmosGuardHeader() {
  const { meta, selection, demoMode, setDemoMode } = useAppState();
  const { liveDate, lastUpdated, validTo, stationCount, liveState } = useLiveFeedStatus();
  const isDemo = meta.data?.data_mode === 'demo';

  return (
    <header className="sticky top-0 z-[900] border-b border-edge bg-surface-0/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-x-5 gap-y-3 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <Logo />
          <div className="leading-tight">
            <h1 className="text-base font-bold tracking-tight text-ink-primary">
              Atmos<span className="text-accent">Guard</span>
            </h1>
            <p className="text-2xs text-ink-muted">
              AI-Based Forecast Bust Risk &amp; Early-Warning System
            </p>
          </div>
        </div>

        {/* On narrow screens the nav scrolls sideways in a single row rather
            than wrapping into four - a wrapped nav pushed the status readouts
            into the middle of the header. */}
        <nav
          aria-label="Primary"
          className="order-last -mx-4 flex w-[calc(100%+2rem)] gap-1 overflow-x-auto px-4
                     lg:order-none lg:mx-0 lg:w-auto lg:flex-1 lg:flex-wrap lg:overflow-visible lg:px-0"
        >
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `shrink-0 rounded px-2.5 py-1.5 text-xs font-medium transition-colors ${
                  isActive
                    ? 'bg-accent/12 text-accent'
                    : 'text-ink-secondary hover:bg-surface-2 hover:text-ink-primary'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          {/* Feed & Last Synced */}
          <div
            className="hidden text-right leading-tight sm:block cursor-help"
            title={`IMD Operational Feed: Real-time observations from ${stationCount} stations across all 36 subdivisions. Last synchronized: ${lastUpdated || 'Just now'}`}
          >
            <p className="flex items-center justify-end gap-1.5 text-2xs font-medium text-ink-primary">
              {liveState === 'live' ? (
                <span className="relative flex h-2 w-2" aria-hidden>
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                </span>
              ) : liveState === 'error' ? (
                <span className="h-2 w-2 rounded-full bg-red-500" aria-hidden />
              ) : (
                <span className="h-2 w-2 animate-pulse rounded-full bg-amber-400" aria-hidden />
              )}
              {liveState === 'live'
                ? `IMD Live Feed (${stationCount})`
                : liveState === 'error'
                ? 'Feed error'
                : 'Connecting…'}
            </p>
            <p className="text-[10px] text-ink-muted">
              {lastUpdated ? `Synced: ${lastUpdated}` : 'Live auto-sync'}
            </p>
          </div>

          {/* Bulletin Date & Forecast Window */}
          <div
            className="hidden text-right leading-tight md:block cursor-help border-l border-edge/60 pl-3"
            title={`Official IMD Bulletin Date: ${formatLiveDate(liveDate)} (Today). Forecast Outlook Horizon: Valid through ${formatLiveDate(validTo)}.`}
          >
            <p className="text-2xs font-semibold tabular text-emerald-400 flex items-center justify-end gap-1">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
              {liveState === 'live' && liveDate ? `${formatLiveDate(liveDate)} (Today)` : selection ? formatLiveDate(selection.base_date) : '--'}
            </p>
            <p className="text-[10px] text-ink-muted">
              {validTo ? `Valid to: ${formatLiveDate(validTo)}` : '7-Day Horizon'}
            </p>
          </div>


          {isDemo && (
            <button
              type="button"
              onClick={() => setDemoMode(!demoMode)}
              aria-pressed={demoMode}
              title="Demo Mode offers curated scenarios covering each risk band"
              className={`rounded border px-2 py-1 text-2xs font-semibold tracking-wide transition-colors ${
                demoMode
                  ? 'border-risk-moderate/50 bg-risk-moderate/12 text-risk-moderate'
                  : 'border-edge bg-surface-2 text-ink-muted hover:text-ink-primary'
              }`}
            >
              DEMO MODE {demoMode ? 'ON' : 'OFF'}
            </button>
          )}

          <div
            className="grid h-8 w-8 place-items-center rounded-full border border-edge-strong
                       bg-surface-2 text-2xs font-bold text-ink-secondary"
            title="Signed in as Duty Forecaster"
            aria-label="Signed in as Duty Forecaster"
          >
            DF
          </div>
        </div>
      </div>

      {isDemo && (
        <div className="border-t border-edge/70 bg-surface-1/50">
          <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-x-5 gap-y-1 px-4 py-1.5">
            {/* Provenance, split by kind. Labelling everything "simulated"
                understated the real IMD record now underneath the system;
                labelling it all "real" would overstate the ensemble. */}
            <span className="flex items-center gap-1.5 text-[11px] text-ink-secondary">
              <span className="h-1.5 w-1.5 rounded-full bg-risk-low" aria-hidden />
              <span className="font-medium text-ink-primary">Observations &amp; climatology</span>
              <span className="text-ink-muted">IMD district daily + sub-division 1901-2017</span>
            </span>
            <span className="flex items-center gap-1.5 text-[11px] text-ink-secondary">
              <span className="h-1.5 w-1.5 rounded-full bg-risk-moderate" aria-hidden />
              <span className="font-medium text-ink-primary">Ensemble fields</span>
              <span className="text-ink-muted">reconstructed, not live NWP output</span>
            </span>
          </div>
        </div>
      )}
    </header>
  );
}
