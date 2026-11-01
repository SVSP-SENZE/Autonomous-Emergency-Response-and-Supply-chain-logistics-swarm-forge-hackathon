/**
 * ReliefMesh Mobile — HTTP client
 * Wraps fetch with timeout, consistent error handling and offline detection.
 */

const DEFAULT_BASE_URL = 'http://10.0.2.2:8000/api/v1'; // Android emulator default

export const API_BASE_URL: string = (
  (process.env.EXPO_PUBLIC_API_BASE_URL as string | undefined) || DEFAULT_BASE_URL
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

  get isNetworkError() {
    return this.httpStatus === 0;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE' | 'PUT';
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
  timeoutMs?: number;
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
    'error' in (payload as Record<string, unknown>)
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
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    options.timeoutMs ?? 10000,
  );

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.params), {
      method: options.method ?? 'GET',
      headers: {
        Accept: 'application/json',
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeout);
    throw new ApiError(
      0,
      'network_error',
      `Cannot reach the ReliefMesh backend at ${API_BASE_URL}. Check your connection or server.`,
    );
  } finally {
    clearTimeout(timeout);
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
  get<T>(path: string, params?: RequestOptions['params']): Promise<T> {
    return request<T>(path, { method: 'GET', params });
  },
  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: 'POST', body });
  },
  patch<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: 'PATCH', body });
  },
};
