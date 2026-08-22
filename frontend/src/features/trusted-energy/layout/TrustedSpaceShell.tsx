import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Activity, BadgeCheck, ChevronDown, Database, FileSignature, Fingerprint, LayoutDashboard, Menu, Network, ScanSearch, Search, Upload, UserRound, X, type LucideIcon } from "lucide-react";
import { useAuth } from "../../../auth";
import { AgentSheet } from "../components/AgentSheet";
import { NotificationCenter } from "../components/NotificationCenter";
import { ROLE_LABELS, labelForCode } from "../../../types";
import { isKnownTrustedPath, navItems, primaryNavItems, getTrustedView, routeForView, trustedMenuCodeForView, TRUSTED_BASE, type TrustedViewKey } from "../types";
import { cn } from "../utils";
import { Badge, Button, IconButton } from "../components/ui-primitives";
import { RemoteState } from "../components/ui-primitives";
import { useTrustedSpaceContext } from "../trusted-space-context";
import { WorkbenchPage } from "../pages/WorkbenchPage";
import { IdentityPage } from "../pages/IdentityPage";
import { CatalogPage } from "../pages/CatalogPage";
import { ExcelUploadPage } from "../../../pages/ExcelUploadPage";
import { AssetPassportPage } from "../pages/AssetPassportPage";
import { ApplyPage } from "../pages/ApplyPage";
import { AuthorizationsPage } from "../pages/AuthorizationsPage";
import { ContractPage } from "../pages/ContractPage";
import { TtcPage } from "../pages/TtcPage";
import { MpcPage } from "../pages/MpcPage";
import { ResultsEvidencePage } from "../pages/ResultsEvidencePage";
import { AuditCenterPage } from "../pages/AuditCenterPage";
import { ForbiddenPage, NotFoundPage } from "../../../pages/StatusPages";

const iconMap: Record<string, LucideIcon> = {
  LayoutDashboard,
  Fingerprint,
  Database,
  FileSignature,
  Network,
  BadgeCheck,
  ScanSearch,
  Upload,
};

const titles: Record<TrustedViewKey, string> = {
  workbench: "工作台",
  identity: "身份中心",
  catalog: "数据目录",
  upload: "数据上传",
  authorizations: "授权记录",
  asset: "数据资产护照",
  apply: "使用申请",
  contract: "合同协商",
    ttc: "可信任务详情",
    mpc: "隐私计算任务",
  results: "计算结果与存证",
  audit: "审计中心",
};

