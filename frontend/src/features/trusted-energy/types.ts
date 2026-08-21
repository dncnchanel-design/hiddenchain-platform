export type TrustedViewKey =
  | "workbench"
  | "identity"
  | "catalog"
  | "authorizations"
  | "asset"
  | "apply"
  | "contract"
  | "ttc"
  | "mpc"
  | "results"
  | "audit";

export const TRUSTED_BASE = "/trusted-space";

export const navItems = [
  { key: "workbench" as const, menuCode: "workbench", label: "工作台", icon: "LayoutDashboard" },
  { key: "identity" as const, menuCode: "identity", label: "身份中心", icon: "Fingerprint" },
  { key: "catalog" as const, menuCode: "catalog", label: "数据目录", icon: "Database" },
  { key: "authorizations" as const, menuCode: "access-requests", label: "授权记录", icon: "FileSignature" },
  { key: "contract" as const, menuCode: "settlements", label: "合同协商", icon: "FileSignature" },
  { key: "mpc" as const, menuCode: "compute", label: "隐私计算", icon: "Network" },
  { key: "results" as const, menuCode: "compute", label: "结果与存证", icon: "BadgeCheck" },
  { key: "audit" as const, menuCode: "audit", label: "审计中心", icon: "ScanSearch" },
];

export function routeForView(key: TrustedViewKey, id?: string) {
  if (key === "asset") return id ? `${TRUSTED_BASE}/assets/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/catalog`;
  if (key === "apply") return id ? `${TRUSTED_BASE}/apply/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/catalog`;
  if (key === "authorizations") return `${TRUSTED_BASE}/authorizations`;
  if (key === "contract") return id ? `${TRUSTED_BASE}/contracts/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/contracts`;
  if (key === "ttc") return id ? `${TRUSTED_BASE}/ttc/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/ttc`;
  if (key === "mpc") return id ? `${TRUSTED_BASE}/mpc/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/mpc`;
  if (key === "results") return id ? `${TRUSTED_BASE}/results/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/results`;
  if (key === "audit") return id ? `${TRUSTED_BASE}/audit/tasks/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/audit`;
  return `${TRUSTED_BASE}/${key}`;
}
export function helpViewForTrustedView(view: TrustedViewKey): string {
  return view === "contract" ? "contracts" : view;
}

export function trustedMenuCodeForView(view: TrustedViewKey): string {
  if (view === "asset") return "asset-passport";
  if (view === "apply" || view === "authorizations") return "access-requests";
  if (view === "ttc") return "settlements";
  return navItems.find((item) => item.key === view)?.menuCode || view;
}

export function isKnownTrustedPath(pathname: string): boolean {
  if (pathname === TRUSTED_BASE || pathname === `${TRUSTED_BASE}/`) return true;
  if (!pathname.startsWith(`${TRUSTED_BASE}/`)) return false;
  const suffix = pathname.slice(`${TRUSTED_BASE}/`.length);
  return /^(workbench|identity|catalog|authorizations|assets(?:\/[^/]+)?|apply(?:\/[^/]+)?|contracts(?:\/[^/]+)?|ttc(?:\/[^/]+)?|mpc(?:\/[^/]+)?|results(?:\/[^/]+)?|audit(?:\/tasks\/[^/]+)?)$/.test(suffix);
}

export function trustedEntityId(pathname: string, segment: "assets" | "apply" | "contracts" | "ttc" | "mpc" | "results" | "audit") {
  if (segment === "audit") {
    const prefix = `${TRUSTED_BASE}/audit/tasks/`;
    if (!pathname.startsWith(prefix)) return undefined;
    const value = pathname.slice(prefix.length).split("/")[0];
    return value ? decodeURIComponent(value) : undefined;
  }
  const prefix = `${TRUSTED_BASE}/${segment}/`;
  if (!pathname.startsWith(prefix)) return undefined;
  const value = pathname.slice(prefix.length).split("/")[0];
  return value ? decodeURIComponent(value) : undefined;
}

export function getTrustedView(pathname: string): TrustedViewKey {
  if (pathname.includes("/identity")) return "identity";
  if (pathname.includes("/catalog")) return "catalog";
  if (pathname.includes("/authorizations")) return "authorizations";
  if (pathname.includes("/assets")) return "asset";
  if (pathname.includes("/apply")) return "apply";
  if (pathname.includes("/contracts")) return "contract";
  if (pathname.includes("/ttc")) return "ttc";
  if (pathname.includes("/mpc")) return "mpc";
  if (pathname.includes("/results")) return "results";
  if (pathname.includes("/audit")) return "audit";
  return "workbench";
}
