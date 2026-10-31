import { Bell, Bot, RefreshCw, Menu } from 'lucide-react';
import { useScenario } from '../../hooks/useScenario';
import { useToast } from '../common/Toast';

const TITLES: Record<string, string> = {
  '/': 'Command Centre',
  '/map': 'Disaster Map',
  '/incidents': 'Incident Intelligence',
  '/logistics': 'Logistics Planning',
  '/dispatch': 'Dispatch Operations',
  '/fleet': 'Fleet Management',
  '/simulation': 'Simulation Lab',
  '/ai': 'AI Activity',
};

interface Props {
  pathname: string;
  lastUpdatedAt: number | null;
  refreshing: boolean;
  onRefresh: () => void;
  onToggleSidebar: () => void;
}

export function TopHeader({ pathname, lastUpdatedAt, refreshing, onRefresh, onToggleSidebar }: Props) {
  const { primary, criticalCount } = useScenario();
  const { push } = useToast();
  const pageName = TITLES[pathname] ?? TITLES[pathname.replace(/\/.*$/, '')] ?? 'Command Centre';

  const notifyCount = criticalCount;

  return (
    <header className="top-header">
      <button className="mobile-menu-btn" onClick={onToggleSidebar} aria-label="Toggle navigation">
        <Menu size={18} />
      </button>

      <div className="header-title">
        <span className="page-name">{pageName}</span>
        <span className="header-sub">
          {primary
            ? `Scenario: ${primary.title} · ${primary.location_name}`
            : 'Scenario: Thanjavur District Flood (seeded demo)'}
        </span>
      </div>

      <div className="header-right">
        <span className="badge sev-high">SIMULATION ACTIVE</span>
        <span className="data-source-pill" title="All records come from the ReliefMesh backend demo database">
          SIMULATED DATA
        </span>
        <span className="last-updated" title="Auto-refreshing simulated operations data">
          {refreshing ? 'Refreshing…' : lastUpdatedAt ? `Updated ${new Date(lastUpdatedAt).toLocaleTimeString()}` : 'Awaiting data…'}
        </span>
        <button
          className="btn ghost small"
          onClick={onRefresh}
          title="Refresh backend data"
          aria-label="Refresh data"
        >
          <RefreshCw size={14} className={refreshing ? 'spin' : ''} />
        </button>
        <button
          className="btn ghost small notification-dot"
          title={
            notifyCount > 0
              ? `${notifyCount} critical incident${notifyCount === 1 ? '' : 's'} in the simulated scenario`
              : 'No critical incidents in the simulated scenario'
          }
          onClick={() =>
            push(
              notifyCount > 0
                ? `${notifyCount} unresolved critical incident notification${notifyCount === 1 ? '' : 's'} (SIMULATED scenario)`
                : 'No unresolved critical incidents in the simulated scenario.',
              notifyCount > 0 ? 'error' : 'info',
            )
          }
          aria-label="Notifications"
        >
          <Bell size={15} />
          {notifyCount > 0 && <span className="dot" />}
        </button>
        <div className="avatar-placeholder" title="Operator console (local session)">
          <Bot size={16} />
        </div>
      </div>
    </header>
  );
}
