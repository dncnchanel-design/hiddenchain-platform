import { describe, expect, it } from "vitest";
import {
  BRAND_SCALE_STEPS,
  contrastRatio,
  createBrandThemeVariables,
  DEFAULT_BRAND_THEME,
  generateBrandScale,
  normalizeBrandTheme,
  TRUSTED_SPACE_NAVY_SCALE,
  TRUSTED_SPACE_NAVY_TOKENS,
} from "./brand-theme";

describe("deployment brand theme", () => {
  it("provides the complete curated trusted-space-navy ramp", () => {
    const scale = generateBrandScale(DEFAULT_BRAND_THEME.primary);
    expect(Object.keys(scale).map(Number).sort((left, right) => left - right)).toEqual([...BRAND_SCALE_STEPS]);
    expect(scale).toEqual(TRUSTED_SPACE_NAVY_SCALE);
    const variables = createBrandThemeVariables(DEFAULT_BRAND_THEME);
    expect(variables).toMatchObject({
      "--brand-primary": TRUSTED_SPACE_NAVY_TOKENS.primary,
      "--brand-primary-hover": TRUSTED_SPACE_NAVY_TOKENS.primaryHover,
      "--brand-primary-active": TRUSTED_SPACE_NAVY_TOKENS.primaryActive,
      "--brand-bg-soft": TRUSTED_SPACE_NAVY_TOKENS.bgSoft,
      "--brand-bg-subtle": TRUSTED_SPACE_NAVY_TOKENS.bgSubtle,
      "--brand-bg-selected": TRUSTED_SPACE_NAVY_TOKENS.bgSelected,
      "--brand-border": TRUSTED_SPACE_NAVY_TOKENS.border,
      "--brand-focus-ring": TRUSTED_SPACE_NAVY_TOKENS.focusRing,
      "--brand-text-on-primary": TRUSTED_SPACE_NAVY_TOKENS.textOnPrimary,
      "--brand-primary-soft": TRUSTED_SPACE_NAVY_TOKENS.bgSoft,
      "--brand-primary-subtle": TRUSTED_SPACE_NAVY_TOKENS.bgSubtle,
      "--brand-primary-selected": TRUSTED_SPACE_NAVY_TOKENS.bgSelected,
      "--brand-primary-border": TRUSTED_SPACE_NAVY_TOKENS.border,
      "--brand-primary-focus": TRUSTED_SPACE_NAVY_TOKENS.focusRing,
    });
    expect(contrastRatio(variables["--brand-on-primary"], variables["--brand-primary"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(variables["--brand-primary-text"], "#FFFFFF")).toBeGreaterThanOrEqual(4.5);
    expect(variables["--brand-primary"]).toBe("#1768A0");
    expect(variables["--brand-border"]).toBe("#A6CBE4");
  });

  it("rebuilds every primitive and semantic token from a neutral blue deployment override", () => {
    const variables = createBrandThemeVariables({ themeId: "neutral-blue", primary: "#1769AA" });
    for (const step of BRAND_SCALE_STEPS) expect(variables[`--brand-${step}`]).toMatch(/^#[0-9A-F]{6}$/);
    expect(variables["--brand-500"]).toBe("#1769AA");
    expect(variables["--brand-primary-bg"]).not.toBe(TRUSTED_SPACE_NAVY_SCALE[50]);
    expect(contrastRatio(variables["--brand-on-primary"], variables["--brand-primary"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(variables["--brand-primary-text"], "#FFFFFF")).toBeGreaterThanOrEqual(4.5);
  });

  it("sanitizes untrusted theme metadata and rejects invalid color input", () => {
    expect(normalizeBrandTheme({ themeId: " Client Theme / 01 ", primary: "not-a-color" })).toEqual({
      themeId: "client-theme-01",
      primary: "#1768A0",
    });
  });
});
