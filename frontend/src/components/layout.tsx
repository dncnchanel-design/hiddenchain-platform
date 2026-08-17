import { Suspense, useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  BarChart3,
  Bell,
  Building2,
  Calculator,
  ChevronDown,
  ChevronRight,
  CircleGauge,
  ClipboardCheck,
  Database,
  FileCheck2,
  FileClock,
  FileText,
  Gavel,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  UserRound,
  UsersRound,
  Workflow,
  X,
  Zap,
} from "lucide-react";
import {
  NAVIGATION_GROUPS,
  WORKSPACE_LABELS,
  canAccessRoute,
  getAvailableWorkspaces,
  getDefaultPath,
  getRoutePolicy,
  getVisibleRoutes,
  getWorkspaceForPath,
  type RouteCode,
  type WorkspaceId,
} from "../access";
import { useAuth } from "../auth";
import { BrandLockup, productDocumentTitle, useProductConfig } from "../branding";
import { preloadRoute } from "../routes";
import { ROLE_LABELS } from "../types";
import { LoadingState } from "./ui";

const routeIcons: Record<RouteCode, React.ElementType> = {
  workbench: CircleGauge,
  "data-space": Network,
  "generation-data": Zap,
  "retail-data": Database,
  rules: Gavel,
  compute: Network,
  settlements: Calculator,
  results: FileCheck2,
  evidence: FileText,
  audit: ClipboardCheck,
  reports: FileText,
  anomalies: AlertTriangle,
  overview: LayoutDashboard,
  system: UsersRound,
  agents: Workflow,
  metrics: BarChart3,
  logs: FileClock,
};

export function WorkspaceSwitcher({ current, onChange }: { current: WorkspaceId; onChange: (workspace: WorkspaceId) => void }) {
  return (
    <div className="workspace-switcher" role="group" aria-label="切换工作空间">
      {(["business", "admin"] as const).map((workspace) => (
        <button key={workspace} type="button" className={workspace === current ? "active" : ""} aria-pressed={workspace === current} onClick={() => onChange(workspace)}>
          {WORKSPACE_LABELS[workspace]}
        </button>
      ))}
    </div>
  );
}

