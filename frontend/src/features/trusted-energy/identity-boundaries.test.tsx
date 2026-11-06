import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { IdentityPage } from "./pages/IdentityPage";
import { loadIdentity, type IdentityPayload } from "./trusted-space-api";

const identity: IdentityPayload = {
  subject: { org_id: "org-heat", org_name: "热能企业", org_type: "HEAT_ENTERPRISE", status: "ACTIVE" },
  actor: { user_id: "user-heat", display_name: "热能企业账户", role_code: "HEAT_ENTERPRISE" },
  did: { did_id: "did:hiddenchain:org:org-heat", credential_status: "VALID" },
  connector: {
    code: "ECLIPSE_EDC", protocol_version: "HCDS_CONNECTOR_1_0", source_count: 8,
    source_capabilities: ["LOCAL_REAL"], capability_state: "ADAPTER",
    readiness: "NOT_CONFIGURED", external_edc_runtime: "NOT_CONFIGURED",
  },
  capability_matrix: {},
};

vi.mock("./components/PageFrame", () => ({ PageFrame: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("../../hooks", () => ({
  useRemote: (loader: unknown) => ({
    loading: false, refreshing: false, error: "", reload: vi.fn(),
    data: loader === loadIdentity
      ? identity
      : { items: [], total: 0, verified_count: 0, energy_domains: [], empty_state: true },
  }),
}));

describe("identity connector capability wording", () => {
  it("labels an unconfigured external EDC independently of registered local data sources", () => {
    const html = renderToStaticMarkup(<IdentityPage />);
    const connectorCard = html.match(/<section[^>]*id="trusted-identity-connector"[^>]*>([\s\S]*?)<\/section>/)?.[1];

    expect(connectorCard).toBeDefined();
    const fields = Object.fromEntries([...connectorCard!.matchAll(/<dt>(.*?)<\/dt><dd>(.*?)<\/dd>/g)]
      .map(([, label, value]) => [label, value.replace(/<[^>]*>/g, "")]));
    expect(fields["已登记数据源"]).toBe("8");
    expect(fields["外部 EDC 状态"]).toBe("未配置");
    expect(fields).not.toHaveProperty("连接状态");
  });
});
