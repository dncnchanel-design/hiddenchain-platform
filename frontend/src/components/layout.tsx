import {
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  Bell,
  Building2,
  ChevronDown,
  ChevronRight,
  LogOut,
  Menu,
  UserRound,
  X,
} from "lucide-react";
import {
  canAccessRoute,
  getDefaultPath,
  getPrimaryNavigation,
  getRoutePolicy,
  getWorkspaceForPath,
  type PrimaryNavigationGroup,
  type PrimaryNavigationId,
  type PrimaryNavigationItem,
} from "../access";
import { useAuth } from "../auth";
import { BrandLockup, productDocumentTitle, useProductConfig } from "../branding";
import { preloadRoute } from "../routes";
import { ROLE_LABELS } from "../types";
import { LoadingState } from "./ui";

const NAV_OPEN_DELAY = 120;
const NAV_CLOSE_DELAY = 220;

export function BusinessLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function AdminLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

function isItemActive(item: PrimaryNavigationItem, pathname: string, search: string, hash: string) {
  const target = new URL(item.to, "https://navigation.local");
  if (target.pathname === "/settlements" && /^\/settlements\/[^/]+$/.test(pathname)) {
    return item.to === "/settlements";
  }
  if (target.pathname !== pathname) return false;
  if (target.search) {
    const expected = new URLSearchParams(target.search);
    const current = new URLSearchParams(search);
    return Array.from(expected.entries()).every(([key, value]) => current.get(key) === value);
  }
  if (target.hash) return target.hash === hash;
  if (pathname === "/settlements" && new URLSearchParams(search).has("view")) return false;
  if (pathname === "/data-space" && hash) return false;
  return true;
}

function groupForPath(pathname: string): PrimaryNavigationId | null {
  if (pathname === "/workbench") return "home";
  const policy = getRoutePolicy(pathname);
  if (!policy) return null;
  if (policy.group === "entry") return "home";
  return policy.group;
}

