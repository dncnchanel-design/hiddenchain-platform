import { describe, expect, it } from "vitest";
import {
  BRAND_SCALE_STEPS,
  contrastRatio,
  createBrandThemeVariables,
  DEFAULT_BRAND_THEME,
  generateBrandScale,
  normalizeBrandTheme,
  POWER_GRID_GREEN_SCALE,
} from "./brand-theme";

describe("deployment brand theme", () => {
  it("provides the complete curated power-grid-green ramp", () => {
    const scale = generateBrandScale(DEFAULT_BRAND_THEME.primary);
    expect(Object.keys(scale).map(Number).sort((left, right) => left - right)).toEqual([...BRAND_SCALE_STEPS]);
    expect(scale).toEqual(POWER_GRID_GREEN_SCALE);
    const variables = createBrandThemeVariables(DEFAULT_BRAND_THEME);
    expect(contrastRatio(variables["--brand-on-primary"], variables["--brand-primary"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(variables["--brand-primary-text"], "#FFFFFF")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(variables["--brand-primary-border"], "#FFFFFF")).toBeGreaterThanOrEqual(3);
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
      primary: "#149376",
    });
  });
});
