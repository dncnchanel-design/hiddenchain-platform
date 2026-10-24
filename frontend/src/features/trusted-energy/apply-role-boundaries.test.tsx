import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ApplyPage } from "./pages/ApplyPage";

const state = vi.hoisted(() => ({ role: "REGULATOR" }));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn(), useLocation: () => ({ pathname: "/trusted-space/apply/asset" }) }));
vi.mock("./trusted-space-context", () => ({ useTrustedSpaceContext: () => ({ context: { actor: { role_code: state.role } } }) }));
vi.mock("./components/PageFrame", () => ({ PageFrame: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("../../hooks", () => ({ useRemote: () => ({ loading: false, refreshing: false, error: "", reload: vi.fn(), data: {
  asset: { asset_id: "asset", asset_name: "用电负荷", provider: { org_name: "数据提供方" }, sensitivity_level: "L2" }, versions: [],
  duration_policy: { min_days: 1, max_days: 180, default_days: 30 }, actions: { can_request_usage: true },
} }) }));

describe("application purpose options follow the authenticated role", () => {
  it("only offers the regulatory purposes that its API can approve", () => {
    state.role = "REGULATOR";
    const html = renderToStaticMarkup(<ApplyPage />);
    expect(html).toContain("能源监管");
    expect(html).toContain("应急处置");
    expect(html).not.toContain("通用业务用途");
    expect(html).not.toContain("交叉分析");
  });
  it.each(["EXCHANGE", "GENERATOR"])("retains all five business purposes for %s", (role) => {
    state.role = role;
    const html = renderToStaticMarkup(<ApplyPage />);
    for (const purpose of ["结算分析", "交叉分析", "模型训练", "审计复核", "其他受控用途"]) expect(html).toContain(purpose);
    expect(html).not.toContain("监管白名单用途");
  });
});
