import { isValidElement, type ReactElement, type ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { QueryOutput, QueryPage } from "./pages/QueryPage";
import { QUERY_TASK_STORAGE_KEY } from "./query-task-lifecycle";

const fixture = vi.hoisted(() => ({ slots: [] as unknown[], cursor: 0, refs: [] as Array<{ current: unknown }>, refCursor: 0, effects: [] as Array<() => unknown>, confirm: vi.fn(), execute: vi.fn() }));
vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useState: (initial: unknown) => {
    const index = fixture.cursor++;
    if (!(index in fixture.slots)) fixture.slots[index] = typeof initial === "function" ? initial() : initial;
    return [fixture.slots[index], (value: unknown) => { fixture.slots[index] = typeof value === "function" ? value(fixture.slots[index]) : value; }];
  },
  useRef: (initial: unknown) => { const index = fixture.refCursor++; fixture.refs[index] ??= { current: initial }; return fixture.refs[index]; },
  useCallback: (callback: unknown) => callback,
  useEffect: (effect: () => unknown) => { fixture.effects.push(effect); },
}));
vi.mock("react-router-dom", () => ({ useLocation: () => ({ search: "?question=fixture-query" }), Link: () => null }));
vi.mock("./trusted-space-context", () => ({ useTrustedSpaceContext: () => ({ context: { actor: { user_id: "user-a", role_code: "GENERATOR" }, current_subject: { org_id: "org-a" }, identity_ref: {} } }) }));
vi.mock("./trusted-space-api", async (original) => ({
  ...await original<typeof import("./trusted-space-api")>(),
  parseTrustedQuery: async () => ({ ready: true, energy_domain: "electricity", resource: "generation", function: "sum", start_date: "2026-11-01", end_date: "2026-11-03" }),
  loadCatalog: async () => ({ total: 1, items: [{ asset_id: "asset-a", status: "ACTIVE", metadata: { resource_id: "generation" }, source: { status: "ACTIVE" }, actions: { can_compute_own: true }, provider: { org_id: "org-a" } }] }),
  loadUsageRequests: async () => ({ total: 0, items: [] }),
  confirmTrustedQuery: (...args: unknown[]) => fixture.confirm(...args),
  executeTrustedQuery: (...args: unknown[]) => fixture.execute(...args),
}));
const storage = new Map<string, string>();
function render() { fixture.cursor = 0; fixture.refCursor = 0; fixture.effects = []; return QueryPage(); }
function nodes(value: ReactNode): Array<ReactElement<Record<string, unknown>>> {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!isValidElement<Record<string, unknown>>(value)) return [];
  return [value, ...nodes(value.props.children as ReactNode)];
}
function output() { return nodes(render()).find((node) => node.type === QueryOutput)!; }
async function prepare() {
  const tree = render();
  const cleanups = fixture.effects.map((effect) => effect());
  const send = nodes(tree).find((node) => node.type === "button" && node.props.children === "发送")!;
  (send.props.onClick as () => void)();
  await vi.waitFor(() => expect(output().props.providers).toHaveLength(1));
  return () => cleanups.forEach((cleanup) => { if (typeof cleanup === "function") cleanup(); });
}
beforeEach(() => {
  fixture.slots = []; fixture.refs = []; fixture.effects = []; fixture.confirm.mockReset(); fixture.execute.mockReset();
  fixture.confirm.mockResolvedValue({ confirmation_token: "confirmation" });
  fixture.execute.mockResolvedValue({ task_id: "task-a", status: "QUEUED" });
  storage.clear(); storage.set("hiddenchain_token", "account-a");
  vi.stubGlobal("sessionStorage", { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key) });
});
afterEach(() => { vi.unstubAllGlobals(); });

it("still submits and persists the current account's confirmed query", async () => {
  await prepare();
  (output().props.onExecute as () => void)();
  await vi.waitFor(() => expect(JSON.parse(storage.get(QUERY_TASK_STORAGE_KEY) || "null")?.task_id).toBe("task-a"));
  expect(JSON.parse(storage.get(QUERY_TASK_STORAGE_KEY)!).owner_user_id).toBe("user-a");
  expect(fixture.execute.mock.calls[0][2]).toBeInstanceOf(AbortSignal);
});

it.each(["unmount", "account-change"])("does not create a query when confirmation finishes after %s", async (change) => {
  let resolve!: (value: unknown) => void;
  fixture.confirm.mockImplementation(() => new Promise((yes) => { resolve = yes; }));
  const unmount = await prepare();
  (output().props.onExecute as () => void)();
  await vi.waitFor(() => expect(fixture.confirm).toHaveBeenCalledOnce());
  if (change === "unmount") unmount();
  else storage.set("hiddenchain_token", "account-b");
  resolve({ confirmation_token: "confirmation" });
  await new Promise((yes) => setTimeout(yes, 0));
  expect(fixture.execute).not.toHaveBeenCalled();
  expect(storage.has(QUERY_TASK_STORAGE_KEY)).toBe(false);
});

it("does not replace a new account's recovery record with an unmounted query response", async () => {
  let resolve!: (value: unknown) => void;
  fixture.execute.mockImplementation(() => new Promise((yes) => { resolve = yes; }));
  const unmount = await prepare();
  (output().props.onExecute as () => void)();
  await vi.waitFor(() => expect(fixture.execute).toHaveBeenCalledOnce());
  unmount();
  storage.set(QUERY_TASK_STORAGE_KEY, "account-b-pending");
  resolve({ task_id: "task-a", status: "QUEUED" });
  await new Promise((yes) => setTimeout(yes, 0));
  expect(storage.get(QUERY_TASK_STORAGE_KEY)).toBe("account-b-pending");
});
