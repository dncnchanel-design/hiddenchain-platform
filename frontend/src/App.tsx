import { Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { AppShell } from "./components/layout";
import { LoadingState } from "./components/ui";
import { pages } from "./routes";

const {
  agents: AgentsPage,
  anomalies: AnomaliesPage,
  audit: AuditPage,
  compute: ComputePage,
  data: DataPage,
  dataSpace: DataSpacePage,
  evidence: EvidencePage,
  login: LoginPage,
  logs: LogsPage,
  metrics: MetricsPage,
  overview: OverviewPage,
  reports: ReportsPage,
  results: ResultsPage,
  rules: RulesPage,
  settlement: SettlementPage,
  system: SystemPage,
  workbench: WorkbenchPage,
} = pages;

function ProtectedShell() {
  const { session, loading } = useAuth();
  if (loading) return <div className="boot-screen"><LoadingState label="正在验证身份" /></div>;
  if (!session) return <Navigate to="/login" replace />;
  return <AppShell />;
}

function LoginGate() {
  const { session, loading } = useAuth();
  if (loading) return <div className="boot-screen"><LoadingState /></div>;
  return session ? <Navigate to="/workbench" replace /> : <Suspense fallback={<div className="boot-screen"><LoadingState /></div>}><LoginPage /></Suspense>;
}

function Allowed({ code, children }: { code: string; children: React.ReactNode }) {
  const { session } = useAuth();
  return session?.menus.some((item) => item.code === code) ? children : <Navigate to="/overview" replace />;
}

export default function App() {
  return (
    <Routes>
        <Route path="/login" element={<LoginGate />} />
        <Route element={<ProtectedShell />}>
          <Route index element={<Navigate to="/workbench" replace />} />
          <Route path="/overview" element={<Allowed code="overview"><OverviewPage /></Allowed>} />
          <Route path="/workbench" element={<Allowed code="workbench"><WorkbenchPage /></Allowed>} />
          <Route path="/data/generation" element={<Allowed code="generation-data"><DataPage mode="generation" /></Allowed>} />
          <Route path="/data/retail" element={<Allowed code="retail-data"><DataPage mode="retail" /></Allowed>} />
          <Route path="/data-space" element={<Allowed code="data-space"><DataSpacePage /></Allowed>} />
          <Route path="/rules" element={<Allowed code="rules"><RulesPage /></Allowed>} />
          <Route path="/settlements" element={<Allowed code="settlements"><SettlementPage /></Allowed>} />
          <Route path="/compute" element={<Allowed code="compute"><ComputePage /></Allowed>} />
          <Route path="/results" element={<Allowed code="results"><ResultsPage /></Allowed>} />
          <Route path="/evidence" element={<Allowed code="evidence"><EvidencePage /></Allowed>} />
          <Route path="/audit" element={<Allowed code="audit"><AuditPage /></Allowed>} />
          <Route path="/agents" element={<Allowed code="agents"><AgentsPage /></Allowed>} />
          <Route path="/anomalies" element={<Allowed code="anomalies"><AnomaliesPage /></Allowed>} />
          <Route path="/logs" element={<Allowed code="logs"><LogsPage /></Allowed>} />
          <Route path="/system" element={<Allowed code="system"><SystemPage /></Allowed>} />
          <Route path="/reports" element={<Allowed code="reports"><ReportsPage /></Allowed>} />
          <Route path="/metrics" element={<Allowed code="metrics"><MetricsPage /></Allowed>} />
          <Route path="*" element={<Navigate to="/overview" replace />} />
        </Route>
    </Routes>
  );
}
