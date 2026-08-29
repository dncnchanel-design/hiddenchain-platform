import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart, LinesChart, MapChart, PieChart, ScatterChart } from "echarts/charts";
import { GeoComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import type { ECharts } from "echarts";
import { CanvasRenderer } from "echarts/renderers";
import { RemoteState } from "./ui-primitives";
import type { PrototypeDashboardPayload } from "../trusted-space-api";

echarts.use([LineChart, LinesChart, MapChart, PieChart, ScatterChart, GeoComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

const CITY_XY: Record<string, [number, number]> = { 济南: [117.0, 36.65], 青岛: [120.38, 36.07], 烟台: [121.45, 37.46], 潍坊: [119.16, 36.71], 临沂: [118.35, 35.1] };
const FLOW_ROUTES = [
  { from: [117.0, 36.65], to: [120.38, 36.07] },
  { from: [117.0, 36.65], to: [121.45, 37.46] },
  { from: [118.35, 35.1], to: [119.16, 36.71] },
];
type PrototypeMap = PrototypeDashboardPayload["map"];

let shandongMapPromise: Promise<void> | null = null;

function getPrototypeColors(host: Element) {
  const styles = getComputedStyle(host);
  const read = (token: string, fallback = "currentColor") => styles.getPropertyValue(token).trim() || fallback;
  return {
    actions: {
      allow: read("--prototype-action-allow"),
      deny: read("--prototype-action-deny"),
      aggregate: read("--prototype-action-aggregate"),
      delay: read("--prototype-action-delay"),
      compute_only: read("--prototype-action-compute"),
    },
    ink: read("--prototype-ink"),
    muted: read("--prototype-muted"),
    navy: read("--prototype-action-navy"),
    line: read("--prototype-chart-grid"),
    surface: read("--prototype-map-surface"),
    mapFill: read("--prototype-map-fill"),
    mapBoundary: read("--prototype-map-boundary"),
    mapLabel: read("--prototype-map-label"),
    mapRoute: read("--prototype-map-route"),
  };
}

type PrototypeColors = ReturnType<typeof getPrototypeColors>;

function ensureShandongMap() {
  if (echarts.getMap("shandong")) return Promise.resolve();
  if (!shandongMapPromise) {
    shandongMapPromise = fetch("/shandong_cities.json")
      .then(async (response) => {
        if (!response.ok) throw new Error(`地图数据加载失败（${response.status}）`);
        return response.json();
      })
      .then((geo) => {
        echarts.registerMap("shandong", geo as any);
      })
      .catch((error) => {
        shandongMapPromise = null;
        throw error;
      });
  }
  return shandongMapPromise;
}

function formatCityDays(value: number | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 }).format(value)}天`;
}

function renderMapOption(chart: ECharts, data: PrototypeMap, index: number, colors: PrototypeColors, metricLabel: string, metricUnit: string) {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scatterData = Object.keys(data.series).map((region) => {
    const [x, y] = CITY_XY[region] || [117, 36];
    return { name: region, region, cityDays: data.city_days?.[region]?.[index], value: [x, y, data.series[region][index] || 0] };
  });
  const lines = FLOW_ROUTES.map((route) => ({ coords: [route.from, route.to], lineStyle: { color: colors.mapRoute, width: 2.5, opacity: 0.7, curveness: 0.25 } }));
  chart.setOption({
    animation: !reduceMotion,
    tooltip: {
      trigger: "item",
      backgroundColor: colors.surface,
      borderColor: colors.line,
      textStyle: { color: colors.ink, fontSize: 12 },
      formatter: (params: any) => {
        if (params.seriesType === "lines") return "跨主体协同 · 数据可用不可见";
        if (!params.data) return params.name;
        return `<div style="font-weight:600">${params.data.region}</div><div>${metricLabel}：<b>${params.data.value[2]}</b> ${metricUnit}</div><div>城市受控天数：<b>${formatCityDays(params.data.cityDays)}</b></div>`;
      },
    },
    geo: {
      map: "shandong",
      roam: true,
      zoom: 1.05,
      center: [119, 36.4],
      layoutCenter: ["50%", "50%"],
      layoutSize: "100%",
      itemStyle: { areaColor: colors.mapFill, borderColor: colors.mapBoundary, borderWidth: 1.2, shadowBlur: 4, shadowColor: "rgba(0,0,0,.08)" },
      emphasis: { itemStyle: { areaColor: colors.mapFill }, label: { show: false } },
    },
    series: [
      { type: "map", map: "shandong", geoIndex: 0, roam: false, data: [] },
      {
        type: "lines",
        coordinateSystem: "geo",
        data: lines,
        zlevel: 2,
        effect: { show: !reduceMotion, period: 5, trailLength: 0.4, symbol: "arrow", symbolSize: 7, color: colors.mapRoute },
        lineStyle: { color: colors.mapRoute, width: 2.5, opacity: 0.7, curveness: 0.25 },
      },
      {
        type: "scatter",
        coordinateSystem: "geo",
        data: scatterData,
        zlevel: 3,
        symbol: "pin",
        symbolSize: (value: any) => Math.max(50, Math.min(90, Number(value?.[2] || 0) / 55)),
        label: { show: true, formatter: (params: any) => `${params.data.region}\n${formatCityDays(params.data.cityDays)}`, fontSize: 13, lineHeight: 18, color: colors.mapLabel, position: "bottom", fontWeight: 700, distance: 10, textBorderColor: colors.surface, textBorderWidth: 3 },
        itemStyle: { color: colors.actions.allow, borderColor: colors.surface, borderWidth: 3, shadowBlur: 20, shadowColor: "rgba(0,0,0,.3)" },
        emphasis: { scale: 1.6, label: { show: true, fontSize: 16 } },
        animationDurationUpdate: 600,
      },
    ],
  }, true);
}

export function DashboardMap({ data, index, metricLabel, metricUnit, ariaLabel }: { data: PrototypeMap; index: number; metricLabel: string; metricUnit: string; ariaLabel: string }) {
  const mapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ECharts | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadError, setLoadError] = useState("");
  const latest = useRef({ data, index, metricLabel, metricUnit });
  useEffect(() => {
    latest.current = { data, index, metricLabel, metricUnit };
  }, [data, index, metricLabel, metricUnit]);

  useEffect(() => {
    let active = true;
    let resize: (() => void) | undefined;
    void ensureShandongMap().then(() => {
      if (!active || !mapRef.current) return;
      const chart = echarts.init(mapRef.current, undefined, { renderer: "canvas" });
      chartRef.current = chart;
      renderMapOption(chart, latest.current.data, latest.current.index, getPrototypeColors(mapRef.current), latest.current.metricLabel, latest.current.metricUnit);
      resize = () => chart.resize();
      window.addEventListener("resize", resize);
    }).catch((error) => {
      if (active) setLoadError(error instanceof Error ? error.message : "地图数据加载失败");
    });
    return () => {
      active = false;
      if (resize) window.removeEventListener("resize", resize);
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, [loadAttempt]);

  useEffect(() => {
    if (chartRef.current && mapRef.current) renderMapOption(chartRef.current, data, index, getPrototypeColors(mapRef.current), metricLabel, metricUnit);
  }, [data, index, metricLabel, metricUnit]);

  const summary = Object.entries(data.series).map(([region, values]) => `${region} ${values[index] ?? 0} ${metricUnit}`).join("，");
  return <div className="prototype-map prototype-map-echart" ref={mapRef} role="img" aria-label={`${ariaLabel}。${summary || "暂无区域受控汇总数据"}`}>
    {loadError ? <RemoteState error={loadError} onRetry={() => { setLoadError(""); setLoadAttempt((value) => value + 1); }} /> : !data.days.length && <div className="prototype-map-empty">暂无区域受控汇总数据</div>}
  </div>;
}

export function SubjectTrendChart({ points, label, unit, ariaLabel }: { points: Array<{ date: string; value: number }>; label: string; unit: string; ariaLabel: string }) {
  const chartRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!chartRef.current || !points.length) return undefined;
    const colors = getPrototypeColors(chartRef.current);
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      animation: !reduceMotion,
      grid: { top: 18, right: 18, bottom: 38, left: 52, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: colors.surface,
        borderColor: colors.line,
        textStyle: { color: colors.ink, fontSize: 12 },
        formatter: (params: any[]) => {
          const point = params?.[0];
          return `${label}<br/>${point?.axisValue || "—"}：<b>${point?.data ?? "—"}</b> ${unit}`;
        },
      },
      xAxis: { type: "category", boundaryGap: false, data: points.map((point) => point.date.slice(5)), axisLabel: { color: colors.muted, fontSize: 10 }, axisLine: { lineStyle: { color: colors.line } } },
      yAxis: { type: "value", name: unit, nameTextStyle: { color: colors.muted, fontSize: 10 }, axisLabel: { color: colors.muted, fontSize: 10 }, splitLine: { lineStyle: { color: colors.line, type: "dashed" } } },
      series: [{ type: "line", name: label, data: points.map((point) => point.value), smooth: 0.25, symbol: "circle", symbolSize: 6, showSymbol: points.length < 14, lineStyle: { color: colors.mapRoute, width: 3 }, itemStyle: { color: colors.mapRoute }, areaStyle: { color: "rgba(0,163,224,.10)" } }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [label, points, unit]);
  const summary = points.map((point) => `${point.date} ${point.value} ${unit}`).join("，");
  return points.length ? <div className="prototype-echart-trend" ref={chartRef} role="img" aria-label={`${ariaLabel}。${summary}`} /> : <div className="prototype-trend-empty" aria-label={ariaLabel}>暂无已签名日度汇总</div>;
}

export function ActionPieChart({ values }: { values: Array<{ name: string; value: number; key: string }> }) {
  const chartRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!chartRef.current || !values.length) return undefined;
    const colors = getPrototypeColors(chartRef.current);
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      animation: !reduceMotion,
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      legend: { bottom: 0, textStyle: { fontSize: 11, color: colors.muted }, itemWidth: 10, itemHeight: 10 },
      color: values.map((item) => colors.actions[item.key as keyof typeof colors.actions] || colors.navy),
      series: [{ type: "pie", radius: ["42%", "68%"], center: ["50%", "44%"], data: values, label: { fontSize: 11, color: colors.muted }, emphasis: { itemStyle: { shadowBlur: 12, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,.15)" } } }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [values]);
  return <div className="prototype-echart-pie" ref={chartRef} role="img" aria-label={`策略命中分布图。${values.map((item) => `${item.name} ${item.value} 次`).join("，")}`} />;
}
