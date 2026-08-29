import { describe, expect, it } from "vitest";
import connectorPageSource from "./pages/ConnectorPage.tsx?raw";

describe("connector page browser-direct boundary", () => {
  it("uses the server catalog and removes prototype uploads and hand-entered resource metadata", () => {
    expect(connectorPageSource).toContain("loadConnectorCatalog");
    expect(connectorPageSource).toContain("原始 CSV 直达本企业连接器，中央只登记签名回执");
    expect(connectorPageSource).not.toContain("loadPrototypeConnector");
    expect(connectorPageSource).not.toContain("uploadPrototypeResource");
    expect(connectorPageSource).not.toContain("downloadPrototypeSample");
    expect(connectorPageSource).not.toContain("createIdempotencyKey");
    expect(connectorPageSource).not.toContain("timeColumn");
    expect(connectorPageSource).not.toContain("numericFields");
    expect(connectorPageSource).not.toContain("资源 ID（小写字母/下划线");
    expect(connectorPageSource).not.toContain("默认拒绝");
  });

  it("preserves recoverable receipt registration without retaining raw file content", () => {
    expect(connectorPageSource).toContain("sessionStorage");
    expect(connectorPageSource).toContain("本地上传成功，待补登记");
    expect(connectorPageSource).toContain("lookupConnectorReceipt");
    expect(connectorPageSource).toContain("补登记");
    expect(connectorPageSource).not.toContain("FileReader");
    expect(connectorPageSource).not.toContain("readAsText");
  });
});
