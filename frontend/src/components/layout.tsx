import { Suspense, useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Blocks,
  Building2,
  Calculator,
  ChevronDown,
  CircleGauge,
  ClipboardCheck,
  Database,
  FileCheck2,
  FileClock,
  FileText,
  Gavel,
  Home,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  ScrollText,
  Search,
  Settings,
  ShieldCheck,
  UsersRound,
  Workflow,
  X,
  Zap,
} from "lucide-react";
import { useAuth } from "../auth";
import { LoadingState } from "./ui";
import { ROLE_LABELS } from "../types";
import { preloadRoute } from "../routes";

const navGroups = [
  {
    label: "工作入口",
    items: [
      { code: "overview", to: "/overview", label: "平台概览", icon: LayoutDashboard },
      { code: "workbench", to: "/workbench", label: "我的工作台", icon: CircleGauge },
    ],
  },
  {
    label: "数据与授权",
    items: [
      { code: "data-space", to: "/data-space", label: "数据目录", icon: Network },
      { code: "generation-data", to: "/data/generation", label: "发电数据", icon: Zap },
      { code: "retail-data", to: "/data/retail", label: "用电数据", icon: Database },
    ],
  },
  {
    label: "计算与回执",
    items: [
      { code: "compute", to: "/compute", label: "隐私计算", icon: Network },
      { code: "settlements", to: "/settlements", label: "可信调用验证", icon: Calculator },
      { code: "results", to: "/results", label: "结果回执", icon: FileCheck2 },
      { code: "evidence", to: "/evidence", label: "可信凭证", icon: Blocks },
    ],
  },
  {
    label: "安全与管理",
    items: [
      { code: "rules", to: "/rules", label: "使用规则", icon: Gavel },
      { code: "audit", to: "/audit", label: "安全审计", icon: ClipboardCheck },
      { code: "reports", to: "/reports", label: "审计报告", icon: FileText },
      { code: "anomalies", to: "/anomalies", label: "风险处置", icon: AlertTriangle },
      { code: "agents", to: "/agents", label: "能力编排", icon: Workflow },
      { code: "logs", to: "/logs", label: "操作记录", icon: FileClock },
      { code: "system", to: "/system", label: "身份管理", icon: Settings },
      { code: "metrics", to: "/metrics", label: "系统状态", icon: BarChart3 },
    ],
  },
];

const pageNames = Object.fromEntries(navGroups.flatMap((group) => group.items.map((item) => [item.to, item.label])));

