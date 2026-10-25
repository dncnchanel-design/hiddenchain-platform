import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { AssistantPlanView } from "./components/AssistantPlanView";
import type { AssistantPlan, AssistantPlanStep } from "./trusted-space-api";
import agentSource from "./components/AgentSheet.tsx?raw";
import layoutSource from "../../components/layout.tsx?raw";

const baseStep: AssistantPlanStep = { step_id: "step", plan_id: "plan", sequence_no: 1, action_code: "LIST_DATA_ASSETS", mode: "READ", status: "SUCCEEDED", state_version: 2, capability_state: "LOCAL_REAL_DETERMINISTIC", source_of_truth: "catalog", allowed_actions: [], output: {} };
function render(overrides: Partial<AssistantPlan> = {}, step: Partial<AssistantPlanStep> = {}, options: { busy?: boolean; onOpenElectricity?: (question: string) => void } = {}) {
  const plan: AssistantPlan = { plan_id: "plan", session_id: "session", intent_code: "LIST_DATA_ASSETS", status: "SUCCEEDED", state_version: 2, capability_state: "LOCAL_REAL_DETERMINISTIC", source_of_truth: "catalog", allowed_actions: [], steps: [{ ...baseStep, ...step }], ...overrides };
  return renderToStaticMarkup(<MemoryRouter><AssistantPlanView plan={plan} busy={options.busy || false} onAction={vi.fn()} onNavigate={vi.fn()} onSuggest={vi.fn()} onOpenElectricity={options.onOpenElectricity} /></MemoryRouter>);
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
  expect(markup).toContain("你能做什么");
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

it("renders verified query receipts with the actual computation destination", () => {
  const markup = render({ intent_code: "VERIFY_EVIDENCE_SUMMARY" }, { action_code: "VERIFY_EVIDENCE_SUMMARY", output: { task_id: "query-1", job_id: "job-1", evidence_kind: "EXECUTION_RECEIPT", verification_status: "MATCHED", items: [{ receipt_id: "receipt-1", verify: { matched: true } }] } });
  expect(markup).toContain("执行回执 1 条");
  expect(markup).toContain("1 条一致");
  expect(markup).toContain("查看关联计算任务");
  expect(markup).toContain("/trusted-space/mpc/job-1");
  expect(markup).not.toContain("/trusted-space/ttc/query-1");
  expect(markup).not.toContain("EXECUTION_RECEIPT");
});

it("keeps missing query receipts unverified after a successful metadata read", () => {
  const markup = render({ intent_code: "VERIFY_EVIDENCE_SUMMARY" }, { action_code: "VERIFY_EVIDENCE_SUMMARY", output: { task_id: "query-1", job_id: "job-1", evidence_kind: "EXECUTION_RECEIPT", verification_status: "UNVERIFIED", items: [] } });
  expect(markup).toContain("存在待处理项");
  expect(markup).toContain("待核验");
  expect(markup).not.toContain("核验一致");
});

it("shows the real receipt count and zero formal reports in query audit explanations", () => {
  const markup = render({ intent_code: "EXPLAIN_AUDIT" }, { action_code: "EXPLAIN_AUDIT", output: { job_id: "job-1", task_id: "query-1", report_count: 0, receipt_count: 2, explanation: "当前依据审计链与执行回执说明，无正式报告。" } });
  expect(markup).toContain("执行回执数");
  expect(markup).toContain("<dd>2</dd>");
  expect(markup).toContain("审计报告数");
  expect(markup).toContain("<dd>0</dd>");
  expect(markup).toContain("无正式报告");
  expect(markup).not.toContain("receipt_count");
});

it("shows the durable manual-review receipt and prevents repeated submission", () => {
  const markup = render({ intent_code: "APPROVE_USAGE_REQUEST", status: "PENDING_REVIEW", allowed_actions: ["execute", "cancel"] }, { action_code: "APPROVE_USAGE_REQUEST", mode: "WRITE", status: "PENDING_REVIEW", request_id: "assistant-review-real", output: { review_requested: true, request_id: "assistant-review-real", business_mutation: false } });
  expect(markup).toContain("复核请求已记录");
  expect(markup).toContain("assistant-review-real");
  expect(markup).not.toContain("提交审批草案");
});

it("offers numbered candidates for missing input and keeps them disabled while a message is pending", () => {
  const markup = render({ intent_code: "CHECK_TTC_STATUS", status: "NEEDS_INPUT", plan: { candidates: [
    { entity_id: "job-1", entity_type: "privacy_compute_job", label: "八月负荷计算", status: "SUCCESS" },
    { entity_id: "task-2", entity_type: "settlement_task", label: "九月电力结算", status: "PENDING" },
  ] }, allowed_actions: ["cancel"] }, { action_code: "CHECK_TTC_STATUS", mode: "NEEDS_INPUT", status: "NEEDS_INPUT" }, { busy: true });
  expect(markup).toContain("待选择");
  expect(markup).toContain("八月负荷计算");
  expect(markup).toContain("九月电力结算");
  expect(markup).toContain("选择第1个");
  expect(markup).toContain("选择第2个");
  expect(markup).toContain("disabled");
  expect(markup).not.toContain("执行查询");
  expect(markup).not.toContain("privacy_compute_job");
});

it.each([
  ["LIST_VISIBLE_DATA_ASSETS", "data_asset", "/trusted-space/assets/asset-load", "售电企业负荷"],
  ["LIST_AUTHORIZED_DATA_ASSETS", "data_asset", "/trusted-space/authorizations?request=request-1", "已授权负荷"],
  ["LIST_AUTHORIZATIONS", "data_usage_request", "/trusted-space/authorizations?request=request-1", "用能分析申请"],
  ["LIST_TASKS", "privacy_compute_job", "/trusted-space/mpc/job-1", "八月负荷计算"],
  ["LIST_AUDIT_REPORTS", "audit_report", "/trusted-space/audit?view=reports&report_id=report-1", "结算审计报告"],
  ["LIST_NOTIFICATIONS", "notification", "/trusted-space/workbench", "授权已批准"],
])("renders readable scoped %s items and their actual destinations", (action, entityType, href, label) => {
  const markup = render({ intent_code: action }, { action_code: action, output: { total: 1, items: [{ entity_id: "item-1", entity_type: entityType, label, status: "ACTIVE", href }], raw_data_accessed: false } });
  expect(markup).toContain(label);
  expect(markup).toContain(href.replaceAll("&", "&amp;"));
  expect(markup).not.toContain("raw_data_accessed");
  expect(markup).not.toContain("entity_type");
});

it("preserves authorized asset metadata, immutable version and remaining uses", () => {
  const markup = render({ intent_code: "LIST_AUTHORIZED_DATA_ASSETS" }, { action_code: "LIST_AUTHORIZED_DATA_ASSETS", output: { total: 1, items: [{ entity_id: "asset-load", entity_type: "data_asset", label: "负荷数据 · 第 2 版", status: "ACTIVE", href: "/trusted-space/assets/asset-load", asset_type: "ELECTRICITY_METRIC", record_count: 8396, version_no: 2, period_start: "2021-01-01", period_end: "2026-09-30", remaining_uses: 0 }] } });
  expect(markup).toContain("8,396 条记录");
  expect(markup).toContain("第 2 版");
  expect(markup).toContain("剩余 0 次");
  expect(markup).toContain("2021-01-01 至 2026-09-30");
});

it("turns role-scoped help prompts into buttons, including operations help", () => {
  const markup = render({ intent_code: "ASSISTANT_HELP" }, { action_code: "ASSISTANT_HELP", output: { help_actions: [{ label: "查看平台技术状态", prompt: "系统运行情况" }], raw_data_accessed: false } });
  expect(markup).toContain("查看平台技术状态");
  expect(markup).toContain("<button");
  expect(markup).not.toContain("查询我的数据");
  expect(markup).not.toContain("help_actions");
});

it("shows only known technical fields and real aggregate counts for operations", () => {
  const markup = render({ intent_code: "SYSTEM_OVERVIEW" }, { action_code: "SYSTEM_OVERVIEW", output: {
    overview: { service_health: { api: "READY", database: "READY", environment: "DEMO", password: "never-render" }, counts: { organizations_total: 13, users_active: 0 } },
    system: { identity_counts: { agents: 7 }, node_counts: { health_confirmed: 7 }, secret: "never-render" },
    agents: { service_health: { explanation_service: "CONFIG_REQUIRED", credential_configured: false, model: "configured-model", secret: "never-render" } },
    raw_data_accessed: false,
  } });
  expect(markup).toContain("API 服务");
  expect(markup).toContain("数据库");
  expect(markup).toContain("组织总数");
  expect(markup).toContain("13");
  expect(markup).toContain("活跃账号数");
  expect(markup).toContain("<dd>0</dd>");
  expect(markup).toContain("节点健康已确认数");
  expect(markup).toContain("configured-model");
  expect(markup).not.toContain("never-render");
  expect(markup).not.toContain("raw_data_accessed");
});

it("opens the known query page with the question encoded as a draft", () => {
  const markup = render({ intent_code: "NAVIGATE_QUERY" }, { action_code: "NAVIGATE_QUERY", output: { navigation: { path: "/trusted-space/query?ignored=1", question: "计算负荷 & 核对" } } });
  expect(markup).toContain("打开智能数据查询");
  expect(markup).toContain("/trusted-space/query?question=");
  expect(markup).toContain(encodeURIComponent("计算负荷"));
  expect(markup).not.toContain("ignored=1");
  expect(markup).not.toContain("执行查询");
});

it.each(["https://example.com/trusted-space/query", "//example.com/trusted-space/query", "javascript:alert(1)", "/unknown", "/trusted-space/\\example.com", "/trusted-space/assets/%E0%A4%A"])("does not link an untrusted or unknown assistant destination %s", (path) => {
  const markup = render({ intent_code: "NAVIGATE_QUERY" }, { action_code: "NAVIGATE_QUERY", output: { navigation: { path, question: "测试" } } });
  expect(markup).not.toContain("href=");
});

it("offers electricity handoff only when the hosting shell supports it", () => {
  const plan = { intent_code: "NAVIGATE_ELECTRICITY" };
  const step = { action_code: "NAVIGATE_ELECTRICITY", output: { navigation: { path: "#electricity", question: "报价计算" } } };
  expect(render(plan, step, { onOpenElectricity: vi.fn() })).toContain("打开电力交易计算");
  expect(render(plan, step)).not.toContain("打开电力交易计算");
  expect(render(plan, step)).not.toContain('href="#electricity"');
});

it("keeps original candidate ordinals when an incomplete entry cannot be offered", () => {
  const markup = render({ status: "NEEDS_INPUT", plan: { candidates: [null, { entity_id: "asset-load", entity_type: "data_asset", label: "负荷数据", status: "ACTIVE" }] } }, { mode: "NEEDS_INPUT", status: "NEEDS_INPUT" });
  expect(markup).toContain("选择第2个");
  expect(markup).not.toContain("选择第1个");
});

it("keeps readable notification status while refusing a link outside known internal routes", () => {
  const markup = render({ intent_code: "LIST_NOTIFICATIONS" }, { action_code: "LIST_NOTIFICATIONS", output: { total: 1, items: [{ entity_id: "notice-1", entity_type: "notification", label: "授权审批待办", status: "UNREAD", href: "https://example.com/notice" }] } });
  expect(markup).toContain("授权审批待办");
  expect(markup).toContain("未读");
  expect(markup).not.toContain("example.com");
});

it("loads the operations assistant only after an administrator opens it and excludes electricity", () => {
  expect(layoutSource).toContain('const AgentSheet = lazy(() => import(');
  expect(layoutSource).toContain('session.user.role_code === "ADMIN" && agentMounted');
  expect(layoutSource).toContain('mode="business" onModeChange={() => {}} operationsOnly');
  expect(agentSource).toContain('mode === "electricity" && !operationsOnly');
  expect(agentSource).toContain('onOpenElectricity={operationsOnly ? undefined');
  expect(agentSource).toContain('!operationsOnly && <Button');
});
