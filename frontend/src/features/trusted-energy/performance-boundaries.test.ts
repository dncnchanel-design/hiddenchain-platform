import { describe, expect, it } from "vitest";
import budgetSource from "../../../scripts/trusted-route-budget.mjs?raw";
import viteSource from "../../../vite.config.ts?raw";
import chartsSource from "./components/WorkbenchCharts.tsx?raw";
import visibleBoundarySource from "./components/VisibleModuleBoundary.tsx?raw";
import shellSource from "./layout/TrustedSpaceShell.tsx?raw";
import querySource from "./pages/QueryPage.tsx?raw";
import workbenchSource from "./pages/WorkbenchPage.tsx?raw";

describe("trusted space performance boundaries", () => {
  it("loads trusted-space pages as separate lazy chunks", () => {
    expect(shellSource).toContain("Suspense");
    expect(shellSource).toContain('import("../pages/WorkbenchPage")');
    expect(shellSource).toContain('import("../pages/QueryPage")');
    expect(shellSource).toContain('import("../pages/ConnectorPage")');
    expect(shellSource).toContain('import("../../../pages/SettlementCreatePage")');
    expect(shellSource).not.toMatch(/import \{ \w+Page \} from "\.\.\/pages\//);
  });

  it("loads ECharts only when a workbench chart boundary becomes visible", () => {
    expect(workbenchSource).toContain('import("../components/WorkbenchCharts")');
    expect(workbenchSource).toContain("VisibleModuleBoundary");
    expect(visibleBoundarySource).toContain("IntersectionObserver");
    expect(workbenchSource).not.toContain('from "echarts/core"');
    expect(chartsSource).toContain('from "echarts/core"');
    expect(chartsSource).toContain("MapChart");
    expect(chartsSource).toContain("LinesChart");
    expect(chartsSource).toContain("ScatterChart");
    expect(chartsSource).toContain("LineChart");
    expect(chartsSource).toContain("PieChart");
    expect(chartsSource).not.toContain('import * as echarts from "echarts"');
  });

  it("loads the query result chart only after its visible boundary is reached", () => {
    expect(querySource).toContain('import("../components/QueryResultChart")');
    expect(querySource).toContain("VisibleModuleBoundary");
    expect(querySource).not.toContain('import { QueryResultChart } from "../components/QueryResultChart"');
    expect(visibleBoundarySource).toContain("RemoteState");
    expect(visibleBoundarySource).toContain("onRetry");
  });

  it("keeps workbench charts recoverable and accessible", () => {
    expect(chartsSource).toContain("shandongMapPromise = null");
    expect(chartsSource).toContain('matchMedia("(prefers-reduced-motion: reduce)")');
    expect(chartsSource).toContain('role="img"');
    expect(workbenchSource).toContain("KPI_ICONS[itemIndex] ?? Database");
    expect(workbenchSource).toContain('className="prototype-timeline-marker"');
  });

  it("does not force legacy Recharts into trusted-space route dependencies", () => {
    expect(viteSource).not.toContain('charts: ["recharts"]');
    expect(viteSource).toContain("trustedRouteStaticBudget");
    expect(viteSource).toContain("250 * 1024");
    expect(budgetSource).toContain('"QueryPage.tsx"');
    expect(budgetSource.match(/\["[A-Za-z]+Page\.tsx"/g)).toHaveLength(14);
    expect(budgetSource).toContain("bytes > limitBytes");
  });
});