export function BusinessLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function AdminLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function AppShell() {
  const { session, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => sessionStorage.getItem("hiddenchain_sidebar_collapsed") === "1");
  const productConfig = useProductConfig();

  const currentWorkspace = session ? getWorkspaceForPath(location.pathname, session) : "business";
  const routePolicy = getRoutePolicy(location.pathname);
  const title = location.pathname === "/settlements/new"
    ? "发起结算任务"
    : /^\/settlements\/[^/]+$/.test(location.pathname)
      ? "结算任务详情"
      : routePolicy?.title || (location.pathname === "/403" ? "无权访问" : "页面状态");
  const availableWorkspaces = useMemo(() => session ? getAvailableWorkspaces(session) : [], [session]);
  const visibleRoutes = useMemo(() => session ? getVisibleRoutes(session, currentWorkspace) : [], [currentWorkspace, session]);
  const groups = NAVIGATION_GROUPS[currentWorkspace].map((group) => ({
    ...group,
    routes: visibleRoutes.filter((route) => route.group === group.id),
  })).filter((group) => group.routes.length > 0);

  useEffect(() => {
    window.scrollTo(0, 0);
    document.title = productDocumentTitle(productConfig, title);
    const closeTimer = window.setTimeout(() => setMobileOpen(false), 0);
    return () => window.clearTimeout(closeTimer);
  }, [location.pathname, productConfig, title]);

  if (!session) return null;

  function toggleCollapsed() {
    setCollapsed((value) => {
      const next = !value;
      sessionStorage.setItem("hiddenchain_sidebar_collapsed", next ? "1" : "0");
      return next;
    });
  }

  function switchWorkspace(workspace: WorkspaceId) {
    if (!availableWorkspaces.includes(workspace)) return;
    sessionStorage.setItem("hiddenchain_workspace", workspace);
    navigate(getDefaultPath(session!, workspace));
  }

  const workspaceHome = getDefaultPath(session, currentWorkspace);
  const roleLabel = ROLE_LABELS[session.user.role_code];
  const organization = String(session.org?.org_name || "当前组织");

  return (
    <div className={`app-shell${collapsed ? " sidebar-collapsed" : ""}`}>
      <button className={`drawer-backdrop ${mobileOpen ? "show" : ""}`} type="button" aria-label="关闭导航" onClick={() => setMobileOpen(false)} />
      <aside className={`sidebar${collapsed ? " is-collapsed" : ""}${mobileOpen ? " open" : ""}`} aria-label={`${WORKSPACE_LABELS[currentWorkspace]}导航`}>
        <div className="brand">
          <Link className="brand-home" to={workspaceHome} aria-label={`${productConfig.productName}工作入口`}>
            <BrandLockup compact={collapsed} />
          </Link>
          <button className="icon-button mobile-only" type="button" onClick={() => setMobileOpen(false)} aria-label="关闭导航"><X size={18} /></button>
        </div>

        <div className="sidebar-workspace" title={WORKSPACE_LABELS[currentWorkspace]}>
          {currentWorkspace === "business" ? <CircleGauge size={16} /> : <LayoutDashboard size={16} />}
          <span>{WORKSPACE_LABELS[currentWorkspace]}</span>
        </div>

        <nav className="main-nav">
          {groups.map((group) => (
            <div className="nav-group" key={group.id}>
              <div className="nav-label">{group.label}</div>
              {group.routes.map((route) => {
                const Icon = routeIcons[route.code];
                return (
                  <NavLink
                    key={route.path}
                    to={route.path}
                    title={collapsed ? route.title : undefined}
                    onMouseEnter={() => preloadRoute(route.path)}
                    onFocus={() => preloadRoute(route.path)}
                    className={({ isActive }) => isActive ? "active" : ""}
                  >
                    <Icon size={17} />
                    <span>{route.title}</span>
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button type="button" onClick={logout} title={collapsed ? "退出登录" : undefined}><LogOut size={17} /><span>退出登录</span></button>
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button menu-button mobile-only" type="button" onClick={() => setMobileOpen(true)} aria-label="打开导航"><Menu size={19} /></button>
            <button className="icon-button sidebar-toggle desktop-only" type="button" onClick={toggleCollapsed} aria-label={collapsed ? "展开侧栏" : "折叠侧栏"}>
              {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            </button>
            <div className="topbar-breadcrumb" aria-label="面包屑">
              <span>{WORKSPACE_LABELS[currentWorkspace]}</span>
              <ChevronRight size={13} aria-hidden="true" />
              <strong>{title}</strong>
            </div>
          </div>

          <div className="topbar-actions">
            {availableWorkspaces.length > 1 && <WorkspaceSwitcher current={currentWorkspace} onChange={switchWorkspace} />}
            {productConfig.environmentName && <span className="environment-tag">{productConfig.environmentName}</span>}
            <div className="topbar-identity" title={`${organization} / ${roleLabel}`}>
              <Building2 size={15} />
              <span><strong>{organization}</strong><small>{roleLabel}</small></span>
            </div>
            {canAccessRoute(session, "/anomalies") && (
              <Link className="icon-button alert-entry" to="/anomalies" title="查看风险与告警" aria-label="查看风险与告警"><Bell size={17} /></Link>
            )}
            <details className="user-menu">
              <summary aria-label="打开用户菜单">
                <UserRound size={17} />
                <span><strong>{session.user.display_name}</strong><small>{roleLabel}</small></span>
                <ChevronDown size={14} aria-hidden="true" />
              </summary>
              <div className="user-menu-panel">
                <div><span>账号</span><strong>{session.user.username}</strong></div>
                <div><span>当前组织</span><strong>{organization}</strong></div>
                <button type="button" onClick={logout}><LogOut size={16} />退出登录</button>
              </div>
            </details>
          </div>
        </header>

        <main key={location.pathname} className="page-content">
          <Suspense fallback={<div className="route-loading"><LoadingState label="正在载入页面" variant="page" /></div>}>
            {currentWorkspace === "admin" ? <AdminLayout><Outlet /></AdminLayout> : <BusinessLayout><Outlet /></BusinessLayout>}
          </Suspense>
        </main>
      </div>
    </div>
  );
}
