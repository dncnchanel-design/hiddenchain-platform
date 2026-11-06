import { isValidElement, type ReactElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api";
import { ConnectorPage } from "./pages/ConnectorPage";
import type { ConnectorCatalogPayload, ConnectorSettlementBinding, ConnectorSignedReceipt, ConnectorTicket } from "./trusted-space-api";

const fixture = vi.hoisted(() => ({
  slots: [] as unknown[], cursor: 0, refs: [] as Array<{ current: unknown }>, refCursor: 0, effects: [] as Array<() => unknown>,
  catalog: null as unknown, reload: vi.fn(), issue: vi.fn(), upload: vi.fn(), register: vi.fn(), lookup: vi.fn(), loadReceipt: vi.fn(),
}));
vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useState: (initial: unknown) => {
    const index = fixture.cursor++;
    if (!(index in fixture.slots)) fixture.slots[index] = typeof initial === "function" ? initial() : initial;
    return [fixture.slots[index], (value: unknown) => { fixture.slots[index] = typeof value === "function" ? value(fixture.slots[index]) : value; }];
  },
  useRef: (initial: unknown) => {
    const index = fixture.refCursor++;
    fixture.refs[index] ??= { current: initial };
    return fixture.refs[index];
  },
  useCallback: (callback: unknown) => callback,
  useEffect: (effect: () => unknown) => { fixture.effects.push(effect); },
}));
vi.mock("../../hooks", () => ({ useRemote: () => ({ data: fixture.catalog, loading: false, error: "", refreshError: "", refreshing: false, reload: fixture.reload }) }));
vi.mock("./trusted-space-api", async (original) => ({
  ...await original<typeof import("./trusted-space-api")>(),
  issueConnectorUploadTicket: (...args: unknown[]) => fixture.issue(...args),
  uploadConnectorCsv: (...args: unknown[]) => fixture.upload(...args),
  registerConnectorReceipt: (...args: unknown[]) => fixture.register(...args),
  lookupConnectorReceipt: (...args: unknown[]) => fixture.lookup(...args),
  loadConnectorReceipt: (...args: unknown[]) => fixture.loadReceipt(...args),
}));

const storage = new Map<string, string>();
const pendingKey = "hiddenchain_connector_pending_receipt_v1";
const binding: ConnectorSettlementBinding = { schema_version: "connector-settlement-binding-v1", trade_batch_no: "NOV-BATCH", period_start: "2026-11-01", period_end: "2026-11-03" };
const ticket = (settlement?: ConnectorSettlementBinding): ConnectorTicket => ({ claims: {
  iss: "hiddenchain-platform", jti: "ticket-november", subject_user_id: "user-generator", organization_id: "org-generator", connector_id: "node-generator", energy_domain: "electricity", resource_id: "generation", resource_name: "发电量", classification: "L3", schema_version: "connector-csv-v1", file_format: "csv", max_bytes: 5_242_880, purpose: "LOCAL_DATASET_INGEST", issued_at: 1, expires_at: 2,
  ...(settlement ? { settlement_binding: settlement } : {}),
}, signature: "ticket-signature", public_key: "public-key", algorithm: "Ed25519" });
const receipt = (settlement?: ConnectorSettlementBinding): ConnectorSignedReceipt => ({
  receipt_id: "receipt-november", ticket_id: "ticket-november", connector_id: "node-generator", organization_id: "org-generator", energy_domain: "electricity", resource_id: "generation", resource_name: "发电量", version: 1, schema_version: "connector-csv-v1", schema_hash: "c".repeat(64), content_hash: "a".repeat(64), record_count: settlement ? 3 : 1, byte_size: 100, local_ref: "connector://node/generation/1", audit_sequence: 1, audit_hash: "d".repeat(64), issued_at: "2026-11-06T00:00:00Z", signature: "receipt-signature", public_key: "public-key", signature_algorithm: "Ed25519", signature_valid: true,
  ...(settlement ? { settlement_summary: { ...settlement, schema_version: "connector-settlement-summary-v1" as const, asset_type: "GENERATION_DATA" as const, aggregation: "SUM" as const, unit: "MWh" as const, energy_mwh: "123.456789", record_count: 3, content_hash: "a".repeat(64), claims_hash: "b".repeat(64), raw_records_returned: false as const } } : {}),
});
const registered = (settlement?: ConnectorSettlementBinding) => ({
  ticket_id: "ticket-november", receipt_id: "receipt-november", status: "VERIFIED", raw_data_centrally_stored: false,
  ...(settlement ? { settlement: { status: "REGISTERED", upload_id: "upload-november", asset_type: "GENERATION_DATA", trade_batch_no: settlement.trade_batch_no, period_start: settlement.period_start, period_end: settlement.period_end } } : {}),
});

