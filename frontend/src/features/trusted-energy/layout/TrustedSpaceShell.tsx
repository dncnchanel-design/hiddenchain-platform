import { useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Cable, ChevronDown, Database, FileSignature, Fingerprint, LayoutDashboard, LogOut, Menu, Network, ScanSearch, Search, ShieldCheck, UserRound, type LucideIcon } from "lucide-react";
import { useAuth } from "../../../auth";
import { NotificationCenter } from "../components/NotificationCenter";
import { ROLE_LABELS, labelForCode } from "../../../types";
import { isKnownTrustedPath, primaryNavItems, getTrustedView, routeForView, trustedMenuCodeForView, TRUSTED_BASE, type TrustedViewKey } from "../types";
import { cn } from "../utils";
import { Badge, Button, IconButton, Sheet } from "../components/ui-primitives";
import { RemoteState } from "../components/ui-primitives";
import { useTrustedSpaceContext } from "../trusted-space-context";
import { loadPrototypeHeader } from "../trusted-space-api";
import { useRemote } from "../../../hooks";
import { WorkbenchPage } from "../pages/WorkbenchPage";
import { IdentityPage } from "../pages/IdentityPage";
import { CatalogPage } from "../pages/CatalogPage";
import { AssetPassportPage } from "../pages/AssetPassportPage";
import { ApplyPage } from "../pages/ApplyPage";
import { StrategyCenterPage } from "../pages/StrategyCenterPage";
import { ContractPage } from "../pages/ContractPage";
import { TtcPage } from "../pages/TtcPage";
import { MpcPage } from "../pages/MpcPage";
import { ResultsEvidencePage } from "../pages/ResultsEvidencePage";
import { AuditCenterPage } from "../pages/AuditCenterPage";
import { QueryPage } from "../pages/QueryPage";
import { ConnectorPage } from "../pages/ConnectorPage";
import { ForbiddenPage, NotFoundPage } from "../../../pages/StatusPages";

const iconMap: Record<string, LucideIcon> = {
  LayoutDashboard,
  Cable,
  Fingerprint,
  Database,
  FileSignature,
  Network,
  ScanSearch,
  Search,
};

const titles: Record<TrustedViewKey, string> = {
  workbench: "全局看板",
  query: "数据问数",
  identity: "身份拓扑",
  catalog: "数据目录",
  connector: "数据接入",
  authorizations: "策略中心",
  asset: "数据资产护照",
  apply: "使用申请",
  contract: "合同协商",
  ttc: "可信任务详情",
  mpc: "计算任务",
  results: "计算任务结果",
  audit: "审计存证",
};

