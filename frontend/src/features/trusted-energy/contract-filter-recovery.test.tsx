import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { ContractPage } from "./pages/ContractPage";
import type { PropsWithChildren } from "react";

vi.mock("./components/PageFrame", () => ({ PageFrame: ({ children }: PropsWithChildren) => <div>{children}</div> }));

vi.mock("../../hooks", () => ({
  useRemote: () => ({ data: { items: [], page: 1, page_size: 12, total: 0 }, loading: false, error: "", reload: vi.fn() }),
  useScopedRemote: () => ({ data: null }),
}));

it("keeps the state selector available when a contract filter matches no records", () => {
  const markup = renderToStaticMarkup(<MemoryRouter initialEntries={["/trusted-space/contracts?state=NEGOTIATED"]}><ContractPage /></MemoryRouter>);
  expect(markup).toContain('aria-label="按合同状态筛选"');
  expect(markup).toContain('value="NEGOTIATED" selected=""');
  expect(markup).toContain("当前主体暂无可见合同或协商记录");
});
