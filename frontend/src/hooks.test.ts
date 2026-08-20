import { describe, expect, it } from "vitest";
import { shouldStopCommandPolling } from "./hooks";

describe("command polling error policy", () => {
  it.each([401, 403, 404])("stops retrying permanent HTTP status %s", (status) => {
    expect(shouldStopCommandPolling(status)).toBe(true);
  });

  it.each([null, undefined, 408, 409, 425, 429, 500, 503])("keeps retrying recoverable status %s", (status) => {
    expect(shouldStopCommandPolling(status)).toBe(false);
  });
});
