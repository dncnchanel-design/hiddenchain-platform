const API_BASE = import.meta.env.VITE_API_BASE || "/api";

export type ApiResponseMetadata = {
  status: number;
  traceId?: string;
  requestId?: string;
  etag?: string;
  idempotencyReplayed: boolean;
};

export type ApiRequestInit = RequestInit & {
  cacheTtlMs?: number;
  retry?: number;
  timeoutMs?: number;
  idempotencyKey?: string;
  ifMatch?: string;
  onResponseMetadata?: (metadata: ApiResponseMetadata) => void;
};

export type ApiCommandOptions = Omit<ApiRequestInit, "body" | "method">;

export type IdempotencyKeyRecord = {
  fingerprint: string;
  key: string;
};

export function createIdempotencyKey(scope: string): string {
  const normalizedScope = scope.replace(/[^a-zA-Z0-9:_-]/g, "-").slice(0, 40) || "command";
  return `${normalizedScope}:${globalThis.crypto.randomUUID()}`.slice(0, 128);
}

export function prepareIdempotencyKey(
  previous: IdempotencyKeyRecord | null | undefined,
  scope: string,
  fingerprint: string,
): IdempotencyKeyRecord {
  if (previous?.fingerprint === fingerprint) return previous;
  return { fingerprint, key: createIdempotencyKey(scope) };
}

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
  traceId?: string;

  constructor(message: string, status: number, traceId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.traceId = traceId;
  }
}

function safeErrorMessage(value: unknown, status: number): string {
  const defaults: Record<number, string> = {
    400: "请求内容不符合要求，请检查后重试",
    401: "会话已失效，请重新登录",
    403: "当前账号无权执行此操作",
    404: "请求的业务对象不存在",
    408: "请求超时，请稍后重试",
    409: "当前状态不允许执行此操作",
    422: "提交内容未通过校验，请检查后重试",
    429: "操作过于频繁，请稍后重试",
  };
  const fallback = defaults[status] || (status >= 500 ? "服务暂时不可用，请稍后重试" : `请求失败（${status}）`);
  if (typeof value !== "string") return fallback;
  const message = value.trim();
  if (!message || message.length > 180) return fallback;
  if (/traceback|exception|sql|select\s|insert\s|update\s|delete\s|\.py\b|node_modules|stack|password|token|secret/i.test(message)) return fallback;
  return message;
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
  const token = sessionStorage.getItem("hiddenchain_token");
  const method = (options.method || "GET").toUpperCase();
  const isGet = method === "GET";
  const ttl = options.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;
  const key = cacheKey(path, token);
  const requestVersion = cacheVersion;
  const cacheEnabled = isGet && ttl > 0 && options.cache !== "no-store";
  const shareInFlight = cacheEnabled && !options.signal;
  if (cacheEnabled) {
    const cached = GET_CACHE.get(key);
    if (cached && cached.expiresAt > Date.now()) return cached.value as T;
    if (cached) GET_CACHE.delete(key);
    const inFlight = shareInFlight ? GET_IN_FLIGHT.get(key) : undefined;
    if (inFlight) return inFlight as Promise<T>;
  }

  const {
    cacheTtlMs: _cacheTtlMs,
    retry: _retry,
    timeoutMs: _timeoutMs,
    idempotencyKey: _idempotencyKey,
    ifMatch: _ifMatch,
    onResponseMetadata: _onResponseMetadata,
    ...requestOptions
  } = options;
  const headers = new Headers(requestOptions.headers);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.idempotencyKey && !headers.has("Idempotency-Key")) headers.set("Idempotency-Key", options.idempotencyKey);
  if (options.ifMatch && !headers.has("If-Match")) headers.set("If-Match", options.ifMatch);

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
        const traceId = response.headers.get("x-trace-id") || undefined;
        const requestId = response.headers.get("x-request-id") || undefined;
        const replayedHeader = response.headers.get("Idempotency-Replayed");
        options.onResponseMetadata?.({
          status: response.status,
          traceId,
          requestId,
          etag: response.headers.get("etag") || undefined,
          idempotencyReplayed: replayedHeader === "true" || replayedHeader === "1",
        });
        if (!response.ok) {
          if (attempt < retries && isRetryableStatus(response.status)) {
            await wait(180 * (attempt + 1));
            continue;
          }
          let body: Record<string, unknown> = {};
          try {
            body = await response.json();
          } catch {
            body = {};
          }
          const errorTraceId = traceId || requestId || (typeof body.trace_id === "string" ? body.trace_id : undefined);
          const detail = body.detail;
          const nestedDetailMessage = detail && typeof detail === "object" && !Array.isArray(detail)
            ? (detail as Record<string, unknown>).message
            : undefined;
          const errorValue = typeof detail === "string"
            ? detail
            : typeof nestedDetailMessage === "string"
              ? nestedDetailMessage
              : body.message;
          const message = safeErrorMessage(errorValue, response.status);
          if (response.status === 401) window.dispatchEvent(new Event("hiddenchain:unauthorized"));
          throw new ApiError(message, response.status, errorTraceId);
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

  if (shareInFlight) {
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

export function post<T>(path: string, body: unknown, options: ApiCommandOptions = {}): Promise<T> {
  return api<T>(path, { ...options, method: "POST", body: JSON.stringify(body) }).then((value) => {
    invalidateApiCache();
    return value;
  });
}

export function postForm<T>(path: string, form: FormData, options: ApiCommandOptions = {}): Promise<T> {
  return api<T>(path, { ...options, method: "POST", body: form }).then((value) => {
    invalidateApiCache();
    return value;
  });
}

export function shortHash(value?: string | null, length = 10): string {
  if (!value) return "—";
  if (value.length <= length * 2) return value;
  return `${value.slice(0, length)}…${value.slice(-6)}`;
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function formatMoney(value?: number | string | null): string {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value));
}

export function formatNumber(value?: number | string | null, fractionDigits = 0): string {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits }).format(Number(value));
}

export function formatPercent(value?: number | string | null, fractionDigits = 1): string {
  const formatted = formatNumber(value, fractionDigits);
  return formatted === "—" ? formatted : `${formatted}%`;
}
