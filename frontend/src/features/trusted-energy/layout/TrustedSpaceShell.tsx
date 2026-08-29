import { Suspense, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Cable, ChevronDown, Database, FileSignature, LayoutDashboard, LogOut, Menu, Network, ScanSearch, Search, ShieldCheck, UserRound, type LucideIcon } from "lucide-react";
import { useAuth } from "../../../auth";
import { retryableLazyNamed, type RetryableLazyComponent } from "../../../components/RetryableLazy";
import { NotificationCenter } from "../components/NotificationCenter";
import { AgentSheet } from "../components/AgentSheet";
import { ROLE_LABELS, labelForCode } from "../../../types";
import { isKnownTrustedPath, primaryNavItems, getTrustedView, routeForView, trustedMenuCodeForView, TRUSTED_BASE, type TrustedViewKey } from "../types";
import { cn } from "../utils";
import { Badge, Button, IconButton, Sheet } from "../components/ui-primitives";
import { RemoteState } from "../components/ui-primitives";
import { useTrustedSpaceContext } from "../trusted-space-context";
import { ForbiddenPage, NotFoundPage } from "../../../pages/StatusPages";
import { productDocumentTitle, useProductConfig } from "../../../branding";
import { canCreateSettlement } from "../../../access";

const trustedPages: Record<TrustedViewKey, RetryableLazyComponent> = {
  workbench: retryableLazyNamed(() => import("../pages/WorkbenchPage"), "WorkbenchPage"),
  query: retryableLazyNamed(() => import("../pages/QueryPage"), "QueryPage"),
  identity: retryableLazyNamed(() => import("../pages/IdentityPage"), "IdentityPage"),
  catalog: retryableLazyNamed(() => import("../pages/CatalogPage"), "CatalogPage"),
  connector: retryableLazyNamed(() => import("../pages/ConnectorPage"), "ConnectorPage"),
  authorizations: retryableLazyNamed(() => import("../pages/AuthorizationsPage"), "AuthorizationsPage"),
  asset: retryableLazyNamed(() => import("../pages/AssetPassportPage"), "AssetPassportPage"),
  apply: retryableLazyNamed(() => import("../pages/ApplyPage"), "ApplyPage"),
  contract: retryableLazyNamed(() => import("../pages/ContractPage"), "ContractPage"),
  ttc: retryableLazyNamed(() => import("../pages/TtcPage"), "TtcPage"),
  mpc: retryableLazyNamed(() => import("../pages/MpcPage"), "MpcPage"),
  results: retryableLazyNamed(() => import("../pages/ResultsEvidencePage"), "ResultsEvidencePage"),
  audit: retryableLazyNamed(() => import("../pages/AuditCenterPage"), "AuditCenterPage"),
};

const settlementCreatePage = retryableLazyNamed(() => import("../../../pages/SettlementCreatePage"), "SettlementCreatePage");
const settlementCreatePath = `${TRUSTED_BASE}/mpc/new`;

const iconMap: Record<string, LucideIcon> = {
  LayoutDashboard,
  Cable,
  Database,
  FileSignature,
  Network,
  ScanSearch,
  Search,
};

const prototypeChromeViews = new Set<TrustedViewKey>([
  "workbench",
  "query",
  "connector",
  "authorizations",
  "asset",
  "apply",
  "contract",
  "ttc",
  "results",
  "audit",
]);

function renderView(view: TrustedViewKey, pathname: string) {
  if (pathname === settlementCreatePath) {
    const SettlementCreatePage = settlementCreatePage;
    return <SettlementCreatePage />;
  }
  const Page = trustedPages[view];
  return <Page />;
}

function preloadView(view: TrustedViewKey) {
  void trustedPages[view].preload().catch(() => undefined);
}

