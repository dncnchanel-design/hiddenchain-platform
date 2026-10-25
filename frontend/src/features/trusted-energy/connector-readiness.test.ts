import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { prepareConnector, prepareQueryConnector } from "./connector-readiness";

const descriptor = { health_url: "https://node.example/health", organization_id: "org-a", energy_domain: "electricity", connector_id: "node-a", raw_data_accessed: false };
const identity = { organization_id: "org-a", energy_domain: "electricity", connector_id: "node-a" };
const healthy = () => new Response(JSON.stringify(identity), { headers: { "content-type": "application/json" } });

beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("uses a public credentialless health GET and accepts only the offered identity", async () => {
  const fetcher = vi.fn().mockResolvedValue(healthy()); vi.stubGlobal("fetch", fetcher);
  await expect(prepareConnector(descriptor)).resolves.toBe(true);
  expect(fetcher).toHaveBeenCalledWith(descriptor.health_url, expect.objectContaining({ method: "GET", credentials: "omit", redirect: "error", referrerPolicy: "no-referrer", cache: "no-store" }));
  const init = fetcher.mock.calls[0][1] as RequestInit;
  expect(init.headers).toBeUndefined(); expect(init.body).toBeUndefined();
  expect(vi.getTimerCount()).toBe(0);
});

it.each(["https://user:secret@node.example/health", "https://node.example/health?token=secret", "https://node.example/health#secret", "http://node.example/health", "https://node.example/compute", "https://node.exa\nmple/health"])("never requests unsafe offered URL %s", async (health_url) => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  await expect(prepareConnector({ ...descriptor, health_url })).resolves.toBe(false);
  expect(fetcher).not.toHaveBeenCalled();
});

it("allows the actual 62-second hosting startup without imposing the old 60-second upload timer", async () => {
  vi.stubGlobal("fetch", vi.fn((_url, init: RequestInit) => new Promise<Response>((resolve, reject) => {
    const timer = setTimeout(() => resolve(healthy()), 62_000);
    init.signal?.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
  })));
  const result = prepareConnector(descriptor);
  await vi.advanceTimersByTimeAsync(62_000);
  await expect(result).resolves.toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});

it("honors Retry-After, then succeeds without polling in the background afterwards", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response("Starting", { status: 429, headers: { "retry-after": "20" } })).mockResolvedValueOnce(healthy());
  vi.stubGlobal("fetch", fetcher);
  const result = prepareConnector(descriptor);
  await vi.advanceTimersByTimeAsync(19_999); expect(fetcher).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1); await expect(result).resolves.toBe(true);
  await vi.advanceTimersByTimeAsync(300_000); expect(fetcher).toHaveBeenCalledTimes(2);
});

it("bounds continual hosting failures to 90 seconds and removes all timers", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response("Starting", { status: 503 })); vi.stubGlobal("fetch", fetcher);
  const result = prepareConnector(descriptor);
  await vi.advanceTimersByTimeAsync(90_000); await expect(result).resolves.toBe(false);
  expect(fetcher).toHaveBeenCalledTimes(7); expect(vi.getTimerCount()).toBe(0);
});

it("stops on rejected or wrong-identity responses", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response("Denied", { status: 403 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...identity, organization_id: "other" }), { headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetcher);
  await expect(prepareConnector(descriptor)).resolves.toBe(false);
  await expect(prepareConnector(descriptor)).resolves.toBe(false);
  expect(fetcher).toHaveBeenCalledTimes(2); expect(vi.getTimerCount()).toBe(0);
});

it("cancels an active startup wait and never starts an already cancelled request", async () => {
  const controller = new AbortController();
  const fetcher = vi.fn().mockResolvedValue(new Response("Starting", { status: 503 })); vi.stubGlobal("fetch", fetcher);
  const result = prepareConnector(descriptor, controller.signal);
  await vi.advanceTimersByTimeAsync(1_000); controller.abort();
  await expect(result).resolves.toBe(false);
  await expect(prepareConnector(descriptor, controller.signal)).resolves.toBe(false);
  expect(fetcher).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(0);
});

it("starts only once per live task while repeated status polls return immediately", async () => {
  const fetcher = vi.fn().mockResolvedValue(healthy()); vi.stubGlobal("fetch", fetcher);
  for (let i = 0; i < 10; i += 1) prepareQueryConnector({ task_id: "once-a", status: "RUNNING", connector_readiness: descriptor });
  prepareQueryConnector({ task_id: "terminal-a", status: "FAILED", connector_readiness: descriptor });
  await vi.advanceTimersByTimeAsync(1);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});

it("can resume an activation cancelled by leaving the query page", async () => {
  const controller = new AbortController();
  const fetcher = vi.fn().mockResolvedValueOnce(new Response("Starting", { status: 503 })).mockResolvedValueOnce(healthy());
  vi.stubGlobal("fetch", fetcher);
  const task = { task_id: "resume-a", status: "RUNNING", connector_readiness: descriptor };
  prepareQueryConnector(task, controller.signal);
  await vi.advanceTimersByTimeAsync(1); controller.abort();
  await vi.advanceTimersByTimeAsync(1);
  prepareQueryConnector(task);
  await vi.advanceTimersByTimeAsync(1);
  expect(fetcher).toHaveBeenCalledTimes(2); expect(vi.getTimerCount()).toBe(0);
});
