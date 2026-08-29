import type { SessionPayload } from "./types";

export interface LegacyLocation {
  pathname: string;
  search?: string;
  hash?: string;
}

export interface LegacyDestination {
  to: string;
  menuCode: "overview" | "catalog" | "connector" | "authorization" | "compute" | "audit";
  menuPath: string;
  exchangeOnly?: boolean;
}

const TRUSTED = "/trusted-space";

function encodedSegment(value: string | null): string | null {
  if (!value) return null;
  try {
    return encodeURIComponent(decodeURIComponent(value));
  } catch {
    return null;
  }
}

function querySegment(value: string | null): string | null {
  return value ? encodeURIComponent(value) : null;
}

function destination(
  pathname: string,
  search: string,
  hash: string,
  menuCode: LegacyDestination["menuCode"],
  menuPath: string,
  exchangeOnly = false,
): LegacyDestination {
  return { to: `${pathname}${search}${hash}`, menuCode, menuPath, ...(exchangeOnly ? { exchangeOnly: true } : {}) };
}

export function legacyBusinessDestination({ pathname, search = "", hash = "" }: LegacyLocation): LegacyDestination | null {
  const routePath = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  if (routePath === "/workbench") return destination(`${TRUSTED}/workbench`, search, hash, "overview", `${TRUSTED}/workbench`);
  if (routePath === "/data-space") {
    const authorization = hash === "#data-authorizations";
    return destination(
      `${TRUSTED}/${authorization ? "authorizations" : "catalog"}`,
      search,
      hash,
      authorization ? "authorization" : "catalog",
      `${TRUSTED}/${authorization ? "authorizations" : "catalog"}`,
    );
  }
  if (["/data/upload", "/data/generation", "/data/retail"].includes(routePath)) {
    return destination(`${TRUSTED}/connector`, search, hash, "connector", `${TRUSTED}/connector`);
  }
  if (routePath === "/rules" || routePath === "/trusted-execution") {
    return destination(`${TRUSTED}/authorizations`, search, hash, "authorization", `${TRUSTED}/authorizations`);
  }
  if (routePath === "/settlements/new") {
    return destination(`${TRUSTED}/mpc/new`, search, hash, "compute", `${TRUSTED}/mpc`, true);
  }
  if (routePath === "/settlements") return destination(`${TRUSTED}/mpc`, search, hash, "compute", `${TRUSTED}/mpc`);

  const settlementMatch = /^\/settlements\/([^/]+)$/.exec(routePath);
  if (settlementMatch) {
    const taskId = encodedSegment(settlementMatch[1]);
    return taskId ? destination(`${TRUSTED}/ttc/${taskId}`, search, hash, "compute", `${TRUSTED}/mpc`) : null;
  }

  if (routePath === "/compute") {
    const jobId = querySegment(new URLSearchParams(search).get("job_id"));
    return destination(`${TRUSTED}/mpc${jobId ? `/${jobId}` : ""}`, search, hash, "compute", `${TRUSTED}/mpc`);
  }
  if (routePath === "/results") {
    const resultId = querySegment(new URLSearchParams(search).get("result_id"));
    return destination(`${TRUSTED}/results${resultId ? `/${resultId}` : ""}`, search, hash, "compute", `${TRUSTED}/mpc`);
  }
  if (["/evidence", "/audit", "/reports", "/anomalies"].includes(routePath)) {
    const taskId = querySegment(new URLSearchParams(search).get("task_id"));
    return destination(`${TRUSTED}/audit${taskId ? `/tasks/${taskId}` : ""}`, search, hash, "audit", `${TRUSTED}/audit`);
  }

  const contractMatch = /^\/contracts\/([^/]+)$/.exec(routePath);
  if (contractMatch) {
    const contractId = encodedSegment(contractMatch[1]);
    return contractId ? destination(`${TRUSTED}/contracts/${contractId}`, search, hash, "compute", `${TRUSTED}/mpc`) : null;
  }

  return null;
}

export function canUseLegacyDestination(session: SessionPayload, target: LegacyDestination): boolean {
  if (target.exchangeOnly && session.user.role_code !== "EXCHANGE") return false;
  return session.menus.some((menu) => menu.code === target.menuCode && menu.path === target.menuPath);
}
