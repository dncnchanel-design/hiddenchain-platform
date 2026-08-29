import type { AuditListPayload, AuditTaskPayload } from "./trusted-space-api";

export type AuditRouteRemoteData =
  | { kind: "list"; page: number; payload: AuditListPayload }
  | { kind: "detail"; taskId: string; payload: AuditTaskPayload };

export function auditListForRoute(data: AuditRouteRemoteData | null, page: number): AuditListPayload | null {
  return data?.kind === "list" && data.page === page ? data.payload : null;
}

export function auditDetailForRoute(data: AuditRouteRemoteData | null, taskId: string): AuditTaskPayload | null {
  return data?.kind === "detail" && data.taskId === taskId ? data.payload : null;
}
