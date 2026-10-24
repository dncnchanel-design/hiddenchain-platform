import { safeDecodeRouteSegment } from "./types";

export interface AssistantContext {
  page_path: string;
  entity_type?: string;
  entity_id?: string;
}

export function assistantContext(pathname: string, search = ""): AssistantContext {
  const page = { page_path: `${pathname}${search}`.slice(0, 255) };
  const params = new URLSearchParams(search);
  const parts = pathname.split("/").filter(Boolean);
  const index = parts.indexOf("trusted-space");
  if (index < 0) return page;
  const segment = parts[index + 1];
  const selected = (type: string, id?: string | null): AssistantContext => id && id.length <= 96 && !Array.from(id).some((character) => character.charCodeAt(0) < 32)
    ? { ...page, entity_type: type, entity_id: id } : page;
  if (segment === "authorizations") return selected("data_usage_request", params.get("request"));
  if (segment === "audit") {
    if (params.get("view") === "reports" && params.get("report_id")) return selected("audit_report", params.get("report_id"));
    if (params.get("view") === "anomalies" && params.get("event_id")) return selected("anomaly_event", params.get("event_id"));
    if (parts[index + 2] === "tasks") return selected("settlement_task", safeDecodeRouteSegment(parts[index + 3] || ""));
    return selected("settlement_task", params.get("task_id"));
  }
  const encoded = parts[index + 2];
  if (!encoded || segment === "mpc" && encoded === "new") return page;
  const types: Record<string, string> = { assets: "data_asset", apply: "data_asset", contracts: "data_contract", ttc: "settlement_task", mpc: "privacy_compute_job", results: "settlement_result" };
  return types[segment] ? selected(types[segment], safeDecodeRouteSegment(encoded)) : page;
}

export function assistantContextKey(context: AssistantContext): string {
  return JSON.stringify([context.page_path, context.entity_type || "", context.entity_id || ""]);
}
