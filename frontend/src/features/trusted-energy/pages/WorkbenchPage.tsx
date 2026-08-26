import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { Activity, ArrowRight, Database, FileCheck2, Link2, Map as MapIcon, Search, ShieldCheck, UsersRound } from "lucide-react";
import { Link } from "react-router-dom";
import { useRemote } from "../../../hooks";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { RemoteState } from "../components/ui-primitives";
import { loadPrototypeDashboard, type PrototypeDashboardPayload } from "../trusted-space-api";

const ACTION_NAMES: Record<string, string> = { allow: "直接提供", deny: "禁止提供", aggregate: "汇总提供", delay: "延迟提供", compute_only: "仅计算不出域" };
const CITY_XY: Record<string, [number, number]> = { 济南: [117.0, 36.65], 青岛: [120.38, 36.07], 烟台: [121.45, 37.46], 潍坊: [119.16, 36.71], 临沂: [118.35, 35.1] };
const FLOW_ROUTES = [
  { from: [117.0, 36.65], to: [120.38, 36.07], label: "电力 ↔ 煤炭" },
  { from: [117.0, 36.65], to: [121.45, 37.46], label: "电力 ↔ 煤炭" },
  { from: [118.35, 35.1], to: [119.16, 36.71], label: "电力调配" },
];
const KPI_ICONS = [Database, ShieldCheck, UsersRound, Link2, Search];
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
    secondary: read("--prototype-ink"),
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
      });
  }
  return shandongMapPromise;
}

function formatTime(value: string) {
  return value.includes("T") ? value.slice(11, 16) : value.slice(-5);
}

function renderMapOption(chart: echarts.ECharts, data: PrototypeMap, index: number, colors: PrototypeColors, metricLabel: string, metricUnit: string) {
  const scatterData = Object.keys(data.series).map((region) => {
    const [x, y] = CITY_XY[region] || [117, 36];
    return { name: region, region, value: [x, y, data.series[region][index] || 0] };
  });
  const lines = FLOW_ROUTES.map((route) => ({ coords: [route.from, route.to], lineStyle: { color: colors.mapRoute, width: 2.5, opacity: 0.7, curveness: 0.25 } }));
  chart.setOption({
    tooltip: {
      trigger: "item",
      backgroundColor: colors.surface,
      borderColor: colors.line,
      textStyle: { color: colors.ink, fontSize: 12 },
      formatter: (params: any) => {
        if (params.seriesType === "lines") return "跨主体协同 · 数据可用不可见";
        if (!params.data) return params.name;
        return `<div style="font-weight:600">${params.data.region}</div><div>${metricLabel}：<b>${params.data.value[2]}</b> ${metricUnit}</div>`;
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
        effect: { show: true, period: 5, trailLength: 0.4, symbol: "arrow", symbolSize: 7, color: colors.mapRoute },
        lineStyle: { color: colors.mapRoute, width: 2.5, opacity: 0.7, curveness: 0.25 },
      },
      {
        type: "scatter",
        coordinateSystem: "geo",
        data: scatterData,
        zlevel: 3,
        symbol: "pin",
        symbolSize: (value: any) => Math.max(50, Math.min(90, Number(value?.[2] || 0) / 55)),
        label: { show: true, formatter: (params: any) => params.data.region, fontSize: 14, color: colors.mapLabel, position: "bottom", fontWeight: 700, distance: 10, textBorderColor: colors.surface, textBorderWidth: 3 },
        itemStyle: { color: colors.actions.allow, borderColor: colors.surface, borderWidth: 3, shadowBlur: 20, shadowColor: "rgba(0,0,0,.3)" },
        emphasis: { scale: 1.6, label: { show: true, fontSize: 16 } },
        animationDurationUpdate: 600,
      },
    ],
  }, true);
}

function DashboardMap({ data, index, metricLabel, metricUnit, ariaLabel }: { data: PrototypeMap; index: number; metricLabel: string; metricUnit: string; ariaLabel: string }) {
  const mapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
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
    }).catch(() => undefined);
    return () => {
      active = false;
      if (resize) window.removeEventListener("resize", resize);
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (chartRef.current && mapRef.current) renderMapOption(chartRef.current, data, index, getPrototypeColors(mapRef.current), metricLabel, metricUnit);
  }, [data, index, metricLabel, metricUnit]);

  return <div className="prototype-map prototype-map-echart" ref={mapRef} aria-label={ariaLabel}>
    {!data.days.length && <div className="prototype-map-empty">暂无区域受控汇总数据</div>}
  </div>;
}

