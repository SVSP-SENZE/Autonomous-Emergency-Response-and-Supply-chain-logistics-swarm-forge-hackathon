import { useEffect, useRef } from 'react';
import { AlertOctagon } from 'lucide-react';

interface Props {
  open: boolean;
  title: string;
  body: string | React.ReactNode;
  bullets?: string[];
  confirmLabel?: string;
  tone?: 'default' | 'danger';
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}

/** Accessible confirmation dialog used before every state-changing action. */
export function ConfirmDialog({
  open,
  title,
  body,
  bullets,
  confirmLabel = 'Confirm',
  tone = 'default',
  onConfirm,
  onCancel,
  busy,
}: Props) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel();
    };
    document.addEventListener('keydown', onKey);
    confirmRef.current?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="modal-card" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-header">
          <AlertOctagon size={18} style={{ color: tone === 'danger' ? 'var(--accent-red)' : 'var(--accent-orange)' }} />
          <span>{title}</span>
        </div>
        <div className="modal-body">
          {typeof body === 'string' ? <p style={{ margin: 0 }}>{body}</p> : body}
          {bullets && bullets.length > 0 && (
            <ul>
              {bullets.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            ref={confirmRef}
            className={`btn ${tone === 'danger' ? 'danger' : 'primary'}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
