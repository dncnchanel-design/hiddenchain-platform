import { afterEach, describe, expect, it, vi } from "vitest";
import { invalidateApiCache } from "../../api";
import { confirmResult, controlComputation, createAssistantSession, createUsageRequest, downloadAudit, loadAsset, loadAssistantMessages, loadAssistantPlans, loadAssistantTools, loadAudit, loadAuditTask, loadCatalog, loadComputation, loadComputationEvents, loadComputations, loadContract, loadContracts, loadNotifications, loadResult, loadResults, loadTtc, loadTtcEvents, loadTtcList, loadTrustedContext, loadTrustedHelp, loadUsageRequests, markAllNotificationsRead, markNotificationRead, postAssistantMessage, postContractAction, runAssistantPlanAction, transitionTtc, transitionUsageRequest, verifyEvidence } from "./trusted-space-api";
import { notificationPath, quickActionPath } from "./trusted-space-ui";

function stubRuntime() {
  vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => "test-token") });
  vi.stubGlobal("window", { setTimeout, clearTimeout, dispatchEvent: vi.fn() });
}

afterEach(() => {
  invalidateApiCache();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Trusted Space API client", () => {
  it("serializes catalog filters and pagination for the server-side read model", async () => {
    stubRuntime();
    let requestedUrl = "";
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request) => {
      requestedUrl = String(url);
      return new Response(JSON.stringify({ items: [], total: 0, page: 2, page_size: 12, empty_state: true }), { status: 200 });
    }));

    await loadCatalog({ query: "出力", assetType: "电力数据", domain: "发电侧", sensitivityLevel: "L4", page: 2, pageSize: 12 });

    expect(requestedUrl).toContain("/api/trust-space/catalog?");
    expect(requestedUrl).toContain("q=%E5%87%BA%E5%8A%9B");
    expect(requestedUrl).toContain("asset_type=%E7%94%B5%E5%8A%9B%E6%95%B0%E6%8D%AE");
    expect(requestedUrl).toContain("domain=%E5%8F%91%E7%94%B5%E4%BE%A7");
    expect(requestedUrl).toContain("sensitivity_level=L4");
    expect(requestedUrl).toContain("page=2");
    expect(requestedUrl).toContain("page_size=12");

    await loadAsset("asset/real");
    expect(requestedUrl).toContain("/api/trust-space/assets/asset%2Freal");
  });

  it("loads dynamic context without assuming a fixture actor", async () => {
    stubRuntime();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      actor: { user_id: "u-2", username: "reviewer", display_name: "审计员", role_code: "EXCHANGE", role_label: "交易中心验证员" },
      current_subject: { org_id: "org-exchange", org_name: "交易中心", status: "ACTIVE" },
      identity_ref: { did: null, credential_status: "NOT_CONFIGURED" },
      role_capabilities: { can_request_usage: false }, visible_menus: [], environment: { name: "TEST", fixture_seed: false }, capabilities: {},
    }), { status: 200 })));

    const value = await loadTrustedContext();

    expect(value.actor.role_code).toBe("EXCHANGE");
    expect(value.current_subject.org_id).toBe("org-exchange");
    expect(value.identity_ref.did).toBeNull();
  });

  it("keeps authorization inbox and applicant-owned lists distinct", async () => {
    stubRuntime();
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request) => {
      requests.push(String(url));
      return new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 12, empty_state: true }), { status: 200 });
    }));

    await loadUsageRequests({ inbox: true, page: 1, pageSize: 12 });
    await loadUsageRequests({ mine: true, page: 1, pageSize: 12 });

    expect(requests[0]).toContain("inbox=true");
    expect(requests[0]).not.toContain("mine=true");
    expect(requests[1]).toContain("mine=true");
    expect(requests[1]).not.toContain("inbox=true");
  });

  it("loads notifications/help/TTC list and maps only safe real entity routes", async () => {
    stubRuntime();
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const value = String(url);
      requests.push({ url: value, init });
      if (value.includes("/notifications/read-all")) return new Response(JSON.stringify({ updated_count: 2, unread_count: 0 }), { status: 200 });
      if (value.includes("/notifications/n-1/read")) return new Response(JSON.stringify({ notification_id: "n-1", read_at: "2026-08-21T10:00:00Z" }), { status: 200 });
      if (value.includes("/notifications?")) return new Response(JSON.stringify({ items: [{ notification_id: "n-1", user_id: "u-1", org_id: "org-1", notification_type: "DATA_USAGE_REQUEST", title: "申请", body: "待审", severity: "INFO", dedupe_key: "n-1", entity_type: "DATA_USAGE_REQUEST", entity_id: "dur-1", created_at: "2026-08-21T09:00:00Z", read_at: null }], total: 1, unread_count: 1, page: 1, page_size: 20, empty_state: false }), { status: 200 });
      if (value.includes("/help?")) return new Response(JSON.stringify({ view: "ttc", version: "20260821.004", title: "TTC 任务", summary: "真实状态机", entries: [], role_code: "EXCHANGE" }), { status: 200 });
      if (value.includes("/ttc?")) return new Response(JSON.stringify({ items: [{ task_id: "ttc-real", task_name: "真实任务", status: "RUNNING", ttc_state: "COMPUTE_EXEC", state_version: 3 }], total: 1, page: 2, page_size: 12, empty_state: false }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    const notifications = await loadNotifications();
    const notificationsPage = await loadNotifications({ page: 2, pageSize: 20 });
    const help = await loadTrustedHelp("ttc");
    const tasks = await loadTtcList({ page: 2, pageSize: 12, status: "RUNNING" });
    await markNotificationRead("n-1", { idempotencyKey: "notification-read:1" });
    await markAllNotificationsRead({ idempotencyKey: "notification-read-all:1" });

    expect(notifications.unread_count).toBe(1);
    expect(notificationsPage.page).toBe(1);
    expect(help.version).toBe("20260821.004");
    expect(tasks.items[0].task_id).toBe("ttc-real");
    expect(requests.some((item) => item.url.includes("/api/trust-space/ttc?page=2&page_size=12&status=RUNNING"))).toBe(true);
    expect(requests.some((item) => item.url.includes("/api/trust-space/notifications?page=2&page_size=20"))).toBe(true);
    expect(new Headers(requests.find((item) => item.url.includes("/notifications/n-1/read"))?.init?.headers).get("Idempotency-Key")).toBe("notification-read:1");
    expect(notificationPath({ entity_type: "DATA_USAGE_REQUEST", entity_id: "dur/1" })).toBe("/trusted-space/authorizations?request=dur%2F1");
    expect(notificationPath({ entity_type: "AUDIT_REPORT", entity_id: "report-1" })).toBeNull();
    expect(quickActionPath({ allowed: true, path: "/trusted-space/catalog" })).toBe("/trusted-space/catalog");
    expect(quickActionPath({ allowed: false, path: "/trusted-space/catalog" })).toBeNull();
  });

  it("serializes a real access request with idempotency and preserves 409/403 errors", async () => {
    stubRuntime();
    let requestInit: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      requestInit = init;
      return new Response(JSON.stringify({ request_id: "dur-1", status: "SUBMITTED", state_version: 1 }), { status: 201 });
    }));
    const result = await createUsageRequest({
      asset_id: "asset-1", asset_version_id: "version-1", purpose: "SETTLEMENT_ANALYSIS", usage_mode: "MPC_AGGREGATE",
      requested_scope: { raw_data_export: false }, requested_fields: ["summary"], duration_days: 30, terms: { accepted: true },
    }, { idempotencyKey: "usage-request:test-1" });
    const headers = new Headers(requestInit?.headers);
    expect(result).toMatchObject({ request_id: "dur-1", status: "SUBMITTED" });
    expect(headers.get("Idempotency-Key")).toBe("usage-request:test-1");
    expect(JSON.parse(String(requestInit?.body))).toMatchObject({ asset_id: "asset-1", usage_mode: "MPC_AGGREGATE" });

    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { code: "IF_MATCH_INVALID", message: "状态已变化" } }), { status: 409 })));
    await expect(transitionUsageRequest("dur-1", "approve", "同意", { ifMatch: "\"1\"", idempotencyKey: "usage-request:approve-1" })).rejects.toEqual(expect.objectContaining({ status: 409, message: "状态已变化" }));

    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "当前账号无权执行此操作" }), { status: 403 })));
    await expect(transitionUsageRequest("dur-1", "approve", "越权", { ifMatch: "\"1\"", idempotencyKey: "usage-request:approve-2" })).rejects.toMatchObject({ status: 403 });
  });

  it("keeps contract list/detail/actions on real IDs with If-Match", async () => {
    stubRuntime();
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      requests.push({ url: String(url), init });
      const body = String(url).includes("/contracts/con-real")
        ? { contract: { contract_id: "con-real" }, agreement: { state: "NEGOTIATED" }, events: [], timeline: [], allowed_actions: ["comment", "counter"] }
        : { items: [{ contract_id: "con-real" }], total: 1, page: 1, page_size: 20, empty_state: false };
      return new Response(JSON.stringify(body), { status: 200 });
    }));

    const list = await loadContracts({ page: 1, pageSize: 20 });
    const detail = await loadContract("con-real");
    expect(list.items[0].contract_id).toBe("con-real");
    expect(detail.contract.contract_id).toBe("con-real");
    expect(requests[0].url).toContain("/api/trust-space/contracts");
    expect(requests[1].url).toContain("/api/trust-space/contracts/con-real");

    await postContractAction("con-real", "counter", { message: "调整结果范围", terms: { output: "aggregate" }, attachments: [] }, { ifMatch: "\"2\"", idempotencyKey: "contract-counter:1" });
    const actionHeaders = new Headers(requests[2].init?.headers);
    expect(requests[2].url).toContain("/api/trust-space/contracts/con-real/counter");
    expect(actionHeaders.get("If-Match")).toBe("\"2\"");
    expect(actionHeaders.get("Idempotency-Key")).toBe("contract-counter:1");
    expect(JSON.parse(String(requests[2].init?.body))).toMatchObject({ message: "调整结果范围", terms: { output: "aggregate" } });
  });

  it("serializes TTC task IDs, cursors and transition concurrency errors", async () => {
    stubRuntime();
    let lastUrl = "";
    let lastInit: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      lastUrl = String(url);
      lastInit = init;
      if (lastUrl.includes("/transitions")) return new Response(JSON.stringify({ detail: { code: "IF_MATCH_INVALID", message: "状态已变化" } }), { status: 409 });
      if (lastUrl.includes("/events")) return new Response(JSON.stringify({ task_id: "ttc-real", items: [], cursor: "3", next_cursor: null, has_more: false, limit: 20 }), { status: 200 });
      return new Response(JSON.stringify({ task: { task_id: "ttc-real", ttc_state: "COMPUTE_EXEC", state_version: 3 }, participants: [], attempts: [], transitions: [], snapshots: [], allowed_actions: ["view"] }), { status: 200 });
    }));

    const detail = await loadTtc("ttc-real");
    const events = await loadTtcEvents("ttc-real", { cursor: "3", limit: 20 });
    expect(detail.task.task_id).toBe("ttc-real");
    expect(events.cursor).toBe("3");
    expect(lastUrl).toContain("cursor=3");
    await expect(transitionTtc("ttc-real", { to_state: "HUMAN_REVIEW", trigger: "UI", reason: "复核" }, { ifMatch: "\"2\"" })).rejects.toMatchObject({ status: 409 });
    expect(new Headers(lastInit?.headers).get("If-Match")).toBe("\"2\"");
  });

  it("keeps computation list/detail and blocked capability truthful", async () => {
    stubRuntime();
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request) => {
      const value = String(url);
      urls.push(value);
      if (value.includes("/computations/job-real/events")) return new Response(JSON.stringify({ job_id: "job-real", items: [], cursor: "4", next_cursor: null, has_more: false, limit: 20 }), { status: 200 });
      if (value.includes("/computations/job-real")) return new Response(JSON.stringify({ job: { job_id: "job-real", task_id: "ttc-real", status: "BLOCKED", progress: 0, input_hashes: [], logs: [] }, participants: [], receipts: [], external_execution: { capability_state: "BLOCKED", source_of_truth: "privacy_compute_jobs/task_participants", cross_domain_participants: [] }, allowed_actions: ["view", "poll_logs"] }), { status: 200 });
      return new Response(JSON.stringify({ items: [{ job_id: "job-real", task_id: "ttc-real", status: "BLOCKED", progress: 0 }], total: 1, page: 1, page_size: 20, empty_state: false }), { status: 200 });
    }));

    const list = await loadComputations({ page: 1, pageSize: 20, status: "BLOCKED" });
    const detail = await loadComputation("job-real");
    const events = await loadComputationEvents("job-real", { cursor: "4", limit: 20 });
    expect(list.items[0].job_id).toBe("job-real");
    expect(detail.external_execution.capability_state).toBe("BLOCKED");
    expect(detail.participants).toHaveLength(0);
    expect(detail.allowed_actions).not.toContain("retry");
    expect(events.cursor).toBe("4");
    expect(urls.some((url) => url.includes("status=BLOCKED"))).toBe(true);
    expect(urls.some((url) => url.includes("cursor=4"))).toBe(true);
  });

  it("serializes truthful computation controls with version and idempotency headers", async () => {
    stubRuntime();
    let requestUrl = "";
    let requestInit: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      requestUrl = String(url);
      requestInit = init;
      return new Response(JSON.stringify({
        action: "cancel",
        action_reason: "人工取消",
        idempotent_replay: false,
        job: { job_id: "job-real", task_id: "ttc-real", status: "CANCELLED", state_version: 2, progress: 0, input_hashes: [], logs: [] },
        participants: [], receipts: [], external_execution: { capability_state: "ADAPTER", source_of_truth: "privacy_compute_jobs", cross_domain_participants: [] },
        allowed_actions: ["view", "poll_logs"], action_reasons: { retry: "没有重试执行器" },
      }), { status: 200, headers: { ETag: '"2"' } });
    }));

    const result = await controlComputation("job-real", "cancel", "人工取消", { ifMatch: '"1"', idempotencyKey: "compute-cancel:1" });
    expect(result.job.status).toBe("CANCELLED");
    expect(requestUrl).toContain("/api/trust-space/computations/job-real/cancel");
    const headers = new Headers(requestInit?.headers);
    expect(headers.get("If-Match")).toBe('"1"');
    expect(headers.get("Idempotency-Key")).toBe("compute-cancel:1");
    expect(JSON.parse(String(requestInit?.body))).toEqual({ reason: "人工取消" });
  });

  it("keeps results/evidence truthful and protects confirm/verify commands", async () => {
    stubRuntime();
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const value = String(url);
      requests.push({ url: value, init });
      if (value.includes("/verify")) return new Response(JSON.stringify({ matched: true, evidence_id: "ev-real", capability_state: "DEMO" }), { status: 200 });
      if (value.includes("/confirm")) {
        if (String(init?.body).includes("REJECT")) return new Response(JSON.stringify({ detail: { code: "RESULT_VERSION_CONFLICT", message: "状态已变化" } }), { status: 409 });
        return new Response(JSON.stringify({ result_id: "result-real", decision: "APPROVE", confirm_status: "CONFIRMED", task: { state_version: 4 } }), { status: 200 });
      }
      if (value.endsWith("/results/result-real")) return new Response(JSON.stringify({
        result: { result_id: "result-real", task_id: "task-real", result_hash: "hash-real", confirm_status: "UNCONFIRMED", result: { total: 12 } },
        task: { task_id: "task-real", state_version: 3 }, signatures: [], evidence: [{ evidence_id: "ev-real", evidence_hash: "ev-hash", tx_hash: null, block_height: null }], formal_evidence: [], allowed_actions: ["view", "confirm_result", "verify_evidence"], capability_state: "LOCAL_REAL",
      }), { status: 200 });
      return new Response(JSON.stringify({ items: [{ result_id: "result-real", task_id: "task-real", result_hash: "hash-real", confirm_status: "UNCONFIRMED" }], total: 1, page: 2, page_size: 20, empty_state: false }), { status: 200 });
    }));

    const list = await loadResults({ page: 2, pageSize: 20 });
    const detail = await loadResult("result-real");
    const verified = await verifyEvidence("ev-real");
    const command = await confirmResult("result-real", { decision: "APPROVE", opinion: "核对通过" }, { ifMatch: '"3"', idempotencyKey: "result-confirm:1" });
    expect(list.items[0].result_id).toBe("result-real");
    expect(detail.result.result_hash).toBe("hash-real");
    expect(detail.evidence[0].tx_hash).toBeNull();
    expect(verified.matched).toBe(true);
    expect(command.confirm_status).toBe("CONFIRMED");
    const commandHeaders = new Headers(requests.find((item) => item.url.includes("/confirm"))?.init?.headers);
    expect(commandHeaders.get("If-Match")).toBe('"3"');
    expect(commandHeaders.get("Idempotency-Key")).toBe("result-confirm:1");

    await expect(confirmResult("result-real", { decision: "REJECT", opinion: "状态冲突" }, { ifMatch: '"2"' })).rejects.toMatchObject({ status: 409 });
  });

  it("loads scoped audit pages and exports server JSON/CSV blobs", async () => {
    stubRuntime();
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request) => {
      const value = String(url);
      urls.push(value);
      if (value.includes("/audit/export?format=json")) return new Response('{"items":[]}', { status: 200, headers: { "Content-Type": "application/json", "Content-Disposition": "attachment; filename=audit-records.json" } });
      if (value.includes("/audit/export?format=csv")) return new Response("record_type,record_id\n", { status: 200, headers: { "Content-Type": "text/csv", "Content-Disposition": "attachment; filename=audit-records.csv" } });
      if (value.includes("/audit/tasks/task-real")) return new Response(JSON.stringify({ task: { task_id: "task-real", ttc_state: "ARCHIVED" }, audit_chain: [], transitions: [], reports: [], evidence: [], allowed_actions: ["view", "export_json", "export_csv"] }), { status: 200 });
      if (value.includes("/audit?")) return new Response(JSON.stringify({ items: [{ record_type: "AUDIT_REPORT", record_id: "report-real", details: { task_id: "task-real" } }], reports: [], total: 1, page: 2, page_size: 50 }), { status: 200 });
      return new Response(JSON.stringify({ detail: "无权导出" }), { status: 403 });
    }));

    const list = await loadAudit({ page: 2, pageSize: 50 });
    const detail = await loadAuditTask("task-real");
    const json = await downloadAudit("json");
    const csv = await downloadAudit("csv");
    expect(list.items[0].record_id).toBe("report-real");
    expect(detail.task.task_id).toBe("task-real");
    expect(await json.blob.text()).toContain("items");
    expect(json.filename).toBe("audit-records.json");
    expect(csv.filename).toBe("audit-records.csv");
    expect(urls.some((url) => url.includes("page=2") && url.includes("page_size=50"))).toBe(true);

    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "无权导出" }), { status: 403 })));
    await expect(downloadAudit("json")).rejects.toMatchObject({ status: 403 });
  });

  it("preserves assistant session, shortcuts, blocked/write plans and versioned actions", async () => {
    stubRuntime();
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const value = String(url);
      requests.push({ url: value, init });
      if (value.endsWith("/assistant/sessions")) return new Response(JSON.stringify({ session_id: "session-real", state_version: 1, status: "ACTIVE", capability_state: "LOCAL_REAL" }), { status: 201 });
      if (value.includes("/messages") && value.endsWith("/messages") && init?.method === "POST") {
        const body = JSON.parse(String(init?.body || "{}")) as { content?: string };
        const status = body.content === "未知意图" ? "BLOCKED" : body.content === "提交申请" ? "PENDING_REVIEW" : "READY";
        return new Response(JSON.stringify({ session: { session_id: "session-real", state_version: 2 }, message: { message_id: `message-${body.content}`, content: body.content }, plan: { plan_id: `plan-${status}`, status, state_version: 1, intent_code: status === "BLOCKED" ? "UNKNOWN_INTENT" : "CHECK_ASSET_INTEGRITY", steps: [{ step_id: "step-real", status, state_version: 1 }] } }), { status: 201 });
      }
      if (value.includes("/plans/") && value.endsWith("/execute")) return new Response(JSON.stringify({ session: { session_id: "session-real", state_version: 3 }, plan: { plan_id: "plan-real", status: "SUCCEEDED", state_version: 2, steps: [{ step_id: "step-real", status: "SUCCEEDED", state_version: 2 }] } }), { status: 200 });
      if (value.includes("/plans/") && value.endsWith("/cancel")) return new Response(JSON.stringify({ session: { session_id: "session-real", state_version: 3 }, plan: { plan_id: "plan-real", status: "CANCELLED", state_version: 2, steps: [{ step_id: "step-real", status: "CANCELLED", state_version: 2 }] } }), { status: 200 });
      if (value.includes("/plans/") && value.endsWith("/retry")) return new Response(JSON.stringify({ session: { session_id: "session-real", state_version: 3 }, plan: { plan_id: "plan-real", status: "READY", state_version: 2, steps: [{ step_id: "step-real", status: "READY", state_version: 2 }] } }), { status: 200 });
      if (value.endsWith("/messages")) return new Response(JSON.stringify({ session: { session_id: "session-real", state_version: 2 }, items: [], total: 0 }), { status: 200 });
      if (value.endsWith("/plans")) return new Response(JSON.stringify({ session: { session_id: "session-real", state_version: 2 }, items: [], total: 0 }), { status: 200 });
      if (value.endsWith("/tools")) return new Response(JSON.stringify({ items: [{ tool_code: "WorkflowEngine", tool_name: "工作流", service_code: "workflow", assistant_actions: ["CHECK_TTC_STATUS"], enabled: true }], total: 1 }), { status: 200 });
      return new Response(JSON.stringify({ detail: "未找到" }), { status: 404 });
    }));

    const session = await createAssistantSession({ page_path: "/trusted-space/results/result-real", entity_type: "settlement_result", entity_id: "result-real" }, { idempotencyKey: "assistant-session:1" });
    const shortcutContents = ["检查资产完整性", "查询授权申请状态", "检查TTC状态", "核验证据摘要", "解释审计报告", "未知意图", "提交申请"];
    const plans = [];
    for (const [index, content] of shortcutContents.entries()) {
      plans.push(await postAssistantMessage("session-real", content, { ifMatch: `"${index + 1}"`, idempotencyKey: `assistant-message:${index}` }));
    }
    const messages = await loadAssistantMessages("session-real");
    const listedPlans = await loadAssistantPlans("session-real");
    const tools = await loadAssistantTools();
    await runAssistantPlanAction("session-real", "plan-real", "execute", { ifMatch: '"1"', idempotencyKey: "assistant-execute:1" }, "step-real");
    await runAssistantPlanAction("session-real", "plan-real", "cancel", { ifMatch: '"2"', idempotencyKey: "assistant-cancel:1" });
    await runAssistantPlanAction("session-real", "plan-real", "retry", { ifMatch: '"2"', idempotencyKey: "assistant-retry:1" });
    expect(session.session_id).toBe("session-real");
    expect(plans.find((item) => item.plan?.status === "BLOCKED") || plans.some((item) => item.plan?.status === "BLOCKED")).toBeTruthy();
    expect(messages.total).toBe(0);
    expect(listedPlans.total).toBe(0);
    expect(tools.items[0].tool_code).toBe("WorkflowEngine");
    expect(requests.some((item) => item.url.endsWith("/execute"))).toBe(true);
    expect(new Headers(requests.find((item) => item.url.endsWith("/execute"))?.init?.headers).get("If-Match")).toBe('"1"');
  });

  it("retries a transient browser transport failure for Agent bootstrap reads", async () => {
    stubRuntime();
    const attempts = new Map<string, number>();
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request) => {
      const value = String(url);
      const count = (attempts.get(value) || 0) + 1;
      attempts.set(value, count);
      if (count === 1) throw new TypeError("Failed to fetch");
      if (value.endsWith("/messages")) {
        return new Response(JSON.stringify({ session: { session_id: "session-real", state_version: 1 }, items: [], total: 0 }), { status: 200 });
      }
      if (value.endsWith("/plans")) {
        return new Response(JSON.stringify({ session: { session_id: "session-real", state_version: 1 }, items: [], total: 0 }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 });
    }));

    await expect(loadAssistantMessages("session-real")).resolves.toMatchObject({ total: 0 });
    await expect(loadAssistantPlans("session-real")).resolves.toMatchObject({ total: 0 });
    await expect(loadAssistantTools()).resolves.toMatchObject({ total: 0 });
    expect([...attempts.values()]).toEqual([2, 2, 2]);
  });
});
