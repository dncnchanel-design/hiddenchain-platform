export const BRAND_SCALE_STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950] as const;

export type BrandScaleStep = (typeof BRAND_SCALE_STEPS)[number];
export type BrandScale = Record<BrandScaleStep, string>;

export interface BrandThemeConfig {
  themeId: string;
  primary: string;
}

export const DEFAULT_BRAND_THEME: BrandThemeConfig = {
  themeId: "trusted-space-navy",
  primary: "#1768A0",
};

export const TRUSTED_SPACE_NAVY_TOKENS = {
  primary: "#1768A0",
  primaryHover: "#125681",
  primaryActive: "#0E4264",
  bgSoft: "#EAF5FC",
  bgSubtle: "#F6F9FC",
  bgSelected: "#DCECF8",
  border: "#A6CBE4",
  focusRing: "rgba(23, 104, 160, 0.18)",
  textOnPrimary: "#FFFFFF",
} as const;

/**
 * Curated starting ramp for the trusted data-space theme named above. Any
 * deployment override is rebuilt from its primary color by the OKLCH ramp
 * generator below.
 */
export const TRUSTED_SPACE_NAVY_SCALE: BrandScale = {
  50: TRUSTED_SPACE_NAVY_TOKENS.bgSubtle,
  100: TRUSTED_SPACE_NAVY_TOKENS.bgSoft,
  200: TRUSTED_SPACE_NAVY_TOKENS.bgSelected,
  300: TRUSTED_SPACE_NAVY_TOKENS.border,
  400: "#74A9CA",
  500: TRUSTED_SPACE_NAVY_TOKENS.primary,
  600: TRUSTED_SPACE_NAVY_TOKENS.primary,
  700: TRUSTED_SPACE_NAVY_TOKENS.primaryHover,
  800: TRUSTED_SPACE_NAVY_TOKENS.primaryActive,
  900: "#0A2540",
  950: "#06192C",
};

type Oklch = { l: number; c: number; h: number };

const RAMP_PROFILE: Record<Exclude<BrandScaleStep, 500>, { l: number; chroma: number }> = {
  50: { l: 0.975, chroma: 0.10 },
  100: { l: 0.94, chroma: 0.20 },
  200: { l: 0.875, chroma: 0.38 },
  300: { l: 0.79, chroma: 0.62 },
  400: { l: 0.69, chroma: 0.82 },
  600: { l: 0.50, chroma: 1.02 },
  700: { l: 0.44, chroma: 0.98 },
  800: { l: 0.37, chroma: 0.90 },
  900: { l: 0.30, chroma: 0.78 },
  950: { l: 0.24, chroma: 0.64 },
};

function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

function normalizeHex(value: string, fallback = DEFAULT_BRAND_THEME.primary): string {
  const raw = String(value || "").trim();
  const match = raw.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (!match) return fallback.toUpperCase();
  const digits = match[1].length === 3
    ? match[1].split("").map((character) => character.repeat(2)).join("")
    : match[1];
  return `#${digits.toUpperCase()}`;
}

function hexToRgb(value: string): [number, number, number] {
  const hex = normalizeHex(value).slice(1);
  return [0, 2, 4].map((index) => Number.parseInt(hex.slice(index, index + 2), 16) / 255) as [number, number, number];
}

