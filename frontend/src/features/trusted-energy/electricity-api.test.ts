import { expect, it } from "vitest";
import { formatElectricityValue } from "./electricity-api";

it("preserves exact decimal results beyond JavaScript's safe integer range", () => {
  expect(formatElectricityValue("999999999999999999999999.01")).toBe("999,999,999,999,999,999,999,999.01");
  expect(formatElectricityValue("-61027.50")).toBe("-61,027.5");
  expect(formatElectricityValue("154.500000")).toBe("154.5");
  expect(formatElectricityValue("458.00")).toBe("458");
});
