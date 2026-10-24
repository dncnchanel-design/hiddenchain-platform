import type { CatalogAsset, QueryIntent, UsageRequest } from "./trusted-space-api";
import { findQueryAuthorization } from "./query-authorization";

export function queryProviders(assets: CatalogAsset[], intent: QueryIntent, requests: UsageRequest[], orgId: string) {
  const hasGrant = (asset: CatalogAsset) => Boolean(findQueryAuthorization(requests, asset, intent, orgId));
  const coversPeriod = (asset: CatalogAsset) => Boolean(asset.latest_version?.period_start && asset.latest_version.period_end);
  return assets.filter((asset) => {
    if (asset.status !== "ACTIVE" || asset.source.status !== "ACTIVE" || asset.metadata?.resource_id !== intent.resource) return false;
    if (!asset.actions.can_request_usage && !hasGrant(asset) && !(asset.actions.can_compute_own && asset.provider.org_id === orgId)) return false;
    const version = asset.latest_version;
    return !(version?.period_start && intent.start_date && intent.start_date < version.period_start) && !(version?.period_end && intent.end_date && intent.end_date > version.period_end);
  }).sort((left, right) => Number(hasGrant(right)) - Number(hasGrant(left)) || Number(coversPeriod(right)) - Number(coversPeriod(left)));
}
