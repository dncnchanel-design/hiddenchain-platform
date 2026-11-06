import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { AuthProvider } from "./auth";

const fixture = vi.hoisted(() => ({
  slots: [] as unknown[], cursor: 0, effects: [] as Array<() => unknown>, api: vi.fn(), post: vi.fn(), invalidate: vi.fn(),
}));
vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useState: (initial: unknown) => {
    const index = fixture.cursor++;
    if (!(index in fixture.slots)) fixture.slots[index] = typeof initial === "function" ? initial() : initial;
    return [fixture.slots[index], (value: unknown) => { fixture.slots[index] = typeof value === "function" ? value(fixture.slots[index]) : value; }];
  },
  useCallback: (callback: unknown) => callback,
  useMemo: (factory: () => unknown) => factory(),
  useEffect: (effect: () => unknown) => { fixture.effects.push(effect); },
}));
vi.mock("./api", async (original) => ({
  ...await original<typeof import("./api")>(),
  api: (...args: unknown[]) => fixture.api(...args),
  post: (...args: unknown[]) => fixture.post(...args),
  invalidateApiCache: () => fixture.invalidate(),
}));

const storage = new Map<string, string>();
const tokenKey = "hiddenchain_token";
const oldSession = { user: { user_id: "old-user" }, menus: [] };
const newSession = { user: { user_id: "new-user" }, menus: [] };
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function render() {
  fixture.cursor = 0; fixture.effects = [];
  return AuthProvider({ children: null }).props.value;
}
async function beginRestore() {
  render(); fixture.effects.forEach((effect) => effect());
  await vi.waitFor(() => expect(fixture.api).toHaveBeenCalledWith("/auth/me"));
}
beforeEach(() => {
  fixture.slots = []; fixture.effects = [];
  fixture.api.mockReset(); fixture.post.mockReset(); fixture.invalidate.mockReset(); storage.clear();
  storage.set(tokenKey, "old-session-token");
  vi.stubGlobal("sessionStorage", { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key) });
  vi.stubGlobal("localStorage", { removeItem: vi.fn() });
  vi.stubGlobal("window", Object.assign(new EventTarget(), { setTimeout, clearTimeout }));
});
afterEach(() => { vi.unstubAllGlobals(); });

it("does not restore a previous identity after logout completed", async () => {
  const restore = deferred<typeof oldSession>();
  fixture.api.mockReturnValue(restore.promise);
  fixture.post.mockResolvedValue(undefined);
  await beginRestore();
  await render().logout();
  restore.resolve(oldSession);
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(render().session).toBeNull();
  expect(storage.has(tokenKey)).toBe(false);
});

it.each([401, 503])("ignores a previous session restoration error after a new login (%s)", async (status) => {
  const restore = deferred<typeof oldSession>();
  fixture.api.mockReturnValue(restore.promise);
  fixture.post.mockResolvedValue({ ...newSession, access_token: "new-session-token" });
  await beginRestore();
  await render().login("new-user", "fixture-password");
  restore.reject(new ApiError("old request failed", status));
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(storage.get(tokenKey)).toBe("new-session-token");
  expect(render().session).toEqual(newSession);
  expect(render().sessionExpired).toBe(false);
  expect(render().sessionError).toBe("");
  expect(render().loading).toBe(false);
});

it("does not clear a newer login when an older server logout finishes", async () => {
  const logout = deferred<void>();
  fixture.post.mockImplementation((path: string) => path === "/auth/logout" ? logout.promise : Promise.resolve({ ...newSession, access_token: "new-session-token" }));
  const oldLogout = render().logout();
  await render().login("new-user", "fixture-password");
  logout.resolve(); await oldLogout;
  expect(storage.get(tokenKey)).toBe("new-session-token");
  expect(render().session).toEqual(newSession);
});

it.each([401, 503])("still handles restoration failures for the current session (%s)", async (status) => {
  const restore = deferred<typeof oldSession>();
  fixture.api.mockReturnValue(restore.promise);
  await beginRestore();
  restore.reject(new ApiError("current request failed", status));
  await vi.waitFor(() => expect(render().loading).toBe(false));
  expect(render().sessionExpired).toBe(status === 401);
  expect(storage.has(tokenKey)).toBe(status !== 401);
  expect(Boolean(render().sessionError)).toBe(status === 503);
});
