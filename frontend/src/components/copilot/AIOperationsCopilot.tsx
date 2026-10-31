import { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, Check, Copy, Loader2, MessageSquarePlus, Send, XCircle } from 'lucide-react';
import { sendAgentChat, listAgentSessions, getAgentSession } from '../../api/agent';
import type { AgentSessionSummary, ToolCallTrace } from '../../types';
import { ApiError } from '../../api/client';
import { renderMarkdown } from '../../utils/markdown';
import { formatTime } from '../../utils/format';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  createdAt?: string;
}

const GREETING =
  'ReliefMesh AI is ready. I can analyse active incidents, estimate supply shortages, evaluate warehouse inventory, calculate safe routes and explain allocation plans.';

const SUGGESTIONS = [
  'Analyse the current disaster situation in Thanjavur.',
  'Identify critical relief centres.',
  'Estimate 24-hour water demand.',
  'Check warehouse stock.',
  'Find a safe route to Thanjavur.',
];

const TOOL_LABELS: Record<string, string> = {
  get_situation_overview: 'DISASTER ANALYSIS',
  list_active_incidents: 'INCIDENT SCAN',
  get_demand_assessment: 'DEMAND ANALYSIS',
  get_warehouse_inventory: 'INVENTORY CHECK',
  compute_resource_allocation: 'RESOURCE ALLOCATION',
  calculate_safe_route: 'ROUTE ANALYSIS',
  get_latest_allocation_plan: 'ALLOCATION SNAPSHOT',
  explain_relief_centre_priority: 'PRIORITY REVIEW',
};

export function AIOperationsCopilot({ height }: { height?: number }) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', content: GREETING },
  ]);
  const [input, setInput] = useState('');
  const [pending, setPending] = useState(false);
  const [turnTools, setTurnTools] = useState<ToolCallTrace[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<AgentSessionSummary[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await listAgentSessions(15));
    } catch {
      setSessions([]);
    }
  }, []);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, pending, turnTools]);

  const hydrateSession = async (id: number) => {
    setError(null);
    setTurnTools([]);
    try {
      const detail = await getAgentSession(id);
      setSessionId(id);
      setMessages(
        detail.messages
          .filter((m) => m.role !== 'system')
          .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content, createdAt: m.created_at })),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load that conversation.');
    }
  };

  const startNewChat = () => {
    setSessionId(null);
    setMessages([{ role: 'assistant', content: GREETING }]);
    setTurnTools([]);
    setError(null);
  };

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || pending) return;
    setInput('');
    setError(null);
    setMessages((current) => [...current, { role: 'user', content: trimmed }]);
    setPending(true);
    try {
      const response = await sendAgentChat(trimmed, sessionId);
      setSessionId(response.session_id);
      setTurnTools(response.tool_calls);
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: response.assistant_message, createdAt: response.created_at },
      ]);
      void refreshSessions();
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `${err.message}${err.hint ? ` — ${err.hint}` : ''}`
          : 'The AI request failed. No data was changed.';
      setError(message);
    } finally {
      setPending(false);
    }
  };

  const copyMessage = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content);
    } catch {
      /* clipboard unavailable — non-critical */
    }
  };

  return (
    <div className="card copilot" style={height ? { height } : undefined}>
      <div className="card-header">
        <Bot size={16} className="header-icon" />
        <h3>AI Operations Copilot</h3>
        <div className="card-header-right">
          <select
            aria-label="Conversation history"
            className="input"
            style={{ width: 'auto', fontSize: 11.5, padding: '3px 8px' }}
            value={sessionId ?? ''}
            onChange={(e) => {
              const value = e.target.value;
              if (value === '') startNewChat();
              else void hydrateSession(Number(value));
            }}
          >
            <option value="">New conversation</option>
            {sessions.map((session) => (
              <option key={session.session_id} value={session.session_id}>
                {session.session_title} ({session.message_count})
              </option>
            ))}
          </select>
          <button className="btn ghost small" onClick={startNewChat} aria-label="New conversation">
            <MessageSquarePlus size={13} /> New
          </button>
        </div>
      </div>

      <div className="copilot-messages" ref={scrollRef}>
        {messages.map((message, index) => (
          <div key={index} className={`msg ${message.role}`}>
            <div className="msg-head">
              <span>{message.role === 'user' ? 'Operator' : 'ReliefMesh AI'}</span>
              {message.createdAt && <span>{formatTime(message.createdAt)}</span>}
              {message.role === 'assistant' && (
                <button
                  className="copy-btn"
                  onClick={() => void copyMessage(message.content)}
                  title="Copy response"
                >
                  {<Copy size={11} />}
                </button>
              )}
            </div>
            <div className="msg-body">{renderMarkdown(message.content)}</div>
          </div>
        ))}

        {turnTools.length > 0 && !pending && (
          <div className="tool-timeline">
            {turnTools.map((tool, index) => (
              <div key={index} className={`tool-card ${tool.status === 'error' ? 'err' : 'ok'}`}>
                <div className="tool-head">
                  {tool.status === 'success' ? (
                    <Check size={12} style={{ color: 'var(--accent-cyan)' }} />
                  ) : (
                    <XCircle size={12} style={{ color: 'var(--accent-red)' }} />
                  )}
                  <span className="tool-name">{TOOL_LABELS[tool.tool_name] ?? tool.tool_name}</span>
                  <span className="tool-time">{tool.execution_time_ms} ms</span>
                </div>
                {tool.summary && <div className="tool-summary">{tool.summary}</div>}
              </div>
            ))}
          </div>
        )}

        {pending && (
          <div className="tool-thinking">
            <Loader2 size={14} className="spin" style={{ color: 'var(--accent-blue)' }} />
            <span>ReliefMesh AI is calling backend tools…</span>
            <span className="typing-dots"><span /><span /><span /></span>
          </div>
        )}

        {error && (
          <div className="msg assistant" style={{ borderColor: 'rgba(241,91,91,0.5)' }}>
            <div className="msg-head">
              <XCircle size={12} style={{ color: 'var(--accent-red)' }} />
              <span>AI request failed</span>
            </div>
            <div className="msg-body">
              <p style={{ margin: 0 }}>{error}</p>
            </div>
          </div>
        )}
      </div>

      <div className="copilot-suggestions">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            className="suggestion-chip"
            disabled={pending}
            onClick={() => void send(suggestion)}
          >
            {suggestion}
          </button>
        ))}
      </div>

      <div className="copilot-input-row">
        <input
          className="input"
          placeholder="Ask about incidents, demand, inventory, routes or plans…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void send(input);
            }
          }}
          disabled={pending}
          aria-label="Message to ReliefMesh AI"
        />
        <button
          className="btn primary"
          onClick={() => void send(input)}
          disabled={pending || !input.trim()}
          aria-label="Send message"
        >
          <Send size={14} />
          {pending ? 'Analyzing…' : 'Send'}
        </button>
      </div>
    </div>
  );
}
