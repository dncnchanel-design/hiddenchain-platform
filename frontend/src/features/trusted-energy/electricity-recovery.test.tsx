import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "../../api";
import { ElectricityChat } from "./components/ElectricityChat";

const fixture = vi.hoisted(() => ({ effects: [] as Array<() => unknown>, updates: [] as unknown[], catalog: { version: "rules", sources: [], scenarios: [] }, saved: [{ id: "my-saved-case" }], history: vi.fn(), remove: vi.fn() }));
vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useEffect: (effect: () => unknown) => { fixture.effects.push(effect); },
  useState: (initial: unknown) => [initial, (value: unknown) => { fixture.updates.push(value); }],
}));
vi.mock("../../auth", () => ({ useAuth: () => ({ session: { user: { user_id: "generator" } } }) }));
vi.mock("./electricity-api", async (original) => ({
  ...await original<typeof import("./electricity-api")>(),
  loadElectricityCatalog: async () => fixture.catalog,
  loadElectricityCases: async () => ({ items: fixture.saved }),
  loadElectricityHistory: (...args: unknown[]) => fixture.history(...args),
}));

beforeEach(() => {
  fixture.effects.length = 0;
  fixture.updates.length = 0;
  fixture.history.mockReset();
  fixture.remove.mockClear();
  vi.stubGlobal("sessionStorage", { getItem: () => "expired-session", removeItem: fixture.remove });
});

it("keeps successful catalog and saved cases available when an old conversation no longer exists", async () => {
  fixture.history.mockRejectedValue(new ApiError("旧会话不存在", 404));
  renderToStaticMarkup(<ElectricityChat onFinish={() => {}} />);
  fixture.effects[0]();
  await vi.waitFor(() => expect(fixture.remove).toHaveBeenCalledWith("electricity-chat:generator"));
  expect(fixture.history).toHaveBeenCalledWith("expired-session");
  expect(fixture.updates).toContain(fixture.catalog);
  expect(fixture.updates).toContain(fixture.saved);
  expect(fixture.updates).toContain("旧会话不存在");
});
