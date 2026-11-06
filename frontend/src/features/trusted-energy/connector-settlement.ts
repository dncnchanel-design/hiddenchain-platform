import { settlementDateCount } from "../../settlement-catalog";
import { ApiError } from "../../api";
import type { ConnectorReceiptPayload, ConnectorSettlementAssetType, ConnectorSettlementBinding, ConnectorSignedReceipt, ConnectorTicket } from "./trusted-space-api";

export function createSettlementBinding(batch: string, start: string, end: string): ConnectorSettlementBinding {
  const tradeBatch = batch.trim();
  if (tradeBatch.length < 3 || tradeBatch.length > 64) throw new Error("交易批次须填写 3–64 个字符");
  const days = settlementDateCount(start, end);
  if (!days) throw new Error("请填写有效的结算起止日期，结束日期不能早于开始日期");
  if (days > 366) throw new Error("演示结算期间不能超过 366 天");
  return { schema_version: "connector-settlement-binding-v1", trade_batch_no: tradeBatch, period_start: start, period_end: end };
}

export function settlementBindingMatches(expected: ConnectorSettlementBinding | undefined, actual: unknown): boolean {
  if (!expected) return actual === undefined || actual === null;
  if (!actual || typeof actual !== "object" || Array.isArray(actual)) return false;
  const binding = actual as Record<string, unknown>;
  return binding.schema_version === expected.schema_version && binding.trade_batch_no === expected.trade_batch_no
    && binding.period_start === expected.period_start && binding.period_end === expected.period_end;
}

function ticketAssetType(ticket: ConnectorTicket): ConnectorSettlementAssetType | null {
  if (ticket.claims.energy_domain !== "electricity") return null;
  return ticket.claims.resource_id === "generation" ? "GENERATION_DATA" : ticket.claims.resource_id === "supply" ? "RETAIL_DATA" : null;
}

function canonicalEnergy(value: unknown): boolean {
  if (typeof value !== "string" || !/^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/.test(value)) return false;
  const [whole, fraction = ""] = value.split(".");
  if (whole.length > 13) return false;
  return BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0")) <= 1_000_000_000_000_000_000n;
}

export function receiptMatchesSettlement(ticket: ConnectorTicket, receipt: ConnectorSignedReceipt): boolean {
  const binding = ticket.claims.settlement_binding;
  const summary = receipt.settlement_summary;
  if (!binding) return summary === undefined || summary === null;
  if (!summary || typeof summary !== "object") return false;
  const days = settlementDateCount(binding.period_start, binding.period_end);
  return days > 0 && days <= 366 && summary.schema_version === "connector-settlement-summary-v1"
    && summary.trade_batch_no === binding.trade_batch_no && summary.period_start === binding.period_start && summary.period_end === binding.period_end
    && summary.asset_type === ticketAssetType(ticket) && summary.aggregation === "SUM" && summary.unit === "MWh"
    && canonicalEnergy(summary.energy_mwh) && summary.record_count === days && receipt.record_count === days
    && summary.content_hash === receipt.content_hash && /^[0-9a-f]{64}$/.test(summary.claims_hash)
    && summary.raw_records_returned === false;
}

export function connectorRegistrationMessage(payload: ConnectorReceiptPayload, ticket: ConnectorTicket, expectedReceiptId?: string): string {
  if (payload.ticket_id !== ticket.claims.jti || !payload.receipt_id || (expectedReceiptId && payload.receipt_id !== expectedReceiptId)) {
    throw new ApiError("登记响应与上传票据不一致，签名回执仍待核验", 502, undefined, { code: "CONNECTOR_REGISTRATION_MISMATCH" });
  }
  const binding = ticket.claims.settlement_binding;
  if (!binding) return "本地上传与签名回执登记均已完成";
  const settlement = payload.settlement;
  if (!settlement || settlement.status !== "REGISTERED" || !settlement.upload_id
    || settlement.trade_batch_no !== binding.trade_batch_no || settlement.period_start !== binding.period_start || settlement.period_end !== binding.period_end
    || settlement.asset_type !== ticketAssetType(ticket)) throw new ApiError("签名回执的结算引用尚未确认，请补登记后重试", 502, undefined, { code: "CONNECTOR_SETTLEMENT_NOT_REGISTERED" });
  return `演示结算数据已登记：批次 ${settlement.trade_batch_no}，${settlement.period_start} 至 ${settlement.period_end}，引用 ${settlement.upload_id}。双方使用相同批次和期间登记后，由交易中心创建结算任务。`;
}

function csvCell(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export function settlementCsvTemplate(binding: ConnectorSettlementBinding, organizationName: string): string {
  const valid = createSettlementBinding(binding.trade_batch_no, binding.period_start, binding.period_end);
  const days = settlementDateCount(valid.period_start, valid.period_end);
  const start = Date.parse(`${valid.period_start}T00:00:00Z`);
  const rows = Array.from({ length: days }, (_, index) => [
    new Date(start + index * 86_400_000).toISOString().slice(0, 10), "", "", organizationName, "MWh",
  ].map(csvCell).join(","));
  return ["record_date,value,region,organization,unit", ...rows].join("\r\n");
}
