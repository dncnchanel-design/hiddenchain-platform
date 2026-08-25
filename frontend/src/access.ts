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

const ALL_ROLES: readonly RoleCode[] = ["GENERATOR", "RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"];
const REVIEW_ROLES: readonly RoleCode[] = ["EXCHANGE", "REGULATOR", "ADMIN"];
const ANALYSIS_ROLES: readonly RoleCode[] = ["RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"];

export const ROUTE_POLICIES: readonly RoutePolicy[] = [
  { code: "workbench", path: "/workbench", title: "工作台", workspace: "business", group: "entry", roles: ALL_ROLES },
  { code: "data-space", path: "/data-space", title: "可信数据目录", workspace: "business", group: "data", roles: ALL_ROLES },
  { code: "rules", path: "/rules", title: "结算规则", workspace: "business", group: "settlement", roles: REVIEW_ROLES },
  { code: "compute", path: "/compute", title: "隐私计算", workspace: "business", group: "compute", roles: ALL_ROLES },
  { code: "settlements", path: "/settlements", title: "结算任务", workspace: "business", group: "settlement", roles: ALL_ROLES },
  { code: "results", path: "/results", title: "结算结果", workspace: "business", group: "settlement", roles: ALL_ROLES },
  { code: "evidence", path: "/evidence", title: "证据台账", workspace: "business", group: "audit", roles: ALL_ROLES },
  { code: "audit", path: "/audit", title: "审计复核", workspace: "business", group: "audit", roles: REVIEW_ROLES },
  { code: "reports", path: "/reports", title: "审计报告", workspace: "business", group: "audit", roles: REVIEW_ROLES },
  { code: "anomalies", path: "/anomalies", title: "风险处置", workspace: "business", group: "audit", roles: REVIEW_ROLES },
  { code: "overview", path: "/overview", title: "管理总览", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "system", path: "/system", title: "组织与权限", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "agents", path: "/agents", title: "能力与服务", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "trusted-execution", path: "/trusted-execution", title: "受控数据使用", workspace: "business", group: "data", roles: REVIEW_ROLES },
  { code: "metrics", path: "/metrics", title: "运行监控", workspace: "admin", group: "manage", roles: ["ADMIN"] },
  { code: "logs", path: "/logs", title: "系统日志", workspace: "admin", group: "manage", roles: ["ADMIN"] },
] as const;

export const NAVIGATION_GROUPS: Readonly<Record<WorkspaceId, readonly { id: NavigationGroupId; label: string }[]>> = {
  business: [
    { id: "entry", label: "工作入口" },
    { id: "settlement", label: "结算业务" },
    { id: "data", label: "可信数据空间" },
    { id: "compute", label: "隐私计算" },
    { id: "audit", label: "审计与风控" },
  ],
  admin: [{ id: "manage", label: "管理功能" }],
};

export const WORKSPACE_LABELS: Readonly<Record<WorkspaceId, string>> = {
  business: "业务工作台",
  admin: "管理控制台",
};

export function getRoutePolicy(pathname: string): RoutePolicy | undefined {
  if (pathname.startsWith("/settlements/")) {
    return ROUTE_POLICIES.find((route) => route.code === "settlements");
  }
  return ROUTE_POLICIES.find((route) => route.path === pathname);
}

export function canAccessRoute(session: SessionPayload, pathname: string): boolean {
  const policy = getRoutePolicy(pathname);
  if (!policy || !policy.roles.includes(session.user.role_code)) return false;
  return session.menus.some((menu) => (
    menu.code === policy.code
    && (menu.path === policy.path || (policy.code === "compute" && menu.path === "/trusted-space/mpc"))
  ));
}

export function canAccessRouteView(session: SessionPayload, pathname: string, search = ""): boolean {
  if (!canAccessRoute(session, pathname)) return false;
  if (pathname === "/compute" && new URLSearchParams(search).get("tab") === "analysis") {
    return ANALYSIS_ROLES.includes(session.user.role_code);
  }
  return true;
}

export function canCreateSettlement(session: SessionPayload): boolean {
  return session.user.role_code === "EXCHANGE" && canAccessRoute(session, "/settlements");
}

