import type { LucideIcon } from 'lucide-react';

interface Props {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  accent?: string;
  sub?: string;
  busy?: boolean;
}

/** One operational KPI. Value always comes from real backend data. */
export function MetricCard({ label, value, icon: Icon, accent, sub, busy }: Props) {
  return (
    <div className="metric-card" style={accent ? ({ '--metric-accent': accent } as React.CSSProperties) : undefined}>
      <div className="metric-label">
        {Icon ? <Icon size={13} /> : null}
        <span>{label}</span>
      </div>
      <div
        className="metric-value"
        style={busy ? { color: 'var(--text-muted)', fontSize: 20 } : undefined}
      >
        {busy ? '···' : value}
      </div>
      {sub ? <div className="metric-sub">{sub}</div> : null}
    </div>
  );
}
