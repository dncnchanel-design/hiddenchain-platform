import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { invalidateApiCache } from "../../api";
import { loadPrototypeDashboard } from "./trusted-space-api";
import { WorkbenchPage } from "./pages/WorkbenchPage";

const state = vi.hoisted(() => ({
  effects: [] as Array<() => unknown>, retry: { current: 0 }, wakeRetry: { current: false }, loader: undefined as undefined | ((signal?: AbortSignal) => Promise<unknown>), cleanup: undefined as (() => void) | undefined,
  remote: { data: null as unknown, loading: false, refreshing: false, error: "", refreshError: "", errorStatus: null as number | null, refreshErrorStatus: null as number | null, reload: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock("react", async (original) => ({ ...await original<typeof import("react")>(), useRef: (value: unknown) => typeof value === "boolean" ? state.wakeRetry : state.retry, useEffect: (effect: () => unknown) => { state.effects.push(effect); } }));
vi.mock("../../hooks", () => ({ useRemote: (loader: (signal?: AbortSignal) => Promise<unknown>) => { state.loader = loader; return state.remote; } }));
vi.mock("react-router-dom", () => ({ Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a> }));
vi.mock("./components/VisibleModuleBoundary", () => ({ VisibleModuleBoundary: () => <div>图表</div> }));
vi.mock("./components/PrototypePageFrame", () => ({ PrototypePageFrame: ({ children }: { children: ReactNode }) => <main>{children}</main>, PrototypeCardTitle: ({ children }: { children: ReactNode }) => <h3>{children}</h3> }));

function dashboard(status = "unavailable", retryable = true) {
  return { metric: { title: "主体指标", label: "负荷", status, retryable, status_label: status, value: status === "available" ? 14 : null, unit: "MW", trend: [], message: "连接器状态", source: "签名汇总", latest_date: "2026-09-30", aggregation: "日均", record_count: 12 },
    view: { kind: "enterprise", visualization: "subject_trend", kpis: [], primary_action: { path: "/trusted-space/query", label: "查询" } }, map: { days: [] }, action_counts: {}, audit: [], timeline: [], data_notice: "状态", data_mode: "subject_connector" };
}

function renderPage() {
  state.cleanup?.();
  state.effects = [];
  const markup = renderToStaticMarkup(<WorkbenchPage />);
  const cleanup = state.effects[0]?.();
  state.cleanup = typeof cleanup === "function" ? cleanup as () => void : undefined;
  return markup;
}

beforeEach(() => {
  vi.useFakeTimers();
  state.retry.current = 0;
  state.wakeRetry.current = false;
  state.loader = undefined;
  state.remote.data = dashboard();
  state.remote.loading = state.remote.refreshing = false;
  state.remote.error = state.remote.refreshError = "";
  state.remote.errorStatus = state.remote.refreshErrorStatus = null;
  state.remote.reload.mockClear();
  vi.stubGlobal("window", { setTimeout, clearTimeout, dispatchEvent: vi.fn() });
  vi.stubGlobal("document", Object.assign(new EventTarget(), { visibilityState: "visible" }));
  vi.stubGlobal("sessionStorage", { getItem: () => "unit-token" });
  invalidateApiCache();
});
afterEach(() => {
  state.cleanup?.(); state.cleanup = undefined;
  vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals();
  invalidateApiCache();
});

it("allows a 17-second cold dashboard response to finish inside its own 25-second request deadline", async () => {
  const fetcher = vi.fn((_url: unknown, options: RequestInit) => new Promise<Response>((resolve, reject) => {
    setTimeout(() => resolve(new Response(JSON.stringify({ metric: { status: "available", value: 14 } }), { status: 200 })), 17_000);
    options.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  }));
  vi.stubGlobal("fetch", fetcher);
  const observed = loadPrototypeDashboard().then((value) => ({ value }), (error: unknown) => ({ error }));
  await vi.advanceTimersByTimeAsync(17_010);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(await observed).toEqual({ value: { metric: { status: "available", value: 14 } } });
});

it("shows available dashboard content while its node starts, then reloads verified data", async () => {
  const descriptor = { health_url: "https://node.example/health", organization_id: "org-a", energy_domain: "electricity", connector_id: "node-a", raw_data_accessed: false };
  state.remote.data = { ...dashboard(), connector_readiness: descriptor };
  const fetcher = vi.fn((_url: unknown, options: RequestInit) => new Promise<Response>((resolve, reject) => {
    const timer = setTimeout(() => resolve(new Response(JSON.stringify(descriptor), { headers: { "content-type": "application/json" } })), 60_000);
    options.signal?.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
  }));
  vi.stubGlobal("fetch", fetcher);
  expect(renderPage()).toContain("主体指标");
  await vi.advanceTimersByTimeAsync(59_999);
  expect(state.remote.reload).not.toHaveBeenCalled();
  expect(fetcher).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(state.remote.reload).toHaveBeenCalledTimes(1);
  expect(state.wakeRetry.current).toBe(true);
});

it("uses the wake hint only for the first dashboard reload after node readiness", async () => {
  const fetcher = vi.fn(async (_url: string | URL | Request) => new Response(JSON.stringify({ metric: { status: "available" } }), { headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetcher);
  renderPage();
  await state.loader?.();
  state.wakeRetry.current = true;
  await state.loader?.();
  await state.loader?.();
  expect(fetcher.mock.calls.map(([url]) => String(url))).toEqual([
    "/api/prototype/dashboard", "/api/prototype/dashboard?wake_retry=true", "/api/prototype/dashboard",
  ]);
});

it("cancels background node activation when leaving the workbench", async () => {
  state.remote.data = { ...dashboard(), connector_readiness: { health_url: "https://node.example/health", organization_id: "org-a", energy_domain: "electricity", connector_id: "node-a", raw_data_accessed: false } };
  let aborted = false;
  vi.stubGlobal("fetch", vi.fn((_url: unknown, options: RequestInit) => new Promise<Response>((_resolve, reject) => {
    options.signal?.addEventListener("abort", () => { aborted = true; reject(new DOMException("Aborted", "AbortError")); }, { once: true });
  })));
  renderPage();
  state.cleanup?.(); state.cleanup = undefined;
  await vi.advanceTimersByTimeAsync(120_000);
  expect(aborted).toBe(true);
  expect(state.remote.reload).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});

it("cancels activation when hidden and starts a fresh one when visible", async () => {
  const descriptor = { health_url: "https://node.example/health", organization_id: "org-a", energy_domain: "electricity", connector_id: "node-a", raw_data_accessed: false };
  state.remote.data = { ...dashboard(), connector_readiness: descriptor };
  let aborted = 0;
  const fetcher = vi.fn((_url: unknown, options: RequestInit) => new Promise<Response>((resolve, reject) => {
    const timer = setTimeout(() => resolve(new Response(JSON.stringify(descriptor), { headers: { "content-type": "application/json" } })), 20_000);
    options.signal?.addEventListener("abort", () => { aborted += 1; clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
  }));
  vi.stubGlobal("fetch", fetcher);
  renderPage();
  expect(fetcher).toHaveBeenCalledTimes(1);
  Object.assign(document, { visibilityState: "hidden" });
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(30_000);
  expect(aborted).toBe(1);
  expect(state.remote.reload).not.toHaveBeenCalled();
  expect(fetcher).toHaveBeenCalledTimes(1);
  Object.assign(document, { visibilityState: "visible" });
  document.dispatchEvent(new Event("visibilitychange"));
  expect(fetcher).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(20_000);
  expect(state.remote.reload).toHaveBeenCalledTimes(1);
});

it("waits until the page is visible before reloading a node that became ready", async () => {
  const descriptor = { health_url: "https://node.example/health", organization_id: "org-a", energy_domain: "electricity", connector_id: "node-a", raw_data_accessed: false };
  state.remote.data = { ...dashboard(), connector_readiness: descriptor };
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => {
    setTimeout(() => resolve(new Response(JSON.stringify(descriptor), { headers: { "content-type": "application/json" } })), 1_000);
  })));
  renderPage();
  Object.assign(document, { visibilityState: "hidden" });
  await vi.advanceTimersByTimeAsync(1_000);
  expect(state.remote.reload).not.toHaveBeenCalled();
  Object.assign(document, { visibilityState: "visible" });
  document.dispatchEvent(new Event("visibilitychange"));
  expect(state.remote.reload).toHaveBeenCalledTimes(1);
});

it("reloads a retryable unavailable metric and stops once a real available result arrives", async () => {
  expect(renderPage()).toContain("—");
  await vi.advanceTimersByTimeAsync(9_999);
  expect(state.remote.reload).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);
  expect(state.remote.reload).toHaveBeenCalledTimes(1);
  state.remote.data = dashboard("available", false);
  expect(renderPage()).toContain("14");
  await vi.advanceTimersByTimeAsync(60_000);
  expect(state.remote.reload).toHaveBeenCalledTimes(1);
});

it("bounds repeated temporary failures to three automatic reloads", async () => {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    renderPage();
    await vi.advanceTimersByTimeAsync(10_000);
  }
  expect(state.remote.reload).toHaveBeenCalledTimes(3);
});

it.each(["unavailable", "not_configured"])("does not retry permanent identity failures or unconfigured nodes (%s)", async (status) => {
  state.remote.data = dashboard(status, false);
  renderPage();
  await vi.advanceTimersByTimeAsync(60_000);
  expect(state.remote.reload).not.toHaveBeenCalled();
});

it("pauses hidden pages and cancels pending recovery when the page unmounts", async () => {
  Object.assign(document, { visibilityState: "hidden" });
  renderPage();
  await vi.advanceTimersByTimeAsync(30_000);
  expect(state.remote.reload).not.toHaveBeenCalled();
  Object.assign(document, { visibilityState: "visible" });
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(10_000);
  expect(state.remote.reload).toHaveBeenCalledTimes(1);
  renderPage();
  state.cleanup?.(); state.cleanup = undefined;
  await vi.advanceTimersByTimeAsync(60_000);
  document.dispatchEvent(new Event("visibilitychange"));
  expect(state.remote.reload).toHaveBeenCalledTimes(1);
});

it.each([401, 403, 422])("does not automatically reload a permanent API error %s", async (status) => {
  state.remote.data = null;
  state.remote.error = "permanent";
  state.remote.errorStatus = status;
  renderPage();
  await vi.advanceTimersByTimeAsync(60_000);
  expect(state.remote.reload).not.toHaveBeenCalled();
});

it("can recover a temporary dashboard API failure before metric data exists", async () => {
  state.remote.data = null;
  state.remote.error = "temporary";
  state.remote.errorStatus = 503;
  renderPage();
  await vi.advanceTimersByTimeAsync(10_000);
  expect(state.remote.reload).toHaveBeenCalledTimes(1);
});

it.each([403, null])("a permanent refresh failure overrides an earlier retryable metric (%s)", async (status) => {
  renderPage();
  await vi.advanceTimersByTimeAsync(10_000);
  state.remote.refreshError = status === null ? "Malformed JSON" : "Access denied";
  state.remote.refreshErrorStatus = status;
  renderPage();
  await vi.advanceTimersByTimeAsync(60_000);
  expect(state.remote.reload).toHaveBeenCalledTimes(1);
});
