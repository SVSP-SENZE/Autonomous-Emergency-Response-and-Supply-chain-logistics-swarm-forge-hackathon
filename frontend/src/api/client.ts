/**
 * Central HTTP client for the ReliefMesh FastAPI backend.
 *
 * - Single configurable base URL (VITE_API_BASE_URL, default localhost:8000/api/v1).
 * - Typed request helpers with abort support (see `withAbort`).
 * - Consistent error handling using the backend error envelope
 *   `{"error": {"code", "message", "details"}}`.
 * - No secrets ever live here: the client only reads public VITE_ variables.
 */

const DEFAULT_BASE_URL = 'http://localhost:8000/api/v1';

export const API_BASE_URL: string = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || DEFAULT_BASE_URL
).replace(/\/+$/, '');

export class ApiError extends Error {
  readonly code: string;
  readonly httpStatus: number;
  readonly details: unknown;

  constructor(httpStatus: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.httpStatus = httpStatus;
    this.code = code || `http_${httpStatus}`;
    this.details = details ?? null;
  }

  /** Human-readable situation-aware hint for known failure modes. */
  get hint(): string | null {
    switch (this.code) {
      case 'ai_not_configured':
        return 'The Groq API key is not configured on the backend. Add GROQ_API_KEY to backend/.env and restart the server.';
      case 'ai_quota_exceeded':
        return 'Groq API quota exhausted. Wait before retrying; the request was not retried automatically.';
      case 'ai_upstream_error':
        return 'The Groq upstream service is unavailable right now. The backend did not modify any data.';
      case 'ai_timeout':
        return 'The Groq request timed out. Try a shorter question.';
      case 'validation_error':
        return 'The backend rejected this request payload.';
      case 'not_found':
        return 'Not found — it may not exist yet for this scenario.';
      default:
        return this.httpStatus >= 500
          ? 'Backend error — check the uvicorn log for details.'
          : null;
    }
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE' | 'PUT';
  body?: unknown;
  signal?: AbortSignal;
  params?: Record<string, string | number | boolean | undefined | null>;
}

function buildUrl(path: string, params?: RequestOptions['params']): string {
  let url = `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
  if (params) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') {
        search.set(key, String(value));
      }
    }
    const qs = search.toString();
    if (qs) url = `${url}?${qs}`;
  }
  return url;
}

function parseErrorEnvelope(payload: unknown, httpStatus: number): ApiError {
  if (
    payload &&
    typeof payload === 'object' &&
    'error' in (payload as Record<string, unknown>) &&
    typeof (payload as Record<string, unknown>).error === 'object'
  ) {
    const err = (payload as { error: Record<string, unknown> }).error;
    if (typeof err.message === 'string') {
      return new ApiError(
        httpStatus,
        typeof err.code === 'string' ? err.code : '',
        err.message,
        err.details,
      );
    }
  }
  return new ApiError(httpStatus, '', `Request failed with HTTP ${httpStatus}`);
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.params), {
      method: options.method ?? 'GET',
      headers: {
        Accept: 'application/json',
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(
      0,
      'network_error',
      `Cannot reach the ReliefMesh backend at ${API_BASE_URL}. Is uvicorn running?`,
    );
  }

  if (response.status === 204) return undefined as T;

  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    throw parseErrorEnvelope(payload, response.status);
  }
  return payload as T;
}

export const http = {
  get<T>(path: string, params?: RequestOptions['params'], signal?: AbortSignal): Promise<T> {
    return request<T>(path, { method: 'GET', params, signal });
  },
  post<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    return request<T>(path, { method: 'POST', body, signal });
  },
  patch<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    return request<T>(path, { method: 'PATCH', body, signal });
  },
  postWithQuery<T>(
    path: string,
    params: RequestOptions['params'],
    body?: unknown,
  ): Promise<T> {
    return request<T>(path, { method: 'POST', params, body });
  },
};

export { buildUrl };
