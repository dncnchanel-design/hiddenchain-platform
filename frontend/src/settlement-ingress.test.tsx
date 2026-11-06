import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { SettlementCreatePage } from "./pages/SettlementCreatePage";

const state = vi.hoisted(() => ({ entries: [] as Array<Record<string, unknown>> }));
vi.mock("./auth", () => ({ useAuth: () => ({ session: { user: { role_code: "EXCHANGE" }, org: { energy_domain: "electricity" } } }) }));
vi.mock("./hooks", () => ({ useRemote: () => ({ loading: false, error: "", reload: vi.fn(), data: {
  organizations: [{ org_id: "generator-new", org_type: "GENERATOR", org_name: "新发电方" }, { org_id: "retailer-new", org_type: "RETAILER", org_name: "新售电方" }],
  rules: [{ rule_id: "rule-current", status: "ACTIVE" }], catalog: { entries: state.entries },
} }) }));

const entry = (asset_type: string, owner_org_id: string, period: string) => ({ asset_type, owner_org_id, trade_batch_no: "BATCH-NOVEMBER", commitment_confirmed: true, quality: { validation_status: "PASSED", period } });
beforeEach(() => { state.entries = [entry("GENERATION_DATA", "generator-new", "2026-11-01/2026-11-03"), entry("RETAIL_DATA", "retailer-new", "2026-11-01/2026-11-03")]; });

it("uses the actual shared batch and period for a ready settlement instead of a fixed month", () => {
  const markup = renderToStaticMarkup(<MemoryRouter initialEntries={["/settlements/new?template=ready"]}><SettlementCreatePage /></MemoryRouter>);
  expect(markup).toContain('value="2026-11-01"');
  expect(markup).toContain('value="2026-11-03"');
  expect(markup).toContain('value="BATCH-NOVEMBER"');
  expect(markup).not.toContain("2026-07");
});

it("does not advertise a ready start when the two parties supplied different periods", () => {
  state.entries[1] = entry("RETAIL_DATA", "retailer-new", "2026-12");
  const markup = renderToStaticMarkup(<MemoryRouter initialEntries={["/settlements/new?template=ready"]}><SettlementCreatePage /></MemoryRouter>);
  expect(markup).not.toContain("已带入一笔可运行的验收起点");
  expect(markup).not.toContain('value="BATCH-NOVEMBER"');
});
