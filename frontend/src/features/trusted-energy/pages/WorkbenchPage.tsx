import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { Activity, Database, FileCheck2, Link2, LockKeyhole, Map as MapIcon, Search, ShieldCheck, UsersRound } from "lucide-react";
import { useRemote } from "../../../hooks";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { RemoteState } from "../components/ui-primitives";
import { loadPrototypeDashboard, type PrototypeDashboardPayload } from "../trusted-space-api";

const ACTION_COLORS: Record<string, string> = {
  allow: "#059669",
  deny: "#dc2626",
  aggregate: "#d97706",
  delay: "#7c3aed",
  compute_only: "#0891b2",
};
const ACTION_NAMES: Record<string, string> = { allow: "直接提供", deny: "禁止提供", aggregate: "汇总提供", delay: "延迟提供", compute_only: "仅计算不出域" };
const CITY_XY: Record<string, [number, number]> = { 济南: [117.0, 36.65], 青岛: [120.38, 36.07], 烟台: [121.45, 37.46], 潍坊: [119.16, 36.71], 临沂: [118.35, 35.1] };
const FLOW_ROUTES = [
  { from: [117.0, 36.65], to: [120.38, 36.07], label: "电力 ↔ 煤炭" },
  { from: [117.0, 36.65], to: [121.45, 37.46], label: "电力 ↔ 煤炭" },
  { from: [118.35, 35.1], to: [119.16, 36.71], label: "电力调配" },
];
const KPI_ICONS = [Database, ShieldCheck, UsersRound, Link2, Search, LockKeyhole];
const CONNECTOR_NOTES = ["电力连接器", "煤炭连接器", "策略引擎", "哈希链存证"];
type PrototypeMap = PrototypeDashboardPayload["map"];

let shandongMapPromise: Promise<void> | null = null;

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

function coalColor(days: number) {
  if (days >= 15) return "#059669";
  if (days >= 7) return "#d97706";
  return "#dc2626";
}

function renderMapOption(chart: echarts.ECharts, data: PrototypeMap, index: number) {
  const coalDays = data.coal_days[index] || 0;
  const scatterData = Object.keys(data.series).map((region) => {
    const [x, y] = CITY_XY[region] || [117, 36];
    return { name: region, region, value: [x, y, data.series[region][index] || 0, coalDays] };
  });
  const lines = FLOW_ROUTES.map((route) => ({ coords: [route.from, route.to], lineStyle: { color: "#00a3e0", width: 2.5, opacity: 0.7, curveness: 0.25 } }));
  chart.setOption({
    tooltip: {
      trigger: "item",
      backgroundColor: "rgba(255,255,255,.96)",
      borderColor: "#e2e8f0",
      textStyle: { color: "#0f172a", fontSize: 12 },
      formatter: (params: any) => {
        if (params.seriesType === "lines") return "跨主体协同 · 数据可用不可见";
        if (!params.data) return params.name;
        return `<div style="font-weight:600">${params.data.region}</div><div>平均负荷：<b>${params.data.value[2]}</b> MW</div><div>电煤可支撑：<b style="color:${coalColor(params.data.value[3])}">${params.data.value[3]}</b> 天</div>`;
      },
    },
    geo: {
      map: "shandong",
      roam: true,
      zoom: 1.05,
      center: [119, 36.4],
      layoutCenter: ["50%", "50%"],
      layoutSize: "100%",
      itemStyle: { areaColor: "#e0f2fe", borderColor: "#64748b", borderWidth: 1.2, shadowBlur: 4, shadowColor: "rgba(0,0,0,.08)" },
      emphasis: { itemStyle: { areaColor: "#bfdbfe" }, label: { show: false } },
    },
    series: [
      { type: "map", map: "shandong", geoIndex: 0, roam: false, data: [] },
      {
        type: "lines",
        coordinateSystem: "geo",
        data: lines,
        zlevel: 2,
        effect: { show: true, period: 5, trailLength: 0.4, symbol: "arrow", symbolSize: 7, color: "#00a3e0" },
        lineStyle: { color: "#00a3e0", width: 2.5, opacity: 0.7, curveness: 0.25 },
      },
      {
        type: "scatter",
        coordinateSystem: "geo",
        data: scatterData,
        zlevel: 3,
        symbol: "pin",
        symbolSize: (value: any) => Math.max(50, Math.min(90, Number(value?.[2] || 0) / 55)),
        label: { show: true, formatter: (params: any) => params.data.region, fontSize: 14, color: "#0f172a", position: "bottom", fontWeight: 700, distance: 10, textBorderColor: "#fff", textBorderWidth: 3 },
        itemStyle: { color: (params: any) => coalColor(Number(params?.data?.value?.[3] || 0)), borderColor: "#fff", borderWidth: 3, shadowBlur: 20, shadowColor: "rgba(0,0,0,.3)" },
        emphasis: { scale: 1.6, label: { show: true, fontSize: 16 } },
        animationDurationUpdate: 600,
      },
    ],
  }, true);
}

