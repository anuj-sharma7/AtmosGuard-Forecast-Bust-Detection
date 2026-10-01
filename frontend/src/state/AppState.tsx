/**
 * Application state: the current selection, and the data derived from it.
 *
 * There is exactly one selection (location, variable, model, horizon, date) and
 * every page reads from it. That is what makes the spec's core requirement work:
 * changing any selector updates the risk score, the explanation, the ensemble,
 * the analogues and the alerts together, because they are all views of one
 * request.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { ApiError, api } from '../api/client';
import type { Meta, NetworkResponse, RiskResponse, Selection } from '../api/types';

interface AsyncValue<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

interface AppStateValue {
  meta: AsyncValue<Meta>;
  risk: AsyncValue<RiskResponse>;
  network: AsyncValue<NetworkResponse>;
  selection: Selection | null;
  demoMode: boolean;
  activeScenario: string | null;
  setLocation: (id: string) => void;
  setVariable: (id: string) => void;
  setModel: (id: string) => void;
  setHorizon: (horizon: number) => void;
  setDemoMode: (on: boolean) => void;
  applyScenario: (id: string) => void;
  reload: () => void;
}

const AppStateContext = createContext<AppStateValue | null>(null);

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Unexpected error';
}

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<AsyncValue<Meta>>({ data: null, loading: true, error: null });
  const [risk, setRisk] = useState<AsyncValue<RiskResponse>>({ data: null, loading: true, error: null });
  const [network, setNetwork] = useState<AsyncValue<NetworkResponse>>({
    data: null,
    loading: true,
    error: null,
  });
  const [selection, setSelection] = useState<Selection | null>(null);
  const [demoMode, setDemoMode] = useState(true);
  const [activeScenario, setActiveScenario] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  // Bootstrap: fetch metadata, then adopt the flagship scenario as the opening
  // view so the dashboard demonstrates the whole product on first paint.
  useEffect(() => {
    let cancelled = false;
    setMeta({ data: null, loading: true, error: null });
    api
      .meta()
      .then((data) => {
        if (cancelled) return;
        setMeta({ data, loading: false, error: null });
        setSelection(data.default_selection);
        setActiveScenario(data.default_selection.scenario_id ?? null);
      })
      .catch((error) => {
        if (!cancelled) setMeta({ data: null, loading: false, error: messageFor(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  useEffect(() => {
    if (!selection) return;
    let cancelled = false;
    setRisk((prev) => ({ data: prev.data, loading: true, error: null }));
    api
      .risk(selection)
      .then((data) => {
        if (!cancelled) setRisk({ data, loading: false, error: null });
      })
      .catch((error) => {
        if (!cancelled) setRisk({ data: null, loading: false, error: messageFor(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [selection]);

  useEffect(() => {
    if (!selection) return;
    let cancelled = false;
    setNetwork((prev) => ({ data: prev.data, loading: true, error: null }));
    api
      .network(selection)
      .then((data) => {
        if (!cancelled) setNetwork({ data, loading: false, error: null });
      })
      .catch((error) => {
        if (!cancelled) setNetwork({ data: null, loading: false, error: messageFor(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [selection]);

  // Any manual change leaves the curated scenario behind - the selection no
  // longer matches it, and pretending otherwise would mislabel the view.
  const update = useCallback((patch: Partial<Selection>) => {
    setSelection((prev) => (prev ? { ...prev, ...patch } : prev));
    setActiveScenario(null);
  }, []);

  const applyScenario = useCallback(
    (id: string) => {
      const scenario = meta.data?.scenarios.find((s) => s.id === id);
      if (!scenario) return;
      setSelection({
        location_id: scenario.location_id,
        variable_id: scenario.variable_id,
        model_id: scenario.model_id,
        horizon: scenario.horizon,
        base_date: scenario.base_date,
      });
      setActiveScenario(id);
    },
    [meta.data],
  );

  const value = useMemo<AppStateValue>(
    () => ({
      meta,
      risk,
      network,
      selection,
      demoMode,
      activeScenario,
      setLocation: (id) => update({ location_id: id }),
      setVariable: (id) => update({ variable_id: id }),
      setModel: (id) => update({ model_id: id }),
      setHorizon: (horizon) => update({ horizon }),
      setDemoMode,
      applyScenario,
      reload: () => setNonce((n) => n + 1),
    }),
    [meta, risk, network, selection, demoMode, activeScenario, update, applyScenario],
  );

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState(): AppStateValue {
  const context = useContext(AppStateContext);
  if (!context) throw new Error('useAppState must be used inside AppStateProvider');
  return context;
}
