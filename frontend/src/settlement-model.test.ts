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

  it("uses the backend-authoritative action before the legacy status fallback", () => {
    const action = taskNextAction({
      ...pendingTask,
      next_action: {
        code: "WAIT_FOR_AUDIT",
        label: "等待审计闸门",
        blocked: true,
        reasons: ["存在一项待复核风险"],
      },
    }, "GENERATOR", "gen-1");

    expect(action).toMatchObject({
      code: "WAIT_FOR_AUDIT",
      label: "等待审计闸门",
      blocker: "存在一项待复核风险",
      blocked: true,
      authoritative: true,
    });
  });

  it("renders persisted TTC transitions as the authoritative trusted chain", () => {
    const chain = trustedChain({
      ...pendingTask,
      ttc: {
        capsule_id: "capsule-1",
        state: "RULE_FROZEN",
        state_version: 3,
        current_attempt: 1,
        execution_snapshot_id: "snapshot-1",
        execution_snapshot_hash: "snapshot-hash",
        authoritative: true,
      },
      trusted_chain: [
        {
          attempt_id: "attempt-1",
          attempt_no: 1,
          sequence_no: 1,
          from_state: "INIT",
          to_state: "IDENTITY_VERIFIED",
          trigger_code: "VERIFY_IDENTITY",
          transition_hash: "identity-transition-hash",
          occurred_at: "2026-08-20T08:00:00Z",
        },
        {
          attempt_id: "attempt-1",
          attempt_no: 1,
          sequence_no: 3,
          from_state: "DATA_AUTHORIZED",
          to_state: "RULE_FROZEN",
          trigger_code: "FREEZE_RULE",
          transition_hash: "freeze-transition-hash",
          occurred_at: "2026-08-20T08:02:00Z",
        },
        {
          attempt_id: "attempt-1",
          attempt_no: 1,
          sequence_no: 2,
          from_state: "IDENTITY_VERIFIED",
          to_state: "DATA_AUTHORIZED",
          trigger_code: "AUTHORIZE_DATA",
          transition_hash: "authorization-transition-hash",
          occurred_at: "2026-08-20T08:01:00Z",
        },
      ],
    });

    expect(chain.map((item) => item.title)).toEqual(["身份验证通过", "数据授权通过", "规则与执行快照冻结"]);
    expect(chain.map((item) => item.state)).toEqual(["complete", "complete", "current"]);
    expect(chain.at(-1)).toMatchObject({
      code: "RULE_FROZEN:attempt-1:1:3:freeze-transition-hash",
      completedAt: "2026-08-20T08:02:00Z",
      evidenceCount: 1,
      abnormal: false,
    });
  });

  it("orders retry transitions by attempt and creates unique chain keys", () => {
    const chain = trustedChain({
      ...pendingTask,
      ttc: { state: "REWORK", authoritative: true },
      trusted_chain: [
        {
          attempt_id: "attempt-2",
          attempt_no: 2,
          sequence_no: 1,
          from_state: "REWORK",
          to_state: "RULE_FROZEN",
          trigger_code: "FREEZE_RETRY",
          transition_hash: "retry-freeze-hash",
          occurred_at: "2026-08-20T09:00:00Z",
        },
        {
          attempt_id: "attempt-1",
          attempt_no: 1,
          sequence_no: 2,
          from_state: "IDENTITY_VERIFIED",
          to_state: "FAILED",
          trigger_code: "COMPUTE_FAILED",
          transition_hash: "failed-hash",
          occurred_at: "2026-08-20T08:01:00Z",
        },
        {
          attempt_id: "attempt-1",
          attempt_no: 1,
          sequence_no: 1,
          from_state: "INIT",
          to_state: "IDENTITY_VERIFIED",
          trigger_code: "VERIFY_IDENTITY",
          transition_hash: "identity-hash",
          occurred_at: "2026-08-20T08:00:00Z",
        },
      ],
    }, { viewerRole: "GENERATOR" });

    expect(chain.map((item) => item.code)).toEqual([
      "IDENTITY_VERIFIED:attempt-1:1:1:identity-hash",
      "FAILED:attempt-1:1:2:failed-hash",
      "RULE_FROZEN:attempt-2:2:1:retry-freeze-hash",
    ]);
    expect(new Set(chain.map((item) => item.code)).size).toBe(chain.length);
    expect(chain[0].path).toBe("/settlements/task-1");
    expect(chain[2].path).toBe("/settlements/task-1");
  });

  it.each(["FAILED", "REJECTED", "INTERRUPTED", "REWORK", "HUMAN_REVIEW", "ANCHOR_RETRY", "CANCELLED", "EXPIRED"])(
    "places TTC abnormal state %s in the exception tab",
    (state) => {
      expect(taskTabFor({ ...pendingTask, status: "READY", ttc: { state } }, "EXCHANGE", "exchange-1")).toBe("exception");
    },
  );

  it("keeps restricted transition targets on an accessible task path", () => {
    const transition = (toState: string) => ({
      attempt_id: "attempt-1",
      attempt_no: 1,
      sequence_no: 1,
      from_state: "INIT",
      to_state: toState,
      trigger_code: "TEST",
      transition_hash: `${toState}-hash`,
      occurred_at: "2026-08-20T08:00:00Z",
    });
    const participantPath = (state: string) => trustedChain(
      { ...pendingTask, trusted_chain: [transition(state)] },
      { viewerRole: "GENERATOR" },
    )[0].path;

    expect(participantPath("IDENTITY_VERIFIED")).toBe("/settlements/task-1");
    expect(participantPath("RULE_FROZEN")).toBe("/settlements/task-1");
    expect(participantPath("AUDIT_GATE")).toBe("/settlements/task-1");
    expect(trustedChain(
      { ...pendingTask, trusted_chain: [transition("RULE_FROZEN")] },
      { viewerRole: "REGULATOR" },
    )[0].path).toBe("/rules?task_id=task-1");
  });
});
