import { useEffect, useMemo, useState } from "react";
import { Area, AreaChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { useRemote } from "../../../hooks";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { RemoteState } from "../components/ui-primitives";
import { loadPrototypeDashboard, type PrototypeDashboardPayload } from "../trusted-space-api";

const ACTION_COLORS: Record<string, string> = {
  allow: "var(--prototype-action-allow)",
  deny: "var(--prototype-action-deny)",
  aggregate: "var(--prototype-action-aggregate)",
  delay: "var(--prototype-action-delay)",
  compute_only: "var(--prototype-action-compute)",
};
const ACTION_NAMES: Record<string, string> = { allow: "直接提供", deny: "禁止提供", aggregate: "汇总提供", delay: "延迟提供", compute_only: "仅计算不出域" };
const CITY_POSITIONS = [{ name: "济南", left: "41%", top: "42%" }, { name: "青岛", left: "76%", top: "51%" }, { name: "烟台", left: "84%", top: "25%" }, { name: "潍坊", left: "64%", top: "42%" }, { name: "临沂", left: "52%", top: "73%" }];

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function actionData(data: PrototypeDashboardPayload) {
  return Object.entries(data.action_counts).filter(([, value]) => value > 0).map(([key, value]) => ({ name: ACTION_NAMES[key] || key, value, key }));
}

function DashboardMap({ data, index }: { data: PrototypeDashboardPayload["map"]; index: number }) {
  const activeValues = Object.values(data.series).map((values) => values[index] || 0);
  const max = Math.max(...activeValues, 1);
  return <div className="prototype-map" aria-label="山东能源供需态势">
    <div className="prototype-map-grid" />
    {CITY_POSITIONS.map((city, cityIndex) => {
      const value = activeValues[cityIndex] || 0;
      return <div className="prototype-map-city" key={city.name} style={{ left: city.left, top: city.top }}><span className="prototype-map-pin" style={{ transform: `scale(${0.85 + value / max * 0.7})` }} /><b>{city.name}</b></div>;
    })}
    <span className="prototype-map-route prototype-map-route-one" /><span className="prototype-map-route prototype-map-route-two" /><span className="prototype-map-route prototype-map-route-three" />
    {!data.days.length && <div className="prototype-map-empty">暂无负荷与库存数据</div>}
  </div>;
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

  const chartData = useMemo(() => {
    if (!data) return [];
    return data.map.days.map((day, dayIndex) => ({ day: day.slice(5), ...Object.fromEntries(Object.entries(data.map.series).map(([name, values]) => [name, values[dayIndex] || 0])) }));
  }, [data]);
  const pieData = data ? actionData(data) : [];
  const gaugePercent = data ? Math.min(100, Math.max(0, data.gauge.days / 60 * 100)) : 0;
  const gaugeColor = data && data.gauge.days >= 15 ? "var(--prototype-action-allow)" : data && data.gauge.days >= 7 ? "var(--prototype-action-aggregate)" : "var(--prototype-action-deny)";

  return <PrototypePageFrame>
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    {data && <>
      <div className="prototype-kpi-grid">{[
        ["数据资源", data.kpis.resources, ""], ["策略规则", data.kpis.rules, ""], ["注册主体", data.kpis.identities, ""], ["存证区块", data.kpis.blocks, ""], ["今日受控查询", data.kpis.today_queries, "is-success"], ["数据不出域保障", data.kpis.no_domain_export, "is-success"],
      ].map(([label, value, tone]) => <div className={`prototype-kpi-card ${tone}`} key={String(label)}><span>{label}</span><strong>{value}</strong></div>)}</div>

      <div className="prototype-dashboard-layout">
        <section className="prototype-card prototype-dashboard-map-card">
          <div className="prototype-card-heading"><div><PrototypeCardTitle>山东能源供需态势</PrototypeCardTitle><div className="prototype-dashboard-legend"><span><i className="is-green" />库存充足（&gt;15天）</span><span><i className="is-orange" />警戒（7-15天）</span><span><i className="is-red" />缺口风险（&lt;7天）</span><span><i className="is-line" />跨主体协同</span></div></div><span className="prototype-day-badge">{data.map.days[index] || "—"}</span></div>
          <DashboardMap data={data.map} index={index} />
          <div className="prototype-slider-row"><button type="button" className="prototype-secondary-button" onClick={() => setPlaying((current) => !current)}>{playing ? "暂停" : "播放"}</button><input type="range" min={0} max={Math.max(0, dayCount - 1)} value={Math.min(index, Math.max(0, dayCount - 1))} onChange={(event) => { setIndex(Number(event.target.value)); setPlaying(false); }} /><span>{playing ? "播放中" : "已暂停"}</span></div>
        </section>
        <aside className="prototype-dashboard-side">
          <section className="prototype-card prototype-gauge-card"><PrototypeCardTitle>电煤库存可支撑天数</PrototypeCardTitle><div className="prototype-gauge" style={{ background: `conic-gradient(${gaugeColor} ${gaugePercent}%, var(--prototype-gauge-track) 0)` }}><div><strong>{data.gauge.days || "—"}</strong><span>天</span></div></div><div className="prototype-gauge-text" style={{ color: gaugeColor }}>{data.gauge.level} · 库存 {data.gauge.inventory} 万吨</div></section>
          <section className="prototype-card prototype-feed-card"><PrototypeCardTitle>实时审计流</PrototypeCardTitle><div className="prototype-feed-list">{data.audit.length ? data.audit.map((item) => <div className="prototype-feed-item" key={item.id}><i className={`is-${item.action}`} /><span><b>{item.action_name}</b> · {item.subject} · {item.resource}</span><time>{formatTime(item.ts)}</time></div>) : <div className="prototype-empty">暂无审计记录</div>}</div></section>
        </aside>
      </div>

      <div className="prototype-dashboard-bottom">
        <section className="prototype-card prototype-chart-card"><PrototypeCardTitle>策略命中分布</PrototypeCardTitle>{pieData.length ? <ResponsiveContainer width="100%" height={205}><PieChart><Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="42%" innerRadius={44} outerRadius={70} paddingAngle={2}>{pieData.map((item) => <Cell key={item.key} fill={ACTION_COLORS[item.key] || "var(--prototype-action-navy)"} />)}</Pie><Tooltip formatter={(value, name) => [value, name]} /><text x="50%" y="44%" textAnchor="middle" dominantBaseline="middle" fill="var(--prototype-ink)" fontSize="18" fontWeight="700">{pieData.reduce((sum, item) => sum + item.value, 0)}</text><text x="50%" y="54%" textAnchor="middle" fill="var(--prototype-muted)" fontSize="11">次裁决</text></PieChart></ResponsiveContainer> : <div className="prototype-empty">暂无策略命中记录</div>}</section>
        <section className="prototype-card prototype-chart-card"><PrototypeCardTitle>连接器健康状态</PrototypeCardTitle><div className="prototype-status-list">{data.connectors.map((item) => <div key={item.name}><span>{item.name}</span><b className={item.status === "异常" ? "is-danger" : ""}>{item.status}</b></div>)}</div></section>
        <section className="prototype-card prototype-chart-card"><PrototypeCardTitle>跨主体协同轨迹</PrototypeCardTitle><div className="prototype-timeline">{data.timeline.length ? data.timeline.map((item) => <div key={item.id}><time>{formatTime(item.ts)}</time><span><b>{item.resource}</b> · {item.subject}</span></div>) : <div className="prototype-empty">暂无跨主体协同记录</div>}</div></section>
      </div>
      {chartData.length > 1 && <section className="prototype-card prototype-trend-card"><PrototypeCardTitle>电力负荷趋势</PrototypeCardTitle><ResponsiveContainer width="100%" height={180}><AreaChart data={chartData}><defs><linearGradient id="prototype-load-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="var(--prototype-accent)" stopOpacity={0.25} /><stop offset="95%" stopColor="var(--prototype-accent)" stopOpacity={0} /></linearGradient></defs><Tooltip /><Area type="monotone" dataKey="load_curve" stroke="var(--prototype-accent)" fill="url(#prototype-load-fill)" strokeWidth={2} /></AreaChart></ResponsiveContainer></section>}
    </>}
  </PrototypePageFrame>;
}
