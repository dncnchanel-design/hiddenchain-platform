import { describe, expect, it } from "vitest";
import {
  BRAND_SCALE_STEPS,
  contrastRatio,
  createBrandThemeVariables,
  DEFAULT_BRAND_THEME,
  generateBrandScale,
  normalizeBrandTheme,
  POWER_GRID_GREEN_SCALE,
  POWER_GRID_GREEN_TOKENS,
} from "./brand-theme";

describe("deployment brand theme", () => {
  it("provides the complete curated power-grid-green ramp", () => {
    const scale = generateBrandScale(DEFAULT_BRAND_THEME.primary);
    expect(Object.keys(scale).map(Number).sort((left, right) => left - right)).toEqual([...BRAND_SCALE_STEPS]);
    expect(scale).toEqual(POWER_GRID_GREEN_SCALE);
    const variables = createBrandThemeVariables(DEFAULT_BRAND_THEME);
    expect(variables).toMatchObject({
      "--brand-primary": POWER_GRID_GREEN_TOKENS.primary,
      "--brand-primary-hover": POWER_GRID_GREEN_TOKENS.primaryHover,
      "--brand-primary-active": POWER_GRID_GREEN_TOKENS.primaryActive,
      "--brand-bg-soft": POWER_GRID_GREEN_TOKENS.bgSoft,
      "--brand-bg-subtle": POWER_GRID_GREEN_TOKENS.bgSubtle,
      "--brand-bg-selected": POWER_GRID_GREEN_TOKENS.bgSelected,
      "--brand-border": POWER_GRID_GREEN_TOKENS.border,
      "--brand-focus-ring": POWER_GRID_GREEN_TOKENS.focusRing,
      "--brand-text-on-primary": POWER_GRID_GREEN_TOKENS.textOnPrimary,
      "--brand-primary-soft": POWER_GRID_GREEN_TOKENS.bgSoft,
      "--brand-primary-subtle": POWER_GRID_GREEN_TOKENS.bgSubtle,
      "--brand-primary-selected": POWER_GRID_GREEN_TOKENS.bgSelected,
      "--brand-primary-border": POWER_GRID_GREEN_TOKENS.border,
      "--brand-primary-focus": POWER_GRID_GREEN_TOKENS.focusRing,
    });
    expect(contrastRatio(variables["--brand-on-primary"], variables["--brand-primary"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(variables["--brand-primary-text"], "#FFFFFF")).toBeGreaterThanOrEqual(4.5);
    expect(variables["--brand-primary"]).toBe("#00524B");
    expect(variables["--brand-border"]).toBe("#A8C5C1");
  });

  it("rebuilds every primitive and semantic token from a neutral blue deployment override", () => {
    const variables = createBrandThemeVariables({ themeId: "neutral-blue", primary: "#1769AA" });
    for (const step of BRAND_SCALE_STEPS) expect(variables[`--brand-${step}`]).toMatch(/^#[0-9A-F]{6}$/);
    expect(variables["--brand-500"]).toBe("#1769AA");
    expect(variables["--brand-primary-bg"]).not.toBe(POWER_GRID_GREEN_SCALE[50]);
    expect(contrastRatio(variables["--brand-on-primary"], variables["--brand-primary"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(variables["--brand-primary-text"], "#FFFFFF")).toBeGreaterThanOrEqual(4.5);
  });

  it("sanitizes untrusted theme metadata and rejects invalid color input", () => {
    expect(normalizeBrandTheme({ themeId: " Client Theme / 01 ", primary: "not-a-color" })).toEqual({
      themeId: "client-theme-01",
      primary: "#00524B",
    });
  });
});
