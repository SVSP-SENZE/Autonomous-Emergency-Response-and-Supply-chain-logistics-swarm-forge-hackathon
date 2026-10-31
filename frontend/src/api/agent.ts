import { http } from './client';
import type {
  AgentChatResponse,
  AgentRunDetail,
  AgentSessionDetail,
  AgentSessionSummary,
  AgentStatusResponse,
} from '../types';

/** Full orchestrator turn: model -> validated read-only tools -> real results. */
export function sendAgentChat(
  message: string,
  sessionId: number | null,
): Promise<AgentChatResponse> {
  return http.post<AgentChatResponse>('/agent/chat', {
    message,
    ...(sessionId !== null ? { session_id: sessionId } : {}),
  });
}

export function listAgentSessions(
  limit = 20,
  signal?: AbortSignal,
): Promise<AgentSessionSummary[]> {
  return http.get<AgentSessionSummary[]>('/agent/sessions', { limit }, signal);
}

export function getAgentSession(
  sessionId: number,
  signal?: AbortSignal,
): Promise<AgentSessionDetail> {
  return http.get<AgentSessionDetail>(`/agent/sessions/${sessionId}`, undefined, signal);
}

export function getAgentRun(
  runId: number,
  signal?: AbortSignal,
): Promise<AgentRunDetail> {
  return http.get<AgentRunDetail>(`/agent/runs/${runId}`, undefined, signal);
}

export function getAgentStatus(signal?: AbortSignal): Promise<AgentStatusResponse> {
  return http.get<AgentStatusResponse>('/agent/status', undefined, signal);
}
