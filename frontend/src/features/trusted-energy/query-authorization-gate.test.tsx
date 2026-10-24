import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { QueryOutput } from "./pages/QueryPage";
import type { CatalogAsset, QueryIntent, UsageRequest } from "./trusted-space-api";
import { findQueryAuthorization } from "./query-authorization";

vi.mock("react-router-dom", () => ({ Link: ({ to, children, ...props }: { to: string; children: React.ReactNode }) => <a href={to} {...props}>{children}</a>, useNavigate: () => vi.fn() }));

const props = {
  intent: { question: "查询6月负荷", requires_authorization: true, requires_confirmation: true, notice: "", ready: true, provider: "manual_rules", energy_domain: "electricity", energy_domain_name: "电力", resource: "load", function: "sum", function_name: "求和", start_date: "2026-06-01", end_date: "2026-06-30" } as QueryIntent,
  providers: [{ asset_id: "asset-electricity-load", asset_name: "用电负荷", provider: { org_id: "org-retailer-t01", org_name: "海岱售电服务有限公司" } }] as CatalogAsset[],
  selectedProviderId: "asset-electricity-load", steps: [{ stage: "解析需求", status: "已完成" as const }, { stage: "授权确认", status: "待授权" as const }],
  onProviderChange: vi.fn(), onExecute: vi.fn(), executeBusy: false, task: null, taskActive: false, execution: null, error: "", pollingError: "", retryLabel: "", onRetry: vi.fn(), identity: { name: "交易中心", did: "did:test:exchange" },
  needsApplication: true, authorizationLoading: false, authorizationError: "", onRefreshAuthorization: vi.fn(),
};

describe("query authorization entry", () => {
  it("sends a trader without a grant to its selected provider application", () => {
    const html = renderToStaticMarkup(<QueryOutput {...props} />);
    expect(html).toContain("申请数据授权");
    expect(html).toContain('/trusted-space/apply/asset-electricity-load');
    expect(html).not.toContain("确认授权并执行连接器计算");
    expect(html).not.toContain("REGULATOR");
  });

  it("offers execution when a valid grant or an authorized subject-rule path exists", () => {
    const html = renderToStaticMarkup(<QueryOutput {...props} needsApplication={false} />);
    expect(html).toContain("确认授权并执行连接器计算");
    expect(html).not.toContain(">申请数据授权</a>");
  });

  it("blocks execution while authorization could not be read and offers a recheck", () => {
    const html = renderToStaticMarkup(<QueryOutput {...props} needsApplication={false} authorizationError="授权读取失败" />);
    expect(html).toContain("授权读取失败");
    expect(html).toContain("重新检查授权");
    expect(html).toMatch(/<button[^>]*disabled[^>]*>确认授权并执行连接器计算/);
  });
});

describe("matching a grant to the actual query", () => {
  const now = Date.parse("2026-10-24T00:00:00Z");
  const grant: UsageRequest = { request_id: "approved", asset: { asset_id: "asset-electricity-load", version_id: "v1" }, applicant: { user_id: "user", org_id: "exchange", org_name: "交易中心", did: "did:exchange" }, provider: { org_id: "org-retailer-t01", org_name: "售电企业", did: "did:retailer" }, purpose: "CROSS_CHECK", usage_mode: "MPC_AGGREGATE", requested_scope: {}, requested_fields: ["summary"], terms: {}, duration_days: 30, expires_at: "2026-10-24T01:00:00", status: "APPROVED", state_version: 1, submitted_at: "2026-10-23T00:00:00Z", actions: [] };
  const asset = { ...props.providers[0], latest_version: { version_id: "v1" } } as CatalogAsset;
  const match = (value: UsageRequest) => findQueryAuthorization([value], asset, props.intent, "exchange", now);

  it("accepts API UTC timestamps without an explicit timezone", () => {
    expect(match(grant)?.request_id).toBe("approved");
  });

  it.each(["SUBMITTED", "REVOKED", "REJECTED"])("does not use a %s request", (status) => {
    expect(match({ ...grant, status })).toBeUndefined();
  });

  it("skips an expired grant and finds the next valid grant", () => {
    expect(findQueryAuthorization([{ ...grant, expires_at: "2026-10-23T00:00:00Z" }, grant], asset, props.intent, "exchange", now)?.request_id).toBe("approved");
  });

  it("keeps tenant, provider and published data-version boundaries", () => {
    expect(match({ ...grant, applicant: { ...grant.applicant, org_id: "another-org" } })).toBeUndefined();
    expect(match({ ...grant, provider: { ...grant.provider, org_id: "another-provider" } })).toBeUndefined();
    expect(match({ ...grant, asset: { ...grant.asset, version_id: "v0" } })).toBeUndefined();
  });

  it.each([{ start_date: "2026-06-02" }, { end_date: "2026-06-03" }, { region: "East" }, { allowed_functions: ["average"] }])("does not reuse an approved grant outside %j", (requested_scope) => {
    expect(match({ ...grant, requested_scope })).toBeUndefined();
  });

  it("honors explicit function fields and keeps ordinary summary grants compatible", () => {
    expect(match({ ...grant, requested_fields: ["load", "average"] })).toBeUndefined();
    expect(match(grant)).toBeDefined();
  });

  it("does not reuse an approved request after its one-use agreement was consumed", () => {
    const consumed = { ...grant, usage_budget: { remaining_uses: 0, usable: false, agreement_state: "CONSUMED" } };
    expect(match(consumed)).toBeUndefined();
    expect(findQueryAuthorization([consumed, grant], asset, props.intent, "exchange", now)?.request_id).toBe("approved");
    expect(match({ ...grant, usage_budget: { remaining_uses: 0, usable: true, agreement_state: "ACTIVE" } })).toBeUndefined();
    expect(match({ ...grant, usage_budget: { remaining_uses: 1, usable: false, agreement_state: "REVOKED" } })).toBeUndefined();
    expect(match({ ...grant, usage_budget: { remaining_uses: 1, usable: true, agreement_state: "ACTIVE" } })).toBeDefined();
  });
});
