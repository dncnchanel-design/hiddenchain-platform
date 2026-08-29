import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export type CommandPollingOptions<T> = {
  enabled?: boolean;
  intervalMs?: number;
  errorRetryMs?: number;
  isTerminal?: (value: T) => boolean;
};

const neverTerminal = () => false;
const PERMANENT_POLLING_ERROR_STATUSES = new Set([401, 403, 404]);
export const MAX_CONSECUTIVE_POLLING_FAILURES = 4;

export function isCurrentRemoteRequest(currentRequestId: number, candidateRequestId: number): boolean {
  return currentRequestId === candidateRequestId;
}

export function shouldStopCommandPolling(status?: number | null): boolean {
  return status !== undefined && status !== null && PERMANENT_POLLING_ERROR_STATUSES.has(status);
}

export function shouldRetryCommandPolling(status?: number | null): boolean {
  return status === undefined
    || status === null
    || status === 408
    || status === 425
    || status === 429
    || status >= 500;
}

export function commandPollingRetryDelay(failureCount: number): number {
  return Math.min(15_000, 2_000 * (2 ** Math.max(0, failureCount - 1)));
}

export function useRemote<T>(loader: (signal?: AbortSignal) => Promise<T>, dependencies: unknown[] = [], requestScope?: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [refreshError, setRefreshError] = useState("");
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [refreshErrorStatus, setRefreshErrorStatus] = useState<number | null>(null);
  const [activeScope, setActiveScope] = useState<string | null>(requestScope ?? null);
  const dataRef = useRef<T | null>(null);
  const requestRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestId = ++requestRef.current;
    setActiveScope(requestScope ?? null);
    const hasData = dataRef.current !== null;
    if (hasData) setRefreshing(true);
    else setLoading(true);
    if (!hasData) setError("");
    if (!hasData) setErrorStatus(null);
    setRefreshError("");
    setRefreshErrorStatus(null);
    try {
      const next = await loader(controller.signal);
      if (!isCurrentRemoteRequest(requestRef.current, requestId)) return;
      dataRef.current = next;
      setData(next);
      setError("");
      setErrorStatus(null);
    } catch (reason) {
      if (!isCurrentRemoteRequest(requestRef.current, requestId)) return;
      if ((reason instanceof DOMException || reason instanceof Error) && reason.name === "AbortError") return;
      const baseMessage = reason instanceof TypeError ? "网络连接失败，请检查连接后重试" : reason instanceof Error ? reason.message : "加载失败";
      const message = reason instanceof ApiError && reason.traceId ? `${baseMessage}（Trace ID：${reason.traceId}）` : baseMessage;
      const status = reason instanceof ApiError ? reason.status : null;
      if (hasData) {
        setRefreshError(message);
        setRefreshErrorStatus(status);
      } else {
        setError(message);
        setErrorStatus(status);
      }
    } finally {
      if (isCurrentRemoteRequest(requestRef.current, requestId)) {
        setLoading(false);
        setRefreshing(false);
        if (controllerRef.current === controller) controllerRef.current = null;
      }
    }
  }, dependencies); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    void reload();
    return () => {
      requestRef.current += 1;
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [reload]);

  return { data, loading, refreshing, error, refreshError, errorStatus, refreshErrorStatus, activeScope, reload, setData };
}

export type ScopedRemoteData<T> = { scopeKey: string; payload: T };

export function dataForRemoteScope<T>(data: ScopedRemoteData<T> | null, scopeKey: string): T | null {
  return data?.scopeKey === scopeKey ? data.payload : null;
}

/**
 * Keeps route-scoped detail data bound to the entity that produced it. A route
 * change may reuse the same component instance, so useRemote's retained refresh
 * data must not be rendered under a different entity id.
 */
export function useScopedRemote<T>(
  scopeKey: string,
  loader: (signal?: AbortSignal) => Promise<T>,
  dependencies: unknown[] = [],
) {
  const remote = useRemote<ScopedRemoteData<T>>(
    async (signal) => ({ scopeKey, payload: await loader(signal) }),
    [scopeKey, ...dependencies],
    scopeKey,
  );
  const scopeActive = remote.activeScope === scopeKey;
  const data = scopeActive ? dataForRemoteScope(remote.data, scopeKey) : null;
  const scopedError = scopeActive && data === null ? remote.error || remote.refreshError : scopeActive ? remote.error : "";
  const scopedErrorStatus = scopeActive && data === null ? remote.errorStatus ?? remote.refreshErrorStatus : scopeActive ? remote.errorStatus : null;

  return {
    ...remote,
    data,
    loading: !scopeActive || (data === null && !scopedError && (remote.loading || remote.refreshing)),
    refreshing: data !== null && remote.refreshing,
    error: scopedError,
    errorStatus: scopedErrorStatus,
    refreshError: scopeActive && data !== null ? remote.refreshError : "",
    refreshErrorStatus: scopeActive && data !== null ? remote.refreshErrorStatus : null,
  };
}

/**
 * Adds non-overlapping polling for asynchronous command resources. Existing
 * screens can keep using useRemote; callers opt in only when a command endpoint
 * exposes durable status and a terminal-state predicate.
 */
export function useCommandPolling<T>(
  loader: (signal?: AbortSignal) => Promise<T>,
  dependencies: unknown[] = [],
  options: CommandPollingOptions<T> = {},
) {
  const remote = useRemote(loader, dependencies);
  const {
    enabled = true,
    intervalMs = 1_500,
    errorRetryMs = 4_000,
    isTerminal = neverTerminal,
  } = options;
  const { data, error, errorStatus, loading, refreshError, refreshErrorStatus, refreshing, reload } = remote;
  const terminal = data !== null && isTerminal(data);
  const permanentError = shouldStopCommandPolling(errorStatus) || shouldStopCommandPolling(refreshErrorStatus);

  useEffect(() => {
    if (!enabled || terminal || permanentError || loading || refreshing) return undefined;
    const delay = error || refreshError ? errorRetryMs : intervalMs;
    const timer = window.setTimeout(() => { void reload(); }, Math.max(250, delay));
    return () => window.clearTimeout(timer);
  }, [enabled, error, errorRetryMs, intervalMs, loading, permanentError, refreshError, refreshing, reload, terminal]);

  return { ...remote, polling: enabled && !terminal && !permanentError, terminal, permanentError };
}
