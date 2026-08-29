import { describe, expect, it } from "vitest";
import { commandPollingRetryDelay, dataForRemoteScope, isCurrentRemoteRequest, shouldRetryCommandPolling, shouldStopCommandPolling } from "./hooks";

describe("command polling error policy", () => {
  it.each([401, 403, 404])("stops retrying permanent HTTP status %s", (status) => {
    expect(shouldStopCommandPolling(status)).toBe(true);
  });

  it.each([null, undefined, 408, 409, 425, 429, 500, 503])("keeps retrying recoverable status %s", (status) => {
    expect(shouldStopCommandPolling(status)).toBe(false);
  });

  it.each([null, undefined, 408, 425, 429, 500, 503])("recognizes finite-retry status %s", (status) => {
    expect(shouldRetryCommandPolling(status)).toBe(true);
  });

  it.each([400, 401, 403, 404, 409, 422])("does not retry non-transient status %s", (status) => {
    expect(shouldRetryCommandPolling(status)).toBe(false);
  });

  it("caps exponential polling backoff", () => {
    expect([1, 2, 3, 4, 5].map(commandPollingRetryDelay)).toEqual([2_000, 4_000, 8_000, 15_000, 15_000]);
  });

  it("rejects late responses and data from the previous route scope", () => {
    const firstRequest = 1;
    const secondRequest = 2;
    const oldData = { scopeKey: "task-a", payload: { taskId: "task-a" } };

    expect(isCurrentRemoteRequest(secondRequest, firstRequest)).toBe(false);
    expect(isCurrentRemoteRequest(secondRequest, secondRequest)).toBe(true);
    expect(dataForRemoteScope(oldData, "task-b")).toBeNull();
    expect(dataForRemoteScope(oldData, "task-a")).toEqual({ taskId: "task-a" });
  });
});
