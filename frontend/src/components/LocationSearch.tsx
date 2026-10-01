/** Type-ahead search across the monitoring network. */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { useAppState } from '../state/AppState';
import type { LocationRef } from '../api/types';
import { RiskChip } from './Primitives';
import { categoryFor } from '../lib/risk';

export function LocationSearch({ onPick }: { onPick?: () => void }) {
  const { meta, network, selection, setLocation } = useAppState();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const blurTimer = useRef<number | undefined>(undefined);
  const inputRef = useRef<HTMLInputElement>(null);
  const [anchor, setAnchor] = useState<{ top: number; left: number; width: number } | null>(null);

  // The results list is rendered into a portal on document.body rather than
  // beside the input. Panels use `backdrop-filter`, which permanently creates
  // a stacking context - so a dropdown nested inside one can never paint above
  // the sticky header, whatever z-index it is given. A portal escapes that
  // context entirely; the trade-off is that the position must be measured.
  const measure = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setAnchor({ top: rect.bottom + 4, left: rect.left, width: rect.width });
  }, []);

  useLayoutEffect(() => {
    if (open) measure();
  }, [open, query, measure]);

  useEffect(() => {
    if (!open) return;
    window.addEventListener('scroll', measure, true);
    window.addEventListener('resize', measure);
    return () => {
      window.removeEventListener('scroll', measure, true);
      window.removeEventListener('resize', measure);
    };
  }, [open, measure]);

  const sites = useMemo<LocationRef[]>(
    () => [...(meta.data?.locations ?? []), ...(meta.data?.regions ?? [])],
    [meta.data],
  );

  const riskById = useMemo(() => {
    const map = new Map<string, number>();
    network.data?.sites.forEach((s) => map.set(s.id, s.risk_score));
    return map;
  }, [network.data]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pool = q
      ? sites.filter((s) => s.name.toLowerCase().includes(q) || s.state.toLowerCase().includes(q))
      : sites.filter((s) => s.featured);
    return pool.slice(0, 9);
  }, [query, sites]);

  const current = sites.find((s) => s.id === selection?.location_id);

  return (
    <div className="relative">
      <label htmlFor="location-search" className="sr-only">
        Search location
      </label>
      <input
        ref={inputRef}
        id="location-search"
        type="search"
        autoComplete="off"
        placeholder="Search location..."
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          blurTimer.current = window.setTimeout(() => setOpen(false), 120);
        }}
        className="w-full rounded border border-edge bg-surface-2 px-3 py-2 text-xs text-ink-primary
                   placeholder:text-ink-muted focus:border-accent/60"
      />

      {current && !open && (
        <p className="mt-1.5 truncate text-2xs text-ink-muted">
          Selected: <span className="text-ink-primary">{current.name}</span>, {current.state}
        </p>
      )}

      {open &&
        anchor &&
        createPortal(
          results.length > 0 ? (
            <ul
              className="fixed z-[1200] max-h-72 overflow-auto rounded-md border border-edge-strong
                         bg-surface-2 py-1 shadow-2xl animate-fade-in"
              style={{ top: anchor.top, left: anchor.left, width: anchor.width }}
              role="listbox"
            >
              {!query.trim() && (
                <li className="px-3 pb-1 pt-1 text-2xs uppercase tracking-wider text-ink-muted">
                  Featured locations
                </li>
              )}
              {results.map((site) => {
                const score = riskById.get(site.id);
                return (
                  <li key={site.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={site.id === selection?.location_id}
                      onMouseDown={(event) => {
                        // Keep focus on the input so the blur timer never fires
                        // before the click is delivered.
                        event.preventDefault();
                        window.clearTimeout(blurTimer.current);
                      }}
                      onClick={() => {
                        setLocation(site.id);
                        setQuery('');
                        setOpen(false);
                        onPick?.();
                      }}
                      className={`flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left
                                  text-xs transition-colors hover:bg-surface-3 ${
                                    site.id === selection?.location_id
                                      ? 'text-accent'
                                      : 'text-ink-primary'
                                  }`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{site.name}</span>
                        <span className="block truncate text-2xs text-ink-muted">{site.state}</span>
                      </span>
                      {score !== undefined && (
                        <RiskChip category={categoryFor(score)} score={score} size="sm" />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div
              className="fixed z-[1200] rounded-md border border-edge-strong bg-surface-2 px-3 py-3
                         text-2xs text-ink-muted shadow-2xl"
              style={{ top: anchor.top, left: anchor.left, width: anchor.width }}
            >
              No location matches "{query}".
            </div>
          ),
          document.body,
        )}

    </div>
  );
}
