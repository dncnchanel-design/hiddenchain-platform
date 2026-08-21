import { describe, expect, it } from "vitest";
import { ROUTE_POLICIES, canAccessRoute, canAccessRouteView, canCreateSettlement, getAvailableWorkspaces, getDefaultPath, getPrimaryNavigation, getVisibleRoutes } from "./access";
import type { RoleCode, SessionPayload } from "./types";

function sessionFor(role: RoleCode, menuPaths = ROUTE_POLICIES.map((route) => route.path)): SessionPayload {
  return {
    user: { user_id: "user-1", org_id: "org-1", username: "tester", display_name: "测试用户", role_code: role, status: "ACTIVE" },
    org: { org_id: "org-1", org_name: "测试组织" },
    did: {},
    menus: ROUTE_POLICIES.filter((route) => menuPaths.includes(route.path)).map((route) => ({ code: route.code, path: route.path, roles: [...route.roles] })),
    field_scopes: {},
  };
}

describe("route access policy", () => {
  it("keeps business users in the business workspace", () => {
    const session = sessionFor("GENERATOR");
    expect(getAvailableWorkspaces(session)).toEqual(["business"]);
    expect(getDefaultPath(session)).toBe("/workbench");
  });

  it("gives administrators separate business and admin workspaces", () => {
    const session = sessionFor("ADMIN");
    expect(getAvailableWorkspaces(session)).toEqual(["business", "admin"]);
    expect(getDefaultPath(session)).toBe("/overview");
    expect(getDefaultPath(session, "business")).toBe("/workbench");
  });

  it("restricts management routes to administrators even when backend menus contain them", () => {
    const regulator = sessionFor("REGULATOR");
    expect(canAccessRoute(regulator, "/agents")).toBe(false);
    expect(canAccessRoute(regulator, "/logs")).toBe(false);
    expect(canAccessRoute(regulator, "/metrics")).toBe(false);
  });

  it("requires both the frontend role policy and a matching backend menu", () => {
    const exchange = sessionFor("EXCHANGE", ["/workbench", "/settlements"]);
    expect(canAccessRoute(exchange, "/settlements")).toBe(true);
    expect(canAccessRoute(exchange, "/rules")).toBe(false);
  });

  it("exposes one shared Excel upload entry instead of side-specific data pages", () => {
    const retailer = sessionFor("RETAILER");
    const paths = getVisibleRoutes(retailer, "business").map((route) => route.path);
    expect(paths).toContain("/data/upload");
    expect(paths).not.toContain("/data/generation");
    expect(paths).not.toContain("/data/retail");
  });

  it("only lets the exchange create a settlement even though all roles can view tasks", () => {
    expect(canCreateSettlement(sessionFor("EXCHANGE"))).toBe(true);
    expect(canCreateSettlement(sessionFor("GENERATOR"))).toBe(false);
    expect(canCreateSettlement(sessionFor("REGULATOR"))).toBe(false);
    expect(canCreateSettlement(sessionFor("ADMIN"))).toBe(false);
  });

  it("rejects restricted query-driven views on direct navigation", () => {
    expect(canAccessRouteView(sessionFor("GENERATOR"), "/compute", "?tab=tasks")).toBe(true);
    expect(canAccessRouteView(sessionFor("GENERATOR"), "/compute", "?tab=analysis")).toBe(false);
    expect(canAccessRouteView(sessionFor("RETAILER"), "/compute", "?tab=analysis")).toBe(true);
  });

  it("builds top-level navigation from the same role and backend menu policy", () => {
    const generatorNavigation = getPrimaryNavigation(sessionFor("GENERATOR"));
    expect(generatorNavigation.map((group) => group.label)).toEqual(["首页", "结算管理", "可信数据空间", "隐私计算", "审计与风控"]);
    expect(generatorNavigation.flatMap((group) => group.items).map((item) => item.label)).not.toContain("发起结算任务");
    expect(generatorNavigation.flatMap((group) => group.items).map((item) => item.label)).not.toContain("用电侧数据");
    expect(generatorNavigation.flatMap((group) => group.items).map((item) => item.label)).toContain("Excel 批量上传");
    expect(generatorNavigation.some((group) => group.id === "manage")).toBe(false);

    const adminNavigation = getPrimaryNavigation(sessionFor("ADMIN"));
    expect(adminNavigation.find((group) => group.id === "manage")?.items.map((item) => item.label)).toEqual([
      "管理总览",
      "组织与权限",
      "能力与服务",
      "运行监控",
      "系统日志",
    ]);
  });

  it("adds only real view entries and gates task creation", () => {
    const exchangeNavigation = getPrimaryNavigation(sessionFor("EXCHANGE"));
    const settlementItems = exchangeNavigation.find((group) => group.id === "settlement")?.items || [];
    expect(settlementItems.map((item) => item.label)).toEqual(["发起结算任务", "结算任务", "待我处理", "结果确认", "结算记录", "结算规则"]);
    expect(settlementItems.find((item) => item.label === "结算记录")?.to).toBe("/settlements?view=completed");

    const restricted = getPrimaryNavigation(sessionFor("EXCHANGE", ["/workbench", "/settlements"]));
    expect(restricted.flatMap((group) => group.items).map((item) => item.label)).not.toContain("结算规则");
    expect(restricted.flatMap((group) => group.items).map((item) => item.label)).not.toContain("结果确认");
  });
});