function SubjectTrendChart({ points, label, unit, ariaLabel }: { points: Array<{ date: string; value: number }>; label: string; unit: string; ariaLabel: string }) {
  const chartRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!chartRef.current || !points.length) return undefined;
    const colors = getPrototypeColors(chartRef.current);
    const chart = echarts.init(chartRef.current);
    chart.setOption({
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
  return points.length ? <div className="prototype-echart-trend" ref={chartRef} aria-label={ariaLabel} /> : <div className="prototype-trend-empty" aria-label={ariaLabel}>暂无已签名日度汇总</div>;
}

function formatMetricValue(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
}

function SubjectMetricCard({ metric }: { metric: PrototypeDashboardPayload["metric"] }) {
  const available = metric.status === "available" && metric.value !== null;
  return <section className={`prototype-card prototype-subject-metric-card is-${metric.status}`}>
    <PrototypeCardTitle><Activity className="prototype-card-icon" size={18} strokeWidth={1.8} />{metric.title}</PrototypeCardTitle>
    <div className="prototype-subject-metric-head"><span>{metric.label}</span><b>{metric.status_label}</b></div>
    <div className="prototype-subject-metric-value">{available ? formatMetricValue(metric.value) : "—"}{available && <em>{metric.unit}</em>}</div>
    {available ? <div className="prototype-subject-metric-facts">
      <span><small>最近数据日</small><b>{metric.latest_date || "—"}</b></span>
      <span><small>统计口径</small><b>{metric.aggregation}</b></span>
      <span><small>记录范围</small><b>{metric.record_count} 条</b></span>
    </div> : <div className="prototype-subject-metric-empty">{metric.message}</div>}
    <div className="prototype-subject-metric-source"><i />{metric.source}</div>
  </section>;
}

function ActionPieChart({ values }: { values: Array<{ name: string; value: number; key: string }> }) {
  const chartRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!chartRef.current || !values.length) return undefined;
    const colors = getPrototypeColors(chartRef.current);
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      legend: { bottom: 0, textStyle: { fontSize: 11, color: colors.muted }, itemWidth: 10, itemHeight: 10 },
      color: values.map((item) => colors.actions[item.key as keyof typeof colors.actions] || colors.navy),
      series: [{ type: "pie", radius: ["42%", "68%"], center: ["50%", "44%"], data: values, label: { fontSize: 11, color: colors.muted }, emphasis: { itemStyle: { shadowBlur: 12, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,.15)" } } }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [values]);
  return <div className="prototype-echart-pie" ref={chartRef} aria-label="策略命中分布图" />;
}

function actionData(data: PrototypeDashboardPayload) {
  return Object.entries(data.action_counts).filter(([, value]) => value > 0).map(([key, value]) => ({ name: ACTION_NAMES[key] || key, value, key }));
}

function RoleFocusPanel({ view, notice, dataMode, dataStatus }: { view: PrototypeDashboardPayload["view"]; notice: string; dataMode: PrototypeDashboardPayload["data_mode"]; dataStatus: PrototypeDashboardPayload["metric"]["status"] }) {
  return <section className={`prototype-role-focus is-${view.kind}`} aria-label={view.focus_title}>
    <div className="prototype-role-focus-heading">
      <div>
        <div className="prototype-overview-label"><span>{view.scope_label}</span><span className="prototype-mode-tag">{view.energy_label}</span></div>
        <h2>{view.title}</h2>
        <p>{view.subtitle}</p>
        <div className={`prototype-data-notice is-${dataMode === "demo" ? "demo" : dataStatus}`}><i />{notice}</div>
      </div>
      <Link className="prototype-role-focus-action" to={view.primary_action.path}>{view.primary_action.label}<ArrowRight size={14} /></Link>
    </div>
  </section>;
}

export function WorkbenchPage() {
  const remote = useRemote(loadPrototypeDashboard, []);
  const data = remote.data;
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const isRegionalMap = data?.view.visualization === "regional_map";
  const dayCount = isRegionalMap ? data?.map.days.length || 0 : 0;

  useEffect(() => {
    if (!playing || dayCount < 2) return undefined;
    const timer = window.setInterval(() => setIndex((current) => (current + 1) % dayCount), 800);
    return () => window.clearInterval(timer);
  }, [dayCount, playing]);

  const pieData = data ? actionData(data) : [];
  const totalActions = pieData.reduce((sum, item) => sum + item.value, 0);

  return <PrototypePageFrame>
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    {data && <>
      <RoleFocusPanel view={data.view} notice={data.data_notice} dataMode={data.data_mode} dataStatus={data.metric.status} />
      <div className="prototype-kpi-grid">{data.view.kpis.map((item, itemIndex) => { const Icon = KPI_ICONS[itemIndex]; return <div className={`prototype-kpi-card${itemIndex > 3 ? " is-success" : ""}`} key={item.label}><div className="prototype-kpi-icon"><Icon size={17} strokeWidth={1.8} /></div><div className="prototype-kpi-label"><span>{item.label}</span><small>{item.meta}</small></div><strong>{item.value}</strong></div>; })}</div>

      <div className="prototype-dashboard-layout">
        <section className="prototype-card prototype-dashboard-map-card">
          <div className="prototype-card-heading"><div><PrototypeCardTitle>{isRegionalMap ? <MapIcon className="prototype-card-icon" size={18} strokeWidth={1.8} /> : <Activity className="prototype-card-icon" size={18} strokeWidth={1.8} />}{data.view.visual_title}</PrototypeCardTitle><div className="prototype-dashboard-subline">{data.view.visual_subtitle}</div>{isRegionalMap && <div className="prototype-dashboard-legend"><span><i className="is-line" />区域受控汇总</span><span><i className="is-line" />跨主体协同</span></div>}</div><span className="prototype-day-badge">{isRegionalMap ? data.map.days[index] || "—" : data.metric.latest_date || "—"}</span></div>
          {isRegionalMap ? <DashboardMap data={data.map} index={index} metricLabel={data.view.visual_value_label} metricUnit={data.view.visual_value_unit} ariaLabel={`${data.view.visual_title}地图`} /> : <SubjectTrendChart points={data.metric.trend} label={data.metric.label} unit={data.metric.unit} ariaLabel={`${data.view.visual_title}趋势图`} />}
          {isRegionalMap && <div className="prototype-slider-row"><button type="button" className="prototype-secondary-button" onClick={() => setPlaying((current) => !current)}>{playing ? "暂停" : "播放"}</button><input aria-label="选择态势日期" type="range" min={0} max={Math.max(0, dayCount - 1)} value={Math.min(index, Math.max(0, dayCount - 1))} onChange={(event) => { setIndex(Number(event.target.value)); setPlaying(false); }} /><span>{playing ? "播放中" : "已暂停"}</span></div>}
        </section>
        <aside className="prototype-dashboard-side">
          <SubjectMetricCard metric={data.metric} />
          <section className="prototype-card prototype-feed-card"><PrototypeCardTitle><FileCheck2 className="prototype-card-icon" size={18} strokeWidth={1.8} />实时审计流</PrototypeCardTitle><div className="prototype-feed-list">{data.audit.length ? data.audit.map((item) => <div className="prototype-feed-item" key={item.id}><i className={`is-${item.action}`} /><span><b>{item.action_name}</b> · {item.subject} · {item.resource}</span><time>{formatTime(item.ts)}</time></div>) : <div className="prototype-empty">暂无审计记录</div>}</div></section>
        </aside>
      </div>

      <div className="prototype-dashboard-bottom">
        <section className="prototype-card prototype-chart-card"><PrototypeCardTitle><Activity className="prototype-card-icon" size={18} strokeWidth={1.8} />策略命中分布</PrototypeCardTitle>{pieData.length ? <ActionPieChart values={pieData} /> : <div className="prototype-empty">暂无策略命中记录</div>}<div className="prototype-card-caption prototype-chart-caption">共 {totalActions} 次裁决</div></section>
        <section className="prototype-card prototype-chart-card"><PrototypeCardTitle><MonitorIcon /><span>连接器健康状态</span></PrototypeCardTitle><div className="prototype-status-list">{data.connectors.map((connector) => <div key={connector.name}><span>{connector.name}</span><b className={/未接入|不可用|异常/.test(connector.status) ? "is-danger" : ""}>{connector.status}</b></div>)}</div></section>
        <section className="prototype-card prototype-chart-card"><PrototypeCardTitle><UsersRound className="prototype-card-icon" size={18} strokeWidth={1.8} />跨主体协同轨迹</PrototypeCardTitle><div className="prototype-timeline">{data.timeline.length ? data.timeline.map((item) => <div key={item.id}><time>{formatTime(item.ts)}</time><span><b>{item.resource}</b> · {item.subject}</span></div>) : <div className="prototype-empty">暂无跨主体协同记录</div>}</div></section>
      </div>
    </>}
  </PrototypePageFrame>;
}

function MonitorIcon() {
  return <ShieldCheck className="prototype-card-icon" size={18} strokeWidth={1.8} />;
}
