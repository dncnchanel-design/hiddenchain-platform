import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SettlementCreatePage } from "./pages/SettlementCreatePage";

const mocks = vi.hoisted(() => ({ domain: "electricity", loader: vi.fn() }));
vi.mock("./auth", () => ({ useAuth: () => ({ session: { user: { role_code: "EXCHANGE" }, org: { energy_domain: mocks.domain } } }) }));
vi.mock("./hooks", () => ({ useRemote: () => { mocks.loader(); return { data: null, loading: true, error: "", reload: vi.fn() }; } }));
vi.mock("react-router-dom", async (importOriginal) => ({
  ...await importOriginal<typeof import("react-router-dom")>(),
  Navigate: ({ to }: { to: string }) => <span>跳转至 {to}</span>,
}));

describe("energy domain of the existing settlement creation flow", () => {
  beforeEach(() => { mocks.domain = "electricity"; mocks.loader.mockReset(); });

  it("preserves the electricity exchange settlement form", () => {
    const markup = renderToStaticMarkup(<MemoryRouter><SettlementCreatePage /></MemoryRouter>);
    expect(markup).toContain("正在准备结算任务");
    expect(markup).not.toContain("跳转至");
    expect(mocks.loader).toHaveBeenCalledTimes(1);
  });

  it.each(["coal", "heat", "gas", "oil"])("directs %s exchanges to supported authorized connector queries before loading settlement data", (domain) => {
    mocks.domain = domain;
    const markup = renderToStaticMarkup(<MemoryRouter><SettlementCreatePage /></MemoryRouter>);
    expect(markup).toContain("/trusted-space/query");
    expect(markup).not.toContain("正在准备结算任务");
    expect(mocks.loader).not.toHaveBeenCalled();
  });
});
