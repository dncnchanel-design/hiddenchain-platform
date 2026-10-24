import type { CatalogAsset, QueryIntent, UsageRequest } from "./trusted-space-api";

const FIXED_FUNCTIONS = new Set(["sum", "average", "max", "min", "count", "median", "growth_rate", "yoy", "mom", "group_by", "threshold", "trend", "psi", "mpc_aggregation"]);

export function findQueryAuthorization(requests: UsageRequest[], asset: CatalogAsset | undefined, intent: QueryIntent | null, orgId: string | undefined, now = Date.now()) {
  if (!asset || !intent || !orgId) return undefined;
  return requests.find((request) => {
    const expiry = request.expires_at && Date.parse(/[zZ]|[+-]\d{2}:\d{2}$/.test(request.expires_at) ? request.expires_at : `${request.expires_at}Z`);
    if (request.status !== "APPROVED" || !expiry || expiry <= now || request.applicant.org_id !== orgId || request.asset.asset_id !== asset.asset_id || request.provider.org_id !== asset.provider.org_id) return false;
    if (request.usage_budget?.usable === false || request.usage_budget?.remaining_uses === 0) return false;
    if (request.asset.version_id && asset.latest_version?.version_id && request.asset.version_id !== asset.latest_version.version_id) return false;
    const scope = request.requested_scope || {};
    for (const key of ["start_date", "period_start"]) if (scope[key] && (typeof scope[key] !== "string" || !intent.start_date || intent.start_date < scope[key])) return false;
    for (const key of ["end_date", "period_end"]) if (scope[key] && (typeof scope[key] !== "string" || !intent.end_date || intent.end_date > scope[key])) return false;
    for (const [key, value] of [["region", intent.region], ["resource", intent.resource], ["function", intent.function], ["function_code", intent.function]] as const) {
      if (scope[key] != null && scope[key] !== "" && scope[key] !== value) return false;
    }
    for (const [key, value] of [["regions", intent.region], ["allowed_regions", intent.region], ["functions", intent.function], ["allowed_functions", intent.function]] as const) {
      if (key in scope && (!Array.isArray(scope[key]) || !scope[key].includes(value))) return false;
    }
    const functions = request.requested_fields.filter((field) => FIXED_FUNCTIONS.has(field));
    return !functions.length || functions.includes(intent.function || "");
  });
}
