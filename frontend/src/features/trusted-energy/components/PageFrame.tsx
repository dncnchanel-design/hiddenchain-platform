import { ArrowLeft, Bot, ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { IconButton } from "./ui-primitives";
import { TrustedHelpPanel } from "./TrustedHelpPanel";

export function PageFrame({ title, description, eyebrow, back, action, children, className = "" }: { title: string; description?: string; eyebrow?: string; back?: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  const navigate = useNavigate();
  return <div className={`trusted-page tw-w-full ${className}`.trim()}>
    <div className="trusted-page-heading">
      <div className="trusted-heading-copy">
        {back && <button className="trusted-back-link" type="button" onClick={() => navigate(back)}><ArrowLeft size={14} />返回</button>}
        <div className="trusted-heading-title-row"><h1>{title}</h1>{eyebrow && <span className="trusted-heading-eyebrow">{eyebrow}</span>}</div>
        {description && <p>{description}</p>}
      </div>
      <div className="trusted-page-actions">{action}<TrustedHelpPanel /><IconButton label="打开智能助手" onClick={() => window.dispatchEvent(new CustomEvent("trusted-energy:agent-open"))}><Bot size={16} /></IconButton></div>
    </div>
    {children}
  </div>;
}

export function Breadcrumb({ items }: { items: string[] }) {
  return <div className="trusted-breadcrumb" aria-label="当前位置">{items.map((item, index) => <span key={`${item}-${index}`}>{index > 0 && <ChevronRight size={12} />}{item}</span>)}</div>;
}
