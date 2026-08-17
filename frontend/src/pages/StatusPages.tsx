import { AlertTriangle, ArrowLeft, Clock3, LogIn, SearchX, ShieldX } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { getDefaultPath } from "../access";
import { useAuth } from "../auth";

function StatusPage({
  icon: Icon,
  code,
  title,
  message,
  children,
}: {
  icon: React.ElementType;
  code: string;
  title: string;
  message: string;
  children: React.ReactNode;
}) {
  return (
    <section className="system-state-page" aria-labelledby={`state-${code}`}>
      <div className="system-state-icon" aria-hidden="true"><Icon size={28} /></div>
      <span className="system-state-code">{code}</span>
      <h1 id={`state-${code}`}>{title}</h1>
      <p>{message}</p>
      <div className="system-state-actions">{children}</div>
    </section>
  );
}

export function ForbiddenPage() {
  const { session } = useAuth();
  const location = useLocation();
  const deniedPath = new URLSearchParams(location.search).get("path") || location.state?.deniedPath || "当前页面";
  const home = session ? getDefaultPath(session) : "/login";
  return (
    <StatusPage icon={ShieldX} code="403" title="无权访问" message={`当前账号没有访问“${deniedPath}”的权限。权限由组织角色和菜单授权共同决定。`}>
      <Link className="button button-primary" to={home}><ArrowLeft size={16} />返回工作入口</Link>
    </StatusPage>
  );
}

export function NotFoundPage() {
  const { session } = useAuth();
  const home = session ? getDefaultPath(session) : "/login";
  return (
    <StatusPage icon={SearchX} code="404" title="页面不存在" message="地址可能已变更，或当前链接不属于本系统。请返回工作入口后重试。">
      <Link className="button button-primary" to={home}><ArrowLeft size={16} />返回工作入口</Link>
    </StatusPage>
  );
}

export function SessionExpiredPage() {
  return (
    <div className="public-state-screen">
      <StatusPage icon={Clock3} code="SESSION" title="会话已失效" message="为保护账户安全，本次会话已结束。重新登录后可继续使用系统。">
        <Link className="button button-primary" to="/login"><LogIn size={16} />重新登录</Link>
      </StatusPage>
    </div>
  );
}

export function UnavailablePage({ message }: { message: string }) {
  return (
    <StatusPage icon={AlertTriangle} code="UNAVAILABLE" title="暂时无法使用" message={message}>
      <button className="button button-secondary" type="button" onClick={() => window.location.reload()}>重新加载</button>
    </StatusPage>
  );
}
