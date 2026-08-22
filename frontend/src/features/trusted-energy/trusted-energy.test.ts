import { describe, expect, it } from "vitest";
import { isKnownTrustedPath, navItems, trustedEntityId, trustedMenuCodeForView, getTrustedView, routeForView, TRUSTED_BASE } from "./types";
import { labelForCode } from "../../types";
import { capabilityMatrix, DEMO_DATA_NOTICE, demoAssets, demoFixtureMetadata, trustedModuleChecklist, trustedViewRoutes } from "./trusted-energy.test-fixtures";

describe("trusted energy console model", () => {
  it("keeps the complete 12-module checklist and reachable deep links", () => {
    expect(trustedModuleChecklist).toHaveLength(12);
    expect(trustedModuleChecklist.map((module) => module.key)).toEqual([
      "login", "workbench", "identity", "catalog", "asset", "apply", "contract", "ttc", "mpc", "results", "audit", "agent",
    ]);
    expect(trustedViewRoutes).toHaveLength(11);
    expect(trustedViewRoutes.some((route) => route.path === `${TRUSTED_BASE}/authorizations`)).toBe(true);
    for (const route of trustedViewRoutes) {
      expect(route.path.startsWith(`${TRUSTED_BASE}/`)).toBe(true);
      expect(route.label.length).toBeGreaterThan(1);
    }
    expect(routeForView("asset", "asset-power-output-001")).toBe(`${TRUSTED_BASE}/assets/asset-power-output-001`);
    expect(navItems).toEqual(expect.arrayContaining([expect.objectContaining({ key: "upload", menuCode: "excel-upload", label: "数据上传" })]));
    expect(routeForView("upload")).toBe(`${TRUSTED_BASE}/upload`);
    expect(getTrustedView(`${TRUSTED_BASE}/upload`)).toBe("upload");
    expect(isKnownTrustedPath(`${TRUSTED_BASE}/upload`)).toBe(true);
    expect(trustedMenuCodeForView("upload")).toBe("excel-upload");
    expect(routeForView("mpc", "com-20260518-001")).toBe(`${TRUSTED_BASE}/mpc/com-20260518-001`);
    expect(getTrustedView(`${TRUSTED_BASE}/results/res-20260518-001`)).toBe("results");
    expect(routeForView("contract")).toBe(`${TRUSTED_BASE}/contracts`);
    expect(routeForView("ttc")).toBe(`${TRUSTED_BASE}/ttc`);
    expect(routeForView("mpc")).toBe(`${TRUSTED_BASE}/mpc`);
    expect(trustedEntityId(`${TRUSTED_BASE}/assets/asset%2Freal`, "assets")).toBe("asset/real");
    expect(getTrustedView(`${TRUSTED_BASE}/contracts`)).toBe("contract");
    expect(getTrustedView(`${TRUSTED_BASE}/ttc/ttc-real`)).toBe("ttc");
    expect(isKnownTrustedPath(`${TRUSTED_BASE}/mpc`)).toBe(true);
    expect(isKnownTrustedPath(`${TRUSTED_BASE}/mpc/job-real`)).toBe(true);
    expect(isKnownTrustedPath(`${TRUSTED_BASE}/unknown`)).toBe(false);
    expect(trustedMenuCodeForView("asset")).toBe("asset-passport");
    expect(trustedMenuCodeForView("mpc")).toBe("compute");
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

  it("localizes user-facing codes while preserving machine identifiers", () => {
    expect(labelForCode("RENEWABLE_FORECAST")).toBe("新能源预测数据");
    expect(labelForCode("GENERATION_DATA")).toBe("发电计量数据");
    expect(labelForCode("DEMO")).toBe("演示能力");
    expect(labelForCode("LOCAL_REAL")).toBe("本地真实能力");
    expect(labelForCode("VerifiableCredential")).toBe("可验证凭证");
    expect(labelForCode("EnergyMarketParticipantCredential")).toBe("能源市场参与方凭证");
    expect(labelForCode("HCDS_CONNECTOR_1_0")).toBe("HCDS 1.0 连接器");
    expect(labelForCode("did:hiddenchain:org:org-generator-t01")).toBe("did:hiddenchain:org:org-generator-t01");
  });
});
