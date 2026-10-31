import { createContext, useContext } from 'react';
import { useBackendData } from './useBackendData';
import { listIncidents } from '../api/incidents';
import type { Incident } from '../types';
import { severityRank } from '../utils/format';

interface ScenarioContextValue {
  incidents: Incident[];
  /** Highest-priority active (non-resolved) incident, or null. */
  primary: Incident | null;
  activeCount: number;
  criticalCount: number;
  incidentsUpdatedAt: number | null;
  refreshIncidents: () => void;
}

/**
 * Shared, lightly-polled incident/scenario state used by the sidebar and
 * header. Data comes only from GET /incidents (real backend records).
 */
export const ScenarioContext = createContext<ScenarioContextValue>({
  incidents: [],
  primary: null,
  activeCount: 0,
  criticalCount: 0,
  incidentsUpdatedAt: null,
  refreshIncidents: () => undefined,
});

export function useScenario() {
  return useContext(ScenarioContext);
}

export function ScenarioProvider({ children }: { children: React.ReactNode }) {
  const state = useBackendData((signal) => listIncidents({}, signal), [], 30000);
  const incidents = state.data?.items ?? [];
  const active = incidents.filter((incident: Incident) => incident.status !== 'resolved');
  const sorted = [...active].sort((a: Incident, b: Incident) => severityRank(b.severity) - severityRank(a.severity));
  const primary = sorted[0] ?? null;
  const criticalCount = incidents.filter((i: Incident) => i.severity === 'critical' && i.status !== 'resolved').length;

  return (
    <ScenarioContext.Provider
      value={{
        incidents,
        primary,
        activeCount: active.length,
        criticalCount,
        incidentsUpdatedAt: state.updatedAt,
        refreshIncidents: state.refresh,
      }}
    >
      {children}
    </ScenarioContext.Provider>
  );
}