const prototypeLabels: Record<TrustedViewKey, string> = {
  workbench: "全局看板",
  query: "数据问数",
  identity: "身份拓扑",
  catalog: "数据目录",
  connector: "数据接入",
  authorizations: "策略中心",
  asset: "数据资产护照",
  apply: "使用申请",
  contract: "合同协商",
  ttc: "可信任务详情",
  mpc: "隐私计算",
  results: "计算任务结果",
  audit: "审计存证",
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

function renderView(view: TrustedViewKey) {
  switch (view) {
    case "query": return <QueryPage />;
    case "identity": return <IdentityPage />;
    case "catalog": return <CatalogPage />;
    case "connector": return <ConnectorPage />;
    case "authorizations": return <StrategyCenterPage />;
    case "asset": return <AssetPassportPage />;
    case "apply": return <ApplyPage />;
    case "contract": return <ContractPage />;
    case "ttc": return <TtcPage />;
    case "mpc": return <MpcPage />;
    case "results": return <ResultsEvidencePage />;
    case "audit": return <AuditCenterPage />;
    case "workbench":
    default: return <WorkbenchPage />;
  }
}

export function TrustedSpaceShell() {
  const { session, logout } = useAuth();
  const trustedContext = useTrustedSpaceContext();
  const location = useLocation();
  const navigate = useNavigate();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const view = getTrustedView(location.pathname);
  const title = titles[view];
  const context = trustedContext.context;
  const targetChrome = prototypeChromeViews.has(view);
  const targetHeader = useRemote(loadPrototypeHeader, [targetChrome]);
  const quickLinks = useMemo(() => {
    const visibleMenuCodes = new Set((context?.visible_menus ?? []).map((menu) => menu.code));
    return primaryNavItems.filter((item) => visibleMenuCodes.has(item.menuCode)).map((item) => ({ ...item, Icon: iconMap[item.icon] }));
  }, [context?.visible_menus]);

  if (trustedContext.loading) return <div className="trusted-space-shell tw-min-h-screen"><RemoteState loading /></div>;
  if (trustedContext.error || !context) return <div className="trusted-space-shell tw-min-h-screen"><RemoteState error={trustedContext.error || "可信数据空间上下文不可用"} onRetry={() => void trustedContext.reload()} /></div>;
  if (!isKnownTrustedPath(location.pathname)) return <div className="trusted-space-shell tw-min-h-screen"><NotFoundPage /></div>;
  const visibleMenuCodes = new Set(context.visible_menus.map((menu) => menu.code));
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

  if (targetChrome) {
    const header = targetHeader.data;
    const targetIdentity = header?.identity || { name: subjectName, role: roleLabel, did: context.identity_ref.did || "did:eds:当前主体" };
    const targetStats = [
      ...(header?.stats || [
        { key: "resources", label: "数据资源", value: 0 },
        { key: "rules", label: "策略规则", value: 0 },
        { key: "identities", label: "注册主体", value: 0 },
        { key: "blocks", label: "存证区块", value: 0 },
      ]),
      { key: "identity", label: "当前身份", value: targetIdentity.role },
    ];
    const subtitle = view === "workbench" ? "数据不出域 · 跨主体可信协同 · 隐私计算 · 全程审计" : "智能理解 · 确定性裁决 · 受控执行 · 可信留痕";
    return <div className="trusted-space-shell prototype-shell tw-min-h-screen">
      <header className="prototype-header">
        <div className="prototype-header-top">
          <div>
            <h1>{header?.title || "能源可信数据空间 · 原型演示"}</h1>
            <div className="prototype-header-sub">{subtitle}</div>
          </div>
          <div className="prototype-identity"><span>{targetIdentity.name}（{targetIdentity.role}）</span><span className="prototype-did">✓ {targetIdentity.did}</span><button type="button" onClick={() => void handleLogout()}>退出登录</button></div>
        </div>
        <div className="prototype-stats-bar">{targetStats.map((item) => <span key={item.key}>{item.label} <b>{item.value}</b>{item.key === "identity" && "（已认证）"}</span>)}</div>
      </header>
      <nav className="prototype-nav" aria-label="主导航">
        {quickLinks.map(({ key }) => <Link key={key} className={cn("prototype-nav-tab", view === key && "is-active")} to={routeForView(key)}>{prototypeLabels[key]}</Link>)}
      </nav>
      <main className="prototype-container" key={location.pathname}>{renderView(view)}</main>
    </div>;
  }

  return <div className="trusted-space-shell tw-min-h-screen">
    <header className="trusted-system-bar">
      <div className="trusted-system-left">
        <IconButton className="trusted-mobile-menu" label="打开左侧导航" aria-expanded={navigationOpen} onClick={() => setNavigationOpen(true)}><Menu size={17} /></IconButton>
        <Link className="trusted-brand" to={`${TRUSTED_BASE}/workbench`} onClick={() => setNavigationOpen(false)}>
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
          <summary aria-label="打开账号菜单">
            <span className="trusted-avatar"><UserRound size={15} /></span>
            <span className="trusted-user-copy"><strong>{subjectName}</strong><small>{roleLabel}</small></span>
            <ChevronDown size={13} aria-hidden="true" />
          </summary>
          <div className="trusted-user-menu-panel">
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
        {quickLinks.map(({ key, label, Icon }) => <button key={key} type="button" aria-current={view === key ? "page" : undefined} className={cn("trusted-drawer-nav-item", view === key && "trusted-drawer-nav-item-active")} onClick={() => goTo(routeForView(key))}><Icon size={16} strokeWidth={1.8} /><span>{label}</span></button>)}
      </nav>
    </Sheet>

    <nav className="trusted-primary-nav" aria-label="可信数据空间主导航">
      <div className="trusted-nav-inner tw-flex tw-items-center">
        {quickLinks.map(({ key, label, Icon }) => <button key={key} type="button" aria-current={view === key ? "page" : undefined} className={cn("trusted-nav-item", view === key && "trusted-nav-item-active")} onClick={() => goTo(routeForView(key))}><Icon size={15} strokeWidth={1.8} /><span>{label}</span></button>)}
        <span className="trusted-nav-spacer" />
      </div>
    </nav>

    <main className="trusted-main" key={location.pathname}>{renderView(view)}</main>
  </div>;
}
