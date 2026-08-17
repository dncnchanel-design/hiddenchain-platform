import { describe, expect, it } from "vitest";
import { taskNextAction, taskTabFor, trustedChain } from "./settlement-model";

const pendingTask = {
  task_id: "task-1",
  status: "PENDING_CONFIRMATION",
  participants: [{ org_id: "gen-1" }, { org_id: "ret-1" }],
  readiness: { preflight_passed: true, ready_data_count: 2, required_data_count: 2 },
  rule: { status: "ACTIVE", rule_version: "v1" },
  authorization_summary: { authorized_count: 2 },
  compute_summary: { status: "SUCCESS", adapter_code: "LOCAL_CONTROLLED_SETTLEMENT_V1" },
  confirmation_summary: { required_count: 2, confirmed_count: 1, remaining_count: 1, confirmed_org_ids: ["ret-1"] },
};

describe("settlement business state", () => {
  it("maps a participant's real confirmation responsibility", () => {
    expect(taskTabFor(pendingTask, "GENERATOR", "gen-1")).toBe("todo");
    expect(taskNextAction(pendingTask, "GENERATOR", "gen-1").label).toBe("确认本方结果");
    expect(taskNextAction(pendingTask, "RETAILER", "ret-1").label).toBe("等待其余主体确认");
  });

  it("keeps an unverified boundary visible in the task rather than inventing completion", () => {
    const chain = trustedChain(pendingTask, {
      results: [{ result_id: "result-1", created_at: "2026-08-17T08:00:00Z" }],
      evidence: [{ evidence_id: "evidence-1", biz_type: "SETTLEMENT_RESULT", created_at: "2026-08-17T08:01:00Z" }],
    });
    expect(chain.find((item) => item.code === "COMPUTE")?.state).toBe("complete");
    expect(chain.find((item) => item.code === "COMPUTE")?.detail).toBe("本地受控结算 · 已完成");
    expect(chain.find((item) => item.code === "CONFIRM")?.state).toBe("current");
    expect(chain.find((item) => item.code === "ARCHIVE")?.state).toBe("pending");
  });
});
