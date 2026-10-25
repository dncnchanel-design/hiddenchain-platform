export type MutableRef<T> = { current: T };

/** Execute one server-authorized metadata read; writes and ambiguous plans wait. */
export function shouldAutoExecuteRead(plan?: { intent_code: string; status: string; allowed_actions?: string[]; steps: { action_code: string; mode: string }[] } | null): boolean {
  const actions = new Set(["LIST_DATA_ASSETS", "LIST_VISIBLE_DATA_ASSETS", "LIST_AUTHORIZED_DATA_ASSETS", "LIST_AUTHORIZATIONS", "LIST_TASKS", "LIST_AUDIT_REPORTS", "LIST_NOTIFICATIONS", "SYSTEM_OVERVIEW", "ASSISTANT_HELP", "NAVIGATE_QUERY", "NAVIGATE_ELECTRICITY", "CHECK_ASSET_INTEGRITY", "QUERY_AUTHORIZATION_STATUS", "CHECK_TTC_STATUS", "EXPLAIN_AUDIT", "VERIFY_EVIDENCE_SUMMARY"]);
  return Boolean(plan && actions.has(plan.intent_code) && plan.status === "READY"
    && plan.allowed_actions?.includes("execute") && plan.steps.length === 1
    && plan.steps[0].action_code === plan.intent_code && plan.steps[0].mode === "READ");
}

/**
 * Keeps StrictMode's duplicate effect mount from creating two sessions.
 * The value ref is intentionally separate from React state so the second
 * effect can reuse a session that resolved before React replayed the effect.
 */
export function resolveOnce<T>(
  valueRef: MutableRef<T | null>,
  promiseRef: MutableRef<Promise<T> | null>,
  factory: () => Promise<T>,
): Promise<T> {
  if (valueRef.current) return Promise.resolve(valueRef.current);
  if (!promiseRef.current) {
    promiseRef.current = factory().then((value) => {
      valueRef.current = value;
      return value;
    });
  }
  return promiseRef.current;
}

export function isLatestRun(active: boolean, runId: number, latestRunId: number): boolean {
  return active && runId === latestRunId;
}

/**
 * Retries only browser transport failures for an idempotent assistant command.
 * The caller must provide an idempotency key before using this helper.
 */
export async function retryTransient<T>(factory: () => Promise<T>, retries = 2, delayMs = 180): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await factory();
    } catch (reason) {
      if (!(reason instanceof TypeError) || attempt >= retries) throw reason;
      if (delayMs > 0) await new Promise<void>((resolve) => setTimeout(resolve, delayMs * (attempt + 1)));
    }
  }
}
