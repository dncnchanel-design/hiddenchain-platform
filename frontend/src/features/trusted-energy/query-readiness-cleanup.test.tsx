import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import { invalidateApiCache } from "../../api";
import { QueryPage } from "./pages/QueryPage";

const captured = vi.hoisted(() => ({ effects: [] as Array<() => unknown> }));
vi.mock("react", async (original) => ({ ...await original<typeof import("react")>(), useEffect: (effect: () => unknown) => { captured.effects.push(effect); } }));
vi.mock("react-router-dom", () => ({ useLocation: () => ({ search: "" }), Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a> }));
vi.mock("./trusted-space-context", () => ({ useTrustedSpaceContext: () => ({ context: null }) }));
vi.mock("./components/VisibleModuleBoundary", () => ({ VisibleModuleBoundary: () => <div>图表</div> }));
vi.mock("./components/PrototypePageFrame", () => ({ PrototypePageFrame: ({ children }: { children: ReactNode }) => <main>{children}</main>, PrototypeCardTitle: ({ children }: { children: ReactNode }) => <h3>{children}</h3> }));

afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); invalidateApiCache(); captured.effects = []; });

it("cancels the original node activation after later status polls and page unmount", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("window", { setTimeout, clearTimeout, dispatchEvent: vi.fn() });
  vi.stubGlobal("document", Object.assign(new EventTarget(), { visibilityState: "visible" }));
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => key === "hiddenchain:trusted-query:pending:v1" ? JSON.stringify({ task_id: "cleanup-task", idempotency_key: "cleanup-key", submission: null }) : "unit-token",
    removeItem: vi.fn(), setItem: vi.fn(),
  });
  const fetcher = vi.fn(async (url: string | URL | Request) => {
    if (String(url) === "https://node.example/health") return new Response("Starting", { status: 503 });
    return new Response(JSON.stringify({ task_id: "cleanup-task", status: "RUNNING", status_url: "/api/trust-space/query/tasks/cleanup-task", result_url: null,
      attempt: 1, max_attempts: 3, failure_code: null, failure_summary: null, created_at: "2026-10-25T00:00:00Z", started_at: null, completed_at: null, idempotent_replay: false,
      connector_readiness: { health_url: "https://node.example/health", organization_id: "org-a", energy_domain: "electricity", connector_id: "node-a", raw_data_accessed: false },
    }), { headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetcher);
  renderToStaticMarkup(<QueryPage />);
  const cleanup = captured.effects[0]() as () => void;
  await vi.advanceTimersByTimeAsync(3_100);
  expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/query/tasks/"))).toHaveLength(3);
  expect(fetcher.mock.calls.filter(([url]) => url === "https://node.example/health")).toHaveLength(1);
  cleanup();
  await vi.advanceTimersByTimeAsync(120_000);
  expect(fetcher.mock.calls.filter(([url]) => url === "https://node.example/health")).toHaveLength(1);
  expect(vi.getTimerCount()).toBe(0);
});
