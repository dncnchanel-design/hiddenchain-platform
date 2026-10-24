import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TtcPage } from "./pages/TtcPage";

const mocks = vi.hoisted(() => ({
  role: "EXCHANGE", calls: 0,
  task: { task_id: "task-1", task_name: "当前结算任务", status: "READY", state_version: 7, allowed_actions: ["RUN_SETTLEMENT"], readiness: { preflight_passed: true } },
  run: vi.fn(), reload: vi.fn(),
  confirm: null as { open: boolean; onConfirm: () => Promise<void> } | null,
}));
vi.mock("../../auth", () => ({ useAuth: () => ({ session: { user: { role_code: mocks.role } } }) }));
vi.mock("react-router-dom", () => ({
  useLocation: () => ({ pathname: "/trusted-space/ttc/task-1" }),
  useNavigate: () => vi.fn(),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));
vi.mock("../../hooks", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../hooks")>(),
  useRemote: () => ({ data: null, loading: false, refreshing: false, error: "", reload: mocks.reload }),
  useScopedRemote: () => ({ data: mocks.calls++ === 0 ? { task: { ...mocks.task, ttc_state: "RULE_FROZEN" }, participants: [], attempts: [], transitions: [], snapshots: [], allowed_actions: ["view"] } : mocks.task, loading: false, refreshing: false, error: "", refreshError: "", reload: mocks.reload }),
}));
vi.mock("./components/PageFrame", () => ({ PageFrame: ({ action, children }: { action: React.ReactNode; children: React.ReactNode }) => <>{action}{children}</> }));
vi.mock("../../components/ui", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../components/ui")>(),
  ConfirmDialog: (props: { open: boolean; onConfirm: () => Promise<void> }) => { mocks.confirm = props; return null; },
}));
vi.mock("./workflow-api", async (importOriginal) => ({
  ...await importOriginal<typeof import("./workflow-api")>(),
  runSettlementTask: mocks.run,
}));

describe("settlement actions in the mounted TTC page", () => {
  afterEach(() => vi.unstubAllGlobals());
  beforeEach(() => {
    vi.stubGlobal("window", { dispatchEvent: vi.fn() });
    mocks.role = "EXCHANGE"; mocks.calls = 0; mocks.confirm = null;
    mocks.task.allowed_actions = ["RUN_SETTLEMENT"];
    mocks.task.readiness.preflight_passed = true;
    mocks.run.mockReset().mockResolvedValue({});
    mocks.reload.mockReset().mockResolvedValue(undefined);
  });

  it("offers the existing run command after its backend preflight passed", () => {
    expect(renderToStaticMarkup(<TtcPage />)).toContain("启动结算");
    expect(mocks.confirm?.open).toBe(false);
  });

  it("does not offer a run to participants or without backend permission", () => {
    mocks.role = "GENERATOR";
    expect(renderToStaticMarkup(<TtcPage />)).not.toContain("启动结算");
    mocks.role = "EXCHANGE"; mocks.calls = 0; mocks.task.allowed_actions = [];
    expect(renderToStaticMarkup(<TtcPage />)).not.toContain("启动结算");
  });

  it("sends the selected task version and stable idempotency key from confirmation", async () => {
    renderToStaticMarkup(<TtcPage />);
    expect(mocks.confirm).not.toBeNull();
    await mocks.confirm!.onConfirm();
    const [taskId, options] = mocks.run.mock.calls[0];
    expect(taskId).toBe("task-1");
    expect(options.ifMatch).toBe('"7"');
    expect(options.idempotencyKey).toMatch(/^settlement-run:/);
    expect(mocks.reload).toHaveBeenCalled();
  });

  it("reuses the same command after an ambiguous transport failure", async () => {
    mocks.run.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    renderToStaticMarkup(<TtcPage />);
    await mocks.confirm!.onConfirm();
    await mocks.confirm!.onConfirm();
    expect(mocks.run).toHaveBeenCalledTimes(2);
    expect(mocks.run.mock.calls[0][1].idempotencyKey).toBe(mocks.run.mock.calls[1][1].idempotencyKey);
  });

  it("does not start a second run while the first command is outstanding", async () => {
    let release!: () => void;
    mocks.run.mockImplementationOnce(() => new Promise<void>((resolve) => { release = resolve; }));
    renderToStaticMarkup(<TtcPage />);
    const first = mocks.confirm!.onConfirm();
    await mocks.confirm!.onConfirm();
    expect(mocks.run).toHaveBeenCalledTimes(1);
    release();
    await first;
  });
});
