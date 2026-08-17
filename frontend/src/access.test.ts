import { describe, expect, it } from "vitest";
import { ROUTE_POLICIES, canAccessRoute, getAvailableWorkspaces, getDefaultPath, getVisibleRoutes } from "./access";
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

  it("does not expose generator-only data entry to retailers", () => {
    const retailer = sessionFor("RETAILER");
    const paths = getVisibleRoutes(retailer, "business").map((route) => route.path);
    expect(paths).toContain("/data/retail");
    expect(paths).not.toContain("/data/generation");
  });
});
