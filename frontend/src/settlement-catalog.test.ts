import { describe, expect, it } from "vitest";
import { catalogSettlementPeriod, findReadySettlementTemplate, findSettlementData, parseSettlementPeriod, settlementDateCount } from "./settlement-catalog";

const entry = (asset_type = "GENERATION_DATA", owner_org_id = "generator", period = "2026-11-01/2026-11-03") => ({ asset_type, owner_org_id, trade_batch_no: "NEW-BATCH", commitment_confirmed: true, quality: { validation_status: "PASSED", period } });

describe("settlement catalog periods", () => {
  it("accepts legacy month/day periods and leap days without local timezone drift", () => {
    expect(parseSettlementPeriod("2024-02")).toEqual({ periodStart: "2024-02-01", periodEnd: "2024-02-29" });
    expect(parseSettlementPeriod("2026-11-03")).toEqual({ periodStart: "2026-11-03", periodEnd: "2026-11-03" });
    expect(settlementDateCount("2024-01-01", "2024-12-31")).toBe(366);
  });
  it.each(["2026-02-29", "2026-11-04/2026-11-03", "2026-11-03/2026-11-04/2026-11-05", "2026-13", ""])("rejects invalid period %s", (period) => {
    expect(parseSettlementPeriod(period)).toBeNull();
  });
  it("rejects contradictory explicit period fields", () => {
    expect(catalogSettlementPeriod({ ...entry(), period_start: "2026-11-01", period_end: "2026-11-02" })).toBeNull();
    expect(catalogSettlementPeriod({ quality: { period_start: "2026-11-01", period_end: "2026-11-03" } })).toEqual({ periodStart: "2026-11-01", periodEnd: "2026-11-03" });
  });
  it("keeps legacy period matching when the API sends null explicit dates", () => {
    const legacy = { ...entry(), quality: { ...entry().quality, period_start: null, period_end: null } };
    expect(catalogSettlementPeriod(legacy)).toEqual({ periodStart: "2026-11-01", periodEnd: "2026-11-03" });
    expect(findSettlementData([legacy], "GENERATION_DATA", "generator", "NEW-BATCH", "2026-11-01", "2026-11-03")).toBe(legacy);
    expect(catalogSettlementPeriod({ quality: { period: "2026-11", period_start: "2026-11-01", period_end: null } })).toBeNull();
  });
  it("requires the selected party, exact batch and exact period", () => {
    const rows = [entry()];
    expect(findSettlementData(rows, "GENERATION_DATA", "generator", " NEW-BATCH ", "2026-11-01", "2026-11-03")).toBe(rows[0]);
    expect(findSettlementData(rows, "GENERATION_DATA", "other", "NEW-BATCH", "2026-11-01", "2026-11-03")).toBeUndefined();
    expect(findSettlementData(rows, "GENERATION_DATA", "generator", "NEW-BATCH", "2026-11-01", "2026-11-04")).toBeUndefined();
  });
  it("uses a matching active-party pair, without hiding a newer unconfirmed version", () => {
    const rows = [entry(), entry("RETAIL_DATA", "retailer")];
    expect(findReadySettlementTemplate(rows, ["generator"], ["retailer"])).toEqual({ generatorId: "generator", retailerId: "retailer", batch: "NEW-BATCH", periodStart: "2026-11-01", periodEnd: "2026-11-03" });
    expect(findReadySettlementTemplate([{ ...rows[0], commitment_confirmed: false }, ...rows], ["generator"], ["retailer"])).toBeNull();
    expect(findReadySettlementTemplate(rows, ["another-generator"], ["retailer"])).toBeNull();
  });
});
