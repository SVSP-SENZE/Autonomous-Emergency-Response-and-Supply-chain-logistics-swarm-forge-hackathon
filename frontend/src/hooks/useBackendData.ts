import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  refreshing: boolean;
  error: ApiError | null;
  updatedAt: number | null;
  refresh: () => void;
}

/**
 * Fetch/poll backend data.
 *
 * - `pollMs` enables lightweight polling, automatically paused while the tab
 *   is hidden (document.visibilityState) to avoid pointless API traffic.
 * - Obsolete in-flight requests are cancelled via AbortController.
 * - Polling errors do NOT clear already-loaded data.
 */
export function useBackendData<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
  pollMs?: number,
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [reloadCounter, setReloadCounter] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const firstLoadDone = useRef(false);

  useEffect(() => {
    firstLoadDone.current = false;
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const controller = new AbortController();

    const run = async () => {
      const isFirstLoad = !firstLoadDone.current;
      if (isFirstLoad) setLoading(true);
      else setRefreshing(true);
      try {
        const result = await fetcherRef.current(controller.signal);
        if (controller.signal.aborted) return;
        setData(result);
        setError(null);
        firstLoadDone.current = true;
        setUpdatedAt(Date.now());
      } catch (err) {
        if (controller.signal.aborted) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err : new ApiError(0, 'client_error', String(err)));
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    };

    void run();

    let intervalId: ReturnType<typeof setInterval> | null = null;
    if (pollMs && pollMs > 0) {
      intervalId = setInterval(() => {
        if (document.visibilityState === 'visible' && !controller.signal.aborted) {
          void run();
        }
      }, pollMs);
    }

    return () => {
      controller.abort();
      if (intervalId) clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, pollMs, reloadCounter]);

  const refresh = useCallback(() => {
    setReloadCounter((count) => count + 1);
  }, []);

  return { data, loading, refreshing, error, updatedAt, refresh };
}
