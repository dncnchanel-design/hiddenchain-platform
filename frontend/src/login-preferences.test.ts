import { describe, expect, it, vi } from "vitest";
import { rememberAccount, rememberedAccount } from "./login-preferences";

describe("remembered login account", () => {
  it("stores only the selected account name and removes it when unchecked", () => {
    const values = new Map<string, string>();
    const storage = { getItem: (key: string) => values.get(key) || null, setItem: (key: string, value: string) => { values.set(key, value); }, removeItem: (key: string) => { values.delete(key); } };
    rememberAccount("generator", true, storage);
    expect(rememberedAccount(storage)).toBe("generator");
    expect([...values.values()]).toEqual(["generator"]);
    rememberAccount("retailer", false, storage);
    expect(rememberedAccount(storage)).toBe("");
    expect(values.size).toBe(0);
  });

  it("does not block login when browser storage is unavailable", () => {
    const blocked = vi.fn(() => { throw new Error("storage disabled"); });
    expect(rememberedAccount({ getItem: blocked })).toBe("");
    expect(() => rememberAccount("generator", true, { setItem: blocked, removeItem: blocked })).not.toThrow();
    expect(() => rememberAccount("generator", false, { setItem: blocked, removeItem: blocked })).not.toThrow();
  });
});
