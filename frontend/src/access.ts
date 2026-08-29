import type { RoleCode, SessionPayload } from "./types";

export type WorkspaceId = "business" | "admin";
export type NavigationGroupId = "entry" | "settlement" | "data" | "compute" | "audit" | "manage";

export type RouteCode =
  | "workbench"
  | "data-space"
  | "rules"
  | "compute"
  | "settlements"
  | "results"
  | "evidence"
  | "audit"
  | "reports"
  | "anomalies"
  | "overview"
  | "system"
  | "agents"
  | "trusted-execution"
  | "metrics"
  | "logs";

export interface RoutePolicy {
  code: RouteCode;
  path: string;
  title: string;
  workspace: WorkspaceId;
  group: NavigationGroupId;
  roles: readonly RoleCode[];
}

export type PrimaryNavigationId = "home" | "settlement" | "data" | "compute" | "audit" | "manage";

export interface PrimaryNavigationItem {
  id: string;
  label: string;
  to: string;
  routePath: string;
}

export interface PrimaryNavigationGroup {
  id: PrimaryNavigationId;
  label: string;
  workspace: WorkspaceId;
  directTo?: string;
  items: PrimaryNavigationItem[];
}

export const ROUTE_POLICIES: readonly RoutePolicy[] = [
  { code: "overview", path: "/overview", title: "管理总览", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "system", path: "/system", title: "组织与权限", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "agents", path: "/agents", title: "能力与服务", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "metrics", path: "/metrics", title: "运行监控", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "logs", path: "/logs", title: "系统日志", workspace: "admin", group: "manage", roles: ["ADMIN"] },
] as const;

export const NAVIGATION_GROUPS: Readonly<Record<WorkspaceId, readonly { id: NavigationGroupId; label: string }[]>> = {
  business: [],
  admin: [{ id: "manage", label: "管理功能" }],
};

export const WORKSPACE_LABELS: Readonly<Record<WorkspaceId, string>> = {
  business: "业务工作台",
  admin: "管理控制台",
};

export function getRoutePolicy(pathname: string): RoutePolicy | undefined {
  return ROUTE_POLICIES.find((route) => route.path === pathname);
}

export function canAccessRoute(session: SessionPayload, pathname: string): boolean {
  const policy = getRoutePolicy(pathname);
  if (!policy || !policy.roles.includes(session.user.role_code)) return false;
  return session.menus.some((menu) => menu.code === policy.code && menu.path === policy.path);
}

export function canAccessRouteView(session: SessionPayload, pathname: string, _search = ""): boolean {
  return canAccessRoute(session, pathname);
}

export function canCreateSettlement(session: SessionPayload): boolean {
  return session.user.role_code === "EXCHANGE"
    && session.menus.some((menu) => menu.code === "compute" && menu.path === "/trusted-space/mpc");
}

export function getVisibleRoutes(session: SessionPayload, workspace: WorkspaceId): RoutePolicy[] {
  return ROUTE_POLICIES.filter((route) => route.workspace === workspace && canAccessRoute(session, route.path));
}

export function getPrimaryNavigation(session: SessionPayload): PrimaryNavigationGroup[] {
  const labels: Partial<Record<RouteCode, string>> = {
    overview: "管理总览",
    system: "组织与权限",
    agents: "能力与服务",
    metrics: "运行监控",
    logs: "系统日志",
  };
  const items = getVisibleRoutes(session, "admin").map((route) => ({
    id: `${route.code}:${route.path}`,
    label: labels[route.code] || route.title,
    to: route.path,
    routePath: route.path,
  }));
  return items.length ? [{ id: "manage", label: "管理控制台", workspace: "admin", items }] : [];
}

export function getAvailableWorkspaces(session: SessionPayload): WorkspaceId[] {
  const workspaces: WorkspaceId[] = [];
  if (session.menus.some((menu) => menu.path === "/trusted-space/workbench")) workspaces.push("business");
  if (getVisibleRoutes(session, "admin").length) workspaces.push("admin");
  return workspaces;
}

export function getDefaultPath(session: SessionPayload, workspace?: WorkspaceId): string {
  const trustedSpaceHome = session.menus.find((menu) => menu.path === "/trusted-space/workbench")?.path;
  if ((!workspace || workspace === "business") && trustedSpaceHome) return trustedSpaceHome;
  const preferred = workspace || (session.user.role_code === "ADMIN" ? "admin" : "business");
  const routes = getVisibleRoutes(session, preferred);
  if (routes.length) return routes.find((route) => route.code === "overview")?.path || routes[0].path;
  return "/403";
}

export function getWorkspaceForPath(pathname: string, session: SessionPayload): WorkspaceId {
  if (pathname.startsWith("/trusted-space/")) return "business";
  return getRoutePolicy(pathname)?.workspace || (session.user.role_code === "ADMIN" ? "admin" : "business");
}
