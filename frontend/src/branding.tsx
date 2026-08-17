import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { ShieldCheck } from "lucide-react";
import { api } from "./api";
import {
  createBrandThemeVariables,
  DEFAULT_BRAND_THEME,
  normalizeBrandTheme,
  type BrandThemeConfig,
} from "./brand-theme";

export interface ProductBrandConfig {
  productName: string;
  productShortName: string;
  productSubtitle: string;
  logo: string;
  logoCompact: string;
  favicon: string;
  customerName: string;
  operatorName: string;
  builderName: string;
  copyrightOwner: string;
  copyrightYear: string;
  supportName: string;
  supportContact: string;
  environmentName: string;
  loginNotice: string;
  brandTheme: BrandThemeConfig;
  environment: "development" | "test" | "production";
  features: {
    fixtureImport: boolean;
    anomalyInjection: boolean;
    testOperations: boolean;
  };
}

export type ProductConfig = ProductBrandConfig;

export type ProductBrandConfigInput = Omit<Partial<ProductBrandConfig>, "brandTheme" | "features"> & {
  brandTheme?: Partial<BrandThemeConfig>;
  features?: Partial<ProductBrandConfig["features"]>;
};

export const DEFAULT_PRODUCT_CONFIG: ProductBrandConfig = {
  productName: "隐链明算",
  productShortName: "隐链明算",
  productSubtitle: "电力交易可信执行平台",
  logo: "",
  logoCompact: "",
  favicon: "",
  customerName: "",
  operatorName: "",
  builderName: "",
  copyrightOwner: "",
  copyrightYear: "",
  supportName: "",
  supportContact: "",
  environmentName: "",
  loginNotice: "",
  brandTheme: DEFAULT_BRAND_THEME,
  environment: "production",
  features: {
    fixtureImport: false,
    anomalyInjection: false,
    testOperations: false,
  },
};

export function mergeProductConfig(value?: ProductBrandConfigInput | null): ProductBrandConfig {
  return {
    ...DEFAULT_PRODUCT_CONFIG,
    ...value,
    brandTheme: normalizeBrandTheme(value?.brandTheme),
    features: { ...DEFAULT_PRODUCT_CONFIG.features, ...(value?.features || {}) },
  };
}

export function productDocumentTitle(config: ProductConfig, pageTitle?: string): string {
  return [pageTitle, config.customerName, config.productName].filter(Boolean).join(" · ");
}

export function productFooterItems(config: ProductConfig, version: string): string[] {
  return [
    `${config.productName} · ${config.productSubtitle}`,
    config.customerName,
    config.operatorName ? `运营：${config.operatorName}` : "",
    config.builderName ? `建设：${config.builderName}` : "",
    config.copyrightOwner ? `© ${config.copyrightYear || new Date().getFullYear()} ${config.copyrightOwner}` : "",
    config.supportName || config.supportContact ? `支持：${[config.supportName, config.supportContact].filter(Boolean).join(" ")}` : "",
    `${config.environmentName ? `${config.environmentName} · ` : ""}系统版本 ${version}`,
  ].filter(Boolean);
}

function applyDocumentBranding(config: ProductConfig) {
  document.title = productDocumentTitle(config);
  const root = document.documentElement;
  root.dataset.brandTheme = config.brandTheme.themeId;
  for (const [name, value] of Object.entries(createBrandThemeVariables(config.brandTheme))) {
    root.style.setProperty(name, value);
  }
  if (!config.favicon) return;
  let favicon = document.querySelector<HTMLLinkElement>("link[rel='icon']");
  if (!favicon) {
    favicon = document.createElement("link");
    favicon.rel = "icon";
    document.head.appendChild(favicon);
  }
  favicon.href = config.favicon;
}

const ProductConfigContext = createContext<ProductConfig>(DEFAULT_PRODUCT_CONFIG);

export function ProductConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState(DEFAULT_PRODUCT_CONFIG);

  useLayoutEffect(() => {
    applyDocumentBranding(config);
  }, [config]);

  useEffect(() => {
    let active = true;
    api<ProductBrandConfigInput>("/public/config", { cacheTtlMs: 60_000, retry: 0 })
      .then((value) => {
        if (!active) return;
        setConfig(mergeProductConfig(value));
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  const value = useMemo(() => config, [config]);
  return <ProductConfigContext.Provider value={value}>{children}</ProductConfigContext.Provider>;
}

export function useProductConfig() {
  return useContext(ProductConfigContext);
}

export function BrandMark({ compact = false, size = 21 }: { compact?: boolean; size?: number }) {
  const config = useProductConfig();
  const source = compact ? config.logoCompact || config.logo : config.logo;
  return source
    ? <img className="brand-image" src={source} alt="" aria-hidden="true" />
    : <ShieldCheck size={size} aria-hidden="true" />;
}

export function BrandLockup({ compact = false }: { compact?: boolean }) {
  const config = useProductConfig();
  return (
    <>
      <span className="brand-mark"><BrandMark compact size={21} /></span>
      {!compact && <span className="brand-copy"><strong>{config.productShortName}</strong><small>{config.productSubtitle}</small></span>}
    </>
  );
}
