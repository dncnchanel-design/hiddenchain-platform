export type ConnectorReadiness = {
  health_url: string;
  organization_id: string;
  energy_domain: string;
  connector_id: string;
  raw_data_accessed: false;
};

function readiness(value: unknown): ConnectorReadiness | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (!["health_url", "organization_id", "energy_domain", "connector_id"].every((key) => typeof item[key] === "string" && item[key] !== "")
    || item.raw_data_accessed !== false) return null;
  const offeredUrl = item.health_url as string;
  if (offeredUrl.includes("\\") || [...offeredUrl].some((character) => character.charCodeAt(0) <= 32 || character.charCodeAt(0) === 127)) return null;
  try {
    const url = new URL(item.health_url as string);
    if ((url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)))
      || url.username || url.password || url.search || url.hash || !url.pathname.endsWith("/health")) return null;
  } catch { return null; }
  return item as ConnectorReadiness;
}

/** Only starts an explicitly offered node for this active operation. It never authorizes a query. */
export async function prepareConnector(value: unknown, signal?: AbortSignal): Promise<boolean> {
  const descriptor = readiness(value);
  if (!descriptor || signal?.aborted) return false;
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(abort, 90_000);
  let delay = 5_000;
  try {
    while (!controller.signal.aborted) {
      let pause = delay;
      try {
        const response = await fetch(descriptor.health_url, {
          method: "GET", credentials: "omit", redirect: "error", referrerPolicy: "no-referrer",
          cache: "no-store", signal: controller.signal,
        });
        if (response.ok) {
          if (!response.headers.get("content-type")?.toLowerCase().includes("application/json")) return false;
          const health: unknown = await response.json();
          if (!health || typeof health !== "object" || Array.isArray(health)) return false;
          const identity = health as Record<string, unknown>;
          return identity.organization_id === descriptor.organization_id && identity.energy_domain === descriptor.energy_domain
            && identity.connector_id === descriptor.connector_id;
        }
        if (response.status < 500 && ![408, 425, 429].includes(response.status)) return false;
        const retryAfter = response.headers.get("retry-after")?.trim() || "";
        if (/^[0-9]{1,6}$/.test(retryAfter) && Number(retryAfter) > 0) pause = Math.min(60_000, Number(retryAfter) * 1_000);
      } catch {
        if (controller.signal.aborted) return false;
      }
      if (controller.signal.aborted) return false;
      await new Promise<void>((resolve) => {
        const finish = () => { clearTimeout(timer); controller.signal.removeEventListener("abort", finish); resolve(); };
        const timer = setTimeout(finish, pause);
        controller.signal.addEventListener("abort", finish, { once: true });
      });
      delay = Math.min(15_000, delay * 2);
    }
    return false;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}

const preparedTasks = new Set<string>();

export function prepareQueryConnector(task: { task_id: string; status: string; connector_readiness?: unknown }, signal?: AbortSignal) {
  if (!["QUEUED", "RUNNING", "PENDING_RETRY"].includes(task.status) || !readiness(task.connector_readiness)
    || signal?.aborted || preparedTasks.has(task.task_id)) return;
  if (preparedTasks.size >= 128) preparedTasks.delete(preparedTasks.values().next().value!);
  preparedTasks.add(task.task_id);
  // Keep task persistence and polling independent of the hosting startup delay.
  void prepareConnector(task.connector_readiness, signal).catch(() => undefined).finally(() => {
    if (signal?.aborted) preparedTasks.delete(task.task_id);
  });
}
