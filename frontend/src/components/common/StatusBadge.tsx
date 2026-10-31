import { titleCase } from '../../utils/format';

/**
 * Status badge: colour class resolved by the caller's map, or generic fallback.
 */
export function StatusBadge({
  value,
  className,
  label,
}: {
  value?: string | null;
  className?: string;
  label?: string;
}) {
  if (!value) return null;
  return (
    <span className={`badge ${className ?? 'badge-plain'}`}>{label ?? titleCase(value)}</span>
  );
}
