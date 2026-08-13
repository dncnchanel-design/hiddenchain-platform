const API_BASE = import.meta.env.VITE_API_BASE || "/api";

type ApiRequestInit = RequestInit & {
  cacheTtlMs?: number;
  retry?: number;
  timeoutMs?: number;
};

type CachedResponse = {
  expiresAt: number;
  value: unknown;
};

const GET_CACHE = new Map<string, CachedResponse>();
const GET_IN_FLIGHT = new Map<string, Promise<unknown>>();
const DEFAULT_CACHE_TTL_MS = 4_000;
const DEFAULT_TIMEOUT_MS = 15_000;
const MAX_CACHE_ENTRIES = 100;
let cacheVersion = 0;

function cacheKey(path: string, token: string | null) {
  return `${token || "anonymous"}:${path}`;
}

function isRetryableStatus(status: number) {
  return status === 408 || status === 425 || status === 429 || status >= 500;
}

function wait(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms));
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function invalidateApiCache() {
  GET_CACHE.clear();
  GET_IN_FLIGHT.clear();
  cacheVersion += 1;
}

function storeCachedResponse(key: string, value: unknown, expiresAt: number) {
  if (GET_CACHE.size >= MAX_CACHE_ENTRIES && !GET_CACHE.has(key)) {
    const oldestKey = GET_CACHE.keys().next().value;
    if (oldestKey) GET_CACHE.delete(oldestKey);
  }
  GET_CACHE.set(key, { value, expiresAt });
}

export async function api<T>(path: string, options: ApiRequestInit = {}): Promise<T> {
  const token = localStorage.getItem("hiddenchain_token");
  const method = (options.method || "GET").toUpperCase();
  const isGet = method === "GET";
  const ttl = options.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;
  const key = cacheKey(path, token);
  const requestVersion = cacheVersion;
  if (isGet && ttl > 0 && options.cache !== "no-store") {
    const cached = GET_CACHE.get(key);
    if (cached && cached.expiresAt > Date.now()) return cached.value as T;
    if (cached) GET_CACHE.delete(key);
    const inFlight = GET_IN_FLIGHT.get(key);
    if (inFlight) return inFlight as Promise<T>;
  }

  const { cacheTtlMs: _cacheTtlMs, retry: _retry, timeoutMs: _timeoutMs, ...requestOptions } = options;
  const headers = new Headers(requestOptions.headers);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const request = (async () => {
    const retries = isGet ? Math.max(0, options.retry ?? 1) : 0;
    for (let attempt = 0; ; attempt += 1) {
      const controller = new AbortController();
      let timedOut = false;
      const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
      const abortFromCaller = () => controller.abort();
      if (options.signal?.aborted) controller.abort();
      else options.signal?.addEventListener("abort", abortFromCaller, { once: true });
      try {
        const response = await fetch(`${API_BASE}${path}`, { ...requestOptions, headers, signal: controller.signal });
        if (!response.ok) {
          if (attempt < retries && isRetryableStatus(response.status)) {
            await wait(180 * (attempt + 1));
            continue;
          }
          let message = `请求失败（${response.status}）`;
          try {
            const body = await response.json();
            message = body.detail || body.message || message;
          } catch {
            // Keep the status-based message for non-JSON errors.
          }
          if (response.status === 401) window.dispatchEvent(new Event("hiddenchain:unauthorized"));
          throw new ApiError(message, response.status);
        }
        if (response.status === 204) return undefined as T;
        const value = await response.json() as T;
        if (isGet && requestVersion === cacheVersion && ttl > 0 && options.cache !== "no-store") {
          storeCachedResponse(key, value, Date.now() + ttl);
        }
        return value;
      } catch (reason) {
        if ((reason instanceof DOMException || (reason instanceof Error && reason.name === "AbortError")) && timedOut) {
          if (attempt < retries) {
            await wait(180 * (attempt + 1));
            continue;
          }
          throw new ApiError("请求超时，请稍后重试", 408);
        }
        if (attempt < retries && reason instanceof TypeError) {
          await wait(180 * (attempt + 1));
          continue;
        }
        throw reason;
      } finally {
        window.clearTimeout(timeout);
        options.signal?.removeEventListener("abort", abortFromCaller);
      }
    }
  })();

  if (isGet && ttl > 0 && options.cache !== "no-store") {
    GET_IN_FLIGHT.set(key, request);
    request.finally(() => {
      if (GET_IN_FLIGHT.get(key) === request) GET_IN_FLIGHT.delete(key);
    }).catch(() => undefined);
  }
  try {
    return await request;
  } finally {
    if (!isGet || ttl <= 0 || options.cache === "no-store") invalidateApiCache();
  }
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "POST", body: JSON.stringify(body) }).then((value) => {
    invalidateApiCache();
    return value;
  });
}

export function shortHash(value?: string | null, length = 10): string {
  if (!value) return "-";
  if (value.length <= length * 2) return value;
  return `${value.slice(0, length)}…${value.slice(-6)}`;
}

export function formatDate(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatMoney(value?: number | string | null): string {
  const numeric = Number(value || 0);
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(numeric);
}
