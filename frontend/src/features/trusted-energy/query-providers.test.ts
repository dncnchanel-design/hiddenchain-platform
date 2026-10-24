import { describe, expect, it } from "vitest";
import type { CatalogAsset, QueryIntent, UsageRequest } from "./trusted-space-api";
import { queryProviders } from "./query-providers";

const intent = { resource: "load", function: "average", start_date: "2026-09-01", end_date: "2026-09-30" } as QueryIntent;
const asset = (id: string, allowed = true, period?: [string, string]): CatalogAsset => ({
  asset_id: id, asset_code: id, asset_name: "用电负荷", asset_type: "CONNECTOR_RESOURCE", classification: "ENERGY_BUSINESS_DATA", sensitivity_level: "L2", status: "ACTIVE", metadata: { resource_id: "load" },
  provider: { org_id: "retailer" }, source: { status: "ACTIVE", capability_label: "LOCAL_REAL" },
  actions: { can_request_usage: allowed, can_review_inbound: false, can_view_passport: true },
  latest_version: { version_id: id + "-v2", version_no: 2, schema_version: "v2", data_hash: "test-hash", status: "ACTIVE", period_start: period?.[0], period_end: period?.[1] },
});

describe("query source selection after a connector upload", () => {
  it("skips an own asset whose application page cannot be used", () => {
    expect(queryProviders([asset("own", false), asset("retailer")], intent, [], "exchange").map(item => item.asset_id)).toEqual(["retailer"]);
  });
  it("offers own data only with the server-provided compute action and matching owner", () => {
    const own = asset("own", false, ["2021-01-01", "2026-09-30"]);
    own.actions.can_compute_own = true;
    expect(queryProviders([own], intent, [], "retailer")).toEqual([own]);
    expect(queryProviders([own], intent, [], "exchange")).toEqual([]);
    own.source.status = "DISABLED";
    expect(queryProviders([own], intent, [], "retailer")).toEqual([]);
  });
  it("prefers known historical coverage to an uploaded series without date metadata", () => {
    expect(queryProviders([asset("upload"), asset("historical", true, ["2021-01-01", "2026-09-30"])], intent, [], "exchange")[0].asset_id).toBe("historical");
  });
  it("never offers a source whose declared data period excludes the query", () => {
    expect(queryProviders([asset("august", true, ["2026-08-01", "2026-08-31"])], intent, [], "exchange")).toEqual([]);
  });
  it("prefers an already approved matching version to a new application", () => {
    const granted = asset("granted");
    const grant = { request_id: "grant", status: "APPROVED", expires_at: "2099-01-01T00:00:00Z", asset: { asset_id: granted.asset_id, version_id: granted.latest_version!.version_id }, provider: { org_id: "retailer" }, applicant: { org_id: "exchange" }, requested_scope: {}, requested_fields: [] } as unknown as UsageRequest;
    expect(queryProviders([asset("historical", true, ["2021-01-01", "2026-09-30"]), granted], intent, [grant], "exchange")[0].asset_id).toBe("granted");
  });
});
