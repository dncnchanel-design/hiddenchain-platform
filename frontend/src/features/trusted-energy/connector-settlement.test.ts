import { describe, expect, it } from "vitest";
import { connectorRegistrationMessage, createSettlementBinding, receiptMatchesSettlement, settlementBindingMatches, settlementCsvTemplate } from "./connector-settlement";
import type { ConnectorSignedReceipt, ConnectorTicket } from "./trusted-space-api";

const binding = createSettlementBinding(" NOV-BATCH ", "2026-11-01", "2026-11-03");
const ticket = { claims: { energy_domain: "electricity", resource_id: "generation", jti: "ticket-new", settlement_binding: binding } } as ConnectorTicket;
const receipt = { receipt_id: "receipt-new", record_count: 3, content_hash: "a".repeat(64), settlement_summary: {
  ...binding, schema_version: "connector-settlement-summary-v1", asset_type: "GENERATION_DATA", aggregation: "SUM", unit: "MWh", energy_mwh: "123.000001", record_count: 3, content_hash: "a".repeat(64), claims_hash: "b".repeat(64), raw_records_returned: false,
} } as unknown as ConnectorSignedReceipt;

describe("connector settlement binding", () => {
  it("normalizes the batch and compares all signed binding fields", () => {
    expect(binding.trade_batch_no).toBe("NOV-BATCH");
    expect(settlementBindingMatches(binding, { ...binding })).toBe(true);
    expect(settlementBindingMatches(binding, { ...binding, trade_batch_no: "OTHER" })).toBe(false);
    expect(settlementBindingMatches(binding, { ...binding, schema_version: "unknown" })).toBe(false);
    expect(settlementBindingMatches(undefined, undefined)).toBe(true);
    expect(settlementBindingMatches(undefined, binding)).toBe(false);
  });
  it.each([
    ["ab", "2026-11-01", "2026-11-03"], ["x".repeat(65), "2026-11-01", "2026-11-03"],
    ["batch", "2026-02-29", "2026-03-01"], ["batch", "2026-11-03", "2026-11-01"],
    ["batch", "2026-01-01", "2027-01-02"], ["batch", "", "2026-11-01"],
  ])("rejects an invalid binding (%s, %s, %s)", (batch, start, end) => {
    expect(() => createSettlementBinding(batch, start, end)).toThrow();
  });
  it("builds one blank energy row for each day, including leap day, and escapes organization text", () => {
    const csv = settlementCsvTemplate(createSettlementBinding("LEAP", "2024-02-28", "2024-03-01"), '企业,"甲"');
    expect(csv.split("\r\n")).toEqual([
      "record_date,value,region,organization,unit",
      '2024-02-28,,,"企业,""甲""",MWh', '2024-02-29,,,"企业,""甲""",MWh', '2024-03-01,,,"企业,""甲""",MWh',
    ]);
  });
});

describe("signed settlement receipt and registration", () => {
  it("accepts matching metadata and keeps legacy unbound receipts compatible", () => {
    expect(receiptMatchesSettlement(ticket, receipt)).toBe(true);
    expect(receiptMatchesSettlement({ claims: { resource_id: "generation" } } as ConnectorTicket, { ...receipt, settlement_summary: undefined })).toBe(true);
    expect(receiptMatchesSettlement({ claims: { resource_id: "generation" } } as ConnectorTicket, receipt)).toBe(false);
    expect(receiptMatchesSettlement(ticket, { ...receipt, settlement_summary: undefined })).toBe(false);
  });
  it.each([
    { trade_batch_no: "OTHER" }, { period_end: "2026-11-04" }, { unit: "MW" }, { asset_type: "RETAIL_DATA" }, { aggregation: "AVERAGE" },
    { energy_mwh: "-1" }, { energy_mwh: "NaN" }, { energy_mwh: "1e3" }, { energy_mwh: "1.0000001" }, { energy_mwh: "1000000000000.000001" },
    { record_count: 2 }, { content_hash: "c".repeat(64) }, { claims_hash: "invalid" }, { raw_records_returned: true },
  ])("rejects a mismatched or invalid summary %j", (change) => {
    expect(receiptMatchesSettlement(ticket, { ...receipt, settlement_summary: { ...receipt.settlement_summary, ...change } } as ConnectorSignedReceipt)).toBe(false);
  });
  it("reports only a backend-confirmed settlement registration", () => {
    const payload = { ticket_id: "ticket-new", receipt_id: "receipt-new", status: "VERIFIED", raw_data_centrally_stored: false as const };
    expect(() => connectorRegistrationMessage(payload, ticket)).toThrow("结算引用尚未确认");
    const settled = { ...payload, settlement: { status: "REGISTERED" as const, upload_id: "upload-new", asset_type: "GENERATION_DATA" as const, trade_batch_no: binding.trade_batch_no, period_start: binding.period_start, period_end: binding.period_end } };
    expect(connectorRegistrationMessage(settled, ticket, "receipt-new")).toContain("引用 upload-new");
    expect(connectorRegistrationMessage(settled, ticket)).toContain("交易中心创建");
    expect(() => connectorRegistrationMessage({ ...settled, ticket_id: "other" }, ticket)).toThrow("票据不一致");
    expect(() => connectorRegistrationMessage({ ...settled, settlement: { ...settled.settlement, period_end: "2026-12-01" } }, ticket)).toThrow("结算引用尚未确认");
  });
});
