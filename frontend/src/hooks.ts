import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export function useRemote<T>(loader: (signal?: AbortSignal) => Promise<T>, dependencies: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [refreshError, setRefreshError] = useState("");
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
    setRefreshError("");
    try {
      const next = await loader(controller.signal);
      if (requestId !== requestRef.current) return;
      dataRef.current = next;
      setData(next);
      setError("");
    } catch (reason) {
      if (requestId !== requestRef.current) return;
      if ((reason instanceof DOMException || reason instanceof Error) && reason.name === "AbortError") return;
      const baseMessage = reason instanceof TypeError ? "网络连接失败，请检查连接后重试" : reason instanceof Error ? reason.message : "加载失败";
      const message = reason instanceof ApiError && reason.traceId ? `${baseMessage}（Trace ID：${reason.traceId}）` : baseMessage;
      if (hasData) setRefreshError(message);
      else setError(message);
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

  return { data, loading, refreshing, error, refreshError, reload, setData };
}
