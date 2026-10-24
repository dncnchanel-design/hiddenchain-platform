import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthorizationsPage } from "./pages/AuthorizationsPage";

const mocks = vi.hoisted(() => ({ selectedId: "request-b", stale: null as unknown, loading: true, error: "", calls: 0 }));
vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useSearchParams: () => [new URLSearchParams(`view=inbox&request=${mocks.selectedId}`), vi.fn()],
}));
vi.mock("../../hooks", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../hooks")>(),
  useRemote: () => ({ data: mocks.calls++ === 0 ? { items: [], page: 1, page_size: 12, total: 0 } : mocks.stale, loading: false, refreshing: false, error: "", reload: vi.fn() }),
  useScopedRemote: (scope: string) => ({ data: (mocks.stale as { request_id?: string })?.request_id === scope ? mocks.stale : null, loading: mocks.loading, refreshing: false, error: mocks.error, refreshError: "", reload: vi.fn() }),
}));
vi.mock("./trusted-space-context", () => ({ useTrustedSpaceContext: () => ({ context: { role_capabilities: { can_review_inbound_requests: true } } }) }));
vi.mock("./components/PageFrame", () => ({ PageFrame: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

describe("authorization request selection", () => {
  beforeEach(() => {
    mocks.calls = 0;
    mocks.loading = true;
    mocks.error = "";
    mocks.stale = { request_id: "request-a", state_version: 1, asset: { asset_name: "旧申请资产", asset_id: "asset-a" }, applicant: { org_name: "旧申请方" }, provider: { org_name: "提供方" }, purpose: "SETTLEMENT", usage_mode: "MPC_AGGREGATE", requested_fields: [], terms: {}, actions: ["approve"], duration_days: 1, submitted_at: "2026-10-24" };
  });

  it("never offers request A actions while request B is loading", () => {
    const markup = renderToStaticMarkup(<AuthorizationsPage />);
    expect(markup).not.toContain("旧申请资产");
    expect(markup).not.toContain("审核操作");
  });

  it("does not revive the old actionable request when the selected request fails", () => {
    mocks.loading = false;
    mocks.error = "当前申请不可访问";
    const markup = renderToStaticMarkup(<AuthorizationsPage />);
    expect(markup).toContain("当前申请不可访问");
    expect(markup).not.toContain("旧申请资产");
    expect(markup).not.toContain("审核操作");
  });
});
