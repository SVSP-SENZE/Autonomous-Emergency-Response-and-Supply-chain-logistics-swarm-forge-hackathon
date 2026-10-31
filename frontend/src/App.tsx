import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Sidebar } from './components/layout/Sidebar';
import { TopHeader } from './components/layout/TopHeader';
import { useBackendData } from './hooks/useBackendData';
import { getHealth } from './api/dashboard';
import { useScenario } from './hooks/useScenario';
import { PageShell } from './pages/routes';

/**
 * Top-level application chrome: sidebar + header + routed page area.
 * The refresh button remounts the page area and re-polls scenario incidents.
 */
export default function App() {
  const { pathname } = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const scenario = useScenario();
  const health = useBackendData(() => getHealth(), [], 30000);

  return (
    <div className="app-shell">
      <Sidebar
        collapsed={collapsed}
        backendOnline={health.data?.status === 'ok'}
        onToggleCollapse={() => setCollapsed((value) => !value)}
      />
      <div className="main-area">
        <TopHeader
          pathname={pathname}
          lastUpdatedAt={scenario.incidentsUpdatedAt}
          refreshing={false}
          onRefresh={() => {
            scenario.refreshIncidents();
            setRefreshKey((key) => key + 1);
          }}
          onToggleSidebar={() => undefined}
        />
        <PageShell key={refreshKey} />
      </div>
    </div>
  );
}
