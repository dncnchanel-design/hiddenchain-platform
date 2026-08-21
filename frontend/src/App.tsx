import { Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { canAccessRouteView, canCreateSettlement, getDefaultPath } from "./access";
import { useAuth } from "./auth";
import { AppShell } from "./components/layout";
import { LoadingState } from "./components/ui";
import { ForbiddenPage, NotFoundPage, SessionExpiredPage, UnavailablePage } from "./pages/StatusPages";
import { pages } from "./routes";

const {
  agents: AgentsPage,
  anomalies: AnomaliesPage,
  audit: AuditPage,
  compute: ComputePage,
  dataSpace: DataSpacePage,
  excelUpload: ExcelUploadPage,
  evidence: EvidencePage,
  login: LoginPage,
  logs: LogsPage,
  metrics: MetricsPage,
  overview: OverviewPage,
  reports: ReportsPage,
  results: ResultsPage,
  rules: RulesPage,
  settlement: SettlementPage,
  settlementCreate: SettlementCreatePage,
  settlementDetail: SettlementDetailPage,
  system: SystemPage,
  trustedExecution: TrustedExecutionPage,
  workbench: WorkbenchPage,
  trustedSpace: TrustedSpaceShell,
} = pages;

function ProtectedShell() {
  const { session, loading, sessionExpired, sessionError } = useAuth();
  if (loading) return <div className="boot-screen"><LoadingState label="正在验证身份" /></div>;
  if (sessionExpired) return <Navigate to="/session-expired" replace />;
  if (sessionError) return <div className="public-state-screen"><UnavailablePage message={sessionError} /></div>;
  if (!session) return <Navigate to="/login" replace />;
  return <AppShell />;
}

function LoginGate() {
  const { session, loading, sessionError } = useAuth();
  if (loading) return <div className="boot-screen"><LoadingState /></div>;
  if (sessionError) return <div className="public-state-screen"><UnavailablePage message={sessionError} /></div>;
  return session ? <Navigate to="/trusted-space/workbench" replace /> : <Suspense fallback={<div className="boot-screen"><LoadingState /></div>}><LoginPage /></Suspense>;
}

function TrustedSpaceGate() {
  const { session, loading, sessionExpired, sessionError } = useAuth();
  if (loading) return <div className="boot-screen"><LoadingState label="正在加载可信数据空间" /></div>;
  if (sessionExpired) return <Navigate to="/session-expired" replace />;
  if (sessionError) return <div className="public-state-screen"><UnavailablePage message={sessionError} /></div>;
  if (!session) return <Navigate to="/login" replace />;
  return <Suspense fallback={<div className="boot-screen"><LoadingState label="正在加载可信数据空间" /></div>}><TrustedSpaceShell /></Suspense>;
}

function Allowed({ path, children }: { path: string; children: React.ReactNode }) {
  const { session } = useAuth();
  const location = useLocation();
  const deniedPath = `${location.pathname}${location.search}${location.hash}`;
  return session && canAccessRouteView(session, path, location.search)
    ? children
    : <Navigate to={`/403?path=${encodeURIComponent(deniedPath)}`} replace state={{ deniedPath }} />;
}

function ExchangeOnly({ children }: { children: React.ReactNode }) {
  const { session } = useAuth();
  return session && canCreateSettlement(session)
    ? children
    : <Navigate to="/403?path=%2Fsettlements%2Fnew" replace />;
}

function WorkspaceHome() {
  const { session } = useAuth();
  return session ? <Navigate to="/trusted-space/workbench" replace /> : null;
}

function SessionExpiredGate() {
  const { session } = useAuth();
  return session ? <Navigate to={getDefaultPath(session)} replace /> : <SessionExpiredPage />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginGate />} />
      <Route path="/session-expired" element={<SessionExpiredGate />} />
      <Route path="/trusted-space/*" element={<TrustedSpaceGate />} />
      <Route element={<ProtectedShell />}>
          <Route index element={<WorkspaceHome />} />
          <Route path="/403" element={<ForbiddenPage />} />
          <Route path="/overview" element={<Allowed path="/overview"><OverviewPage /></Allowed>} />
          <Route path="/workbench" element={<Allowed path="/workbench"><WorkbenchPage /></Allowed>} />
          <Route path="/data/upload" element={<Allowed path="/data/upload"><ExcelUploadPage /></Allowed>} />
          <Route path="/data/generation" element={<Navigate to="/data/upload" replace />} />
          <Route path="/data/retail" element={<Navigate to="/data/upload" replace />} />
          <Route path="/data-space" element={<Allowed path="/data-space"><DataSpacePage /></Allowed>} />
          <Route path="/rules" element={<Allowed path="/rules"><RulesPage /></Allowed>} />
          <Route path="/settlements" element={<Allowed path="/settlements"><SettlementPage /></Allowed>} />
          <Route path="/settlements/new" element={<Allowed path="/settlements/new"><ExchangeOnly><SettlementCreatePage /></ExchangeOnly></Allowed>} />
          <Route path="/settlements/:taskId" element={<Allowed path="/settlements/:taskId"><SettlementDetailPage /></Allowed>} />
          <Route path="/compute" element={<Allowed path="/compute"><ComputePage /></Allowed>} />
          <Route path="/results" element={<Allowed path="/results"><ResultsPage /></Allowed>} />
          <Route path="/evidence" element={<Allowed path="/evidence"><EvidencePage /></Allowed>} />
          <Route path="/audit" element={<Allowed path="/audit"><AuditPage /></Allowed>} />
          <Route path="/agents" element={<Allowed path="/agents"><AgentsPage /></Allowed>} />
          <Route path="/anomalies" element={<Allowed path="/anomalies"><AnomaliesPage /></Allowed>} />
          <Route path="/logs" element={<Allowed path="/logs"><LogsPage /></Allowed>} />
          <Route path="/system" element={<Allowed path="/system"><SystemPage /></Allowed>} />
          <Route path="/trusted-execution" element={<Allowed path="/trusted-execution"><TrustedExecutionPage /></Allowed>} />
          <Route path="/reports" element={<Allowed path="/reports"><ReportsPage /></Allowed>} />
          <Route path="/metrics" element={<Allowed path="/metrics"><MetricsPage /></Allowed>} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
    </Routes>
  );
}
