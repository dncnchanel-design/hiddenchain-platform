import { Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { canAccessRouteView, getDefaultPath } from "./access";
import { useAuth } from "./auth";
import { AppShell } from "./components/layout";
import { LoadingState } from "./components/ui";
import { ForbiddenPage, NotFoundPage, SessionExpiredPage, UnavailablePage } from "./pages/StatusPages";
import { pages } from "./routes";
import { TrustedSpaceProvider } from "./features/trusted-energy/trusted-space-context";
import { canUseLegacyDestination, legacyBusinessDestination } from "./legacy-routes";

const {
  agents: AgentsPage,
  login: LoginPage,
  logs: LogsPage,
  metrics: MetricsPage,
  overview: OverviewPage,
  system: SystemPage,
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
  return session ? <Navigate to={getDefaultPath(session)} replace /> : <Suspense fallback={<div className="boot-screen"><LoadingState /></div>}><LoginPage /></Suspense>;
}

function TrustedSpaceGate() {
  const { session, loading, sessionExpired, sessionError } = useAuth();
  if (loading) return <div className="boot-screen"><LoadingState label="正在加载可信数据空间" /></div>;
  if (sessionExpired) return <Navigate to="/session-expired" replace />;
  if (sessionError) return <div className="public-state-screen"><UnavailablePage message={sessionError} /></div>;
  if (!session) return <Navigate to="/login" replace />;
  if (!session.menus.some((menu) => menu.path.startsWith("/trusted-space/"))) {
    return <Navigate to="/403?path=%2Ftrusted-space" replace />;
  }
  return <Suspense fallback={<div className="boot-screen"><LoadingState label="正在加载可信数据空间" /></div>}><TrustedSpaceProvider><TrustedSpaceShell /></TrustedSpaceProvider></Suspense>;
}

function Allowed({ path, children }: { path: string; children: React.ReactNode }) {
  const { session } = useAuth();
  const location = useLocation();
  const deniedPath = `${location.pathname}${location.search}${location.hash}`;
  return session && canAccessRouteView(session, path, location.search)
    ? children
    : <Navigate to={`/403?path=${encodeURIComponent(deniedPath)}`} replace state={{ deniedPath }} />;
}

function LegacyBusinessRedirect() {
  const { session, loading, sessionExpired, sessionError } = useAuth();
  const location = useLocation();
  if (loading) return <div className="boot-screen"><LoadingState label="正在迁移旧地址" /></div>;
  if (sessionExpired) return <Navigate to="/session-expired" replace />;
  if (sessionError) return <div className="public-state-screen"><UnavailablePage message={sessionError} /></div>;
  if (!session) return <Navigate to="/login" replace state={{ returnTo: `${location.pathname}${location.search}${location.hash}` }} />;
  const target = legacyBusinessDestination(location);
  if (!target) return <NotFoundPage />;
  if (!canUseLegacyDestination(session, target)) {
    const deniedPath = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to={`/403?path=${encodeURIComponent(deniedPath)}`} replace state={{ deniedPath }} />;
  }
  return <Navigate to={target.to} replace state={location.state} />;
}

function WorkspaceHome() {
  const { session } = useAuth();
  return session ? <Navigate to={getDefaultPath(session)} replace /> : null;
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
      <Route path="/workbench" element={<LegacyBusinessRedirect />} />
      <Route path="/data/upload" element={<LegacyBusinessRedirect />} />
      <Route path="/data/generation" element={<LegacyBusinessRedirect />} />
      <Route path="/data/retail" element={<LegacyBusinessRedirect />} />
      <Route path="/data-space" element={<LegacyBusinessRedirect />} />
      <Route path="/rules" element={<LegacyBusinessRedirect />} />
      <Route path="/settlements" element={<LegacyBusinessRedirect />} />
      <Route path="/settlements/new" element={<LegacyBusinessRedirect />} />
      <Route path="/settlements/:taskId" element={<LegacyBusinessRedirect />} />
      <Route path="/compute" element={<LegacyBusinessRedirect />} />
      <Route path="/results" element={<LegacyBusinessRedirect />} />
      <Route path="/evidence" element={<LegacyBusinessRedirect />} />
      <Route path="/audit" element={<LegacyBusinessRedirect />} />
      <Route path="/anomalies" element={<LegacyBusinessRedirect />} />
      <Route path="/trusted-execution" element={<LegacyBusinessRedirect />} />
      <Route path="/reports" element={<LegacyBusinessRedirect />} />
      <Route path="/contracts/:contractId" element={<LegacyBusinessRedirect />} />
      <Route element={<ProtectedShell />}>
          <Route index element={<WorkspaceHome />} />
          <Route path="/403" element={<ForbiddenPage />} />
          <Route path="/overview" element={<Allowed path="/overview"><OverviewPage /></Allowed>} />
          <Route path="/agents" element={<Allowed path="/agents"><AgentsPage /></Allowed>} />
          <Route path="/logs" element={<Allowed path="/logs"><LogsPage /></Allowed>} />
          <Route path="/system" element={<Allowed path="/system"><SystemPage /></Allowed>} />
          <Route path="/metrics" element={<Allowed path="/metrics"><MetricsPage /></Allowed>} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
    </Routes>
  );
}