function render() {
  fixture.cursor = 0; fixture.refCursor = 0; fixture.effects = [];
  return ConnectorPage();
}
function nodes(value: ReactNode): Array<ReactElement<Record<string, unknown>>> {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!isValidElement<Record<string, unknown>>(value)) return [];
  return [value, ...nodes(value.props.children as ReactNode)];
}
function text(value: ReactNode): string {
  if (Array.isArray(value)) return value.map(text).join("");
  if (isValidElement<Record<string, unknown>>(value)) return text(value.props.children as ReactNode);
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}
function field(tree: ReactNode, label: string) {
  const node = nodes(tree).find((item) => item.type === "label" && nodes(item).some((child) => child.type === "span" && text(child) === label));
  return node ? nodes(node).find((item) => item.type === "select" || item.type === "input") : undefined;
}
function change(label: string, value: string) {
  const target = field(render(), label)!;
  (target.props.onChange as (event: { target: { value: string } }) => void)({ target: { value } });
}
function click(label: string) {
  const target = nodes(render()).find((item) => item.type === "button" && item.props["aria-label"] === label)!;
  (target.props.onClick as () => void)();
}
function chooseFile() {
  render();
  fixture.refs[0].current = { files: [new File(["record_date,value\n2026-11-01,123\n"], "generation.csv", { type: "text/csv" })], value: "generation.csv" };
}
function fillBinding() {
  change("用于演示结算", "yes"); change("交易批次", " NOV-BATCH ");
  change("结算开始日期", binding.period_start); change("结算结束日期", binding.period_end);
}
function pending(settlement?: ConnectorSettlementBinding) {
  return { version: 1, saved_at: "2026-11-06T00:00:00Z", ticket: ticket(settlement), ticket_id: "ticket-november", upload_url: "https://node.example/ingest", receipt_lookup_url: "https://node.example/ingest/receipts/lookup", connector_id: "node-generator", organization_id: "org-generator", resource_id: "generation", resource_name: "发电量", receipt: null };
}

