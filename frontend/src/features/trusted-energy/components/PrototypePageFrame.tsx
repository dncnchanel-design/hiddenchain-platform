import { useLocation } from "react-router-dom";
import { getTrustedView, type TrustedViewKey } from "../types";

const prototypePageTitles: Partial<Record<TrustedViewKey, string>> = {
  workbench: "运行总览",
  query: "智能数据查询",
  connector: "数据连接",
  authorizations: "数据授权",
  audit: "审计追溯",
};

export function PrototypePageFrame({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  const view = getTrustedView(useLocation().pathname);
  return <div className={`prototype-page ${className}`.trim()}><h1 className="sr-only">{prototypePageTitles[view] || "可信数据空间"}</h1>{children}</div>;
}

export function PrototypeCardTitle({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return <div className="prototype-card-title"><h3>{children}</h3>{action}</div>;
}
