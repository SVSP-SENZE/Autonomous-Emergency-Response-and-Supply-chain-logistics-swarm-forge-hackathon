import type { ReactNode } from 'react';

export type StageState = 'not_started' | 'in_progress' | 'completed' | 'failed' | 'needs_approval';

export interface PipelineRecord {
  label: string;
  /** Optional internal link to the record's page. */
  href?: string;
  detail?: string;
}

export interface PipelineStage {
  key: string;
  label: string;
  hint: string;
  state: StageState;
  detail?: string;
  records?: PipelineRecord[];
}

const STATE_LABEL: Record<StageState, string> = {
  not_started: 'Not started',
  in_progress: 'In progress',
  completed: 'Completed',
  failed: 'Failed',
  needs_approval: 'Awaiting operator',
};

/**
 * End-to-end response pipeline derived from ACTUAL backend records.
 * Each stage opens its supporting records; states are explicit, never animated
 * to completion.
 */
export function ResponsePipeline({ stages }: { stages: PipelineStage[] }) {
  return (
    <div className="pipeline" role="list">
      {stages.map((stage, index) => (
        <div
          key={stage.key}
          className={`pipeline-stage ${stage.state}`}
          role="listitem"
          title={stage.hint}
        >
          <div className="stage-name">{stage.label}</div>
          <div className="stage-state">{stage.detail ?? STATE_LABEL[stage.state]}</div>
          {stage.records && stage.records.length > 0 && (
            <div className="stack-8" style={{ marginTop: 8, alignItems: 'stretch' }}>
              {stage.records.map((record, i) => (
                <span key={i} className="muted" style={{ fontSize: 10, textAlign: 'left' }}>
                  · {record.label}
                </span>
              ))}
            </div>
          )}
          {index < stages.length - 1 && (
            <span className="stage-arrow" aria-hidden>
              ›
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

export type { ReactNode };
