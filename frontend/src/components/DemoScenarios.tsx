/**
 * Demo Mode scenario picker.
 *
 * Each entry selects a real point in the demonstration dataset that lands in a
 * particular risk band. It does not inject a score - the model still computes
 * the answer - so what a judge sees is the system working, not a mock-up.
 */

import { useAppState } from '../state/AppState';
import { RiskChip } from './Primitives';

export function DemoScenarios() {
  const { meta, activeScenario, applyScenario, demoMode } = useAppState();
  if (!demoMode || !meta.data?.scenarios.length) return null;

  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {meta.data.scenarios.map((scenario) => {
          const active = scenario.id === activeScenario;
          return (
            <button
              key={scenario.id}
              type="button"
              onClick={() => applyScenario(scenario.id)}
              aria-pressed={active}
              title={scenario.summary}
              className={`flex items-center gap-1.5 rounded border px-2 py-1 text-2xs font-medium
                          transition-colors ${
                            active
                              ? 'border-accent/60 bg-accent/12 text-accent'
                              : 'border-edge bg-surface-2 text-ink-secondary hover:border-edge-strong hover:text-ink-primary'
                          }`}
            >
              {scenario.title.replace(' - flagship case', '')}
              <RiskChip category={scenario.expected_band} size="sm" />
            </button>
          );
        })}
      </div>

      {activeScenario && (
        <p className="mt-2 text-2xs leading-relaxed text-ink-muted">
          {meta.data.scenarios.find((s) => s.id === activeScenario)?.summary}
        </p>
      )}
    </div>
  );
}
