import { afterEach, describe, expect, it, vi } from "vitest";
import { invalidateApiCache } from "../../api";
import { canRunSettlementTask, decideAuditReport, resolveAuditAnomaly, runSettlementTask } from "./workflow-api";

afterEach(() => { invalidateApiCache(); vi.unstubAllGlobals(); });

function runtime() {
  vi.stubGlobal("sessionStorage", { getItem: () => "test-token" });
  vi.stubGlobal("window", { setTimeout, clearTimeout, dispatchEvent: vi.fn() });
  const fetch = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("existing workflow command contracts", () => {
  const ready = { task_id: "task/1", task_name: "结算任务", status: "READY", state_version: 7, allowed_actions: ["RUN_SETTLEMENT"], readiness: { preflight_passed: true } };

  it("only enables an explicitly authorized, ready exchange run or retry", () => {
    expect(canRunSettlementTask("EXCHANGE", ready)).toBe(true);
    expect(canRunSettlementTask("EXCHANGE", { ...ready, status: "EXCEPTION", allowed_actions: ["RETRY_SETTLEMENT"] })).toBe(true);
    expect(canRunSettlementTask("GENERATOR", ready)).toBe(false);
    expect(canRunSettlementTask("REGULATOR", ready)).toBe(false);
    expect(canRunSettlementTask("EXCHANGE", { ...ready, allowed_actions: [] })).toBe(false);
    expect(canRunSettlementTask("EXCHANGE", { ...ready, readiness: { preflight_passed: false } })).toBe(false);
    expect(canRunSettlementTask("EXCHANGE", { ...ready, ttc: { state: "CANCELLED" } })).toBe(false);
  });

  it("runs the selected task with the frozen version and same command key on retry", async () => {
    const fetch = runtime();
    await runSettlementTask(ready.task_id, { ifMatch: '"7"', idempotencyKey: "run-task:retry" });
    await runSettlementTask(ready.task_id, { ifMatch: '"7"', idempotencyKey: "run-task:retry" });
    expect(fetch).toHaveBeenCalledTimes(2);
    for (const [url, init] of fetch.mock.calls as unknown as Array<[string, RequestInit]>) {
      expect(url).toBe("/api/settlement/tasks/task%2F1/run");
      expect(new Headers(init.headers).get("If-Match")).toBe('"7"');
      expect(new Headers(init.headers).get("Idempotency-Key")).toBe("run-task:retry");
      expect(JSON.parse(String(init.body))).toEqual({ compute_mode: "LOCAL_CONTROLLED", algorithm_code: "CONTROLLED_SETTLEMENT_V1" });
    }
  });

  it("submits the selected report decision and opinion without changing its target", async () => {
    const fetch = runtime();
    await decideAuditReport("report/1", "REJECT", "签名需要重新核验", { idempotencyKey: "report:1" });
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/audit/reports/report%2F1/decision");
    expect(JSON.parse(String(init.body))).toEqual({ decision: "REJECT", opinion: "签名需要重新核验" });
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("report:1");
  });

  it("closes or returns an anomaly for rework using its own version", async () => {
    const fetch = runtime();
    await resolveAuditAnomaly("event/1", { resolution: "复核后退回重算", disposition: "REWORK" }, 4, { idempotencyKey: "anomaly:1" });
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/anomalies/event%2F1/resolve");
    expect(JSON.parse(String(init.body))).toEqual({ resolution: "复核后退回重算", disposition: "REWORK" });
    expect(new Headers(init.headers).get("If-Match")).toBe('"4"');
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("anomaly:1");
  });
});