beforeEach(() => {
  fixture.slots = []; fixture.refs = []; fixture.effects = []; storage.clear();
  fixture.catalog = { connector: { connector_id: "node-generator", organization_id: "org-generator", organization_name: "新发电方", energy_domain: "electricity", endpoint: "https://node.example", status: "ACTIVE", capability_state: "LOCAL_REAL" }, resources: [{ resource_id: "generation", resource_name: "发电量", unit: "MWh", schema_version: "connector-csv-v1", required_columns: ["record_date", "value"], optional_columns: ["unit"], current_version: null, record_count: null, status: "NOT_REGISTERED", settlement_asset_type: "GENERATION_DATA" }], upload_contract: { mode: "BROWSER_TO_SUBJECT_CONNECTOR", file_format: "csv", max_bytes: 5_242_880, ticket_lifetime_seconds: 300 } } satisfies ConnectorCatalogPayload;
  fixture.reload.mockReset().mockResolvedValue(undefined);
  fixture.issue.mockReset().mockImplementation(async (_resource: string, _classification: string, options: { settlementBinding?: ConnectorSettlementBinding }) => ({ ticket: ticket(options.settlementBinding), upload_url: "https://node.example/ingest", receipt_lookup_url: "https://node.example/ingest/receipts/lookup", connector: { connector_id: "node-generator", organization_id: "org-generator", energy_domain: "electricity" } }));
  fixture.upload.mockReset().mockImplementation(async (_url: string, uploadedTicket: ConnectorTicket) => receipt(uploadedTicket.claims.settlement_binding));
  fixture.register.mockReset().mockImplementation(async (value: ConnectorSignedReceipt) => registered(value.settlement_summary ? binding : undefined));
  fixture.lookup.mockReset().mockResolvedValue(receipt());
  fixture.loadReceipt.mockReset().mockResolvedValue({ ticket_id: "ticket-november", receipt_id: null, status: "PENDING" });
  vi.stubGlobal("sessionStorage", { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key) });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("settlement upload form", () => {
  it.each([false, true])("distinguishes a definite CSV rejection from an uncertain network failure (network=%s)", async (network) => {
    fixture.upload.mockRejectedValue(new ApiError("fixture upload failure", network ? 503 : 422, undefined, { code: network ? "CONNECTOR_NETWORK_OR_CORS" : "CONNECTOR_VALIDATION" }));
    chooseFile(); click("将 CSV 直传企业连接器并登记签名回执");
    await vi.waitFor(() => expect(text(render())).toContain("fixture upload failure"));
    expect(storage.has(pendingKey)).toBe(network);
    expect(field(render(), "规范资源")?.props.disabled).toBe(network);
    expect(fixture.register).not.toHaveBeenCalled();
  });
  it.each([false, true])("recovers an already registered receipt centrally without contacting the connector (bound=%s)", async (bound) => {
    storage.set(pendingKey, JSON.stringify(pending(bound ? binding : undefined)));
    fixture.loadReceipt.mockResolvedValue(registered(bound ? binding : undefined));
    render(); fixture.effects.forEach((effect) => effect());
    await vi.waitFor(() => expect(storage.has(pendingKey)).toBe(false));
    expect(fixture.lookup).not.toHaveBeenCalled();
    expect(fixture.register).not.toHaveBeenCalled();
    expect(fixture.upload).not.toHaveBeenCalled();
  });
  it("does not send a selected file after its page has unmounted while awaiting a ticket", async () => {
    let resolveTicket!: (value: unknown) => void;
    fixture.issue.mockImplementation(() => new Promise((resolve) => { resolveTicket = resolve; }));
    chooseFile();
    const cleanups = fixture.effects.map((effect) => effect());
    click("将 CSV 直传企业连接器并登记签名回执");
    cleanups.forEach((cleanup) => { if (typeof cleanup === "function") cleanup(); });
    resolveTicket({ ticket: ticket(), upload_url: "https://node.example/ingest", receipt_lookup_url: "https://node.example/ingest/receipts/lookup", connector: { connector_id: "node-generator", organization_id: "org-generator", energy_domain: "electricity" } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fixture.upload).not.toHaveBeenCalled();
    expect(storage.has(pendingKey)).toBe(false);
  });
  it("does not send the file when the account changed while requesting its ticket", async () => {
    storage.set("hiddenchain_token", "first-account");
    let resolveTicket!: (value: unknown) => void;
    fixture.issue.mockImplementation(() => new Promise((resolve) => { resolveTicket = resolve; }));
    chooseFile(); click("将 CSV 直传企业连接器并登记签名回执");
    storage.set("hiddenchain_token", "second-account");
    resolveTicket({ ticket: ticket(), upload_url: "https://node.example/ingest", receipt_lookup_url: "https://node.example/ingest/receipts/lookup", connector: { connector_id: "node-generator", organization_id: "org-generator", energy_domain: "electricity" } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fixture.upload).not.toHaveBeenCalled();
    expect(field(render(), "规范资源")?.props.disabled).toBe(false);
  });
  it("preserves a newer pending upload when an unmounted upload returns its receipt", async () => {
    let resolveUpload!: (value: ConnectorSignedReceipt) => void;
    fixture.upload.mockImplementation(() => new Promise((resolve) => { resolveUpload = resolve; }));
    chooseFile();
    const cleanups = fixture.effects.map((effect) => effect());
    click("将 CSV 直传企业连接器并登记签名回执");
    await vi.waitFor(() => expect(fixture.upload).toHaveBeenCalledOnce());
    cleanups.forEach((cleanup) => { if (typeof cleanup === "function") cleanup(); });
    storage.set(pendingKey, "new-account-pending-record");
    resolveUpload(receipt());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fixture.register).not.toHaveBeenCalled();
    expect(storage.get(pendingKey)).toBe("new-account-pending-record");
  });
  it.each([false, true])("unlocks a pending upload after the server confirms its recovery window expired (receipt=%s)", async (hasReceipt) => {
    storage.set(pendingKey, JSON.stringify({ ...pending(binding), receipt: hasReceipt ? receipt(binding) : null }));
    const expired = new ApiError("回执补登记期已过，请重新接入该资源", 410);
    if (hasReceipt) fixture.register.mockRejectedValue(expired);
    else fixture.lookup.mockRejectedValue(expired);
    render(); fixture.effects.forEach((effect) => effect());
    await vi.waitFor(() => expect(storage.has(pendingKey)).toBe(false));
    expect(field(render(), "规范资源")?.props.disabled).toBe(false);
    expect(text(render())).toContain("重新接入");
    expect(fixture.upload).not.toHaveBeenCalled();
  });
  it("hides the optional settlement mode when the server catalog does not allow it", () => {
    delete (fixture.catalog as ConnectorCatalogPayload).resources[0].settlement_asset_type;
    expect(field(render(), "用于演示结算")).toBeUndefined();
  });
  it("keeps ordinary uploads unbound and does not announce settlement readiness", async () => {
    chooseFile(); click("将 CSV 直传企业连接器并登记签名回执");
    await vi.waitFor(() => expect(fixture.register).toHaveBeenCalledOnce());
    expect(fixture.issue.mock.calls[0][2].settlementBinding).toBeUndefined();
    expect(text(render())).toContain("本地上传与签名回执登记均已完成");
    expect(text(render())).not.toContain("演示结算数据已登记");
  });
  it("uploads with the signed normalized binding and reports the actual registered reference", async () => {
    chooseFile(); fillBinding(); click("将 CSV 直传企业连接器并登记签名回执");
    await vi.waitFor(() => expect(text(render())).toContain("引用 upload-november"));
    expect(fixture.issue.mock.calls[0][2]).toEqual({ settlementBinding: binding, signal: expect.any(AbortSignal) });
    expect(fixture.upload.mock.calls[0][1].claims.settlement_binding).toEqual(binding);
    expect(fixture.register.mock.calls[0][0].settlement_summary.energy_mwh).toBe("123.456789");
    expect(text(render())).toContain("由交易中心创建结算任务");
    expect(storage.has(pendingKey)).toBe(false);
  });
  it("rejects invalid date ranges before requesting a ticket", () => {
    chooseFile(); fillBinding(); change("结算结束日期", "2026-10-31"); click("将 CSV 直传企业连接器并登记签名回执");
    expect(fixture.issue).not.toHaveBeenCalled();
    expect(text(render())).toContain("结束日期不能早于开始日期");
  });
  it("stops before sending the file when the ticket binding differs", async () => {
    chooseFile(); fillBinding();
    fixture.issue.mockResolvedValue({ ticket: ticket({ ...binding, trade_batch_no: "OTHER" }), upload_url: "https://node.example/ingest", receipt_lookup_url: "https://node.example/ingest/receipts/lookup", connector: { connector_id: "node-generator", organization_id: "org-generator", energy_domain: "electricity" } });
    click("将 CSV 直传企业连接器并登记签名回执");
    await vi.waitFor(() => expect(text(render())).toContain("一次性上传凭证与当前目录不一致"));
    expect(fixture.upload).not.toHaveBeenCalled();
  });
  it("retains recovery metadata and locks context when the receipt binding differs", async () => {
    chooseFile(); fillBinding();
    fixture.upload.mockResolvedValue(receipt({ ...binding, period_end: "2026-11-04" }));
    click("将 CSV 直传企业连接器并登记签名回执");
    await vi.waitFor(() => expect(text(render())).toContain("签名回执与当前票据不一致"));
    expect(fixture.register).not.toHaveBeenCalled();
    expect(field(render(), "交易批次")?.props.disabled).toBe(true);
    expect(field(render(), "规范资源")?.props.disabled).toBe(true);
    expect(storage.get(pendingKey)).toContain("settlement_binding");
    expect(storage.get(pendingKey)).not.toContain("record_date,value");
  });
  it("does not clear recovery data if central registration has no settlement reference", async () => {
    chooseFile(); fillBinding(); fixture.register.mockResolvedValue(registered());
    click("将 CSV 直传企业连接器并登记签名回执");
    await vi.waitFor(() => expect(text(render())).toContain("结算引用尚未确认"));
    expect(storage.has(pendingKey)).toBe(true);
    expect(text(render())).not.toContain("演示结算数据已登记");
  });
  it.each([false, true])("restores pending receipt registration without uploading again (bound=%s)", async (bound) => {
    storage.set(pendingKey, JSON.stringify(pending(bound ? binding : undefined)));
    fixture.lookup.mockResolvedValue(receipt(bound ? binding : undefined));
    const tree = render();
    expect(field(tree, "规范资源")?.props.disabled).toBe(true);
    if (bound) expect(field(tree, "交易批次")?.props.value).toBe("NOV-BATCH");
    fixture.effects.forEach((effect) => effect());
    await vi.waitFor(() => expect(storage.has(pendingKey)).toBe(false));
    expect(fixture.upload).not.toHaveBeenCalled();
    expect(fixture.issue).not.toHaveBeenCalled();
    expect(fixture.lookup).toHaveBeenCalledOnce();
    expect(text(render())).toContain(bound ? "引用 upload-november" : "本地上传与签名回执登记均已完成");
  });
  it("downloads blank daily values for the selected binding", async () => {
    fillBinding();
    let exported: Blob | undefined;
    vi.spyOn(URL, "createObjectURL").mockImplementation((value) => { exported = value as Blob; return "blob:test"; });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.stubGlobal("document", { createElement: () => ({ click: vi.fn() }) });
    click("在浏览器本地生成并下载规范 CSV 示例");
    expect(await exported!.text()).toContain("2026-11-01,,,新发电方,MWh\r\n2026-11-02,,,新发电方,MWh\r\n2026-11-03,,,新发电方,MWh");
    expect(await exported!.text()).not.toContain(",100,");
  });
});
