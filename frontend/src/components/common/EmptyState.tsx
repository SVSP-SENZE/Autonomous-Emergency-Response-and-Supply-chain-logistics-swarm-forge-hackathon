import { Inbox } from 'lucide-react';

export function EmptyState({ message, children }: { message: string; children?: React.ReactNode }) {
  return (
    <div className="empty-state">
      <Inbox size={26} className="state-icon" />
      <div>
        <div>{message}</div>
        {children}
      </div>
    </div>
  );
}
