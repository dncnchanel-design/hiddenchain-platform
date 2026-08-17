import { describe, expect, it } from "vitest";
import { DEFAULT_PRODUCT_CONFIG, mergeProductConfig, productDocumentTitle, productFooterItems } from "./branding";

describe("white-label product config", () => {
  it("overrides product, logo, customer and document title without losing feature defaults", () => {
    const config = mergeProductConfig({
      productName: "北辰电力结算平台",
      productShortName: "北辰结算",
      logo: "https://assets.example.com/beichen.svg",
      customerName: "北辰电力交易中心",
      operatorName: "北辰运营中心",
      builderName: "北辰数字科技",
      copyrightOwner: "北辰电力交易中心",
      copyrightYear: "2026",
      supportName: "北辰服务台",
      supportContact: "support@example.com",
      features: { ...DEFAULT_PRODUCT_CONFIG.features, fixtureImport: true },
    });

    expect(config.productName).toBe("北辰电力结算平台");
    expect(config.productShortName).toBe("北辰结算");
    expect(config.logo).toBe("https://assets.example.com/beichen.svg");
    expect(config.customerName).toBe("北辰电力交易中心");
    expect(config.features.fixtureImport).toBe(true);
    expect(config.features.anomalyInjection).toBe(false);
    expect(productDocumentTitle(config, "结算任务")).toBe("结算任务 · 北辰电力交易中心 · 北辰电力结算平台");
    expect(productFooterItems(config, "1.2.3")).toEqual(expect.arrayContaining([
      "运营：北辰运营中心",
      "建设：北辰数字科技",
      "© 2026 北辰电力交易中心",
      "支持：北辰服务台 support@example.com",
      "系统版本 1.2.3",
    ]));
  });
});
