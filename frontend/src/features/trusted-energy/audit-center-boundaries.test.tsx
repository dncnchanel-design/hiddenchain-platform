import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuditCenterPage } from "./pages/AuditCenterPage";
import { auditDetailForRoute, auditListForRoute, type AuditRouteRemoteData } from "./audit-route-state";

const mocks = vi.hoisted(() => ({
  pathname: "/trusted-space/audit",
  data: null as unknown,
  loaders: [] as Array<(signal?: AbortSignal) => Promise<unknown>>,
  loadAudit: vi.fn(),
  loadAuditTask: vi.fn(),
  navigate: vi.fn(),
  loading: false,
  refreshing: false,
  error: "",
  refreshError: "",
}));

vi.mock("react-router-dom", () => ({
  useLocation: () => ({ pathname: mocks.pathname }),
  useNavigate: () => mocks.navigate,
}));
vi.mock("../../hooks", () => ({
  useRemote: (loader: (signal?: AbortSignal) => Promise<unknown>) => {
    mocks.loaders.push(loader);
    return { data: mocks.data, loading: mocks.loading, refreshing: mocks.refreshing, error: mocks.error, refreshError: mocks.refreshError, reload: vi.fn() };
  },
}));
vi.mock("./trusted-space-api", async (importOriginal) => ({
  ...await importOriginal<typeof import("./trusted-space-api")>(),
  loadAudit: mocks.loadAudit,
  loadAuditTask: mocks.loadAuditTask,
}));

describe("trusted audit center boundaries", () => {
  beforeEach(() => {
    mocks.pathname = "/trusted-space/audit";
    mocks.loaders = [];
    mocks.loadAudit.mockReset().mockResolvedValue({});
    mocks.loadAuditTask.mockReset().mockResolvedValue({});
    mocks.navigate.mockReset();
    mocks.loading = false;
    mocks.refreshing = false;
    mocks.error = "";
    mocks.refreshError = "";
    mocks.data = { kind: "list", page: 1, payload: {
      items: [], reports: [], total: 0, page: 1, page_size: 20, empty_state: true,
    } };
  });

  it("uses the formal paged audit API and exposes no demo write controls", async () => {
    const markup = renderToStaticMarkup(<AuditCenterPage />);
    await mocks.loaders[0]();

    expect(mocks.loadAudit).toHaveBeenCalledWith({ page: 1, pageSize: 20 }, undefined);
    expect(markup).toContain("正式审计页保持只读");
    expect(markup).not.toContain("模拟篡改");
    expect(markup).not.toContain("恢复");
  });

  it("consumes the deep-linked task id and renders evidence receipt state", async () => {
    mocks.pathname = "/trusted-space/audit/tasks/task-real";
    mocks.data = { kind: "detail", taskId: "task-real", payload: {
      task: { task_id: "task-real", task_name: "真实任务", ttc_state: "ARCHIVED", status: "SUCCEEDED" },
      audit_chain: [], transitions: [], reports: [],
      evidence: [{ evidence_id: "evidence-real", status: "CONFIRMED", verification_status: "MATCHED", evidence_hash: "hash-real" }],
      execution_receipts: [{ receipt_id: "receipt-real", status: "CONFIRMED", request_hash: "request-real", result_hash: "result-real" }],
    } };
    const markup = renderToStaticMarkup(<AuditCenterPage />);
    await mocks.loaders[0]();

    expect(mocks.loadAuditTask).toHaveBeenCalledWith("task-real", undefined);
    expect(markup).toContain("摘要一致");
    expect(markup).toContain("receipt-real");
  });

  it("rejects stale list/detail payloads when the route key changes", () => {
    const list = { kind: "list", page: 1, payload: { items: [], reports: [], total: 0, page: 1, page_size: 20, empty_state: true } } as AuditRouteRemoteData;
    const detail = { kind: "detail", taskId: "task-a", payload: { task: { task_id: "task-a" }, audit_chain: [], transitions: [], reports: [], evidence: [], execution_receipts: [] } } as AuditRouteRemoteData;

    expect(auditDetailForRoute(list, "task-a")).toBeNull();
    expect(auditDetailForRoute(detail, "task-b")).toBeNull();
    expect(auditListForRoute(detail, 1)).toBeNull();
  });

  it("shows the new-route failure instead of stale task data", () => {
    mocks.pathname = "/trusted-space/audit/tasks/task-b";
    mocks.data = { kind: "detail", taskId: "task-a", payload: { task: { task_id: "task-a", task_name: "旧任务" }, audit_chain: [], transitions: [], reports: [], evidence: [], execution_receipts: [] } };
    mocks.refreshError = "新任务不可访问";

    const markup = renderToStaticMarkup(<AuditCenterPage />);

    expect(markup).toContain("新任务不可访问");
    expect(markup).not.toContain("旧任务");
  });

  it("shows loading instead of casting stale list data on list-to-detail navigation", () => {
    mocks.pathname = "/trusted-space/audit/tasks/task-new";
    mocks.data = { kind: "list", page: 1, payload: { items: [], reports: [], total: 0, page: 1, page_size: 20, empty_state: true } };
    mocks.refreshing = true;

    const markup = renderToStaticMarkup(<AuditCenterPage />);

    expect(markup).toContain("正在加载真实数据");
    expect(markup).not.toContain("审计与存证中心");
  });
});