export function AppShell() {
  const { session, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const allowed = useMemo(() => new Set(session?.menus.map((item) => item.code) || []), [session]);
  const isAdmin = session?.user.role_code === "ADMIN";
  const title = isAdmin && location.pathname === "/overview" ? "系统管理员总览" : pageNames[location.pathname] || "可信数据协同平台";

  useEffect(() => {
    window.scrollTo(0, 0);
    setOpen(false);
  }, [location.pathname]);

  if (!session) return null;

  return (
    <div className="app-shell">
      <div className={`drawer-backdrop ${open ? "show" : ""}`} onClick={() => setOpen(false)} />
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-mark"><ShieldCheck size={22} /></div>
          <div><strong>隐链明算</strong><span>可信数据协同平台</span></div>
          <button className="icon-button mobile-only" onClick={() => setOpen(false)} title="关闭导航"><X size={19} /></button>
        </div>
        <div className="space-context">
          <div><Building2 size={15} />当前数据空间</div>
          <strong>{String(session.org.org_name || "当前组织")}</strong>
          <span><span className="health-dot" />服务正常</span>
        </div>
        <nav className="main-nav">
          {navGroups.map((group) => {
            const items = group.items.filter((item) => allowed.has(item.code));
            if (!items.length) return null;
            return (
              <div className="nav-group" key={group.label}>
                <div className="nav-label">{group.label}</div>
                {items.map(({ code, to, label, icon: Icon }) => (
                  <NavLink key={to} to={to} onMouseEnter={() => preloadRoute(to)} onFocus={() => preloadRoute(to)} onClick={() => setOpen(false)} className={({ isActive }) => isActive ? "active" : ""}>
                    <Icon size={17} /><span>{isAdmin && code === "overview" ? "系统总览" : label}</span>
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <button onClick={logout}><LogOut size={17} /><span>退出当前主体</span></button>
        </div>
      </aside>
      <div className="app-main">
        <div className="portal-masthead">
          <div className="portal-masthead-inner">
            <div className="portal-brand">
              <div className="portal-brand-mark"><ShieldCheck size={29} /></div>
              <div><strong>隐链明算</strong><span>可信数据平台</span></div>
            </div>
            <div className="portal-slogan">
              <span>可信数据服务</span>
              <strong>数据调用 · 隐私计算 · 可信回执</strong>
            </div>
            <div className="portal-utilities"><span className="portal-date">2026年08月</span></div>
          </div>
        </div>
        <nav className="portal-nav" aria-label="门户导航">
          <div className="portal-nav-inner">
            <NavLink to="/workbench" end onMouseEnter={() => preloadRoute("/workbench")} onFocus={() => preloadRoute("/workbench")}><Home size={16} /><span>我的工作台</span></NavLink>
            <NavLink to="/overview" onMouseEnter={() => preloadRoute("/overview")} onFocus={() => preloadRoute("/overview")}><LayoutDashboard size={16} /><span>平台能力</span></NavLink>
            {allowed.has("data-space") && <NavLink to="/data-space" onMouseEnter={() => preloadRoute("/data-space")} onFocus={() => preloadRoute("/data-space")}><Network size={16} /><span>数据目录</span></NavLink>}
            {allowed.has("compute") && <NavLink to="/compute" onMouseEnter={() => preloadRoute("/compute")} onFocus={() => preloadRoute("/compute")}><Network size={16} /><span>隐私计算</span></NavLink>}
            {allowed.has("settlements") && <NavLink to="/settlements" onMouseEnter={() => preloadRoute("/settlements")} onFocus={() => preloadRoute("/settlements")}><Calculator size={16} /><span>可信调用验证</span></NavLink>}
            {allowed.has("audit") && <NavLink to="/audit" onMouseEnter={() => preloadRoute("/audit")} onFocus={() => preloadRoute("/audit")}><ClipboardCheck size={16} /><span>安全监管</span></NavLink>}
            {allowed.has("reports") && <NavLink to="/reports" onMouseEnter={() => preloadRoute("/reports")} onFocus={() => preloadRoute("/reports")}><FileText size={16} /><span>审计报告</span></NavLink>}
            <div className="portal-nav-tools"><Search size={15} /><span>系统在线</span><i /></div>
          </div>
        </nav>
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button menu-button" onClick={() => setOpen(true)} title="打开导航"><Menu size={20} /></button>
            <div><span>{isAdmin ? "平台管理" : "业务工作台"}</span><strong>{title}</strong></div>
          </div>
          <div className="topbar-signals">
            <div className="signal"><Activity size={16} /><span>服务正常</span></div>
            <div className="signal"><KeyRound size={16} /><span>身份有效</span></div>
            <div className="signal"><ShieldCheck size={16} /><span>策略在线</span></div>
          </div>
          <div className="account">
            <div className="account-avatar">{session.user.display_name.slice(0, 1)}</div>
            <div><strong>{session.user.display_name}</strong><span>{ROLE_LABELS[session.user.role_code]}</span></div>
            <ChevronDown size={15} />
          </div>
        </header>
        <main key={location.pathname} className="page-content page-enter"><Suspense fallback={<div className="route-loading"><LoadingState label="正在打开工作台" /></div>}><Outlet /></Suspense></main>
        <footer className="portal-footer">
          <div className="portal-footer-inner">
            <div className="portal-footer-brand"><strong>隐链明算</strong><span>可信数据平台</span></div>
            <div className="portal-footer-meta"><span>服务状态：正常</span></div>
          </div>
        </footer>
      </div>
    </div>
  );
}
