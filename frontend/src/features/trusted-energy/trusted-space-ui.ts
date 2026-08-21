import type { TrustedNotification, WorkbenchQuickAction } from "./trusted-space-api";

export function notificationPath(notification: Pick<TrustedNotification, "entity_type" | "entity_id">): string | null {
  if (!notification.entity_id) return null;
  const entityType = (notification.entity_type || "").toUpperCase();
  const id = encodeURIComponent(notification.entity_id);
  if (entityType === "DATA_USAGE_REQUEST") return `/trusted-space/authorizations?request=${id}`;
  if (entityType === "DATA_CONTRACT") return `/trusted-space/contracts/${id}`;
  if (entityType === "SETTLEMENT_TASK") return `/trusted-space/ttc/${id}`;
  if (entityType === "SETTLEMENT_RESULT") return `/trusted-space/results/${id}`;
  return null;
}

export function quickActionPath(action: Pick<WorkbenchQuickAction, "allowed" | "path">): string | null {
  const path = action.path.trim();
  return action.allowed && path ? path : null;
}
