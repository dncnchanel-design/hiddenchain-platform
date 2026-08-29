export type TrustedViewKey =
  | "workbench"
  | "query"
  | "identity"
  | "catalog"
  | "connector"
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
  { key: "workbench" as const, menuCode: "overview", label: "运行总览", icon: "LayoutDashboard" },
  { key: "query" as const, menuCode: "query", label: "智能数据查询", icon: "Search" },
  { key: "catalog" as const, menuCode: "catalog", label: "数据目录", icon: "Database" },
  { key: "connector" as const, menuCode: "connector", label: "数据连接", icon: "Cable" },
  { key: "authorizations" as const, menuCode: "authorization", label: "数据授权", icon: "FileSignature" },
  { key: "audit" as const, menuCode: "audit", label: "审计追溯", icon: "ScanSearch" },
  { key: "mpc" as const, menuCode: "compute", label: "隐私计算", icon: "Network" },
];

export const primaryNavItems = navItems;

export function safeDecodeRouteSegment(value: string): string | undefined {
  try {
    return decodeURIComponent(value);
  } catch {
    return undefined;
  }
}

export function routeForView(key: TrustedViewKey, id?: string) {
  if (key === "asset") return id ? `${TRUSTED_BASE}/assets/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/catalog`;
  if (key === "apply") return id ? `${TRUSTED_BASE}/apply/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/catalog`;
  if (key === "connector") return `${TRUSTED_BASE}/connector`;
  if (key === "query") return `${TRUSTED_BASE}/query`;
  if (key === "authorizations") return `${TRUSTED_BASE}/authorizations`;
  if (key === "contract") return id ? `${TRUSTED_BASE}/contracts/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/contracts`;
  if (key === "ttc") return id ? `${TRUSTED_BASE}/ttc/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/ttc`;
  if (key === "mpc") return id ? `${TRUSTED_BASE}/mpc/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/mpc`;
  if (key === "results") return id ? `${TRUSTED_BASE}/results/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/results`;
  if (key === "audit") return id ? `${TRUSTED_BASE}/audit/tasks/${encodeURIComponent(id)}` : `${TRUSTED_BASE}/audit`;
  return `${TRUSTED_BASE}/${key}`;
}
export function helpViewForTrustedView(view: TrustedViewKey): string {
  if (view === "query") return "catalog";
  if (view === "connector") return "identity";
  return view === "contract" ? "contracts" : view;
}

export function trustedMenuCodeForView(view: TrustedViewKey): string {
  if (view === "identity") return "participants";
  if (view === "asset") return "catalog";
  if (view === "connector") return "connector";
  if (view === "apply" || view === "authorizations") return "authorization";
  if (view === "contract" || view === "ttc" || view === "results") return "compute";
  return navItems.find((item) => item.key === view)?.menuCode || view;
}

export function isKnownTrustedPath(pathname: string): boolean {
  if (pathname === TRUSTED_BASE || pathname === `${TRUSTED_BASE}/`) return true;
  if (!pathname.startsWith(`${TRUSTED_BASE}/`)) return false;
  const suffix = pathname.slice(`${TRUSTED_BASE}/`.length);
  return /^(workbench|query|identity|catalog|connector|authorizations|assets(?:\/[^/]+)?|apply(?:\/[^/]+)?|contracts(?:\/[^/]+)?|ttc(?:\/[^/]+)?|mpc(?:\/[^/]+)?|results(?:\/[^/]+)?|audit(?:\/tasks\/[^/]+)?)$/.test(suffix)
    && suffix.split("/").every((segment) => safeDecodeRouteSegment(segment) !== undefined);
}

export function trustedEntityId(pathname: string, segment: "assets" | "apply" | "contracts" | "ttc" | "mpc" | "results" | "audit") {
  if (segment === "audit") {
    const prefix = `${TRUSTED_BASE}/audit/tasks/`;
    if (!pathname.startsWith(prefix)) return undefined;
    const value = pathname.slice(prefix.length).split("/")[0];
    return value ? safeDecodeRouteSegment(value) : undefined;
  }
  const prefix = `${TRUSTED_BASE}/${segment}/`;
  if (!pathname.startsWith(prefix)) return undefined;
  const value = pathname.slice(prefix.length).split("/")[0];
  return value ? safeDecodeRouteSegment(value) : undefined;
}

export function getTrustedView(pathname: string): TrustedViewKey {
  if (pathname.includes("/query")) return "query";
  if (pathname.includes("/identity")) return "identity";
  if (pathname.includes("/catalog")) return "catalog";
  if (pathname.includes("/connector")) return "connector";
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
