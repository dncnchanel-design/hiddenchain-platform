import { describe, expect, it, vi } from "vitest";
import {
  clearPendingQueryTask,
  QUERY_TASK_STORAGE_KEY,
  readPendingQueryTask,
  recoverPendingQuerySubmission,
  writePendingQueryTask,
} from "./query-task-lifecycle";
import { commandPollingRetryDelay, shouldRetryCommandPolling, shouldStopCommandPolling } from "../../hooks";

function memoryStore() {
  const values = new Map<string, string>();
  return {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => { values.set(key, value); }),
    removeItem: vi.fn((key: string) => { values.delete(key); }),
  };
}

describe("trusted query task lifecycle", () => {
  const submission = {
    authorization_id: "authorization-real",
    provider_org_id: "provider-real",
    energy_domain: "electricity",
    resource: "load",
    function: "average",
    start_date: "2026-06-01",
    end_date: "2026-06-30",
    region: "济南",
    decimals: 2,
  };

  it("persists only canonical recovery metadata and the stable idempotency key", () => {
    const store = memoryStore();
    const source = {
      taskId: "task-real",
      idempotencyKey: "trusted-query:key-real",
      submission,
      confirmation_token: "must-not-persist",
      result: { raw: "must-not-persist" },
    };

    writePendingQueryTask(store, source);

    expect(JSON.parse(store.setItem.mock.calls[0][1])).toEqual({
      task_id: "task-real",
      idempotency_key: "trusted-query:key-real",
      submission,
    });
    expect(store.setItem.mock.calls[0][1]).not.toContain("confirmation_token");
    expect(store.setItem.mock.calls[0][1]).not.toContain("must-not-persist");
    expect(readPendingQueryTask(store)).toEqual({ taskId: "task-real", idempotencyKey: "trusted-query:key-real", submission });
    clearPendingQueryTask(store);
    expect(store.removeItem).toHaveBeenCalledWith(QUERY_TASK_STORAGE_KEY);
  });

  it("rejects malformed recovery metadata", () => {
    const store = memoryStore();
    store.setItem(QUERY_TASK_STORAGE_KEY, JSON.stringify({ task_id: "task-real", idempotency_key: "" }));
    expect(readPendingQueryTask(store)).toBeNull();
    store.setItem(QUERY_TASK_STORAGE_KEY, "not-json");
    expect(readPendingQueryTask(store)).toBeNull();
    store.setItem(QUERY_TASK_STORAGE_KEY, JSON.stringify({ task_id: null, idempotency_key: "preflight-old" }));
    expect(readPendingQueryTask(store)).toBeNull();
  });

  it("recovers the pre-submit crash window with a fresh transient token and the original key", async () => {
    const confirm = vi.fn().mockResolvedValue({ confirmation_token: "transient-token" });
    const execute = vi.fn().mockResolvedValue({ task_id: "task-recovered" });
    const pending = { taskId: null, idempotencyKey: "trusted-query:stable", submission };

    await expect(recoverPendingQuerySubmission(pending, confirm, execute)).resolves.toEqual({ task_id: "task-recovered" });
    expect(confirm).toHaveBeenCalledWith(submission, undefined);
    expect(execute).toHaveBeenCalledWith(
      { ...submission, confirmation_token: "transient-token" },
      "trusted-query:stable",
      undefined,
    );
  });

  it("stops permanent statuses and limits transient backoff", () => {
    expect([401, 403, 404].every((status) => shouldStopCommandPolling(status))).toBe(true);
    expect([null, 408, 425, 429, 500, 503].every((status) => shouldRetryCommandPolling(status))).toBe(true);
    expect([400, 401, 403, 404, 409, 422].every((status) => !shouldRetryCommandPolling(status))).toBe(true);
    expect([1, 2, 3, 4, 5].map(commandPollingRetryDelay)).toEqual([2_000, 4_000, 8_000, 15_000, 15_000]);
  });
});
