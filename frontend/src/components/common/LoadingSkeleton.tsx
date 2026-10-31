export function LoadingSkeleton({ variant = 'lines' }: { variant?: 'lines' | 'block' | 'table' }) {
  if (variant === 'block') {
    return <div className="skeleton skeleton-block" />;
  }
  if (variant === 'table') {
    return (
      <div aria-hidden>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="skeleton skeleton-line" style={{ height: 22, opacity: 1 - i * 0.15 }} />
        ))}
      </div>
    );
  }
  return (
    <div aria-hidden>
      <div className="skeleton skeleton-line w60" />
      <div className="skeleton skeleton-line w80" />
      <div className="skeleton skeleton-line" />
    </div>
  );
}
