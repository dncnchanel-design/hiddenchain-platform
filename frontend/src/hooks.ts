import { useCallback, useEffect, useRef, useState } from "react";

export function useRemote<T>(loader: (signal?: AbortSignal) => Promise<T>, dependencies: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [refreshError, setRefreshError] = useState("");
  const dataRef = useRef<T | null>(null);
  const requestRef = useRef(0);

  const reload = useCallback(async () => {
    const requestId = ++requestRef.current;
    const hasData = dataRef.current !== null;
    if (hasData) setRefreshing(true);
    else setLoading(true);
    if (!hasData) setError("");
    setRefreshError("");
    try {
      const next = await loader();
      if (requestId !== requestRef.current) return;
      dataRef.current = next;
      setData(next);
      setError("");
    } catch (reason) {
      if (requestId !== requestRef.current) return;
      const message = reason instanceof Error ? reason.message : "加载失败";
      if (hasData) setRefreshError(message);
      else setError(message);
    } finally {
      if (requestId === requestRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, dependencies); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    void reload();
    return () => {
      requestRef.current += 1;
    };
  }, [reload]);

  return { data, loading, refreshing, error, refreshError, reload, setData };
}
