import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { AriaComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import type { EChartsOption } from "echarts";
import { CanvasRenderer } from "echarts/renderers";
import type { ControlledQueryResult } from "../trusted-space-api";
import { buildQueryChartModel } from "../query-chart";

echarts.use([BarChart, LineChart, PieChart, AriaComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export function QueryResultChart({ result }: { result: ControlledQueryResult }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const model = useMemo(() => buildQueryChartModel(result), [result]);

  useEffect(() => {
    if (!hostRef.current || !model) return undefined;

    const host = hostRef.current;
    const styles = getComputedStyle(host);
    const primary = styles.getPropertyValue("--energy-brand").trim() || "currentColor";
    const success = styles.getPropertyValue("--energy-success").trim() || primary;
    const warning = styles.getPropertyValue("--energy-warning").trim() || primary;
    const info = styles.getPropertyValue("--energy-info").trim() || primary;
    const muted = styles.getPropertyValue("--energy-muted").trim() || "currentColor";
    const line = styles.getPropertyValue("--energy-line").trim() || "currentColor";
    const surface = styles.getPropertyValue("--energy-surface").trim() || "transparent";
    const chart = echarts.init(host, undefined, { renderer: "canvas" });
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const labels = model.data.map(({ label }) => label);

    const option: EChartsOption = model.kind === "pie"
      ? {
          animation: !reduceMotion,
          aria: { enabled: true },
          color: [success, warning, primary, info],
          legend: { bottom: 0, left: "center", icon: "roundRect", textStyle: { color: muted, fontSize: 11 } },
          tooltip: { trigger: "item", formatter: `{b}: {c} ${model.unit}（{d}%）` },
          series: [{
            type: "pie",
            radius: ["42%", "72%"],
            center: ["50%", "45%"],
            avoidLabelOverlap: true,
            label: { color: muted, fontSize: 11, formatter: "{b}\n{c}" },
            itemStyle: { borderColor: surface, borderWidth: 3 },
            data: model.data.map(({ label, value }) => ({ name: label, value })),
          }],
        }
      : {
          animation: !reduceMotion,
          aria: { enabled: true },
          grid: { top: 30, right: 18, bottom: labels.length > 6 ? 58 : 38, left: 56, containLabel: true },
          tooltip: { trigger: "axis", axisPointer: { type: model.kind === "line" ? "line" : "shadow" }, valueFormatter: (value) => `${value} ${model.unit}` },
          xAxis: { type: "category", data: labels, axisTick: { alignWithLabel: true }, axisLine: { lineStyle: { color: line } }, axisLabel: { color: muted, fontSize: 11, interval: 0, rotate: labels.length > 6 ? 35 : 0 } },
          yAxis: { type: "value", name: model.unit, nameTextStyle: { color: muted, fontSize: 11 }, axisLabel: { color: muted, fontSize: 11 }, splitLine: { lineStyle: { color: line, type: "dashed" } } },
          series: model.kind === "line"
            ? [{ type: "line", data: model.data.map(({ value }) => value), smooth: false, symbol: "circle", symbolSize: 7, lineStyle: { color: info, width: 2 }, itemStyle: { color: info }, areaStyle: { color: `${info}18` }, emphasis: { scale: true } }]
            : [{ type: "bar", data: model.data.map(({ value }) => value), barMaxWidth: 42, itemStyle: { color: primary, borderRadius: [5, 5, 0, 0] }, emphasis: { itemStyle: { color: info } } }],
        };

    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    const observer = "ResizeObserver" in window ? new ResizeObserver(resize) : null;
    observer?.observe(host);

    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [model]);

  return <section className="trusted-query-chart" aria-labelledby="trusted-query-chart-title">
    <div className="trusted-query-chart-header">
      <strong id="trusted-query-chart-title">{model?.title || "结果可视化"}</strong>
      <span>{model?.description || "当前结果没有可绘制的数值摘要"}</span>
    </div>
    {model ? <div ref={hostRef} className="trusted-query-chart-canvas" role="img" aria-label={model.ariaLabel} /> : <div className="trusted-query-chart-empty">当前结果没有可绘制的数值摘要</div>}
  </section>;
}
