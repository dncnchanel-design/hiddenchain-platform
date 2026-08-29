import { gzipSync } from "node:zlib";

const budgetedTrustedPages = new Map([
  ["WorkbenchPage.tsx", "/features/trusted-energy/pages/WorkbenchPage.tsx"],
  ["QueryPage.tsx", "/features/trusted-energy/pages/QueryPage.tsx"],
  ["IdentityPage.tsx", "/features/trusted-energy/pages/IdentityPage.tsx"],
  ["CatalogPage.tsx", "/features/trusted-energy/pages/CatalogPage.tsx"],
  ["ConnectorPage.tsx", "/features/trusted-energy/pages/ConnectorPage.tsx"],
  ["AuthorizationsPage.tsx", "/features/trusted-energy/pages/AuthorizationsPage.tsx"],
  ["AssetPassportPage.tsx", "/features/trusted-energy/pages/AssetPassportPage.tsx"],
  ["ApplyPage.tsx", "/features/trusted-energy/pages/ApplyPage.tsx"],
  ["ContractPage.tsx", "/features/trusted-energy/pages/ContractPage.tsx"],
  ["TtcPage.tsx", "/features/trusted-energy/pages/TtcPage.tsx"],
  ["MpcPage.tsx", "/features/trusted-energy/pages/MpcPage.tsx"],
  ["ResultsEvidencePage.tsx", "/features/trusted-energy/pages/ResultsEvidencePage.tsx"],
  ["AuditCenterPage.tsx", "/features/trusted-energy/pages/AuditCenterPage.tsx"],
  ["SettlementCreatePage.tsx", "/pages/SettlementCreatePage.tsx"],
]);

export function trustedRouteStaticBudget(limitBytes) {
  return {
    name: "trusted-route-static-budget",
    apply: "build",
    generateBundle(_options, bundle) {
      const chunks = Object.values(bundle).filter((output) => output.type === "chunk");
      const byFile = new Map(chunks.map((chunk) => [chunk.fileName, chunk]));
      const entry = chunks.find((chunk) => chunk.isEntry);
      const moduleIds = (chunk) => [chunk.facadeModuleId, ...chunk.moduleIds].filter(Boolean).map((id) => id.replaceAll("\\", "/"));
      const ownsModule = (chunk, suffix) => moduleIds(chunk).some((id) => id.endsWith(suffix));
      const shell = chunks.find((chunk) => ownsModule(chunk, "/features/trusted-energy/layout/TrustedSpaceShell.tsx"));
      if (!entry || !shell) this.error("无法定位可信空间入口，不能执行静态脚本预算检查");

      const staticGzipBytes = (roots) => {
        const seen = new Set();
        const pending = roots.map((chunk) => chunk.fileName);
        while (pending.length) {
          const fileName = pending.pop();
          if (!fileName || seen.has(fileName)) continue;
          seen.add(fileName);
          const chunk = byFile.get(fileName);
          if (chunk) pending.push(...chunk.imports);
        }
        return [...seen].reduce((total, fileName) => {
          const chunk = byFile.get(fileName);
          return total + (chunk ? gzipSync(chunk.code).byteLength : 0);
        }, 0);
      };

      const rows = [...budgetedTrustedPages]
        .map(([page, suffix]) => ({ page, chunk: chunks.find((chunk) => ownsModule(chunk, suffix)) }))
        .map(({ page, chunk }) => {
          if (!chunk) this.error(`无法定位可信空间页面 ${page}，不能执行静态脚本预算检查`);
          return { page, bytes: staticGzipBytes([entry, shell, chunk]) };
        })
        .sort((left, right) => left.page.localeCompare(right.page));

      this.info(`[trusted-route-static-budget] ${rows.map(({ page, bytes }) => `${page} ${(bytes / 1024).toFixed(1)} KiB`).join(" | ")}`);
      const violations = rows.filter(({ bytes }) => bytes > limitBytes);
      if (violations.length) {
        this.error(`可信空间静态脚本超过 ${(limitBytes / 1024).toFixed(0)} KiB：${violations.map(({ page, bytes }) => `${page} ${(bytes / 1024).toFixed(1)} KiB`).join("，")}`);
      }
    },
  };
}
