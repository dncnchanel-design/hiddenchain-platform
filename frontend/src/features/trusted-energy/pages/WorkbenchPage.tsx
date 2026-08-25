import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Cell, Line, LineChart, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
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
const CITY_COLORS = ["var(--prototype-action-navy)", "var(--prototype-accent)", "var(--prototype-action-allow)", "var(--prototype-action-aggregate)", "var(--prototype-action-delay)"];
const CITY_POSITIONS = [
  { name: "济南", left: "41%", top: "42%" },
  { name: "青岛", left: "76%", top: "51%" },
  { name: "烟台", left: "84%", top: "25%" },
  { name: "潍坊", left: "64%", top: "42%" },
  { name: "临沂", left: "52%", top: "73%" },
];

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "未提供" : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function formatNumber(value: number, fractionDigits = 0) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: fractionDigits, minimumFractionDigits: fractionDigits }).format(value);
}

function actionData(data: PrototypeDashboardPayload) {
  return Object.entries(data.action_counts).filter(([, value]) => value > 0).map(([key, value]) => ({ name: ACTION_NAMES[key] || key, value, key }));
}

function DashboardMap({ data, index }: { data: PrototypeDashboardPayload["map"]; index: number }) {
  const cities = CITY_POSITIONS.map((city, cityIndex) => ({
    ...city,
    value: data.series[city.name]?.[index] || 0,
    color: CITY_COLORS[cityIndex],
  }));
  const max = Math.max(...cities.map((city) => city.value), 1);
  const totalLoad = cities.reduce((sum, city) => sum + city.value, 0);
  const coalDays = data.coal_days[index] || 0;

  return <div className="prototype-map" aria-label="山东能源供需态势">
    <div className="prototype-map-grid" />
    <div className="prototype-map-summary"><span>当前区域负荷</span><strong>{formatNumber(totalLoad)} MW</strong><small>5 个能源节点已接入</small></div>
    <div className="prototype-map-status"><i className={coalDays >= 15 ? "is-green" : coalDays >= 7 ? "is-orange" : "is-red"} /><span>库存覆盖</span><b>{coalDays ? `${formatNumber(coalDays, 1)} 天` : "暂无数据"}</b></div>
    {cities.map((city) => <div className="prototype-map-city" key={city.name} style={{ left: city.left, top: city.top }} title={`${city.name} ${formatNumber(city.value)} MW`}>
      <span className="prototype-map-pin" style={{ background: city.color, transform: `rotate(-45deg) scale(${0.85 + city.value / max * 0.7})` }} />
      <b>{city.name}</b>
      <small>{formatNumber(city.value)} MW</small>
    </div>)}
    <span className="prototype-map-route prototype-map-route-one" />
    <span className="prototype-map-route prototype-map-route-two" />
    <span className="prototype-map-route prototype-map-route-three" />
    <span className="prototype-map-route prototype-map-route-four" />
    <div className="prototype-map-scale"><span>供需协同路径</span><span><i />数据节点</span><span><i className="is-line" />跨主体调用</span></div>
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
    return data.map.days.map((day, dayIndex) => ({
      day: day.slice(5),
      coal_days: data.map.coal_days[dayIndex] || 0,
      ...Object.fromEntries(Object.entries(data.map.series).map(([name, values]) => [name, values[dayIndex] || 0])),
    }));
  }, [data]);
  const pieData = data ? actionData(data) : [];
  const currentCoalDays = data?.map.coal_days[index] || data?.gauge.days || 0;
  const currentInventory = data?.map.coal_inventory[index] || data?.gauge.inventory || 0;
  const currentConsumption = data?.map.coal_consumption[index] || 0;
  const currentLoad = data ? CITY_POSITIONS.reduce((sum, city) => sum + (data.map.series[city.name]?.[index] || 0), 0) : 0;
  const peakLoad = data ? Math.max(...CITY_POSITIONS.flatMap((city) => data.map.series[city.name] || []), 0) : 0;
  const gaugePercent = Math.min(100, Math.max(0, currentCoalDays / 24 * 100));
  const gaugeColor = currentCoalDays >= 15 ? "var(--prototype-action-allow)" : currentCoalDays >= 7 ? "var(--prototype-action-aggregate)" : "var(--prototype-action-deny)";
  const latestDay = data?.map.days[index] || "暂无日期";
  const totalActions = pieData.reduce((sum, item) => sum + item.value, 0);
  const connectorNotes = ["最近心跳 00:32", "最近心跳 00:47", "策略版本 2026.08", "追加写入正常"];

  return <PrototypePageFrame>
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    {data && <>
      <section className="prototype-dashboard-overview">
        <div>
          <div className="prototype-overview-label"><span>运行总览</span><span className={`prototype-data-badge is-${data.data_mode}`}>{data.data_notice}</span></div>
          <h2>山东能源供需态势</h2>
          <p>用受控汇总观察电力负荷、煤炭库存与跨主体协同，原始明细始终留在企业侧。</p>
        </div>
        <div className="prototype-overview-facts">
          <span><small>监测窗口</small><b>近 7 日</b></span>
          <span><small>当前日期</small><b>{latestDay}</b></span>
          <span><small>存证状态</small><b className={data.chain.ok ? "is-good" : "is-bad"}>{data.chain.ok ? "哈希链完整" : "待核验"}</b></span>
        </div>
      </section>

      <div className="prototype-kpi-grid">{[
        { label: "数据资源", value: data.kpis.resources, detail: "已发布目录", tone: "" },
        { label: "策略规则", value: data.kpis.rules, detail: "当前适用策略", tone: "" },
        { label: "注册主体", value: data.kpis.identities, detail: "可协同参与方", tone: "" },
        { label: "存证区块", value: data.kpis.blocks, detail: data.chain.ok ? "哈希链完整" : "待核验", tone: "" },
        { label: "今日受控查询", value: data.kpis.today_queries, detail: "过去 24 小时", tone: "is-success" },
        { label: "数据不出域保障", value: data.kpis.no_domain_export, detail: "原始明细不返回", tone: "is-success" },
      ].map((item) => <div className={`prototype-kpi-card ${item.tone}`} key={item.label}>
        <div className="prototype-kpi-label"><span>{item.label}</span><small>{item.detail}</small></div>
        <strong>{item.value}</strong>
      </div>)}</div>

      <div className="prototype-dashboard-layout">
        <section className="prototype-card prototype-dashboard-map-card">
          <div className="prototype-card-heading">
            <div>
              <PrototypeCardTitle action={<span className="prototype-day-badge">{latestDay}</span>}>山东能源供需态势</PrototypeCardTitle>
              <div className="prototype-dashboard-subline"><span>当前区域负荷 <b>{formatNumber(currentLoad)} MW</b></span><span>库存覆盖 <b>{formatNumber(currentCoalDays, 1)} 天</b></span><span>跨主体调用路径 <b>12 条</b></span></div>
              <div className="prototype-dashboard-legend"><span><i className="is-green" />库存充足（&gt;15天）</span><span><i className="is-orange" />警戒（7-15天）</span><span><i className="is-red" />缺口风险（&lt;7天）</span><span><i className="is-line" />跨主体协同</span></div>
            </div>
          </div>
          <DashboardMap data={data.map} index={index} />
          <div className="prototype-slider-row"><button type="button" className="prototype-secondary-button" onClick={() => setPlaying((current) => !current)}>{playing ? "暂停" : "播放"}</button><input aria-label="选择态势日期" type="range" min={0} max={Math.max(0, dayCount - 1)} value={Math.min(index, Math.max(0, dayCount - 1))} onChange={(event) => { setIndex(Number(event.target.value)); setPlaying(false); }} /><span>{playing ? "播放中" : "已暂停"}</span></div>
          <div className="prototype-trend-panel">
            <div className="prototype-trend-header"><div><strong>区域负荷趋势</strong><span>MW · 近 7 日</span></div><span>峰值 {formatNumber(peakLoad)} MW</span></div>
            {chartData.length > 1 ? <ResponsiveContainer width="100%" height={148}><LineChart data={chartData} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid stroke="var(--prototype-chart-grid)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="day" tick={{ fill: "var(--prototype-muted)", fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fill: "var(--prototype-muted)", fontSize: 10 }} tickLine={false} axisLine={false} width={38} tickFormatter={(value) => `${Math.round(Number(value) / 1000)}k`} />
              <Tooltip />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />
              {CITY_POSITIONS.map((city, cityIndex) => <Line key={city.name} type="monotone" dataKey={city.name} name={city.name} stroke={CITY_COLORS[cityIndex]} strokeWidth={2} dot={false} activeDot={{ r: 3 }} />)}
            </LineChart></ResponsiveContainer> : <div className="prototype-empty">暂无负荷趋势数据</div>}
          </div>
        </section>

        <aside className="prototype-dashboard-side">
          <section className="prototype-card prototype-gauge-card">
            <PrototypeCardTitle action={<span className={`prototype-mode-tag is-${data.data_mode}`}>{data.data_mode === "demo" ? "演示口径" : "实时"}</span>}>电煤库存可支撑天数</PrototypeCardTitle>
            <div className="prototype-gauge" style={{ background: `conic-gradient(${gaugeColor} ${gaugePercent}%, var(--prototype-gauge-track) 0)` }}><div><strong>{currentCoalDays ? formatNumber(currentCoalDays, 1) : "暂无"}</strong><span>天</span></div></div>
            <div className="prototype-gauge-text" style={{ color: gaugeColor }}>{currentCoalDays >= 15 ? "库存充足" : currentCoalDays >= 7 ? "库存警戒" : "缺口风险"} · 当前覆盖 {formatNumber(currentCoalDays, 1)} 天</div>
            <div className="prototype-gauge-facts"><span><small>当前库存</small><b>{formatNumber(currentInventory, 1)}<em>万吨</em></b></span><span><small>日均消耗</small><b>{formatNumber(currentConsumption, 1)}<em>万吨</em></b></span><span><small>安全线</small><b>15<em>天</em></b></span></div>
            <div className="prototype-gauge-footnote">库存统计来自企业侧受控汇总，不展示原始明细。</div>
          </section>
          <section className="prototype-card prototype-feed-card">
            <PrototypeCardTitle action={<span className="prototype-card-caption">最近 24 小时</span>}>实时审计流</PrototypeCardTitle>
            <div className="prototype-feed-list">{data.audit.length ? data.audit.map((item) => <div className="prototype-feed-item" key={item.id}><i className={`is-${item.action}`} /><span><b>{item.action_name}</b><small>{item.subject} · {item.resource}</small></span><time>{formatTime(item.ts)}</time></div>) : <div className="prototype-empty">暂无审计记录</div>}</div>
            <div className="prototype-feed-footer"><span><i className="is-live" />实时写入</span><b>{data.audit.length} 条事件</b></div>
          </section>
        </aside>
      </div>

      <div className="prototype-dashboard-bottom">
        <section className="prototype-card prototype-chart-card">
          <PrototypeCardTitle action={<span className="prototype-card-caption">{totalActions} 次裁决</span>}>策略命中分布</PrototypeCardTitle>
          <div className="prototype-pie-layout">{pieData.length ? <>
            <div className="prototype-pie-wrap"><ResponsiveContainer width="100%" height={160}><PieChart><Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="48%" innerRadius={42} outerRadius={66} paddingAngle={2}>{pieData.map((item) => <Cell key={item.key} fill={ACTION_COLORS[item.key] || "var(--prototype-action-navy)"} />)}</Pie><Tooltip formatter={(value, name) => [value, name]} /><text x="50%" y="45%" textAnchor="middle" dominantBaseline="middle" fill="var(--prototype-ink)" fontSize="18" fontWeight="700">{totalActions}</text><text x="50%" y="56%" textAnchor="middle" fill="var(--prototype-muted)" fontSize="10">次裁决</text></PieChart></ResponsiveContainer></div>
            <div className="prototype-action-list">{pieData.map((item) => <div key={item.key}><span><i style={{ background: ACTION_COLORS[item.key] }} />{item.name}</span><b>{item.value}<small>{Math.round(item.value / totalActions * 100)}%</small></b></div>)}</div>
          </> : <div className="prototype-empty">暂无策略命中记录</div>}</div>
        </section>
        <section className="prototype-card prototype-chart-card">
          <PrototypeCardTitle action={<span className="prototype-card-caption">4 个服务</span>}>连接器健康状态</PrototypeCardTitle>
          <div className="prototype-status-list">{data.connectors.map((item, itemIndex) => <div className="prototype-status-row" key={item.name}><span><i className={`prototype-connector-icon is-${itemIndex}`} /><span><b>{item.name}</b><small>{connectorNotes[itemIndex]}</small></span></span><strong className={item.status.includes("异常") ? "is-danger" : ""}><i />{item.status}</strong></div>)}</div>
          <div className="prototype-card-footnote"><i className="is-live" />状态来自连接器心跳与审计哈希链</div>
        </section>
        <section className="prototype-card prototype-chart-card">
          <PrototypeCardTitle action={<span className="prototype-card-caption">跨主体协同</span>}>协同轨迹</PrototypeCardTitle>
          <div className="prototype-timeline">{data.timeline.length ? data.timeline.map((item) => <div key={item.id}><i className="prototype-timeline-marker" /><time>{formatTime(item.ts)}</time><span><b>{item.resource}</b><small>{item.action_name} · {item.subject}</small></span></div>) : <div className="prototype-empty">暂无跨主体协同记录</div>}</div>
        </section>
      </div>
    </>}
  </PrototypePageFrame>;
}
