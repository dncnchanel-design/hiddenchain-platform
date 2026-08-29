import { describe, expect, it, vi } from "vitest";
import { createRetryableModuleLoader } from "./RetryableLazy";
import { LoginPage } from "../pages/LoginPage";
import { pages } from "../routes";
import retryableLazySource from "./RetryableLazy.tsx?raw";

describe("retryable lazy module loader", () => {
  it("keeps the authentication boot page synchronous", async () => {
    expect(pages.login).toBe(LoginPage);
    await expect(pages.login.preload()).resolves.toBe(LoginPage);
  });

  it("clears a rejected preload so the next attempt can load the page", async () => {
    const page = () => null;
    const loader = vi.fn()
      .mockRejectedValueOnce(new Error("temporary chunk failure"))
      .mockResolvedValueOnce({ Page: page });
    const load = createRetryableModuleLoader(loader, "Page");

    await expect(load()).rejects.toThrow("temporary chunk failure");
    await expect(load()).resolves.toEqual({ default: page });
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("shares a successful module request across preload and render", async () => {
    const page = () => null;
    const loader = vi.fn().mockResolvedValue({ Page: page });
    const load = createRetryableModuleLoader(loader, "Page");

    const first = load();
    const second = load();

    expect(second).toBe(first);
    await expect(first).resolves.toEqual({ default: page });
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("keeps the lazy component type stable across suspended first renders", () => {
    const lazyDeclaration = retryableLazySource.indexOf("const LazyPage = lazy(load)");
    const componentDeclaration = retryableLazySource.indexOf("function RetryableLazyPage()");

    expect(lazyDeclaration).toBeGreaterThan(-1);
    expect(lazyDeclaration).toBeLessThan(componentDeclaration);
  });

  it("times out a module request that never settles and permits a fresh load", async () => {
    vi.useFakeTimers();
    try {
      const page = () => null;
      const loader = vi.fn()
        .mockReturnValueOnce(new Promise(() => undefined))
        .mockResolvedValueOnce({ Page: page });
      const load = createRetryableModuleLoader(loader, "Page", 25);

      const firstAttempt = expect(load()).rejects.toThrow("timed out after 25ms");
      await vi.advanceTimersByTimeAsync(25);
      await firstAttempt;
      await expect(load()).resolves.toEqual({ default: page });
      expect(loader).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
