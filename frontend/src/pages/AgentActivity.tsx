import { useState } from 'react';
import {
  Bot,
  Cpu,
  Wrench,
  Brain,
  Link as LinkIcon,
} from 'lucide-react';
import { useBackendData } from '../hooks/useBackendData';
import {
  getAgentRun,
  getAgentSession,
  getAgentStatus,
  listAgentSessions,
} from '../api/agent';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { StatusBadge } from '../components/common/StatusBadge';
import { renderMarkdown } from '../utils/markdown';
import { formatDateTime, formatTime } from '../utils/format';

const RUN_STATUS_CLASS = {
  running: 'badge-plain',
  completed: 'badge sev-low',
  failed: 'badge sev-high',
} as const;

export function AgentActivityPage() {
  const status = useBackendData((signal) => getAgentStatus(signal), [], 30000);
  const sessions = useBackendData((signal) => listAgentSessions(20, signal), [], 15000);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [runId, setRunId] = useState<number | null>(null);

  const session = useBackendData(async (signal) => (sessionId === null ? null : getAgentSession(sessionId, signal)), [sessionId], 15000);
  const run = useBackendData(async (signal) => (runId === null ? null : getAgentRun(runId, signal)), [runId], 0);

  return (
    <div className="stack-16">
      {/* Copilot status */}
      {status.error ? (
        <ErrorState error={status.error} onRetry={status.refresh} />
      ) : status.loading ? (
        <LoadingSkeleton variant="lines" />
      ) : (
        status.data && (
          <div className="callout info" role="status">
            <div className="spread">
              <span>
                <Cpu size={14} style={{ verticalAlign: -2, marginRight: 6 }} />
                <strong>Groq copilot — {status.data.model}</strong>
                {' · '}provider {status.data.provider}
                {' · '}
                {status.data.status === 'ready'
                  ? 'API key configured (server-side only)'
                  : 'API key not configured — chat disabled by design, everything else keeps working'}
              </span>
            </div>
            <div className="muted" style={{ marginTop: 4, fontSize: 12.5 }}>
              The copilot is strictly read-only: it may query maps, demand, allocation, routes, fleet, weather and
              dispatch summaries through a validated tool allowlist — it can never mutate operational state. Draft
              order generation is an explicit operator action, never an AI action.
            </div>
          </div>
        )
      )}

      <div className="grid-2-1" style={{ alignItems: 'stretch' }}>
        <div className="card">
          <div className="card-header">
            <Bot size={15} className="header-icon" />
            <h3>Agent sessions</h3>
          </div>
          <div className="card-body">
            {sessions.error ? (
              <ErrorState error={sessions.error} onRetry={sessions.refresh} />
            ) : sessions.loading ? (
              <LoadingSkeleton variant="lines" />
            ) : (sessions.data?.length ?? 0) === 0 ? (
              <EmptyState message="No copilot sessions yet — open the AI Operations Copilot on any page and ask an operational question." />
            ) : (
              <div className="stack-8">
                {sessions.data!.map((candidate) => (
                  <button
                    key={candidate.session_id}
                    className={`session-row ${sessionId === candidate.session_id ? 'active' : ''}`}
                    onClick={() => {
                      setSessionId(candidate.session_id);
                      setRunId(null);
                    }}
                  >
                    <div className="spread">
                      <strong style={{ fontSize: 13 }}>{candidate.session_title}</strong>
                      <span className="muted" style={{ fontSize: 11 }}>
                        {candidate.message_count} msgs
                      </span>
                    </div>
                    <div className="muted" style={{ fontSize: 11 }}>
                      created {formatTime(candidate.created_at)} · updated {formatTime(candidate.updated_at)}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h3>{sessionId !== null ? `Session #${sessionId}` : 'Session transcript'}</h3>
            <div className="card-header-right muted">
              {session.data ? `${session.data.runs.length} copilot runs` : ''}
            </div>
          </div>
          <div className="card-body">
            {sessionId === null ? (
              <EmptyState message="Select a session to see the full transcript and its copilot runs." />
            ) : session.loading ? (
              <LoadingSkeleton variant="lines" />
            ) : session.error ? (
              <ErrorState error={session.error} onRetry={session.refresh} />
            ) : !session.data ? (
              <EmptyState message="Session could not be loaded." />
            ) : (
              <div className="stack-10">
                {session.data.messages.map((message, index) => (
                  <div key={`${message.role}-${index}`} className={message.role === 'user' ? 'chat-bubble user' : 'chat-bubble assistant'}>
                    <div className="chat-role">
                      {message.role === 'user' ? 'Operator' : 'Copilot'} · {formatTime(message.created_at)}
                    </div>
                    {message.role === 'user' ? (
                      <div style={{ whiteSpace: 'pre-wrap' }}>{message.content}</div>
                    ) : (
                      <>{renderMarkdown(message.content)}</>
                    )}
                  </div>
                ))}

                {session.data.runs.length > 0 && (
                  <div>
                    <div className="section-title" style={{ marginBottom: 6 }}>Copilot runs</div>
                    <div className="stack-6">
                      {session.data.runs.map((candidate) => (
                        <button
                          key={candidate.run_id}
                          className={`run-row ${runId === candidate.run_id ? 'selected' : ''}`}
                          onClick={() => setRunId(candidate.run_id)}
                        >
                          <div className="spread">
                            <span className="row-8">
                              <StatusBadge value={candidate.status} className={RUN_STATUS_CLASS[candidate.status]} />
                              <strong style={{ fontSize: 12.5 }}>Run #{candidate.run_id}</strong>
                              <span className="muted" style={{ fontSize: 11 }}>{candidate.model_name}</span>
                            </span>
                            <span className="muted" style={{ fontSize: 11 }}>
                              {candidate.tool_call_count} tool calls
                            </span>
                          </div>
                          {candidate.error_message && (
                            <div style={{ color: 'var(--accent-red)', fontSize: 12 }}>
                              Error: {candidate.error_message}
                            </div>
                          )}
                          <div className="muted" style={{ fontSize: 11 }}>
                            {formatDateTime(candidate.created_at)}
                            {candidate.completed_at ? ` → ${formatTime(candidate.completed_at)}` : ' → still running'}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Run detail with tool executions */}
      <div className="card">
        <div className="card-header">
          <Brain size={15} className="header-icon" />
          <h3>
            {run.data ? `Run #${run.data.run_id} — tool execution trace` : 'Run detail'}
          </h3>
          <div className="card-header-right muted">
            {run.data ? `${run.data.tool_call_count} tool calls · model ${run.data.model_name}` : ''}
          </div>
        </div>
        <div className="card-body">
          {runId === null ? (
            <EmptyState message="Select a copilot run above to inspect every tool call it made and exactly what came back from the API." />
          ) : run.loading ? (
            <LoadingSkeleton variant="lines" />
          ) : run.error ? (
            <ErrorState error={run.error} onRetry={run.refresh} />
          ) : !run.data ? (
            <EmptyState message="Run could not be loaded." />
          ) : (
            <div className="stack-10">
              <div className="kv-row">
                <span className="k">Status</span>
                <span className="v">
                  <StatusBadge value={run.data.status} className={RUN_STATUS_CLASS[run.data.status]} />
                </span>
              </div>
              <div className="kv-row">
                <span className="k">Operator asked</span>
                <span className="v">{run.data.user_message}</span>
              </div>
              {run.data.error_message && (
                <div style={{ color: 'var(--accent-red)' }}>
                  Run error: {run.data.error_message}
                  <div className="muted" style={{ fontSize: 12 }}>
                    Failures are visible on purpose — the copilot operates on live data and can hit real API errors;
                    nothing is hidden.
                  </div>
                </div>
              )}
              {run.data.assistant_message && (
                <div className="chat-bubble assistant">
                  <div className="chat-role">Copilot answer</div>
                  <>{renderMarkdown(run.data.assistant_message)}</>
                </div>
              )}

              <div>
                <div className="section-title" style={{ marginBottom: 6 }}>
                  <Wrench size={13} /> Tool executions ({run.data.tool_executions.length})
                </div>
                {run.data.tool_executions.length === 0 ? (
                  <div className="muted">This run answered without calling any tool.</div>
                ) : (
                  <div className="stack-8">
                    {run.data.tool_executions.map((tool, index) => (
                      <div key={index} className="tool-exec card" style={{ padding: 8 }}>
                        <div className="spread">
                          <span className="row-8">
                            <strong style={{ fontSize: 12.5 }}>{tool.tool_name}</strong>
                            <span className={`badge ${tool.status === 'success' ? 'sev-low' : 'sev-high'}`}>
                              {tool.status}
                            </span>
                            <span className="muted" style={{ fontSize: 11 }}>{tool.execution_time_ms} ms</span>
                          </span>
                          <span className="muted" style={{ fontSize: 11 }}>{formatTime(tool.created_at)}</span>
                        </div>
                        <details>
                          <summary className="muted" style={{ fontSize: 12, cursor: 'pointer' }}>
                            Arguments &amp; raw result
                          </summary>
                          <pre className="code-block">
                          {JSON.stringify(tool.arguments_json, null, 2)}
                          </pre>
                          <pre className="code-block">
                          {JSON.stringify(tool.result_json, null, 2)}
                          </pre>
                        </details>
                        {tool.result_summary && (
                          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                            {tool.result_summary}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="muted" style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
        <LinkIcon size={12} /> Ask the copilot live from the AI Operations Copilot panel; the transcript and the full
        tool traces with real API payloads appear here automatically.
      </div>
    </div>
  );
}
