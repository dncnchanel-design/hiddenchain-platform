import { describe, expect, it, vi } from "vitest";
import { isLatestRun, resolveOnce, retryTransient } from "./assistant-state";

describe("assistant session state", () => {
  it("shares one session request across StrictMode-style duplicate mounts", async () => {
    const valueRef = { current: null as { session_id: string } | null };
    const promiseRef = { current: null as Promise<{ session_id: string }> | null };
    const request = vi.fn(async () => ({ session_id: "session-real" }));

    const [first, second] = await Promise.all([
      resolveOnce(valueRef, promiseRef, request),
      resolveOnce(valueRef, promiseRef, request),
    ]);

    expect(first).toEqual({ session_id: "session-real" });
    expect(second).toEqual(first);
    expect(request).toHaveBeenCalledTimes(1);
    expect(valueRef.current).toEqual(first);
    expect(await resolveOnce(valueRef, promiseRef, request)).toEqual(first);
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("accepts only the active effect run", () => {
    expect(isLatestRun(true, 2, 2)).toBe(true);
    expect(isLatestRun(true, 1, 2)).toBe(false);
    expect(isLatestRun(false, 2, 2)).toBe(false);
  });

  it("retries an idempotent session command after a browser transport failure", async () => {
    let attempts = 0;
    const value = await retryTransient(async () => {
      attempts += 1;
      if (attempts === 1) throw new TypeError("Failed to fetch");
      return "session-real";
    }, 2, 0);

    expect(value).toBe("session-real");
    expect(attempts).toBe(2);
  });
});
