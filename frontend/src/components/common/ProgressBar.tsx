import { formatPercent } from '../../utils/format';

export function ProgressBar({
  percent,
  tone = 'auto',
  showLabel = true,
}: {
  percent: number;
  tone?: 'auto' | 'primary' | 'warn' | 'ok' | 'err';
  showLabel?: boolean;
}) {
  const clamped = Math.max(0, Math.min(100, percent));
  const resolved =
    tone === 'auto'
      ? clamped >= 100
        ? 'ok'
        : clamped >= 50
          ? ''
          : 'warn'
      : tone === 'primary'
        ? ''
        : tone;
  return (
    <div className="row-8" style={{ flexWrap: 'nowrap' }}>
      <div className="progress-track" style={{ flex: 1 }}>
        <div className={`progress-fill ${resolved}`} style={{ width: `${clamped}%` }} />
      </div>
      {showLabel && (
        <span className="muted" style={{ fontVariantNumeric: 'tabular-nums', minWidth: 38, textAlign: 'right' }}>
          {formatPercent(clamped)}
        </span>
      )}
    </div>
  );
}

/** Shortage visualisation: bar sized by percentage, colour-coded by severity. */
export function ShortageBar({ percent }: { percent: number }) {
  const clamped = Math.max(0, Math.min(100, percent));
  const color =
    clamped >= 75
      ? 'var(--accent-red)'
      : clamped >= 35
        ? 'var(--accent-orange)'
        : clamped > 0
          ? '#ffd740'
          : 'var(--accent-green)';
  return (
    <div className="shortage-bar">
      <div style={{ width: `${clamped}%`, background: color }} />
    </div>
  );
}
