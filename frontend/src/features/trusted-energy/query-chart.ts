import type { ControlledQueryResult } from "./trusted-space-api";

export type QueryChartKind = "bar" | "line" | "pie";

export type QueryChartData = {
  label: string;
  value: number;
};

export type QueryChartModel = {
  kind: QueryChartKind;
  title: string;
  description: string;
  unit: string;
  data: QueryChartData[];
  ariaLabel: string;
};

const RATE_FUNCTION_NAMES = new Set(["增长率", "同比", "环比"]);

function numericEntries(value: Record<string, number | string>): QueryChartData[] {
  return Object.entries(value)
    .filter(([, item]) => typeof item === "number" && Number.isFinite(item))
    .map(([label, item]) => ({ label, value: item as number }));
}

function chartAriaLabel(result: ControlledQueryResult, model: Omit<QueryChartModel, "ariaLabel">): string {
  const values = model.data.map(({ label, value }) => `${label}${value}${model.unit}`).join("，");
  return `${result.resource_name}${model.title}，${values}`;
}

export function buildQueryChartModel(result: ControlledQueryResult): QueryChartModel | null {
  const raw = result.result;

  const trend = (result.trend || []).filter(
    (point) => point && typeof point.date === "string" && point.date && Number.isFinite(point.value),
  );
  if (trend.length > 1) {
    const model = {
      kind: "line" as const,
      title: "受控趋势",
      description: `${trend.length} 个主体连接器返回的日度汇总点，原始记录未返回`,
      unit: result.unit,
      data: trend.map((point) => ({ label: point.date, value: point.value })),
    };
    return { ...model, ariaLabel: chartAriaLabel(result, model) };
  }

  if (typeof raw === "number" && Number.isFinite(raw)) {
    const model = {
      kind: result.function_name === "趋势" ? "line" as const : "bar" as const,
      title: `${result.function_name}结果`,
      description: "按固定函数返回单项计算结果",
      unit: RATE_FUNCTION_NAMES.has(result.function_name) || result.function_name === "趋势" ? "%" : result.unit,
      data: [{ label: result.resource_name, value: raw }],
    };
    return { ...model, ariaLabel: chartAriaLabel(result, model) };
  }

  if (!raw || typeof raw !== "object") return null;

  const values = numericEntries(raw);
  if (!values.length) return null;

  const isThreshold = result.function_name === "阈值判断" || ("满足" in raw && "不满足" in raw);
  if (isThreshold) {
    const model = {
      kind: "pie" as const,
      title: "阈值判断结果",
      description: "按授权范围返回满足与不满足的记录数量",
      unit: "条",
      data: values,
    };
    return { ...model, ariaLabel: chartAriaLabel(result, model) };
  }

  const isTrend = result.function_name === "趋势" || "变化率" in raw || "方向" in raw;
  if (isTrend) {
    const direction = typeof raw["方向"] === "string" ? raw["方向"] : "未说明";
    const model = {
      kind: "line" as const,
      title: "趋势变化",
      description: `方向：${direction}；只展示连接器返回的数值摘要`,
      unit: "%",
      data: values,
    };
    return { ...model, ariaLabel: chartAriaLabel(result, model) };
  }

  const model = {
    kind: "bar" as const,
    title: result.function_name === "分组汇总" ? "分组汇总结果" : `${result.function_name}结果`,
    description: "按后端返回的数值摘要展示，不返回原始记录",
    unit: result.unit,
    data: values,
  };
  return { ...model, ariaLabel: chartAriaLabel(result, model) };
}
