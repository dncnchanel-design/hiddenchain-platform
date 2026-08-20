import { describe, expect, it } from "vitest";
import { capabilityMatrix, DEMO_DATA_NOTICE, demoAssets, demoFixtureMetadata, trustedModuleChecklist, trustedViewRoutes, getTrustedView, routeForView, TRUSTED_BASE } from "./types";

describe("trusted energy console model", () => {
  it("keeps the complete 12-module checklist and reachable deep links", () => {
    expect(trustedModuleChecklist).toHaveLength(12);
    expect(trustedModuleChecklist.map((module) => module.key)).toEqual([
      "login", "workbench", "identity", "catalog", "asset", "apply", "contract", "ttc", "mpc", "results", "audit", "agent",
    ]);
    expect(trustedViewRoutes).toHaveLength(10);
    for (const route of trustedViewRoutes) {
      expect(route.path.startsWith(`${TRUSTED_BASE}/`)).toBe(true);
      expect(route.label.length).toBeGreaterThan(1);
    }
    expect(routeForView("asset", "asset-power-output-001")).toBe(`${TRUSTED_BASE}/assets/asset-power-output-001`);
    expect(routeForView("mpc", "com-20260518-001")).toBe(`${TRUSTED_BASE}/mpc/com-20260518-001`);
    expect(getTrustedView(`${TRUSTED_BASE}/results/res-20260518-001`)).toBe("results");
  });

  it("locks capability truth labels to the product boundary", () => {
    expect(capabilityMatrix).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: "MPC 计算", truth: "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST" }),
      expect.objectContaining({ name: "EDC / Connector", truth: "ADAPTER" }),
      expect.objectContaining({ name: "TEE 远程证明", truth: "BLOCKED" }),
      expect.objectContaining({ name: "区块链锚定 / FISCO BCOS", truth: "DEMO" }),
    ]));
    expect(new Set(capabilityMatrix.map((item) => item.truth))).toEqual(new Set(["LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST", "ADAPTER", "BLOCKED", "DEMO"]));
  });

  it("marks energy values and assets as controlled demo fixtures", () => {
    expect(DEMO_DATA_NOTICE).toContain("演示数据");
    expect(demoFixtureMetadata.settlement).toContain("演示夹具");
    expect(demoFixtureMetadata.anchoring).toContain("DEMO");
    expect(demoAssets.every((asset) => asset.name.length > 0 && asset.updatedAt.length > 0)).toBe(true);
    expect(demoAssets.find((asset) => asset.id === "asset-power-output-001")?.quality).toBe(98.5);
  });
});
