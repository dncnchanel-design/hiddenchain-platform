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

export function shouldStopCommandPolling(status?: number | null): boolean {
  return status !== undefined && status !== null && PERMANENT_POLLING_ERROR_STATUSES.has(status);
}

export function useRemote<T>(loader: (signal?: AbortSignal) => Promise<T>, dependencies: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [refreshError, setRefreshError] = useState("");
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [refreshErrorStatus, setRefreshErrorStatus] = useState<number | null>(null);
  const dataRef = useRef<T | null>(null);
  const requestRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestId = ++requestRef.current;
    const hasData = dataRef.current !== null;
    if (hasData) setRefreshing(true);
    else setLoading(true);
    if (!hasData) setError("");
    if (!hasData) setErrorStatus(null);
    setRefreshError("");
    setRefreshErrorStatus(null);
    try {
      const next = await loader(controller.signal);
      if (requestId !== requestRef.current) return;
      dataRef.current = next;
      setData(next);
      setError("");
      setErrorStatus(null);
    } catch (reason) {
      if (requestId !== requestRef.current) return;
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
      if (requestId === requestRef.current) {
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

  return { data, loading, refreshing, error, refreshError, errorStatus, refreshErrorStatus, reload, setData };
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
