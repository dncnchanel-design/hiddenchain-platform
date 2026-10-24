import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { AssistantPlanView } from "./components/AssistantPlanView";
import type { AssistantPlan, AssistantPlanStep } from "./trusted-space-api";

const baseStep: AssistantPlanStep = { step_id: "step", plan_id: "plan", sequence_no: 1, action_code: "LIST_DATA_ASSETS", mode: "READ", status: "SUCCEEDED", state_version: 2, capability_state: "LOCAL_REAL_DETERMINISTIC", source_of_truth: "catalog", allowed_actions: [], output: {} };
function render(overrides: Partial<AssistantPlan> = {}, step: Partial<AssistantPlanStep> = {}) {
  const plan: AssistantPlan = { plan_id: "plan", session_id: "session", intent_code: "LIST_DATA_ASSETS", status: "SUCCEEDED", state_version: 2, capability_state: "LOCAL_REAL_DETERMINISTIC", source_of_truth: "catalog", allowed_actions: [], steps: [{ ...baseStep, ...step }], ...overrides };
  return renderToStaticMarkup(<MemoryRouter><AssistantPlanView plan={plan} busy={false} onAction={vi.fn()} onNavigate={vi.fn()} onSuggest={vi.fn()} /></MemoryRouter>);
}

it("shows personal data names, count, period and a scoped detail link without a JSON dump", () => {
  const markup = render({}, { output: { total: 1, items: [{ asset_id: "asset-load", asset_name: "本方用电负荷", asset_type: "ELECTRICITY_METRIC", record_count: 8396, period_start: "2021-01-01", period_end: "2026-09-30" }], raw_data_accessed: false } });
  expect(markup).toContain("本方用电负荷");
  expect(markup).toContain("8,396 条记录");
  expect(markup).toContain("2021-01-01 至 2026-09-30");
  expect(markup).toContain('/trusted-space/assets/asset-load');
  expect(markup).not.toContain("raw_data_accessed");
});

it("shows an honest empty catalog and a next step", () => {
  const markup = render({}, { output: { total: 0, items: [] } });
  expect(markup).toContain("当前账号尚未登记本方数据");
  expect(markup).toContain("打开数据目录");
  expect(markup).not.toContain("已阻断");
});

it("asks for a task selection instead of presenting missing input as a system failure", () => {
  const markup = render({ intent_code: "CHECK_TTC_STATUS", status: "BLOCKED", allowed_actions: ["cancel"] }, { action_code: "CHECK_TTC_STATUS", status: "BLOCKED", mode: "BLOCKED", error_code: "ASSISTANT_TARGET_REQUIRED" });
  expect(markup).toContain("待选择");
  expect(markup).toContain('/trusted-space/mpc');
  expect(markup).not.toContain("已阻断");
  expect(markup).not.toContain("执行查询");
});

it("does not offer execute or retry for a legacy unsupported plan", () => {
  const markup = render({ intent_code: "UNKNOWN_INTENT", status: "BLOCKED", allowed_actions: ["execute", "cancel", "retry"] }, { status: "BLOCKED", output: { error_code: "UNKNOWN_ASSISTANT_ACTION" } });
  expect(markup).toContain("查询我的数据");
  expect(markup).not.toContain("重试查询");
  expect(markup).not.toContain("执行查询");
  expect(markup).not.toContain("UNKNOWN_ASSISTANT_ACTION");
});

it("preserves a real permission denial", () => {
  const markup = render({ intent_code: "VERIFY_EVIDENCE_SUMMARY", status: "BLOCKED", plan: { explanation: "当前角色没有执行该指令的权限。" }, allowed_actions: ["cancel"] }, { status: "BLOCKED", error_code: "ASSISTANT_ROLE_DENIED" });
  expect(markup).toContain("已阻断");
  expect(markup).toContain("当前角色没有执行该指令的权限");
  expect(markup).not.toContain("执行查询");
});

it("keeps write intents as a manual review action", () => {
  const markup = render({ intent_code: "APPROVE_USAGE_REQUEST", status: "PENDING_REVIEW", allowed_actions: ["execute"] }, { action_code: "APPROVE_USAGE_REQUEST", mode: "WRITE", status: "PENDING_REVIEW" });
  expect(markup).toContain("提交审批草案");
  expect(markup).not.toContain("执行查询");
});

it("discloses when there are more catalog items", () => {
  const markup = render({}, { output: { total: 100, items: [], has_more: true } });
  expect(markup).toContain("打开数据目录继续查看");
});

it("discloses failed evidence checks even when the metadata query succeeded", () => {
  const markup = render({ intent_code: "VERIFY_EVIDENCE_SUMMARY" }, { action_code: "VERIFY_EVIDENCE_SUMMARY", output: { task_id: "task-real", items: [{ verify: { matched: true } }, { verify: { matched: false } }, {}] } });
  expect(markup).toContain("1 条一致、1 条不一致、1 条待核验");
  expect(markup).toContain("存在待处理项");
  expect(markup).toContain('/trusted-space/ttc/task-real');
});

it("preserves missing integrity records and a failed quality decision", () => {
  const markup = render({ intent_code: "CHECK_ASSET_INTEGRITY" }, { action_code: "CHECK_ASSET_INTEGRITY", output: { asset_id: "asset-real", integrity: { version_present: true, passport_present: false, quality_present: true, raw_data_accessed: false }, quality: { decision: "REJECTED" } } });
  expect(markup).toContain("资产护照");
  expect(markup).toContain("未登记");
  expect(markup).toContain("质量判定");
  expect(markup).toContain("已拒绝");
  expect(markup).toContain("存在待处理项");
});

it("shows the durable manual-review receipt and prevents repeated submission", () => {
  const markup = render({ intent_code: "APPROVE_USAGE_REQUEST", status: "PENDING_REVIEW", allowed_actions: ["execute", "cancel"] }, { action_code: "APPROVE_USAGE_REQUEST", mode: "WRITE", status: "PENDING_REVIEW", request_id: "assistant-review-real", output: { review_requested: true, request_id: "assistant-review-real", business_mutation: false } });
  expect(markup).toContain("复核请求已记录");
  expect(markup).toContain("assistant-review-real");
  expect(markup).not.toContain("提交审批草案");
});