function DashboardMap({ data, index }: { data: PrototypeMap; index: number }) {
  const mapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const latest = useRef({ data, index });
  latest.current = { data, index };

  useEffect(() => {
    let active = true;
    let resize: (() => void) | undefined;
    void ensureShandongMap().then(() => {
      if (!active || !mapRef.current) return;
      const chart = echarts.init(mapRef.current, undefined, { renderer: "canvas" });
      chartRef.current = chart;
      renderMapOption(chart, latest.current.data, latest.current.index);
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
    if (chartRef.current) renderMapOption(chartRef.current, data, index);
  }, [data, index]);

  return <div className="prototype-map prototype-map-echart" ref={mapRef} aria-label="山东能源供需态势地图">
    {!data.days.length && <div className="prototype-map-empty">暂无负荷与库存数据</div>}
  </div>;
}

function GaugeChart({ days, level }: { days: number; level: string }) {
  const gaugeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!gaugeRef.current) return undefined;
    const color = coalColor(days);
    const chart = echarts.init(gaugeRef.current);
    chart.setOption({
      series: [{
        type: "gauge",
        min: 0,
        max: 60,
        splitNumber: 6,
        radius: "92%",
        progress: { show: true, width: 12, itemStyle: { color } },
        axisLine: { lineStyle: { width: 12, color: [[1, "#e2e8f0"]] } },
        axisLabel: { fontSize: 10, color: "#94a3b8" },
        pointer: { width: 4, itemStyle: { color: "#475569" } },
        detail: { fontSize: 26, color: "#0f172a", offsetCenter: [0, "55%"], formatter: "{value} 天", fontWeight: 700 },
        title: { fontSize: 12, offsetCenter: [0, "82%"], color: "#64748b" },
        data: [{ value: days, name: level }],
      }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [days, level]);
  return <div className="prototype-echart-gauge" ref={gaugeRef} aria-label={`电煤库存可支撑 ${days} 天`} />;
}

function ActionPieChart({ values }: { values: Array<{ name: string; value: number; key: string }> }) {
  const chartRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!chartRef.current || !values.length) return undefined;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      legend: { bottom: 0, textStyle: { fontSize: 11, color: "#64748b" }, itemWidth: 10, itemHeight: 10 },
      color: values.map((item) => ACTION_COLORS[item.key] || "#0b3d91"),
      series: [{ type: "pie", radius: ["42%", "68%"], center: ["50%", "44%"], data: values, label: { fontSize: 11, color: "#64748b" }, emphasis: { itemStyle: { shadowBlur: 12, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,.15)" } } }],
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

export function WorkbenchPage() {
  const remote = useRemote(loadPrototypeDashboard, []);
  const data = remote.data;
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const dayCount = data?.map.days.length || 0;

  useEffect(() => {
    if (!playing || dayCount < 2) return undefined;
    const timer = window.setInterval(() => setIndex((current) => (current + 1) % dayCount), 800);
    return () => window.clearInterval(timer);
  }, [dayCount, playing]);

  useEffect(() => {
    if (dayCount && index >= dayCount) setIndex(0);
  }, [dayCount, index]);

  const pieData = data ? actionData(data) : [];
  const totalActions = pieData.reduce((sum, item) => sum + item.value, 0);

  return <PrototypePageFrame>
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    {data && <>
      <div className="prototype-kpi-grid">{[
        ["数据资源", data.kpis.resources], ["策略规则", data.kpis.rules], ["注册主体", data.kpis.identities], ["存证区块", data.kpis.blocks], ["今日受控查询", data.kpis.today_queries], ["数据不出域保障", data.kpis.no_domain_export],
      ].map(([label, value], itemIndex) => { const Icon = KPI_ICONS[itemIndex]; return <div className={`prototype-kpi-card${itemIndex > 3 ? " is-success" : ""}`} key={String(label)}><div className="prototype-kpi-icon"><Icon size={17} strokeWidth={1.8} /></div><span>{label}</span><strong>{value}</strong></div>; })}</div>

      <div className="prototype-dashboard-layout">
        <section className="prototype-card prototype-dashboard-map-card">
          <div className="prototype-card-heading"><div><PrototypeCardTitle><MapIcon className="prototype-card-icon" size={18} strokeWidth={1.8} />山东能源供需态势</PrototypeCardTitle><div className="prototype-dashboard-subline">电力负荷 · 电煤库存 · 跨主体协同，三位一体综合态势</div><div className="prototype-dashboard-legend"><span><i className="is-green" />库存充足（&gt;15天）</span><span><i className="is-orange" />警戒（7-15天）</span><span><i className="is-red" />缺口风险（&lt;7天）</span><span><i className="is-line" />跨主体协同</span></div></div><span className="prototype-day-badge">{data.map.days[index] || "—"}</span></div>
          <DashboardMap data={data.map} index={index} />
          <div className="prototype-slider-row"><button type="button" className="prototype-secondary-button" onClick={() => setPlaying((current) => !current)}>{playing ? "暂停" : "播放"}</button><input aria-label="选择态势日期" type="range" min={0} max={Math.max(0, dayCount - 1)} value={Math.min(index, Math.max(0, dayCount - 1))} onChange={(event) => { setIndex(Number(event.target.value)); setPlaying(false); }} /><span>{playing ? "播放中" : "已暂停"}</span></div>
        </section>
        <aside className="prototype-dashboard-side">
          <section className="prototype-card prototype-gauge-card"><PrototypeCardTitle><Activity className="prototype-card-icon" size={18} strokeWidth={1.8} />电煤库存可支撑天数</PrototypeCardTitle><GaugeChart days={data.gauge.days} level={data.gauge.level} /><div className="prototype-gauge-text" style={{ color: coalColor(data.gauge.days) }}>{data.gauge.level} · 库存 {data.gauge.inventory} 万吨</div></section>
          <section className="prototype-card prototype-feed-card"><PrototypeCardTitle><FileCheck2 className="prototype-card-icon" size={18} strokeWidth={1.8} />实时审计流</PrototypeCardTitle><div className="prototype-feed-list">{data.audit.length ? data.audit.map((item) => <div className="prototype-feed-item" key={item.id}><i className={`is-${item.action}`} /><span><b>{item.action_name}</b> · {item.subject} · {item.resource}</span><time>{formatTime(item.ts)}</time></div>) : <div className="prototype-empty">暂无审计记录</div>}</div></section>
        </aside>
      </div>

      <div className="prototype-dashboard-bottom">
        <section className="prototype-card prototype-chart-card"><PrototypeCardTitle><Activity className="prototype-card-icon" size={18} strokeWidth={1.8} />策略命中分布</PrototypeCardTitle>{pieData.length ? <ActionPieChart values={pieData} /> : <div className="prototype-empty">暂无策略命中记录</div>}<div className="prototype-card-caption prototype-chart-caption">共 {totalActions} 次裁决</div></section>
        <section className="prototype-card prototype-chart-card"><PrototypeCardTitle><MonitorIcon /><span>连接器健康状态</span></PrototypeCardTitle><div className="prototype-status-list">{CONNECTOR_NOTES.map((name, itemIndex) => <div key={name}><span>{name}</span><b className={itemIndex === 3 && !data.chain.ok ? "is-danger" : ""}>{itemIndex === 3 ? (data.chain.ok ? "完整" : "异常") : "正常"}</b></div>)}</div></section>
        <section className="prototype-card prototype-chart-card"><PrototypeCardTitle><UsersRound className="prototype-card-icon" size={18} strokeWidth={1.8} />跨主体协同轨迹</PrototypeCardTitle><div className="prototype-timeline">{data.timeline.length ? data.timeline.map((item) => <div key={item.id}><time>{formatTime(item.ts)}</time><span><b>{item.resource}</b> · {item.subject}</span></div>) : <div className="prototype-empty">暂无跨主体协同记录</div>}</div></section>
      </div>
    </>}
  </PrototypePageFrame>;
}

function MonitorIcon() {
  return <ShieldCheck className="prototype-card-icon" size={18} strokeWidth={1.8} />;
}