function srgbToLinear(value: number): number {
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

function linearToSrgb(value: number): number {
  return value <= 0.0031308 ? 12.92 * value : 1.055 * value ** (1 / 2.4) - 0.055;
}

function hexToOklch(value: string): Oklch {
  const [red, green, blue] = hexToRgb(value).map(srgbToLinear) as [number, number, number];
  const l = Math.cbrt(0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue);
  const m = Math.cbrt(0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue);
  const s = Math.cbrt(0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue);
  const lightness = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const b = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return {
    l: lightness,
    c: Math.sqrt(a * a + b * b),
    h: Math.atan2(b, a),
  };
}

function oklchToLinearRgb({ l, c, h }: Oklch): [number, number, number] {
  const a = c * Math.cos(h);
  const b = c * Math.sin(h);
  const lRoot = l + 0.3963377774 * a + 0.2158037573 * b;
  const mRoot = l - 0.1055613458 * a - 0.0638541728 * b;
  const sRoot = l - 0.0894841775 * a - 1.291485548 * b;
  const lCube = lRoot ** 3;
  const mCube = mRoot ** 3;
  const sCube = sRoot ** 3;
  return [
    4.0767416621 * lCube - 3.3077115913 * mCube + 0.2309699292 * sCube,
    -1.2684380046 * lCube + 2.6097574011 * mCube - 0.3413193965 * sCube,
    -0.0041960863 * lCube - 0.7034186147 * mCube + 1.707614701 * sCube,
  ];
}

function inSrgbGamut(values: [number, number, number]): boolean {
  return values.every((value) => value >= -0.00001 && value <= 1.00001);
}

function oklchToHex(color: Oklch): string {
  let chroma = color.c;
  let rgb = oklchToLinearRgb({ ...color, c: chroma });
  if (!inSrgbGamut(rgb)) {
    let low = 0;
    let high = chroma;
    for (let index = 0; index < 24; index += 1) {
      const candidate = (low + high) / 2;
      const candidateRgb = oklchToLinearRgb({ ...color, c: candidate });
      if (inSrgbGamut(candidateRgb)) {
        low = candidate;
      } else {
        high = candidate;
      }
    }
    chroma = low;
    rgb = oklchToLinearRgb({ ...color, c: chroma });
  }
  return `#${rgb.map((channel) => Math.round(clamp(linearToSrgb(channel)) * 255).toString(16).padStart(2, "0")).join("")}`.toUpperCase();
}

export function generateBrandScale(primary: string): BrandScale {
  const normalized = normalizeHex(primary);
  if (normalized === DEFAULT_BRAND_THEME.primary.toUpperCase()) return { ...TRUSTED_SPACE_NAVY_SCALE };
  const base = hexToOklch(normalized);
  const scale = { 500: normalized } as BrandScale;
  for (const step of BRAND_SCALE_STEPS) {
    if (step === 500) continue;
    const profile = RAMP_PROFILE[step];
    scale[step] = oklchToHex({
      l: profile.l,
      c: Math.max(0.012, base.c * profile.chroma),
      h: Number.isFinite(base.h) ? base.h : 0,
    });
  }
  return scale;
}

function relativeLuminance(value: string): number {
  const [red, green, blue] = hexToRgb(value).map(srgbToLinear) as [number, number, number];
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function hexToRgba(value: string, alpha: number): string {
  const [red, green, blue] = hexToRgb(value).map((channel) => Math.round(channel * 255)) as [number, number, number];
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

export function contrastRatio(foreground: string, background: string): number {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

export function createBrandThemeVariables(theme: BrandThemeConfig): Record<string, string> {
  const scale = generateBrandScale(theme.primary);
  const isDefaultTheme = normalizeHex(theme.primary) === DEFAULT_BRAND_THEME.primary;
  const actionSteps = [600, 700, 800, 900, 950] as const;
  const actionIndex = Math.max(0, actionSteps.findIndex((step) => contrastRatio("#FFFFFF", scale[step]) >= 4.5));
  const primaryStep = actionSteps[actionIndex];
  const hoverStep = actionSteps[Math.min(actionIndex + 1, actionSteps.length - 1)];
  const activeStep = actionSteps[Math.min(actionIndex + 2, actionSteps.length - 1)];
  const semantic = isDefaultTheme
    ? TRUSTED_SPACE_NAVY_TOKENS
    : {
        primary: scale[primaryStep],
        primaryHover: scale[hoverStep],
        primaryActive: scale[activeStep],
        bgSoft: scale[100],
        bgSubtle: scale[50],
        bgSelected: scale[200],
        border: scale[300],
        focusRing: hexToRgba(scale[primaryStep], 0.18),
        textOnPrimary: "#FFFFFF",
      };
  const variables: Record<string, string> = {};

  for (const step of BRAND_SCALE_STEPS) variables[`--brand-${step}`] = scale[step];
  Object.assign(variables, {
    "--brand-accent": semantic.primary,
    "--brand-primary": semantic.primary,
    "--brand-primary-hover": semantic.primaryHover,
    "--brand-primary-active": semantic.primaryActive,
    "--brand-bg-soft": semantic.bgSoft,
    "--brand-bg-subtle": semantic.bgSubtle,
    "--brand-bg-selected": semantic.bgSelected,
    "--brand-border": semantic.border,
    "--brand-focus-ring": semantic.focusRing,
    "--brand-text-on-primary": semantic.textOnPrimary,
    "--brand-primary-subtle": semantic.bgSubtle,
    "--brand-primary-selected": semantic.bgSelected,
    "--brand-primary-focus": semantic.focusRing,
    "--brand-primary-strong": semantic.primary,
    "--brand-primary-text": semantic.primary,
    "--brand-primary-border": semantic.border,
    "--brand-primary-border-subtle": semantic.border,
    "--brand-primary-bg": semantic.bgSoft,
    "--brand-primary-bg-hover": semantic.bgSelected,
    "--brand-primary-bg-subtle": semantic.bgSubtle,
    "--brand-primary-soft": semantic.bgSoft,
    "--brand-primary-softer": semantic.bgSubtle,
    "--brand-primary-dark": semantic.primaryActive,
    "--brand-primary-darker": scale[900],
    "--brand-focus-ring-soft": semantic.focusRing,
    "--brand-on-primary": semantic.textOnPrimary,
    "--chart-series-brand": semantic.primary,
  });
  return variables;
}

export function normalizeBrandTheme(value?: Partial<BrandThemeConfig> | null): BrandThemeConfig {
  return {
    themeId: String(value?.themeId || DEFAULT_BRAND_THEME.themeId).trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-") || DEFAULT_BRAND_THEME.themeId,
    primary: normalizeHex(value?.primary || DEFAULT_BRAND_THEME.primary),
  };
}