function renderView(view: TrustedViewKey) {
  switch (view) {
    case "identity": return <IdentityPage />;
    case "catalog": return <CatalogPage />;
    case "upload": return <ExcelUploadPage />;
    case "authorizations": return <AuthorizationsPage />;
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
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(() => typeof window !== "undefined" && window.location.hash === "#agent");
  const view = getTrustedView(location.pathname);
  const title = titles[view];
  const currentNav = navItems.find((item) => item.key === view);
  const context = trustedContext.context;
  const quickLinks = useMemo(() => {
    const visibleMenuCodes = new Set((context?.visible_menus ?? []).map((menu) => menu.code));
    return primaryNavItems.filter((item) => visibleMenuCodes.has(item.menuCode)).map((item) => ({ ...item, Icon: iconMap[item.icon] }));
  }, [context?.visible_menus]);

  useEffect(() => {
    const openAgent = () => setAgentOpen(true);
    window.addEventListener("trusted-energy:agent-open", openAgent);
    return () => window.removeEventListener("trusted-energy:agent-open", openAgent);
  }, []);

  if (trustedContext.loading) return <div className="trusted-space-shell tw-min-h-screen"><RemoteState loading /></div>;
  if (trustedContext.error || !context) return <div className="trusted-space-shell tw-min-h-screen"><RemoteState error={trustedContext.error || "可信数据空间上下文不可用"} onRetry={() => void trustedContext.reload()} /></div>;
  if (!isKnownTrustedPath(location.pathname)) return <div className="trusted-space-shell tw-min-h-screen"><NotFoundPage /></div>;
  const visibleMenuCodes = new Set(context.visible_menus.map((menu) => menu.code));
  if (!visibleMenuCodes.has(trustedMenuCodeForView(view))) return <div className="trusted-space-shell tw-min-h-screen"><ForbiddenPage /></div>;
  const subjectName = context.current_subject.org_name || context.actor.display_name || session?.user?.username || "当前主体";
  const roleLabel = context.actor.role_label || ROLE_LABELS[context.actor.role_code as keyof typeof ROLE_LABELS] || labelForCode(context.actor.role_code, "未登记角色");
  const did = context.identity_ref.did || "未配置去中心化身份标识";
  const activeGroup = currentNav?.key === "identity" ? "主体与身份" : currentNav?.key === "catalog" || currentNav?.key === "upload" || currentNav?.key === "authorizations" ? "数据空间" : currentNav?.key === "contract" || currentNav?.key === "mpc" ? "协作与计算" : currentNav?.key === "audit" || currentNav?.key === "results" ? "证据与审计" : "工作台";

  function goTo(path: string) {
    setMobileNavOpen(false);
    navigate(path);
  }

  return <div className="trusted-space-shell tw-min-h-screen">
    <header className="trusted-system-bar">
      <div className="trusted-system-left">
        <IconButton className="trusted-mobile-menu" label={mobileNavOpen ? "关闭导航" : "打开导航"} onClick={() => setMobileNavOpen((value) => !value)}>{mobileNavOpen ? <X size={17} /> : <Menu size={17} />}</IconButton>
        <Link className="trusted-brand" to={`${TRUSTED_BASE}/workbench`} onClick={() => setMobileNavOpen(false)}>
          <span className="trusted-brand-mark">隐</span>
          <span><strong>隐链明算</strong><small>能源可信数据空间</small></span>
        </Link>
        <span className="trusted-divider" aria-hidden="true" />
        <span className="trusted-org-label">能源可信数据与隐私计算空间</span>
      </div>
      <div className="trusted-system-right">
        <Badge tone="success" dot>{context.environment.name === "TEST" ? "本地受控环境" : labelForCode(context.environment.name, "受控环境")}</Badge>
        <span className="trusted-system-pulse"><i />{context.current_subject.status === "ACTIVE" ? "服务状态正常" : "主体状态异常"}</span>
        <NotificationCenter />
        <div className="trusted-user-menu"><span className="trusted-avatar"><UserRound size={15} /></span><span className="trusted-user-copy"><strong>{subjectName}</strong><small>{roleLabel}</small></span><ChevronDown size={13} /></div>
        <Button variant="ghost" size="sm" className="trusted-logout" onClick={() => { logout(); navigate("/login"); }}>退出</Button>
      </div>
    </header>

    <nav className={cn("trusted-primary-nav", mobileNavOpen && "trusted-primary-nav-open")} aria-label="可信数据空间主导航">
      <div className="trusted-nav-inner tw-flex tw-items-center">
        {quickLinks.map(({ key, label, Icon }) => <button key={key} type="button" className={cn("trusted-nav-item", view === key && "trusted-nav-item-active")} onClick={() => goTo(routeForView(key))}><Icon size={15} strokeWidth={1.8} /><span>{label}</span></button>)}
        <span className="trusted-nav-spacer" />
        <button type="button" className="trusted-nav-agent" onClick={() => setAgentOpen(true)}><Activity size={15} />Agent助手</button>
      </div>
    </nav>

    <div className="trusted-context-bar"><div><span>隐链明算</span><b>/</b><span>{activeGroup}</span><b>/</b><strong>{title}</strong></div><div className="trusted-context-right"><span className="trusted-mono">{did}</span><span>·</span><span>会话有效</span><button type="button" onClick={() => goTo(`${routeForView("catalog")}?focus=search`)}><Search size={13} />查找资产</button></div></div>

    <main className="trusted-main" key={location.pathname}>{renderView(view)}</main>

    <AgentSheet open={agentOpen} onOpenChange={setAgentOpen} />
  </div>;
}
