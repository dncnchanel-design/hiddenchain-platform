import { retryableLazyNamed, type RetryableLazyComponent } from "./components/RetryableLazy";
import { LoginPage } from "./pages/LoginPage";

type LazyPage = RetryableLazyComponent;

const eagerLoginPage = Object.assign(LoginPage, {
  preload: () => Promise.resolve(LoginPage),
}) satisfies RetryableLazyComponent;

export const pages = {
  agents: retryableLazyNamed(() => import("./pages/AgentsPage"), "AgentsPage"),
  // Authentication is the boot path and must never depend on an async route chunk.
  login: eagerLoginPage,
  logs: retryableLazyNamed(() => import("./pages/LogsPage"), "LogsPage"),
  metrics: retryableLazyNamed(() => import("./pages/MetricsPage"), "MetricsPage"),
  overview: retryableLazyNamed(() => import("./pages/OverviewPage"), "OverviewPage"),
  system: retryableLazyNamed(() => import("./pages/SystemPage"), "SystemPage"),
  trustedSpace: retryableLazyNamed(() => import("./features/trusted-energy/layout/TrustedSpaceShell"), "TrustedSpaceShell"),
};

const routePages: Array<[string, LazyPage]> = [
  ["/agents", pages.agents],
  ["/logs", pages.logs],
  ["/metrics", pages.metrics],
  ["/overview", pages.overview],
  ["/system", pages.system],
];

export function preloadRoute(path: string) {
  const page = routePages.find(([prefix]) => path === prefix || (prefix.endsWith("/") && path.startsWith(prefix)));
  page?.[1].preload().catch(() => undefined);
}
