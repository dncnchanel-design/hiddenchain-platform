import { api, post, type ApiCommandOptions } from "../../api";

export type SettlementTaskSummary = {
  task_id: string;
  task_name: string;
  status: string;
  state_version: number;
  allowed_actions?: string[];
  ttc?: { state?: string };
  readiness?: { preflight_passed?: boolean; preflight_blockers?: string[] };
};

export function canRunSettlementTask(role: string, task: SettlementTaskSummary | null) {
  return role === "EXCHANGE" && Boolean(task?.readiness?.preflight_passed)
    && Boolean(task?.allowed_actions?.some((action) => action === "RUN_SETTLEMENT" || action === "RETRY_SETTLEMENT"))
    && !["REJECTED", "CANCELLED", "EXPIRED", "ARCHIVED"].includes(task?.ttc?.state || "");
}

export function loadSettlementTask(taskId: string, options: ApiCommandOptions = {}) {
  return api<SettlementTaskSummary>(`/settlement/tasks/${encodeURIComponent(taskId)}`, { cache: "no-store", ...options });
}

export function runSettlementTask(taskId: string, options: ApiCommandOptions) {
  return post(`/settlement/tasks/${encodeURIComponent(taskId)}/run`, {
    compute_mode: "LOCAL_CONTROLLED", algorithm_code: "CONTROLLED_SETTLEMENT_V1",
  }, { timeoutMs: 120_000, ...options });
}

export function decideAuditReport(reportId: string, decision: "APPROVE" | "REJECT", opinion: string, options: ApiCommandOptions) {
  return post(`/audit/reports/${encodeURIComponent(reportId)}/decision`, { decision, opinion }, options);
}

export function resolveAuditAnomaly(eventId: string, body: { resolution: string; disposition: "ACK" | "IGNORE" | "REWORK" }, stateVersion: number, options: ApiCommandOptions) {
  return post(`/anomalies/${encodeURIComponent(eventId)}/resolve`, body, { ...options, ifMatch: `"${stateVersion}"` });
}
