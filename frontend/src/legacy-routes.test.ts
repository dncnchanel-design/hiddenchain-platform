// @ts-expect-error Vitest runs this source-contract check in Node without shipping Node typings.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { canUseLegacyDestination, legacyBusinessDestination, type LegacyDestination } from "./legacy-routes";
import type { RoleCode, SessionPayload } from "./types";
import appSource from "./App.tsx?raw";
import routesSource from "./routes.tsx?raw";
import shellSource from "./features/trusted-energy/layout/TrustedSpaceShell.tsx?raw";
import trustedWorkbenchSource from "./features/trusted-energy/pages/WorkbenchPage.tsx?raw";
import trustedResultsSource from "./features/trusted-energy/pages/ResultsEvidencePage.tsx?raw";

function session(role: RoleCode, code: string, path: string): SessionPayload {
  return {
    user: { user_id: "user", org_id: "org", username: "user", display_name: "用户", role_code: role, status: "ACTIVE" },
    org: {},
    did: {},
    menus: [{ code, path, roles: [role] }],
    field_scopes: {},
  };
}

function target(pathname: string, search = "", hash = "") {
  const result = legacyBusinessDestination({ pathname, search, hash });
  expect(result, pathname).not.toBeNull();
  return result as LegacyDestination;
}

describe("legacy business route migration", () => {
  it.each([
    ["/workbench", "?scope=mine", "#focus", "/trusted-space/workbench?scope=mine#focus"],
    ["/data-space", "?task_id=task-1", "", "/trusted-space/catalog?task_id=task-1"],
    ["/data-space", "?task_id=task-1", "#data-authorizations", "/trusted-space/authorizations?task_id=task-1#data-authorizations"],
    ["/rules", "?task_id=task-1", "#rule", "/trusted-space/authorizations?task_id=task-1#rule"],
    ["/trusted-execution", "?request_id=req-1", "", "/trusted-space/authorizations?request_id=req-1"],
    ["/settlements", "?view=todo", "", "/trusted-space/mpc?view=todo"],
    ["/settlements/", "?view=todo", "", "/trusted-space/mpc?view=todo"],
    ["/settlements/new", "?template=ready", "#review", "/trusted-space/mpc/new?template=ready#review"],
    ["/settlements/task%2Freal", "?from=notice", "#trusted-chain", "/trusted-space/ttc/task%2Freal?from=notice#trusted-chain"],
    ["/compute", "?job_id=job%2Freal&task_id=task-real", "#logs", "/trusted-space/mpc/job%2Freal?job_id=job%2Freal&task_id=task-real#logs"],
    ["/compute", "?task_id=task-real", "", "/trusted-space/mpc?task_id=task-real"],
    ["/results", "?task_id=task-real", "#confirmation", "/trusted-space/results?task_id=task-real#confirmation"],
    ["/results", "?result_id=result%2Freal", "", "/trusted-space/results/result%2Freal?result_id=result%2Freal"],
    ["/evidence", "?task_id=task%2Freal&format=json", "#chain", "/trusted-space/audit/tasks/task%2Freal?task_id=task%2Freal&format=json#chain"],
    ["/audit", "?task_id=task-real", "", "/trusted-space/audit/tasks/task-real?task_id=task-real"],
    ["/reports", "?task_id=task-real", "", "/trusted-space/audit/tasks/task-real?task_id=task-real"],
    ["/anomalies", "?task_id=task-real", "", "/trusted-space/audit/tasks/task-real?task_id=task-real"],
    ["/contracts/contract%2Freal", "?revision=2", "#history", "/trusted-space/contracts/contract%2Freal?revision=2#history"],
  ])("preserves identifiers, query, and hash for %s", (pathname, search, hash, expected) => {
    expect(target(pathname, search, hash).to).toBe(expected);
  });

  it("fails closed for malformed or unknown legacy paths", () => {
    expect(legacyBusinessDestination({ pathname: "/settlements/%E0%A4%A" })).toBeNull();
    expect(legacyBusinessDestination({ pathname: "/contracts/%E0%A4%A" })).toBeNull();
    expect(legacyBusinessDestination({ pathname: "/policy-center" })).toBeNull();
  });

  it("authorizes against the destination module, never a deleted legacy menu", () => {
    const create = target("/settlements/new", "?template=ready");
    expect(canUseLegacyDestination(session("EXCHANGE", "compute", "/trusted-space/mpc"), create)).toBe(true);
    expect(canUseLegacyDestination(session("GENERATOR", "compute", "/trusted-space/mpc"), create)).toBe(false);
    expect(canUseLegacyDestination(session("EXCHANGE", "settlements", "/settlements"), create)).toBe(false);
    expect(canUseLegacyDestination(session("ADMIN", "overview", "/overview"), target("/workbench"))).toBe(false);
    expect(canUseLegacyDestination(session("REGULATOR", "audit", "/trusted-space/audit"), target("/reports"))).toBe(true);
  });

  it("registers every compatibility path without loading the retired business pages", () => {
    for (const path of [
      "/workbench", "/data-space", "/rules", "/settlements", "/settlements/new",
      "/settlements/:taskId", "/compute", "/results", "/evidence", "/audit",
      "/reports", "/anomalies", "/trusted-execution", "/contracts/:contractId",
    ]) expect(appSource).toContain(`path="${path}" element={<LegacyBusinessRedirect />}`);

    for (const retiredPage of ["SettlementPage", "SettlementDetailPage", "ComputePage", "DataSpacePage", "ReportsPage", "RulesPage"]) {
      expect(routesSource).not.toContain(`import("./pages/${retiredPage}")`);
    }
    expect(shellSource).toContain('import("../../../pages/SettlementCreatePage")');
    expect(shellSource).toContain("canCreateSettlement(session)");
    expect(shellSource).toContain('visibleMenuCodes.has("compute")');
    expect(trustedWorkbenchSource).toContain('path === "/trusted-space/mpc/new"');
    expect(trustedWorkbenchSource).toContain('import("../../../pages/SettlementCreatePage")');
    expect(trustedResultsSource).toContain('searchParams.get("task_id")');
    expect(trustedResultsSource).toContain("taskId: requestedTaskId || undefined");
  });

  it("keeps core Trusted Space calls to action out of retired routes and policy-center links", () => {
    const trustedSources = import.meta.glob("./features/trusted-energy/**/*.{ts,tsx}", {
      eager: true,
      import: "default",
      query: "?raw",
    }) as Record<string, string>;
    const retiredTarget = /\b(?:to|path)\s*=\s*["']\/(?:workbench|data-space|rules|settlements|compute|results|evidence|audit|reports|anomalies|trusted-execution)(?:[/?#"'])/;
    for (const [sourcePath, source] of Object.entries(trustedSources)) {
      expect(source, sourcePath).not.toMatch(retiredTarget);
      expect(source, sourcePath).not.toMatch(/\/(?:policy-center|strategy-center)/);
    }

    const prototypeSource = readFileSync(new URL("../../backend/app/routers/prototype.py", import.meta.url), "utf8");
    const workbenchSource = readFileSync(new URL("../../backend/app/services/trust_space.py", import.meta.url), "utf8");
    expect(prototypeSource).toContain('primary_action = {"label": "发起结算任务", "path": "/trusted-space/mpc/new"}');
    expect(workbenchSource).toContain('path="/trusted-space/mpc/new"');
  });
});