export function getVisibleRoutes(session: SessionPayload, workspace: WorkspaceId): RoutePolicy[] {
  return ROUTE_POLICIES.filter((route) => route.workspace === workspace && canAccessRoute(session, route.path));
}

export function getPrimaryNavigation(session: SessionPayload): PrimaryNavigationGroup[] {
  const visibleRoutes = [...getVisibleRoutes(session, "business"), ...getVisibleRoutes(session, "admin")];
  const routeByCode = new Map(visibleRoutes.map((route) => [route.code, route]));
  const item = (code: RouteCode, label: string, to?: string): PrimaryNavigationItem | null => {
    const route = routeByCode.get(code);
    return route ? { id: `${code}:${to || route.path}`, label, to: to || route.path, routePath: route.path } : null;
  };
  const compact = (items: Array<PrimaryNavigationItem | null>) => items.filter((entry): entry is PrimaryNavigationItem => Boolean(entry));
  const groups: PrimaryNavigationGroup[] = [];
  const workbench = routeByCode.get("workbench");

  if (workbench) {
    groups.push({ id: "home", label: "首页", workspace: "business", directTo: workbench.path, items: [] });
  }

  const settlementItems = compact([
    canCreateSettlement(session) ? { id: "settlement:create", label: "发起结算任务", to: "/settlements/new", routePath: "/settlements" } : null,
    item("settlements", "结算任务"),
    item("settlements", "待我处理", "/settlements?view=todo"),
    item("results", "结果确认"),
    item("settlements", "结算记录", "/settlements?view=completed"),
    item("rules", "结算规则"),
  ]);
  if (settlementItems.length) groups.push({ id: "settlement", label: "结算管理", workspace: "business", items: settlementItems });

  const dataItems = compact([
    item("data-space", "数据目录"),
    item("trusted-execution", "受控数据使用"),
    item("data-space", "数据授权记录", "/data-space#data-authorizations"),
  ]);
  if (dataItems.length) groups.push({ id: "data", label: "可信数据空间", workspace: "business", items: dataItems });

  const computeItems = compact([
    item("compute", "计算任务", "/compute?tab=tasks"),
    item("compute", "计算方案", "/compute#compute-strategies"),
    ANALYSIS_ROLES.includes(session.user.role_code)
      ? item("compute", "用电分析", "/compute?tab=analysis")
      : null,
  ]);
  if (computeItems.length) groups.push({ id: "compute", label: "隐私计算", workspace: "business", items: computeItems });

  const auditItems = compact([
    item("evidence", "审计凭证"),
    item("audit", "审计复核"),
    item("reports", "审计报告"),
    item("anomalies", "风险处置"),
  ]);
  if (auditItems.length) groups.push({ id: "audit", label: "审计与风控", workspace: "business", items: auditItems });

  const manageItems = compact([
    item("overview", "管理总览"),
    item("system", "组织与权限"),
    item("agents", "能力与服务"),
    item("metrics", "运行监控"),
    item("logs", "系统日志"),
  ]);
  if (manageItems.length) groups.push({ id: "manage", label: "管理控制台", workspace: "admin", items: manageItems });

  return groups;
}

export function getAvailableWorkspaces(session: SessionPayload): WorkspaceId[] {
  return (["business", "admin"] as const).filter((workspace) => getVisibleRoutes(session, workspace).length > 0);
}

export function getDefaultPath(session: SessionPayload, workspace?: WorkspaceId): string {
  const trustedSpaceHome = session.menus.find((menu) => menu.path === "/trusted-space/workbench")?.path;
  if (!workspace && trustedSpaceHome) return trustedSpaceHome;
  const preferred = workspace || (session.user.role_code === "ADMIN" ? "admin" : "business");
  const routes = getVisibleRoutes(session, preferred);
  if (routes.length) return preferred === "admin" ? routes.find((route) => route.code === "overview")?.path || routes[0].path : routes.find((route) => route.code === "workbench")?.path || routes[0].path;
  return getVisibleRoutes(session, "business")[0]?.path || "/403";
}

export function getWorkspaceForPath(pathname: string, session: SessionPayload): WorkspaceId {
  return getRoutePolicy(pathname)?.workspace || (session.user.role_code === "ADMIN" ? "admin" : "business");
}
