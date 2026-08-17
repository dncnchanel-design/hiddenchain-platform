import { describe, expect, it } from "vitest";
import { formatMoney, formatNumber, formatPercent, shortHash } from "./api";

describe("production formatters", () => {
  it("uses the common missing-value marker", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatNumber(undefined)).toBe("—");
    expect(formatPercent("")).toBe("—");
    expect(shortHash(null)).toBe("—");
  });

  it("formats currency, numbers and percentages consistently", () => {
    expect(formatMoney(1234.5)).toContain("1,234.50");
    expect(formatNumber(1234.567, 2)).toBe("1,234.57");
    expect(formatPercent(98.456)).toBe("98.5%");
  });

  it("shortens long identifiers without losing both ends", () => {
    expect(shortHash("1234567890abcdefghijklmnopqrstuvwxyz", 6)).toBe("123456…uvwxyz");
  });
});
