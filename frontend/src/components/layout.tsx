import { useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Blocks,
  Bot,
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
  Info,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Megaphone,
  Menu,
  Network,
  Newspaper,
  PhoneCall,
  ScrollText,
  Search,
  Settings,
  ShieldCheck,
  UsersRound,
  X,
  Zap,
} from "lucide-react";
import { useAuth } from "../auth";
import { ROLE_LABELS } from "../types";

const navGroups = [
  {
    label: "平台总览",
    items: [
      { code: "overview", to: "/overview", label: "平台总览", icon: LayoutDashboard },
      { code: "workbench", to: "/workbench", label: "角色工作台", icon: CircleGauge },
    ],
  },
  {
    label: "数据调用与资产",
    items: [
      { code: "generation-data", to: "/data/generation", label: "发电侧数据", icon: Zap },
      { code: "retail-data", to: "/data/retail", label: "售电与用电数据", icon: Database },
      { code: "data-space", to: "/data-space", label: "可信数据调用", icon: Network },
    ],
  },
  {
    label: "隐私计算与验证",
    items: [
      { code: "compute", to: "/compute", label: "隐私计算", icon: Network },
      { code: "rules", to: "/rules", label: "用途与规则控制", icon: Gavel },
      { code: "settlements", to: "/settlements", label: "能源场景验证", icon: Calculator },
      { code: "results", to: "/results", label: "结果与回执", icon: FileCheck2 },
      { code: "evidence", to: "/evidence", label: "区块链存证", icon: Blocks },
      { code: "audit", to: "/audit", label: "监管审计", icon: ClipboardCheck },
      { code: "agents", to: "/agents", label: "Agent 协同", icon: Bot },
      { code: "anomalies", to: "/anomalies", label: "异常处置", icon: AlertTriangle },
    ],
  },
  {
    label: "支撑管理",
    items: [
      { code: "logs", to: "/logs", label: "全过程日志", icon: FileClock },
      { code: "system", to: "/system", label: "主体与 DID", icon: Settings },
      { code: "reports", to: "/reports", label: "可信报告", icon: FileText },
      { code: "metrics", to: "/metrics", label: "运行指标", icon: BarChart3 },
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

  if (!session) return null;

  return (
    <div className="app-shell">
      <div className={`drawer-backdrop ${open ? "show" : ""}`} onClick={() => setOpen(false)} />
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-mark"><LayoutDashboard size={22} /></div>
          <div><strong>工作台导航</strong><span>数据调用与隐私计算</span></div>
          <button className="icon-button mobile-only" onClick={() => setOpen(false)} title="关闭导航"><X size={19} /></button>
        </div>
        <div className="space-context">
          <div><Building2 size={15} />当前数据空间</div>
          <strong>{String(session.org.org_name || "演示空间")}</strong>
          <span><span className="health-dot" />空间连接正常</span>
        </div>
        <nav className="main-nav">
          {navGroups.map((group) => {
            const items = group.items.filter((item) => allowed.has(item.code));
            if (!items.length) return null;
            return (
              <div className="nav-group" key={group.label}>
                <div className="nav-label">{group.label}</div>
                {items.map(({ code, to, label, icon: Icon }) => (
                  <NavLink key={to} to={to} onClick={() => setOpen(false)} className={({ isActive }) => isActive ? "active" : ""}>
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
              <div><strong>隐链明算</strong><span>可信数据协同平台</span></div>
            </div>
            <div className="portal-slogan">
              <span>可信数据调用与隐私计算服务门户</span>
              <strong>数据可调用 · 计算可验证 · 隐私不出域</strong>
            </div>
            <div className="portal-utilities">
              <a href="#notice"><Megaphone size={14} />服务公告</a>
              <a href="#guide"><Info size={14} />使用指南</a>
              <a href="#support"><PhoneCall size={14} />业务支持</a>
              <span className="portal-date">2026年08月</span>
            </div>
          </div>
        </div>
        <nav className="portal-nav" aria-label="门户导航">
          <div className="portal-nav-inner">
            <NavLink to="/workbench" end><Home size={16} /><span>我的工作台</span></NavLink>
            <NavLink to="/overview"><LayoutDashboard size={16} /><span>平台能力</span></NavLink>
            {allowed.has("data-space") && <NavLink to="/data-space"><Network size={16} /><span>数据调用</span></NavLink>}
            {allowed.has("compute") && <NavLink to="/compute"><Network size={16} /><span>隐私计算</span></NavLink>}
            {allowed.has("settlements") && <NavLink to="/settlements"><Calculator size={16} /><span>场景验证</span></NavLink>}
            {allowed.has("audit") && <NavLink to="/audit"><ClipboardCheck size={16} /><span>安全监管</span></NavLink>}
            {allowed.has("reports") && <NavLink to="/reports"><Newspaper size={16} /><span>信息公开</span></NavLink>}
            <div className="portal-nav-tools"><Search size={15} /><span>系统在线</span><i /></div>
          </div>
        </nav>
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button menu-button" onClick={() => setOpen(true)} title="打开导航"><Menu size={20} /></button>
            <div><span>{isAdmin ? "系统运维工作台" : "可信数据协同工作台"}</span><strong>{title}</strong></div>
          </div>
          <div className="topbar-signals">
            <div className="signal"><Activity size={16} /><span>服务正常</span></div>
            <div className="signal"><KeyRound size={16} /><span>DID 有效</span></div>
          </div>
          <div className="account">
            <div className="account-avatar">{session.user.display_name.slice(0, 1)}</div>
            <div><strong>{session.user.display_name}</strong><span>{ROLE_LABELS[session.user.role_code]}</span></div>
            <ChevronDown size={15} />
          </div>
        </header>
        <main className="page-content"><Outlet /></main>
        <footer className="portal-footer">
          <div className="portal-footer-inner">
            <div className="portal-footer-brand"><strong>隐链明算可信数据协同平台</strong><span>以能源电力为验证场景的数据调用与隐私计算基础设施</span></div>
            <div className="portal-footer-links"><a href="#notice">通知公告</a><a href="#guide">使用指南</a><a href="#support">业务支持</a><a href="#security">安全与隐私</a></div>
            <div className="portal-footer-meta"><span>演示运行环境</span><span>服务状态：正常</span></div>
          </div>
        </footer>
      </div>
    </div>
  );
}
