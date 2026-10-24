import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportsPage } from "../../pages/ReportsPage";
import { AnomaliesPage } from "../../pages/AnomaliesPage";

const mocks = vi.hoisted(() => ({ role: "REGULATOR", data: null as unknown }));
vi.mock("../../auth", () => ({ useAuth: () => ({ session: { user: { role_code: mocks.role } } }) }));
vi.mock("../../hooks", () => ({ useRemote: () => ({ data: mocks.data, loading: false, refreshing: false, error: "", reload: vi.fn() }) }));

describe("audit action pages reused inside trusted space", () => {
  beforeEach(() => { mocks.role = "REGULATOR"; });

  it("limits a report notification to the named report and keeps the approval action", () => {
    mocks.data = { reports: [
      { report_id: "report-a", task_id: "task-1", report_title: "目标报告", status: "GENERATED" },
      { report_id: "report-b", task_id: "task-1", report_title: "其他报告", status: "GENERATED" },
    ], tasks: [] };
    const markup = renderToStaticMarkup(<MemoryRouter><ReportsPage taskId="task-1" reportId="report-a" /></MemoryRouter>);
    expect(markup).toContain("目标报告");
    expect(markup).not.toContain("其他报告");
    expect(markup).toContain("批准</button>");
    expect(markup).toContain('href="/trusted-space/ttc/task-1"');
  });

  it("keeps report writes out of a non-regulator render", () => {
    mocks.role = "GENERATOR";
    mocks.data = { reports: [{ report_id: "report-a", task_id: "task-1", report_title: "报告", status: "GENERATED" }], tasks: [] };
    const markup = renderToStaticMarkup(<MemoryRouter><ReportsPage /></MemoryRouter>);
    expect(markup).not.toContain("批准</button>");
    expect(markup).not.toContain("驳回</button>");
  });

  it("limits an anomaly deep link to its event while preserving disposition", () => {
    mocks.data = [
      { event_id: "event-a", task_id: "task-1", title: "目标事件", status: "OPEN", state_version: 3 },
      { event_id: "event-b", task_id: "task-1", title: "其他事件", status: "OPEN", state_version: 4 },
    ];
    const markup = renderToStaticMarkup(<MemoryRouter><AnomaliesPage taskId="task-1" eventId="event-a" /></MemoryRouter>);
    expect(markup).toContain("目标事件");
    expect(markup).not.toContain("其他事件");
    expect(markup).toContain("处置</button>");
    expect(markup).toContain('href="/trusted-space/audit/tasks/task-1"');
    expect(markup).not.toContain('href="/trusted-space/ttc/task-1"');
  });
});
