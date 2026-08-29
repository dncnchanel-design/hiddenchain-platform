export const QUERY_TASK_STORAGE_KEY = "hiddenchain:trusted-query:pending:v1";

export type PendingQuerySubmission = {
  authorization_id?: string;
  provider_org_id: string;
  energy_domain: string;
  resource: string;
  function: string;
  start_date: string;
  end_date: string;
  region?: string;
  decimals: number;
};

export type PendingQueryTask = {
  taskId: string | null;
  idempotencyKey: string;
  submission: PendingQuerySubmission | null;
};

type SessionStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function validIdentifier(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maxLength;
}

function optionalIdentifier(value: unknown, maxLength: number): string | undefined | null {
  if (value === undefined || value === null || value === "") return undefined;
  return validIdentifier(value, maxLength) ? value : null;
}

function pendingSubmission(value: unknown): PendingQuerySubmission | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const source = value as Record<string, unknown>;
  const authorizationId = optionalIdentifier(source.authorization_id, 160);
  const region = optionalIdentifier(source.region, 160);
  if (authorizationId === null || region === null) return null;
  if (!validIdentifier(source.provider_org_id, 160)
    || !validIdentifier(source.energy_domain, 80)
    || !validIdentifier(source.resource, 160)
    || !validIdentifier(source.function, 80)
    || typeof source.start_date !== "string"
    || typeof source.end_date !== "string"
    || !/^\d{4}-\d{2}-\d{2}$/.test(source.start_date)
    || !/^\d{4}-\d{2}-\d{2}$/.test(source.end_date)
    || !Number.isInteger(source.decimals)
    || Number(source.decimals) < 0
    || Number(source.decimals) > 6) return null;
  return {
    ...(authorizationId ? { authorization_id: authorizationId } : {}),
    provider_org_id: source.provider_org_id,
    energy_domain: source.energy_domain,
    resource: source.resource,
    function: source.function,
    start_date: source.start_date,
    end_date: source.end_date,
    ...(region ? { region } : {}),
    decimals: Number(source.decimals),
  };
}

export function readPendingQueryTask(store: Pick<SessionStore, "getItem">): PendingQueryTask | null {
  try {
    const raw = store.getItem(QUERY_TASK_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (!validIdentifier(parsed.idempotency_key, 160)) return null;
    if (parsed.task_id !== null && !validIdentifier(parsed.task_id, 160)) return null;
    const submission = pendingSubmission(parsed.submission);
    if (parsed.task_id === null && !submission) return null;
    return {
      taskId: parsed.task_id as string | null,
      idempotencyKey: parsed.idempotency_key,
      submission,
    };
  } catch {
    return null;
  }
}

export function writePendingQueryTask(store: Pick<SessionStore, "setItem">, value: PendingQueryTask) {
  try {
    store.setItem(QUERY_TASK_STORAGE_KEY, JSON.stringify({
      task_id: value.taskId,
      idempotency_key: value.idempotencyKey,
      submission: value.submission ? {
        ...(value.submission.authorization_id ? { authorization_id: value.submission.authorization_id } : {}),
        provider_org_id: value.submission.provider_org_id,
        energy_domain: value.submission.energy_domain,
        resource: value.submission.resource,
        function: value.submission.function,
        start_date: value.submission.start_date,
        end_date: value.submission.end_date,
        ...(value.submission.region ? { region: value.submission.region } : {}),
        decimals: value.submission.decimals,
      } : null,
    }));
    return true;
  } catch {
    return false;
  }
}

export function clearPendingQueryTask(store: Pick<SessionStore, "removeItem">) {
  try {
    store.removeItem(QUERY_TASK_STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

export async function recoverPendingQuerySubmission<Result>(
  pending: PendingQueryTask,
  confirm: (submission: PendingQuerySubmission, signal?: AbortSignal) => Promise<{ confirmation_token: string }>,
  execute: (
    submission: PendingQuerySubmission & { confirmation_token: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ) => Promise<Result>,
  signal?: AbortSignal,
): Promise<Result> {
  if (pending.taskId !== null || !pending.submission) throw new Error("待恢复查询元数据不完整");
  const confirmation = await confirm(pending.submission, signal);
  return execute(
    { ...pending.submission, confirmation_token: confirmation.confirmation_token },
    pending.idempotencyKey,
    signal,
  );
}
