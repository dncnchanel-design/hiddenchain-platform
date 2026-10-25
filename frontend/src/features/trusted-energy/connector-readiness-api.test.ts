import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { invalidateApiCache } from "../../api";
import { loadPrototypeDashboard, loadTrustedQueryTask } from "./trusted-space-api";

const descriptor = { health_url: "https://node.example/health", organization_id: "org-a", energy_domain: "electricity", connector_id: "node-a", raw_data_accessed: false };
const health = () => new Response(JSON.stringify({ organization_id: "org-a", energy_domain: "electricity", connector_id: "node-a" }), { headers: { "content-type": "application/json" } });
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
const task = { task_id: "api-readiness-a", status: "RUNNING", status_url: "/api/trust-space/query/tasks/api-readiness-a", result_url: null, attempt: 1, max_attempts: 3, failure_code: null, failure_summary: null, created_at: "2026-10-25T00:00:00Z", started_at: "2026-10-25T00:00:00Z", completed_at: null, idempotent_replay: false, connector_readiness: descriptor };

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("window", { setTimeout, clearTimeout, dispatchEvent: vi.fn() });
  vi.stubGlobal("sessionStorage", { getItem: () => "unit-token" });
  invalidateApiCache();
});
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); invalidateApiCache(); });

it("reloads the signed dashboard only after its own offered node is ready", async () => {
  let dashboardCalls = 0;
  const fetcher = vi.fn(async (url: string | URL | Request) => {
    if (String(url) === descriptor.health_url) return health();
    dashboardCalls += 1;
    return json(dashboardCalls === 1 ? { metric: { status: "unavailable", retryable: true }, connector_readiness: descriptor }
      : { metric: { status: "available", value: 15, source: "verified-backend" } });
  });
  vi.stubGlobal("fetch", fetcher);
  await expect(loadPrototypeDashboard()).resolves.toMatchObject({ metric: { status: "available", value: 15, source: "verified-backend" } });
  expect(fetcher).toHaveBeenCalledTimes(3);
  const reloaded = fetcher.mock.calls[2] as unknown as [string, RequestInit];
  expect(reloaded[1].cache).toBe("no-store");
});

it.each([false, undefined])("never activates a permanent or unknown dashboard failure (%s)", async (retryable) => {
  const fetcher = vi.fn().mockResolvedValue(json({ metric: { status: "unavailable", retryable }, connector_readiness: descriptor }));
  vi.stubGlobal("fetch", fetcher);
  await expect(loadPrototypeDashboard()).resolves.toMatchObject({ metric: { status: "unavailable" } });
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("returns the persisted task immediately and activates its offered node once across polls", async () => {
  const controller = new AbortController();
  const fetcher = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    if (String(url) === descriptor.health_url) return new Promise<Response>((resolve, reject) => {
      const timer = setTimeout(() => resolve(health()), 62_000);
      init?.signal?.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
    });
    return json(task);
  });
  vi.stubGlobal("fetch", fetcher);
  await expect(loadTrustedQueryTask(task.task_id, controller.signal)).resolves.toMatchObject({ task_id: task.task_id, status: "RUNNING" });
  await expect(loadTrustedQueryTask(task.task_id, controller.signal)).resolves.toMatchObject({ task_id: task.task_id });
  const nodeCalls = fetcher.mock.calls.filter(([url]) => url === descriptor.health_url);
  expect(nodeCalls).toHaveLength(1);
  expect(new Headers(nodeCalls[0][1]?.headers).has("Authorization")).toBe(false);
  expect(nodeCalls[0][1]?.credentials).toBe("omit");
  await vi.advanceTimersByTimeAsync(62_000);
  expect(vi.getTimerCount()).toBe(0);
});
