import { Suspense, useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  BarChart3,
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
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
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
      { code: "workbench", to: "/workbench", label: "工作台", icon: CircleGauge },
      { code: "overview", to: "/overview", label: "平台概览", icon: LayoutDashboard },
    ],
  },
  {
    label: "数据与授权",
    items: [
      { code: "data-space", to: "/data-space", label: "数据目录", icon: Network },
      { code: "generation-data", to: "/data/generation", label: "发电数据", icon: Zap },
      { code: "retail-data", to: "/data/retail", label: "用电数据", icon: Database },
      { code: "rules", to: "/rules", label: "授权规则", icon: Gavel },
    ],
  },
  {
    label: "计算与验证",
    items: [
      { code: "compute", to: "/compute", label: "隐私计算", icon: Network },
      { code: "settlements", to: "/settlements", label: "调用验证", icon: Calculator },
      { code: "results", to: "/results", label: "结果确认", icon: FileCheck2 },
    ],
  },
  {
    label: "审计与凭证",
    items: [
      { code: "evidence", to: "/evidence", label: "审计凭证", icon: FileText },
      { code: "audit", to: "/audit", label: "安全审计", icon: ClipboardCheck },
      { code: "reports", to: "/reports", label: "审计报告", icon: FileText },
      { code: "anomalies", to: "/anomalies", label: "风险处置", icon: AlertTriangle },
      { code: "logs", to: "/logs", label: "操作记录", icon: FileClock },
    ],
  },
  {
    label: "系统管理",
    items: [
      { code: "system", to: "/system", label: "组织与身份", icon: UsersRound },
      { code: "agents", to: "/agents", label: "能力编排", icon: Workflow },
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
  const title = isAdmin && location.pathname === "/overview" ? "系统管理员总览" : pageNames[location.pathname] || "隐链明算";

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
          <div><strong>隐链明算</strong><span>电力交易可信执行平台</span></div>
          <button className="icon-button mobile-only" onClick={() => setOpen(false)} title="关闭导航"><X size={19} /></button>
        </div>
        <div className="space-context">
          <div><Building2 size={15} />当前组织</div>
          <strong>{String(session.org.org_name || "当前组织")}</strong>
          <span>当前工作空间 · 默认业务空间</span>
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
          <button onClick={logout}><LogOut size={17} /><span>退出登录</span></button>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button menu-button" onClick={() => setOpen(true)} title="打开导航"><Menu size={20} /></button>
            <div><span>隐链明算 / {isAdmin ? "平台管理" : "业务工作台"}</span><strong>{title}</strong></div>
          </div>
          <div className="topbar-signals">
            <div className="signal"><Activity size={16} /><span>系统状态正常</span></div>
            <div className="signal signal-muted"><KeyRound size={16} /><span>{ROLE_LABELS[session.user.role_code]}</span></div>
          </div>
          <div className="account">
            <div className="account-avatar">{session.user.display_name.slice(0, 1)}</div>
            <div><strong>{session.user.display_name}</strong><span>{ROLE_LABELS[session.user.role_code]}</span></div>
            <ChevronDown size={15} />
          </div>
        </header>
        <main key={location.pathname} className="page-content page-enter"><Suspense fallback={<div className="route-loading"><LoadingState label="正在打开工作台" /></div>}><Outlet /></Suspense></main>
      </div>
    </div>
  );
}
