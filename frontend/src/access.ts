import type { RoleCode, SessionPayload } from "./types";

export type WorkspaceId = "business" | "admin";
export type NavigationGroupId = "entry" | "data" | "compute" | "audit" | "manage";

export type RouteCode =
  | "workbench"
  | "data-space"
  | "generation-data"
  | "retail-data"
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

const ALL_ROLES: readonly RoleCode[] = ["GENERATOR", "RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"];
const REVIEW_ROLES: readonly RoleCode[] = ["EXCHANGE", "REGULATOR", "ADMIN"];

export const ROUTE_POLICIES: readonly RoutePolicy[] = [
  { code: "workbench", path: "/workbench", title: "工作台", workspace: "business", group: "entry", roles: ALL_ROLES },
  { code: "data-space", path: "/data-space", title: "数据目录", workspace: "business", group: "data", roles: ALL_ROLES },
  { code: "generation-data", path: "/data/generation", title: "发电侧数据", workspace: "business", group: "data", roles: ["GENERATOR", "EXCHANGE", "REGULATOR", "ADMIN"] },
  { code: "retail-data", path: "/data/retail", title: "用电侧数据", workspace: "business", group: "data", roles: ["RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"] },
  { code: "rules", path: "/rules", title: "授权规则", workspace: "business", group: "data", roles: REVIEW_ROLES },
  { code: "compute", path: "/compute", title: "隐私计算", workspace: "business", group: "compute", roles: ALL_ROLES },
  { code: "settlements", path: "/settlements", title: "调用验证", workspace: "business", group: "compute", roles: ALL_ROLES },
  { code: "results", path: "/results", title: "结果确认", workspace: "business", group: "compute", roles: ALL_ROLES },
  { code: "evidence", path: "/evidence", title: "审计凭证", workspace: "business", group: "audit", roles: ALL_ROLES },
  { code: "audit", path: "/audit", title: "审计复核", workspace: "business", group: "audit", roles: REVIEW_ROLES },
  { code: "reports", path: "/reports", title: "审计报告", workspace: "business", group: "audit", roles: REVIEW_ROLES },
  { code: "anomalies", path: "/anomalies", title: "风险处置", workspace: "business", group: "audit", roles: REVIEW_ROLES },
  { code: "overview", path: "/overview", title: "管理总览", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "system", path: "/system", title: "组织与权限", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "agents", path: "/agents", title: "能力与服务", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "metrics", path: "/metrics", title: "运行监控", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "logs", path: "/logs", title: "系统日志", workspace: "admin", group: "manage", roles: ["ADMIN"] },
] as const;

export const NAVIGATION_GROUPS: Readonly<Record<WorkspaceId, readonly { id: NavigationGroupId; label: string }[]>> = {
  business: [
    { id: "entry", label: "工作入口" },
    { id: "data", label: "数据与授权" },
    { id: "compute", label: "计算与验证" },
    { id: "audit", label: "审计与风控" },
  ],
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

export function getVisibleRoutes(session: SessionPayload, workspace: WorkspaceId): RoutePolicy[] {
  return ROUTE_POLICIES.filter((route) => route.workspace === workspace && canAccessRoute(session, route.path));
}

export function getAvailableWorkspaces(session: SessionPayload): WorkspaceId[] {
  return (["business", "admin"] as const).filter((workspace) => getVisibleRoutes(session, workspace).length > 0);
}

export function getDefaultPath(session: SessionPayload, workspace?: WorkspaceId): string {
  const preferred = workspace || (session.user.role_code === "ADMIN" ? "admin" : "business");
  const routes = getVisibleRoutes(session, preferred);
  if (routes.length) return preferred === "admin" ? routes.find((route) => route.code === "overview")?.path || routes[0].path : routes.find((route) => route.code === "workbench")?.path || routes[0].path;
  return getVisibleRoutes(session, "business")[0]?.path || "/403";
}

export function getWorkspaceForPath(pathname: string, session: SessionPayload): WorkspaceId {
  return getRoutePolicy(pathname)?.workspace || (session.user.role_code === "ADMIN" ? "admin" : "business");
}