export function TrustedSpaceShell() {
  const { session, logout } = useAuth();
  const productConfig = useProductConfig();
  const trustedContext = useTrustedSpaceContext();
  const location = useLocation();
  const navigate = useNavigate();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const view = getTrustedView(location.pathname);
  const isSettlementCreate = location.pathname === settlementCreatePath;
  const context = trustedContext.context;
  const targetChrome = prototypeChromeViews.has(view);
  const visibleMenuCodes = useMemo(() => {
    const sessionMenus = new Set((session?.menus || []).map((menu) => `${menu.code}:${menu.path}`));
    return new Set((context?.visible_menus || []).filter((menu) => sessionMenus.has(`${menu.code}:${menu.path}`)).map((menu) => menu.code));
  }, [context?.visible_menus, session?.menus]);
  const quickLinks = useMemo(() => {
    return primaryNavItems.filter((item) => visibleMenuCodes.has(item.menuCode)).map((item) => ({ ...item, Icon: iconMap[item.icon] }));
  }, [visibleMenuCodes]);

  useEffect(() => {
    const openAgent = () => setAgentOpen(true);
    window.addEventListener("trusted-energy:agent-open", openAgent);
    return () => window.removeEventListener("trusted-energy:agent-open", openAgent);
  }, []);

  useEffect(() => {
    const viewTitle = isSettlementCreate
      ? "发起结算任务"
      : view === "identity"
        ? "主体中心"
        : primaryNavItems.find((item) => item.key === view)?.label || "可信数据空间";
    document.title = productDocumentTitle(productConfig, viewTitle);
    window.scrollTo(0, 0);
  }, [isSettlementCreate, productConfig, view]);

  if (trustedContext.loading) return <div className="trusted-space-shell tw-min-h-screen"><RemoteState loading /></div>;
  if (trustedContext.error || !context) return <div className="trusted-space-shell tw-min-h-screen"><RemoteState error={trustedContext.error || "可信数据空间上下文不可用"} onRetry={() => void trustedContext.reload()} /></div>;
  if (!isKnownTrustedPath(location.pathname)) return <div className="trusted-space-shell tw-min-h-screen"><NotFoundPage /></div>;
  if (isSettlementCreate && (!session || !canCreateSettlement(session) || !visibleMenuCodes.has("compute"))) return <div className="trusted-space-shell tw-min-h-screen"><ForbiddenPage /></div>;
  if (!visibleMenuCodes.has(trustedMenuCodeForView(view))) return <div className="trusted-space-shell tw-min-h-screen"><ForbiddenPage /></div>;
  const subjectName = context.current_subject.org_name || context.actor.display_name || session?.user?.username || "当前主体";
  const roleLabel = context.actor.role_label || ROLE_LABELS[context.actor.role_code as keyof typeof ROLE_LABELS] || labelForCode(context.actor.role_code, "未登记角色");

  function goTo(path: string) {
    setNavigationOpen(false);
    navigate(path);
  }

  async function handleLogout() {
    if (logoutBusy) return;
    setLogoutBusy(true);
    await logout();
    navigate("/login", { replace: true });
  }

  return <div className={cn("trusted-space-shell", targetChrome && "prototype-shell", "tw-min-h-screen")}>
    <header className="trusted-system-bar">
      <div className="trusted-system-left">
        <IconButton className="trusted-mobile-menu" label="打开左侧导航" aria-expanded={navigationOpen} onClick={() => setNavigationOpen(true)}><Menu size={17} /></IconButton>
        <Link className="trusted-brand" to={`${TRUSTED_BASE}/workbench`} onMouseEnter={() => preloadView("workbench")} onFocus={() => preloadView("workbench")} onClick={() => setNavigationOpen(false)}>
          <span className="trusted-brand-mark"><ShieldCheck size={20} strokeWidth={2.1} /></span>
          <span><strong>隐链明算</strong></span>
        </Link>
        <span className="trusted-divider" aria-hidden="true" />
        <span className="trusted-org-label">多能源可信数据与隐私计算平台</span>
      </div>
      <div className="trusted-system-right">
        <Badge tone="success" dot>{context.environment.name === "DEMO" ? "公开演示环境" : context.environment.name === "TEST" ? "本地测试环境" : "受控运行环境"}</Badge>
        <span className="trusted-system-pulse"><i />{context.current_subject.status === "ACTIVE" ? "主体状态正常" : "主体状态异常"}</span>
        <NotificationCenter />
        <details className="trusted-user-menu">
          <summary aria-label="打开主体中心和账号菜单">
            <span className="trusted-avatar"><UserRound size={15} /></span>
            <span className="trusted-user-copy"><strong>{subjectName}</strong><small>{roleLabel}</small></span>
            <ChevronDown size={13} aria-hidden="true" />
          </summary>
          <div className="trusted-user-menu-panel">
            {visibleMenuCodes.has("participants") && <Link className="trusted-subject-center-link" to={routeForView("identity")} onMouseEnter={() => preloadView("identity")} onFocus={() => preloadView("identity")} onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); setNavigationOpen(false); }}><UserRound size={14} /><span><strong>主体中心</strong><small>身份与能力管理</small></span></Link>}
            <div><span>账号</span><strong>{context.actor.username}</strong></div>
            <div><span>当前组织</span><strong>{subjectName}</strong></div>
            <div><span>当前角色</span><strong>{roleLabel}</strong></div>
            <div><span>身份状态</span><strong>{context.identity_ref.credential_status === "VALID" ? "已核验" : "未配置"}</strong></div>
            <Button type="button" variant="danger" size="sm" busy={logoutBusy} onClick={() => void handleLogout()}><LogOut size={14} />退出登录</Button>
          </div>
        </details>
      </div>
    </header>

    <Sheet open={navigationOpen} onOpenChange={setNavigationOpen} title="可信数据空间导航" side="left" className="trusted-navigation-sheet">
      <nav className="trusted-drawer-nav" aria-label="左侧可信数据空间导航">
        {quickLinks.map(({ key, label, Icon }) => <button key={key} type="button" aria-current={view === key ? "page" : undefined} className={cn("trusted-drawer-nav-item", view === key && "trusted-drawer-nav-item-active")} onMouseEnter={() => preloadView(key)} onFocus={() => preloadView(key)} onClick={() => goTo(routeForView(key))}><Icon size={16} strokeWidth={1.8} /><span>{label}</span></button>)}
      </nav>
    </Sheet>

    <nav className="trusted-primary-nav" aria-label="可信数据空间主导航">
      <div className="trusted-nav-inner tw-flex tw-items-center">
        {quickLinks.map(({ key, label, Icon }) => <button key={key} type="button" aria-current={view === key ? "page" : undefined} className={cn("trusted-nav-item", view === key && "trusted-nav-item-active")} onMouseEnter={() => preloadView(key)} onFocus={() => preloadView(key)} onClick={() => goTo(routeForView(key))}><Icon size={15} strokeWidth={1.8} /><span>{label}</span></button>)}
        <span className="trusted-nav-spacer" />
      </div>
    </nav>

    <main className={cn("trusted-main", targetChrome && "prototype-container")} key={location.pathname}>
      <Suspense fallback={<RemoteState loading />}>{renderView(view, location.pathname)}</Suspense>
    </main>
    <AgentSheet open={agentOpen} onOpenChange={setAgentOpen} />
  </div>;
}
