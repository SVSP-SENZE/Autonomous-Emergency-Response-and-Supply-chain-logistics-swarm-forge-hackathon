import { Routes, Route, useLocation } from 'react-router-dom';
import { CommandCentrePage } from './CommandCentre';
import { DisasterMapPage } from './DisasterMapPage';
import { IncidentsPage } from './Incidents';
import { LogisticsPlanningPage } from './LogisticsPlanning';
import { DispatchOperationsPage } from './DispatchOperations';
import { FleetManagementPage } from './FleetManagement';
import { SimulationLabPage } from './SimulationLab';
import { AgentActivityPage } from './AgentActivity';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<CommandCentrePage />} />
      <Route path="/map" element={<DisasterMapPage />} />
      <Route path="/incidents" element={<IncidentsPage />} />
      <Route path="/logistics" element={<LogisticsPlanningPage />} />
      <Route path="/dispatch" element={<DispatchOperationsPage />} />
      <Route path="/fleet" element={<FleetManagementPage />} />
      <Route path="/simulation" element={<SimulationLabPage />} />
      <Route path="/ai" element={<AgentActivityPage />} />
      <Route
        path="*"
        element={
          <div className="card card-body" style={{ maxWidth: 420 }}>
            This page does not exist.
          </div>
        }
      />
    </Routes>
  );
}

export function PageShell() {
  const location = useLocation();
  return (
    <div className="page-area">
      <AppRoutes key={location.pathname} />
    </div>
  );
}
