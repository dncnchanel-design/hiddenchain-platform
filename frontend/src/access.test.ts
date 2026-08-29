import { describe, expect, it } from "vitest";
import { ROUTE_POLICIES, canAccessRoute, canCreateSettlement, getAvailableWorkspaces, getDefaultPath, getPrimaryNavigation, getVisibleRoutes } from "./access";
import type { RoleCode, SessionPayload } from "./types";

const trustedMenus = [
  ["overview", "/trusted-space/workbench"],
  ["query", "/trusted-space/query"],
  ["catalog", "/trusted-space/catalog"],
  ["connector", "/trusted-space/connector"],
  ["authorization", "/trusted-space/authorizations"],
  ["audit", "/trusted-space/audit"],
  ["compute", "/trusted-space/mpc"],
  ["participants", "/trusted-space/identity"],
] as const;

function sessionFor(role: RoleCode, menus = role === "ADMIN"
  ? ROUTE_POLICIES.map((route) => [route.code, route.path] as const)
  : trustedMenus): SessionPayload {
  return {
    user: { user_id: "user-1", org_id: "org-1", username: "tester", display_name: "测试用户", role_code: role, status: "ACTIVE" },
    org: { org_id: "org-1", org_name: "测试组织" },
    did: {},
    menus: menus.map(([code, path]) => ({ code, path, roles: [role] })),
    field_scopes: {},
  };
}

describe("route access policy", () => {
  it("sends business users to Trusted Space without exposing legacy AppShell routes", () => {
    const session = sessionFor("GENERATOR");
    expect(getAvailableWorkspaces(session)).toEqual(["business"]);
    expect(getDefaultPath(session)).toBe("/trusted-space/workbench");
    expect(getVisibleRoutes(session, "business")).toEqual([]);
    expect(getPrimaryNavigation(session)).toEqual([]);
    for (const path of ["/workbench", "/data-space", "/rules", "/settlements", "/compute", "/results", "/evidence", "/audit", "/reports", "/anomalies", "/trusted-execution"]) {
      expect(canAccessRoute(session, path), path).toBe(false);
    }
  });

  it("keeps administrators in the five-route sanitized workspace", () => {
    const session = sessionFor("ADMIN");
    expect(getAvailableWorkspaces(session)).toEqual(["admin"]);
    expect(getDefaultPath(session)).toBe("/overview");
    expect(getDefaultPath(session, "business")).toBe("/403");
    expect(getVisibleRoutes(session, "admin").map((route) => route.path)).toEqual([
      "/overview", "/system", "/agents", "/metrics", "/logs",
    ]);
    expect(getPrimaryNavigation(session).flatMap((group) => group.items).map((item) => item.label)).toEqual([
      "管理总览", "组织与权限", "能力与服务", "运行监控", "系统日志",
    ]);
  });

  it("requires the exact trusted compute capability for the compatibility create entry", () => {
    expect(canCreateSettlement(sessionFor("EXCHANGE"))).toBe(true);
    expect(canCreateSettlement(sessionFor("GENERATOR"))).toBe(false);
    expect(canCreateSettlement(sessionFor("ADMIN"))).toBe(false);
    expect(canCreateSettlement(sessionFor("EXCHANGE", [["compute", "/compute"]]))).toBe(false);
    expect(canCreateSettlement(sessionFor("EXCHANGE", [["overview", "/trusted-space/workbench"]]))).toBe(false);
  });

  it("requires both the administrator role and its exact backend menu", () => {
    expect(canAccessRoute(sessionFor("ADMIN"), "/agents")).toBe(true);
    expect(canAccessRoute(sessionFor("REGULATOR", [["agents", "/agents"]]), "/agents")).toBe(false);
    expect(canAccessRoute(sessionFor("ADMIN", [["agents", "/legacy-agents"]]), "/agents")).toBe(false);
  });
});