function TopNavigation({
  groups,
  mobileOpen,
  onNavigate,
  onCloseMobile,
}: {
  groups: PrimaryNavigationGroup[];
  mobileOpen: boolean;
  onNavigate: () => void;
  onCloseMobile: () => void;
}) {
  const location = useLocation();
  const routeKey = `${location.pathname}${location.search}${location.hash}`;
  const [openState, setOpenState] = useState<{ id: PrimaryNavigationId; routeKey: string } | null>(null);
  const openId = openState?.routeKey === routeKey ? openState.id : null;
  const navRef = useRef<HTMLElement>(null);
  const openTimer = useRef<number | null>(null);
  const closeTimer = useRef<number | null>(null);
  const triggerRefs = useRef(new Map<PrimaryNavigationId, HTMLButtonElement>());
  const activeGroupId = groupForPath(location.pathname);

  function clearTimers() {
    if (openTimer.current !== null) window.clearTimeout(openTimer.current);
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    openTimer.current = null;
    closeTimer.current = null;
  }

  function scheduleOpen(id: PrimaryNavigationId) {
    clearTimers();
    openTimer.current = window.setTimeout(() => setOpenState({ id, routeKey }), NAV_OPEN_DELAY);
  }

  function scheduleClose() {
    clearTimers();
    closeTimer.current = window.setTimeout(() => setOpenState(null), NAV_CLOSE_DELAY);
  }

  function focusMenuItem(id: PrimaryNavigationId, index: number) {
    window.requestAnimationFrame(() => {
      const items = navRef.current?.querySelectorAll<HTMLAnchorElement>(`#primary-menu-${id} [role="menuitem"]`);
      if (!items?.length) return;
      const normalized = (index + items.length) % items.length;
      items[normalized]?.focus();
    });
  }

  function handleTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>, group: PrimaryNavigationGroup) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpenState((value) => value?.routeKey === routeKey && value.id === group.id ? null : { id: group.id, routeKey });
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpenState({ id: group.id, routeKey });
      focusMenuItem(group.id, event.key === "ArrowDown" ? 0 : -1);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setOpenState(null);
    }
  }

  function handleMenuKeyDown(event: KeyboardEvent<HTMLAnchorElement>, group: PrimaryNavigationGroup, index: number) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      focusMenuItem(group.id, index + (event.key === "ArrowDown" ? 1 : -1));
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      focusMenuItem(group.id, event.key === "Home" ? 0 : -1);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setOpenState(null);
      triggerRefs.current.get(group.id)?.focus();
    }
  }

  useEffect(() => {
    function closeOnOutsidePointer(event: PointerEvent) {
      if (navRef.current && !navRef.current.contains(event.target as Node)) setOpenState(null);
    }
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, []);

  useEffect(() => () => {
    if (openTimer.current !== null) window.clearTimeout(openTimer.current);
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
  }, []);

  return (
    <nav ref={navRef} className={`primary-navigation${mobileOpen ? " mobile-open" : ""}`} aria-label="主导航">
      <div className="mobile-navigation-header">
        <strong>业务导航</strong>
        <button type="button" className="icon-button" onClick={onCloseMobile} aria-label="关闭业务导航"><X size={18} /></button>
      </div>
      <div className="primary-navigation-list">
        {groups.map((group) => {
          const active = activeGroupId === group.id;
          if (group.directTo) {
            return (
              <Link
                key={group.id}
                className={`primary-navigation-link${active ? " active" : ""}`}
                to={group.directTo}
                aria-current={active ? "page" : undefined}
                onMouseEnter={() => preloadRoute(group.directTo!)}
                onFocus={() => preloadRoute(group.directTo!)}
                onClick={onNavigate}
              >
                {group.label}
              </Link>
            );
          }

          const open = openId === group.id;
          return (
            <div
              className={`primary-navigation-group${active ? " active" : ""}${open ? " open" : ""}`}
              key={group.id}
              onMouseEnter={() => scheduleOpen(group.id)}
              onMouseLeave={scheduleClose}
            >
              <button
                ref={(node) => { if (node) triggerRefs.current.set(group.id, node); }}
                type="button"
                className="primary-navigation-trigger"
                aria-expanded={open}
                aria-haspopup="menu"
                aria-controls={`primary-menu-${group.id}`}
                aria-current={active ? "page" : undefined}
                onClick={() => {
                  clearTimers();
                  setOpenState((value) => value?.routeKey === routeKey && value.id === group.id ? null : { id: group.id, routeKey });
                }}
                onFocus={() => group.items.slice(0, 2).forEach((entry) => preloadRoute(entry.routePath))}
                onKeyDown={(event) => handleTriggerKeyDown(event, group)}
              >
                <span>{group.label}</span>
                <ChevronDown size={13} aria-hidden="true" />
              </button>
              {open && (
                <div id={`primary-menu-${group.id}`} className="primary-navigation-menu" role="menu" aria-label={`${group.label}功能`}>
                  {group.items.map((entry, index) => {
                    const itemActive = isItemActive(entry, location.pathname, location.search, location.hash);
                    return (
                      <Link
                        key={entry.id}
                        to={entry.to}
                        role="menuitem"
                        className={itemActive ? "active" : ""}
                        aria-current={itemActive ? "page" : undefined}
                        onMouseEnter={() => preloadRoute(entry.routePath)}
                        onFocus={() => preloadRoute(entry.routePath)}
                        onClick={() => { setOpenState(null); onNavigate(); }}
                        onKeyDown={(event) => handleMenuKeyDown(event, group, index)}
                      >
                        <span>{entry.label}</span>
                        {itemActive && <span className="menu-current-label">当前</span>}
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </nav>
  );
}

function Breadcrumbs({ groups, title }: { groups: PrimaryNavigationGroup[]; title: string }) {
  const location = useLocation();
  const groupId = groupForPath(location.pathname);
  const group = groups.find((entry) => entry.id === groupId);
  const segments: Array<{ label: string; to?: string }> = [];

  if (group?.id === "home") {
    segments.push({ label: "首页" });
  } else if (group) {
    segments.push({ label: group.label, to: group.items[0]?.to });
    if (/^\/settlements\/[^/]+$/.test(location.pathname)) {
      const taskId = decodeURIComponent(location.pathname.split("/").at(-1) || "");
      segments.push({ label: "结算任务", to: "/settlements" }, { label: taskId });
    } else if (location.pathname === "/settlements/new") {
      segments.push({ label: "结算任务", to: "/settlements" }, { label: "发起结算任务" });
    } else {
      segments.push({ label: title });
    }
  } else {
    segments.push({ label: "页面状态" }, { label: title });
  }

  return (
    <nav className="route-context" aria-label="面包屑">
      <ol>
        {segments.map((segment, index) => (
          <li key={`${segment.label}-${index}`}>
            {index > 0 && <ChevronRight size={12} aria-hidden="true" />}
            {segment.to && index < segments.length - 1 ? <Link to={segment.to}>{segment.label}</Link> : <span aria-current={index === segments.length - 1 ? "page" : undefined}>{segment.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function AppShell() {
  const { session, logout } = useAuth();
  const location = useLocation();
  const routeKey = `${location.pathname}${location.search}${location.hash}`;
  const [mobileState, setMobileState] = useState<{ open: boolean; routeKey: string }>({ open: false, routeKey });
  const mobileOpen = mobileState.open && mobileState.routeKey === routeKey;
  const productConfig = useProductConfig();

  const currentWorkspace = session ? getWorkspaceForPath(location.pathname, session) : "business";
  const routePolicy = getRoutePolicy(location.pathname);
  const title = location.pathname === "/settlements/new"
    ? "发起结算任务"
    : /^\/settlements\/[^/]+$/.test(location.pathname)
      ? "结算任务详情"
      : routePolicy?.title || (location.pathname === "/403" ? "无权访问" : "页面状态");
  const navigation = useMemo(() => session ? getPrimaryNavigation(session) : [], [session]);

  useEffect(() => {
    window.scrollTo(0, 0);
    document.title = productDocumentTitle(productConfig, title);
  }, [location.pathname, productConfig, title]);

  if (!session) return null;

  const workspaceHome = getDefaultPath(session, currentWorkspace);
  const roleLabel = ROLE_LABELS[session.user.role_code];
  const organization = String(session.org?.org_name || "当前组织");

  return (
    <div className="app-shell">
      <button className={`mobile-navigation-backdrop${mobileOpen ? " show" : ""}`} type="button" aria-label="关闭业务导航" onClick={() => setMobileState({ open: false, routeKey })} />
      <header className="application-header">
        <div className="system-bar">
          <div className="system-bar-inner">
            <Link className="system-brand" to={workspaceHome} aria-label={`${productConfig.productName}工作入口`}>
              <BrandLockup />
            </Link>
            <button className="icon-button mobile-navigation-toggle" type="button" onClick={() => setMobileState({ open: true, routeKey })} aria-label="打开业务导航"><Menu size={19} /></button>
            <div className="system-context">
              <div className="institution-summary" title={organization}>
                <Building2 size={15} aria-hidden="true" />
                <span><small>当前机构</small><strong>{organization}</strong></span>
              </div>
              <div className="role-summary"><small>当前角色</small><strong>{roleLabel}</strong></div>
              {productConfig.environmentName && <span className="system-environment">{productConfig.environmentName}</span>}
              {canAccessRoute(session, "/anomalies") && (
                <Link className="system-alert-entry" to="/anomalies" title="查看风险与告警" aria-label="查看风险与告警"><Bell size={17} /></Link>
              )}
              <details className="user-menu system-user-menu">
                <summary aria-label="打开用户菜单">
                  <UserRound size={17} />
                  <span><strong>{session.user.display_name}</strong><small>{roleLabel}</small></span>
                  <ChevronDown size={13} aria-hidden="true" />
                </summary>
                <div className="user-menu-panel">
                  <div><span>账号</span><strong>{session.user.username}</strong></div>
                  <div><span>当前组织</span><strong>{organization}</strong></div>
                  <button type="button" onClick={logout}><LogOut size={16} />退出登录</button>
                </div>
              </details>
            </div>
          </div>
        </div>
        <div className="primary-navigation-bar">
          <div className="primary-navigation-inner">
            <TopNavigation groups={navigation} mobileOpen={mobileOpen} onNavigate={() => setMobileState({ open: false, routeKey })} onCloseMobile={() => setMobileState({ open: false, routeKey })} />
          </div>
        </div>
        <div className="route-context-bar">
          <div className="route-context-inner"><Breadcrumbs groups={navigation} title={title} /></div>
        </div>
      </header>

      <main key={location.pathname} className="page-content">
        <Suspense fallback={<div className="route-loading"><LoadingState label="正在载入页面" variant="page" /></div>}>
          {currentWorkspace === "admin" ? <AdminLayout><Outlet /></AdminLayout> : <BusinessLayout><Outlet /></BusinessLayout>}
        </Suspense>
      </main>
    </div>
  );
}
