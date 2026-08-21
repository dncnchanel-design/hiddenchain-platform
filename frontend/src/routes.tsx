import { lazy, type ComponentType, type LazyExoticComponent } from "react";

type Loader = () => Promise<Record<string, unknown>>;
type LazyPage<P = any> = LazyExoticComponent<ComponentType<P>> & { preload: () => Promise<unknown> };
function lazyNamed<P>(loader: Loader, exportName: string): LazyPage<P> {
  let promise: Promise<{ default: ComponentType<P> }> | undefined;
  const load = () => {
    promise ||= loader().then((module) => ({ default: module[exportName] as ComponentType<P> }));
    return promise;
  };
  const component = lazy(load) as LazyPage<P>;
  component.preload = load;
  return component;
}

export const pages = {
  agents: lazyNamed(() => import("./pages/AgentsPage"), "AgentsPage"),
  anomalies: lazyNamed(() => import("./pages/AnomaliesPage"), "AnomaliesPage"),
  audit: lazyNamed(() => import("./pages/AuditPage"), "AuditPage"),
  compute: lazyNamed(() => import("./pages/ComputePage"), "ComputePage"),
  excelUpload: lazyNamed(() => import("./pages/ExcelUploadPage"), "ExcelUploadPage"),
  dataSpace: lazyNamed(() => import("./pages/DataSpacePage"), "DataSpacePage"),
  evidence: lazyNamed(() => import("./pages/EvidencePage"), "EvidencePage"),
  login: lazyNamed(() => import("./pages/LoginPage"), "LoginPage"),
  logs: lazyNamed(() => import("./pages/LogsPage"), "LogsPage"),
  metrics: lazyNamed(() => import("./pages/MetricsPage"), "MetricsPage"),
  overview: lazyNamed(() => import("./pages/OverviewPage"), "OverviewPage"),
  reports: lazyNamed(() => import("./pages/ReportsPage"), "ReportsPage"),
  results: lazyNamed(() => import("./pages/ResultsPage"), "ResultsPage"),
  rules: lazyNamed(() => import("./pages/RulesPage"), "RulesPage"),
  settlement: lazyNamed(() => import("./pages/SettlementPage"), "SettlementPage"),
  settlementCreate: lazyNamed(() => import("./pages/SettlementCreatePage"), "SettlementCreatePage"),
  settlementDetail: lazyNamed(() => import("./pages/SettlementDetailPage"), "SettlementDetailPage"),
  system: lazyNamed(() => import("./pages/SystemPage"), "SystemPage"),
  trustedExecution: lazyNamed(() => import("./pages/TrustedExecutionPage"), "TrustedExecutionPage"),
  workbench: lazyNamed(() => import("./pages/WorkbenchPage"), "WorkbenchPage"),
  trustedSpace: lazyNamed(() => import("./features/trusted-energy/layout/TrustedSpaceShell"), "TrustedSpaceShell"),
};

const routePages: Array<[string, LazyPage]> = [
  ["/agents", pages.agents],
  ["/anomalies", pages.anomalies],
  ["/audit", pages.audit],
  ["/compute", pages.compute],
  ["/data/upload", pages.excelUpload],
  ["/data-space", pages.dataSpace],
  ["/evidence", pages.evidence],
  ["/logs", pages.logs],
  ["/metrics", pages.metrics],
  ["/overview", pages.overview],
  ["/reports", pages.reports],
  ["/results", pages.results],
  ["/rules", pages.rules],
  ["/settlements/new", pages.settlementCreate],
  ["/settlements/", pages.settlementDetail],
  ["/settlements", pages.settlement],
  ["/system", pages.system],
  ["/trusted-execution", pages.trustedExecution],
  ["/workbench", pages.workbench],
];

export function preloadRoute(path: string) {
  const page = routePages.find(([prefix]) => path === prefix || (prefix.endsWith("/") && path.startsWith(prefix)));
  page?.[1].preload().catch(() => undefined);
}
