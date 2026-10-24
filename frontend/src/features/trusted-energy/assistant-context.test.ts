import { describe, expect, it } from "vitest";
import { assistantContext, assistantContextKey } from "./assistant-context";

describe("assistant page context", () => {
  it("preserves each business identifier's actual type", () => {
    expect(assistantContext("/trusted-space/mpc/job-1")).toMatchObject({ entity_type: "privacy_compute_job", entity_id: "job-1" });
    expect(assistantContext("/trusted-space/assets/asset-1")).toMatchObject({ entity_type: "data_asset", entity_id: "asset-1" });
    expect(assistantContext("/trusted-space/mpc/new").entity_id).toBeUndefined();
  });
  it("reads the selected authorization and report from their real query links", () => {
    expect(assistantContext("/trusted-space/authorizations", "?request=request-1&view=outbound")).toMatchObject({ entity_type: "data_usage_request", entity_id: "request-1" });
    expect(assistantContext("/trusted-space/audit", "?view=reports&report_id=report-1")).toMatchObject({ entity_type: "audit_report", entity_id: "report-1" });
    expect(assistantContext("/trusted-space/audit", "?view=anomalies&event_id=event-1")).toMatchObject({ entity_type: "anomaly_event", entity_id: "event-1" });
    expect(assistantContext("/trusted-space/audit/tasks/task-1")).toMatchObject({ entity_type: "settlement_task", entity_id: "task-1" });
  });
  it("isolates sessions when a path or selected entity changes", () => {
    const asset = assistantContext("/trusted-space/assets/asset-1");
    const job = assistantContext("/trusted-space/mpc/job-1");
    const first = assistantContext("/trusted-space/authorizations", "?request=request-1");
    const second = assistantContext("/trusted-space/authorizations", "?request=request-2");
    expect(assistantContextKey(asset)).not.toBe(assistantContextKey(job));
    expect(assistantContextKey(first)).not.toBe(assistantContextKey(second));
    expect(assistantContextKey(first)).toBe(assistantContextKey({ ...first }));
  });
  it("keeps page-only and malformed contexts free of invented identifiers", () => {
    expect(assistantContext("/trusted-space/catalog").entity_id).toBeUndefined();
    expect(assistantContext("/trusted-space/assets/%E0%A4%A").entity_id).toBeUndefined();
    expect(assistantContext("/trusted-space/authorizations", "?request=").entity_id).toBeUndefined();
    expect(assistantContext("/trusted-space/catalog", "?q=" + "x".repeat(400)).page_path.length).toBeLessThanOrEqual(255);
  });
});
