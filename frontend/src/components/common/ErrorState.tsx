import { AlertTriangle, RefreshCw } from 'lucide-react';
import type { ApiError } from '../../api/client';

interface Props {
  title?: string;
  error: ApiError | null;
  onRetry?: () => void;
  compact?: boolean;
}

export function ErrorState({ title = 'Failed to load data', error, onRetry, compact }: Props) {
  if (!error) return null;
  return (
    <div className="error-state" role="alert">
      {!compact && <AlertTriangle size={26} className="state-icon" />}
      <div>
        <strong>{title}</strong>
        <div className="error-message">
          {error.message}
          {error.hint ? <div><small>{error.hint}</small></div> : null}
        </div>
      </div>
      <span className="error-code">{error.code}</span>
      {onRetry && (
        <button className="btn ghost small" onClick={onRetry}>
          <RefreshCw size={13} /> Retry
        </button>
      )}
    </div>
  );
}
