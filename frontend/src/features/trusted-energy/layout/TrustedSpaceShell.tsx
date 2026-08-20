import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Activity, BadgeCheck, Bell, ChevronDown, Database, FileSignature, Fingerprint, LayoutDashboard, Menu, Network, ScanSearch, Search, UserRound, X, type LucideIcon } from "lucide-react";
import { useAuth } from "../../../auth";
import { AgentSheet } from "../components/AgentSheet";
import { navItems, getTrustedView, routeForView, TRUSTED_BASE, type TrustedViewKey } from "../types";
import { cn } from "../utils";
import { Badge, Button, IconButton } from "../components/ui-primitives";
import { WorkbenchPage } from "../pages/WorkbenchPage";
import { IdentityPage } from "../pages/IdentityPage";
import { CatalogPage } from "../pages/CatalogPage";
import { AssetPassportPage } from "../pages/AssetPassportPage";
import { ApplyPage } from "../pages/ApplyPage";
import { ContractPage } from "../pages/ContractPage";
import { TtcPage } from "../pages/TtcPage";
import { MpcPage } from "../pages/MpcPage";
import { ResultsEvidencePage } from "../pages/ResultsEvidencePage";
import { AuditCenterPage } from "../pages/AuditCenterPage";

const iconMap: Record<string, LucideIcon> = {
  LayoutDashboard,
  Fingerprint,
  Database,
  FileSignature,
  Network,
  BadgeCheck,
  ScanSearch,
};

const titles: Record<TrustedViewKey, string> = {
  workbench: "工作台",
  identity: "身份中心",
  catalog: "数据目录",
  asset: "数据资产护照",
  apply: "使用申请",
  contract: "合同协商",
  ttc: "TTC 任务详情",
  mpc: "MPC 计算任务",
  results: "计算结果与存证",
  audit: "审计中心",
};

function renderView(view: TrustedViewKey) {
  switch (view) {
    case "identity": return <IdentityPage />;
    case "catalog": return <CatalogPage />;
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
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(() => typeof window !== "undefined" && window.location.hash === "#agent");
  const view = getTrustedView(location.pathname);
  const title = titles[view];
  const currentNav = navItems.find((item) => item.key === view);
  const subjectName = session?.user?.display_name || session?.user?.username || "东部绿能企业";
  const did = "did:energy:generator001";
  const activeGroup = currentNav?.key === "identity" ? "主体与身份" : currentNav?.key === "catalog" ? "数据空间" : currentNav?.key === "contract" || currentNav?.key === "mpc" ? "协作与计算" : currentNav?.key === "audit" || currentNav?.key === "results" ? "证据与审计" : "工作台";

  const quickLinks = useMemo(() => navItems.map((item) => ({ ...item, Icon: iconMap[item.icon] })), []);

  useEffect(() => {
    const openAgent = () => setAgentOpen(true);
    window.addEventListener("trusted-energy:agent-open", openAgent);
    return () => window.removeEventListener("trusted-energy:agent-open", openAgent);
  }, []);

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
        <span className="trusted-org-label">Trusted Energy Data &amp; Privacy Computing Space</span>
      </div>
      <div className="trusted-system-right">
        <Badge tone="success" dot>本地受控环境</Badge>
        <span className="trusted-system-pulse"><i />服务状态正常</span>
        <IconButton label="通知"><Bell size={16} /></IconButton>
        <div className="trusted-user-menu"><span className="trusted-avatar"><UserRound size={15} /></span><span className="trusted-user-copy"><strong>{subjectName}</strong><small>数据提供方</small></span><ChevronDown size={13} /></div>
        <Button variant="ghost" size="sm" className="trusted-logout" onClick={() => { logout(); navigate("/login"); }}>退出</Button>
      </div>
    </header>

    <nav className={cn("trusted-primary-nav", mobileNavOpen && "trusted-primary-nav-open")} aria-label="可信数据空间主导航">
      <div className="trusted-nav-inner tw-flex tw-items-center">
        {quickLinks.map(({ key, label, Icon }) => <button key={key} type="button" className={cn("trusted-nav-item", view === key && "trusted-nav-item-active")} onClick={() => goTo(routeForView(key))}><Icon size={15} strokeWidth={1.8} /><span>{label}</span></button>)}
        <span className="trusted-nav-spacer" />
        <button type="button" className="trusted-nav-agent" onClick={() => setAgentOpen(true)}><Activity size={15} />Agent 助手</button>
      </div>
    </nav>

    <div className="trusted-context-bar"><div><span>隐链明算</span><b>/</b><span>{activeGroup}</span><b>/</b><strong>{title}</strong></div><div className="trusted-context-right"><span className="trusted-mono">{did}</span><span>·</span><span>会话有效</span><button type="button" onClick={() => setAgentOpen(true)}><Search size={13} />查找资产</button></div></div>

    <main className="trusted-main" key={location.pathname}>{renderView(view)}</main>

    <AgentSheet open={agentOpen} onOpenChange={setAgentOpen} />
  </div>;
}
