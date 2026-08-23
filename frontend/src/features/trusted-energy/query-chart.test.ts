import { describe, expect, it } from "vitest";
import { buildQueryChartModel } from "./query-chart";
import type { ControlledQueryResult } from "./trusted-space-api";

function result(overrides: Partial<ControlledQueryResult>): ControlledQueryResult {
  return {
    task_id: "task-1",
    authorization_scope: "受控范围",
    generated_at: "2026-08-23T00:00:00Z",
    result: 12,
    unit: "吨",
    resource_name: "煤炭库存",
    function_name: "平均值",
    digital_signature: "签名",
    audit_recorded: true,
    raw_records_returned: false,
    capability: "本地受控计算",
    ...overrides,
  };
}

describe("buildQueryChartModel", () => {
  it("将单项数值结果建模为柱状图", () => {
    const model = buildQueryChartModel(result({ result: 12.5 }));
    expect(model?.kind).toBe("bar");
    expect(model?.data).toEqual([{ label: "煤炭库存", value: 12.5 }]);
    expect(model?.unit).toBe("吨");
  });

  it("将分组结果保留为后端返回的多个数值", () => {
    const model = buildQueryChartModel(result({ function_name: "分组汇总", result: { 华东: 9, 华北: 7, 说明: "已隐藏" } }));
    expect(model?.kind).toBe("bar");
    expect(model?.data).toEqual([{ label: "华东", value: 9 }, { label: "华北", value: 7 }]);
  });

  it("将阈值结果建模为环形图并使用记录数", () => {
    const model = buildQueryChartModel(result({ function_name: "阈值判断", result: { 满足: 4, 不满足: 2 } }));
    expect(model?.kind).toBe("pie");
    expect(model?.unit).toBe("条");
  });

  it("趋势使用折线模型并保留方向说明", () => {
    const model = buildQueryChartModel(result({ function_name: "趋势", result: { 方向: "上升", 变化率: 8.2 } }));
    expect(model?.data).toEqual([{ label: "变化率", value: 8.2 }]);
    expect(model?.kind).toBe("line");
    expect(model?.unit).toBe("%");
    expect(model?.description).toContain("方向：上升");
  });

  it("没有数值摘要时不渲染图表", () => {
    expect(buildQueryChartModel(result({ result: { 方向: "平稳" } }))).toBeNull();
  });
});
