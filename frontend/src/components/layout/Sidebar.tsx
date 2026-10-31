import { NavLink } from 'react-router-dom';
import {
  Activity,
  Bot,
  Bus,
  ChevronLeft,
  FlaskConical,
  LayoutDashboard,
  Map as MapIcon,
  PackageSearch,
  ShieldAlert,
  Waves,
} from 'lucide-react';
import { useScenario } from '../../hooks/useScenario';

const NAV_ITEMS = [
  { to: '/', label: 'Command Centre', icon: LayoutDashboard },
  { to: '/map', label: 'Disaster Map', icon: MapIcon },
  { to: '/incidents', label: 'Incident Intelligence', icon: ShieldAlert },
  { to: '/logistics', label: 'Logistics Planning', icon: PackageSearch },
  { to: '/dispatch', label: 'Dispatch Operations', icon: Waves },
  { to: '/fleet', label: 'Fleet Management', icon: Bus },
  { to: '/simulation', label: 'Simulation Lab', icon: FlaskConical },
  { to: '/ai', label: 'AI Activity', icon: Bot },
];

interface Props {
  collapsed: boolean;
  onToggleCollapse: () => void;
  backendOnline: boolean;
}

export function Sidebar({ collapsed, onToggleCollapse, backendOnline }: Props) {
  const { activeCount } = useScenario();

  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-top">
        <div className="logo-mark">
          <Activity size={18} strokeWidth={2.4} />
        </div>
        <div className="logo-text">
          <strong>ReliefMesh</strong>
          <span>Autonomous Disaster Response</span>
        </div>
      </div>

      <div className="nav-section-label">Operations</div>
      <nav aria-label="Primary">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            title={label}
          >
            <Icon size={17} className="nav-icon" />
            <span className="nav-label">{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footnote">
        <div className="sidebar-status">
          <span className={`pulse-dot ${backendOnline ? '' : 'offline'}`} />
          <span>{backendOnline ? 'Backend connected' : 'Backend offline'}</span>
        </div>
        <div className="sidebar-status">
          <span className="sim-note" style={{ fontSize: 10 }}>
            <Waves size={11} /> Simulation mode
          </span>
        </div>
        <div>
          {activeCount} active incident{activeCount === 1 ? '' : 's'} · demo scenario
        </div>
      </div>

      <button
        className="collapse-btn"
        onClick={onToggleCollapse}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <ChevronLeft size={15} style={{ transform: collapsed ? 'rotate(180deg)' : 'none' }} />
      </button>
    </aside>
  );
}
