import { beforeEach, describe, expect, it, vi } from "vitest";
import { ROUTE_POLICIES, getAvailableWorkspaces, getVisibleRoutes } from "./access";
import { AgentsPage } from "./pages/AgentsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { MetricsPage } from "./pages/MetricsPage";
import { SystemPage } from "./pages/SystemPage";
import type { SessionPayload } from "./types";

const { apiMock, useRemoteMock } = vi.hoisted(() => ({ apiMock: vi.fn(), useRemoteMock: vi.fn() }));

vi.mock("./api", () => ({ api: apiMock }));
vi.mock("./hooks", () => ({ useRemote: useRemoteMock }));

const adminSession: SessionPayload = {
  user: { user_id: "admin-1", org_id: "platform", username: "admin", display_name: "管理员", role_code: "ADMIN", status: "ACTIVE" },
  org: { org_id: "platform", org_name: "平台" },
  did: {},
  menus: ROUTE_POLICIES.map((route) => ({ code: route.code, path: route.path, roles: [...route.roles] })),
  field_scopes: {},
};

describe("administrator data boundary", () => {
  beforeEach(() => {
    apiMock.mockReset();
    apiMock.mockResolvedValue({});
    useRemoteMock.mockReset();
    useRemoteMock.mockReturnValue({ data: null, loading: true, refreshing: false, error: "", reload: vi.fn() });
  });

  it("keeps administrators out of every business and regulatory route", () => {
    expect(getAvailableWorkspaces(adminSession)).toEqual(["admin"]);
    expect(getVisibleRoutes(adminSession, "business")).toEqual([]);
    expect(getVisibleRoutes(adminSession, "admin").map((route) => route.path)).toEqual([
      "/overview",
      "/system",
      "/agents",
      "/metrics",
      "/logs",
    ]);
  });

  it("loads each administrator page from exactly one sanitized endpoint", async () => {
    OverviewPage();
    SystemPage();
    AgentsPage();
    MetricsPage();
    for (const [loader] of useRemoteMock.mock.calls) await loader();

    expect(apiMock.mock.calls.map(([path]) => path)).toEqual([
      "/admin/overview",
      "/admin/system",
      "/admin/agents",
      "/metrics/summary",
    ]);
  });
});
