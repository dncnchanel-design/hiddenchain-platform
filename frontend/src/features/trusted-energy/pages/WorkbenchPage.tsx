import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Cell, Line, LineChart, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useRemote } from "../../../hooks";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { RemoteState } from "../components/ui-primitives";
import { loadPrototypeDashboard, type PrototypeDashboardPayload } from "../trusted-space-api";
import { useTrustedSpaceContext } from "../trusted-space-context";

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
  { name: "济南", x: 286, y: 232 },
  { name: "青岛", x: 560, y: 284 },
  { name: "烟台", x: 611, y: 126 },
  { name: "潍坊", x: 421, y: 226 },
  { name: "临沂", x: 362, y: 404 },
];
const SHANDONG_OUTLINE = "M282 101 C312 82 343 78 370 91 C403 76 441 82 462 103 C493 92 530 98 550 121 C581 112 618 124 637 148 C671 157 688 181 676 205 C694 225 690 254 669 270 C684 294 675 321 650 335 C657 365 640 390 614 399 C616 429 595 451 567 452 C552 480 521 493 495 481 C472 501 442 493 427 470 C398 468 377 450 372 424 C343 418 321 396 320 370 C291 361 278 338 286 313 C260 299 251 272 264 248 C244 226 249 199 269 183 C251 156 258 126 282 115 C273 110 274 105 282 101 Z";
const SHANDONG_BOUNDARIES = [
  "M294 164 C337 174 365 160 398 171 C433 182 461 169 497 177 C534 185 563 171 604 186",
  "M275 215 C313 224 340 210 373 220 C411 230 442 216 475 227 C514 239 550 222 588 237 C620 249 651 242 677 251",
  "M284 270 C323 278 347 265 379 278 C417 293 445 276 481 288 C519 300 551 284 583 297 C612 309 642 301 669 316",
  "M321 124 C310 157 319 181 309 211 C297 244 305 270 297 303 C289 329 303 350 321 370",
  "M369 93 C360 126 371 153 360 183 C348 214 361 242 350 275 C340 306 350 331 346 360 C344 389 356 412 372 424",
  "M453 101 C442 134 452 160 442 190 C430 224 442 250 431 281 C421 311 432 341 424 372 C420 408 428 438 447 472",
  "M540 118 C524 145 535 173 524 205 C512 237 524 264 512 296 C503 328 513 354 507 385 C503 414 515 436 522 470",
  "M621 145 C603 169 616 194 605 222 C595 250 606 276 595 306 C587 333 598 360 588 391 C583 417 592 438 602 450",
  "M267 183 C300 191 326 186 350 195 C377 205 402 196 427 205 C454 215 480 207 505 216 C533 226 556 216 579 225 C603 235 625 228 649 239",
  "M318 367 C344 355 365 365 389 376 C413 388 432 380 456 390 C481 401 508 389 531 400 C553 411 578 402 610 399",
];
const SHANDONG_ISLANDS = ["M625 90 l9 -8 12 3 5 9 -10 7 -12 -3 Z", "M653 101 l6 -6 9 3 2 7 -7 5 Z"];
const MAP_ROUTES = [
  { d: "M286 232 C365 164 491 106 611 126", label: "济南—烟台" },
  { d: "M286 232 C337 216 381 214 421 226", label: "济南—潍坊" },
  { d: "M421 226 C475 228 525 253 560 284", label: "潍坊—青岛" },
  { d: "M421 226 C394 275 370 337 362 404", label: "潍坊—临沂" },
];

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "未提供" : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function formatNumber(value: number, fractionDigits = 0) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: fractionDigits, minimumFractionDigits: fractionDigits }).format(value);
}

function formatBeijingDate(value: Date) {
  const parts = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(value);
  const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function actionData(data: PrototypeDashboardPayload) {
  return Object.entries(data.action_counts).filter(([, value]) => value > 0).map(([key, value]) => ({ name: ACTION_NAMES[key] || key, value, key }));
}

function DashboardMap({ data, index, domain }: { data: PrototypeDashboardPayload["map"]; index: number; domain: string }) {
  const cities = CITY_POSITIONS.map((city) => ({
    ...city,
    value: data.series[city.name]?.[index] || 0,
  }));
  const max = Math.max(...cities.map((city) => city.value), 1);
  return <div className="prototype-map" aria-label="山东能源供需态势">
    <svg className="prototype-map-svg" viewBox="210 45 520 460" role="img" aria-labelledby="prototype-map-title prototype-map-description">
      <title id="prototype-map-title">山东能源供需态势地图</title>
      <desc id="prototype-map-description">山东省区划示意、五个能源节点及跨主体协同路径。</desc>
      <defs>
        <marker id="prototype-map-arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto" markerUnits="userSpaceOnUse">
          <path d="M0 0 L10 5 L0 10 Z" fill="var(--prototype-accent)" />
        </marker>
      </defs>
      <path className="prototype-map-province" d={SHANDONG_OUTLINE} />
      <g className="prototype-map-boundaries" aria-hidden="true">{SHANDONG_BOUNDARIES.map((path) => <path d={path} key={path} />)}</g>
      <g className="prototype-map-islands" aria-hidden="true">{SHANDONG_ISLANDS.map((path) => <path d={path} key={path} />)}</g>
      <g className="prototype-map-routes" aria-label="跨主体协同路径">{MAP_ROUTES.map((route) => <path d={route.d} key={route.label} aria-label={route.label} markerEnd="url(#prototype-map-arrow)" />)}</g>
      <g className="prototype-map-nodes">{cities.map((city) => {
        const scale = 0.9 + city.value / max * 0.35;
        const coalDays = data.coal_days[index] || 0;
        const nodeLabel = domain === "coal" ? `${city.name}，库存覆盖 ${formatNumber(coalDays, 1)} 天` : `${city.name}，受控负荷 ${formatNumber(city.value)} MW`;
        return <g className="prototype-map-node" key={city.name} transform={`translate(${city.x} ${city.y}) scale(${scale})`} tabIndex={0} aria-label={nodeLabel}>
          <title>{nodeLabel}</title>
          <circle className="prototype-map-node-halo" r="29" />
          <path className="prototype-map-node-pin" d="M0 -23 C15 -23 24 -12 24 0 C24 13 0 36 0 36 C0 36 -24 13 -24 0 C-24 -12 -15 -23 0 -23 Z" fill="var(--prototype-map-node)" />
          <circle className="prototype-map-node-core" cy="-4" r="10" />
          <text className="prototype-map-node-label" y="60" textAnchor="middle">{city.name}</text>
        </g>;
      })}</g>
    </svg>
    {!data.days.length && <div className="prototype-map-empty">暂无负荷与库存数据</div>}
  </div>;
}

export function WorkbenchPage() {
  const remote = useRemote(loadPrototypeDashboard, []);
  const trustedSpace = useTrustedSpaceContext();
  const data = remote.data;
  const domain = trustedSpace.context?.current_subject.energy_domain || "cross";
  const domainName = ({ electricity: "电力", coal: "煤炭", heat: "热能", gas: "天然气", oil: "石油", cross: "跨能源" } as Record<string, string>)[domain] || "跨能源";
  const [index, setIndex] = useState(0);
  const [now, setNow] = useState(() => new Date());
  const dayCount = data?.map.days.length || 0;

  useEffect(() => {
    if (dayCount < 2) return undefined;
    const timer = window.setInterval(() => setIndex((current) => (current + 1) % dayCount), 2200);
    return () => window.clearInterval(timer);
  }, [dayCount]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

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
  const peakLoad = data ? Math.max(...CITY_POSITIONS.flatMap((city) => data.map.series[city.name] || []), 0) : 0;
  const gaugePercent = Math.min(100, Math.max(0, currentCoalDays / 24 * 100));
  const gaugeColor = currentCoalDays >= 15 ? "var(--prototype-action-allow)" : currentCoalDays >= 7 ? "var(--prototype-action-aggregate)" : "var(--prototype-action-deny)";
  const beijingDate = formatBeijingDate(now);
  const totalActions = pieData.reduce((sum, item) => sum + item.value, 0);
  const connectorNotes = ["最近心跳 00:32", "最近心跳 00:47", "策略版本 2026.08", "追加写入正常"];

  return <PrototypePageFrame>
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    {data && <>
      <section className="prototype-dashboard-overview">
        <div>
          <div className="prototype-overview-label"><span>运行总览</span><span className={`prototype-data-badge is-${data.data_mode}`}>{data.data_notice}</span></div>
          <h2>山东能源供需态势</h2>
          <p>用受控汇总观察{domainName}业务指标与跨主体协同，原始明细始终留在企业侧。</p>
        </div>
        <div className="prototype-overview-facts">
          <span><small>监测窗口</small><b>近 7 日</b></span>
          <span><small>当前日期</small><b>{beijingDate}</b></span>
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
              <PrototypeCardTitle action={<span className="prototype-day-badge" aria-live="polite" aria-label={`北京时间 ${beijingDate}`}>{beijingDate}</span>}>山东能源供需态势</PrototypeCardTitle>
              <div className="prototype-dashboard-subline"><span>{domain === "coal" ? "煤炭库存 · 供耗平衡 · 跨主体协同" : `${domainName}业务指标 · 受控查询 · 跨主体协同`}</span></div>
              <div className="prototype-dashboard-legend">{domain === "coal" ? <><span><i className="is-green" />库存充足（&gt;15天）</span><span><i className="is-orange" />警戒（7-15天）</span><span><i className="is-red" />缺口风险（&lt;7天）</span></> : <span><i className="is-line" />受控负荷趋势</span>}<span><i className="is-line" />跨主体协同</span></div>
            </div>
          </div>
          <DashboardMap data={data.map} index={index} domain={domain} />
          <div className="prototype-trend-panel">
            {domain === "electricity" ? <><div className="prototype-trend-header"><div><strong>区域负荷趋势</strong><span>MW · 近 7 日</span></div><span>峰值 {formatNumber(peakLoad)} MW</span></div>
            {chartData.length > 1 ? <ResponsiveContainer width="100%" height={148}><LineChart data={chartData} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid stroke="var(--prototype-chart-grid)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="day" tick={{ fill: "var(--prototype-muted)", fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fill: "var(--prototype-muted)", fontSize: 10 }} tickLine={false} axisLine={false} width={38} tickFormatter={(value) => `${Math.round(Number(value) / 1000)}k`} />
              <Tooltip />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />
              {CITY_POSITIONS.map((city, cityIndex) => <Line key={city.name} type="monotone" dataKey={city.name} name={city.name} stroke={CITY_COLORS[cityIndex]} strokeWidth={2} dot={false} activeDot={{ r: 3 }} />)}
            </LineChart></ResponsiveContainer> : <div className="prototype-empty">暂无负荷趋势数据</div>}</> : <div className="prototype-domain-reference">当前为{domainName}主体，页面不套用电力或煤炭演示趋势；请从数据目录发起受控查询。</div>}
          </div>
        </section>

        <aside className="prototype-dashboard-side">
          {domain === "coal" ? <section className="prototype-card prototype-gauge-card">
            <PrototypeCardTitle action={<span className={`prototype-mode-tag is-${data.data_mode}`}>{data.data_mode === "demo" ? "演示口径" : "实时"}</span>}>煤炭库存可支撑天数</PrototypeCardTitle>
            <div className="prototype-gauge" style={{ background: `conic-gradient(${gaugeColor} ${gaugePercent}%, var(--prototype-gauge-track) 0)` }}><div><strong>{currentCoalDays ? formatNumber(currentCoalDays, 1) : "暂无"}</strong><span>天</span></div></div>
            <div className="prototype-gauge-text" style={{ color: gaugeColor }}>{currentCoalDays >= 15 ? "库存充足" : currentCoalDays >= 7 ? "库存警戒" : "缺口风险"} · 当前覆盖 {formatNumber(currentCoalDays, 1)} 天</div>
            <div className="prototype-gauge-facts"><span><small>当前库存</small><b>{formatNumber(currentInventory, 1)}<em>万吨</em></b></span><span><small>日均消耗</small><b>{formatNumber(currentConsumption, 1)}<em>万吨</em></b></span><span><small>安全线</small><b>15<em>天</em></b></span></div>
            <div className="prototype-gauge-footnote">库存统计来自煤炭企业侧受控汇总，不展示原始明细。</div>
          </section> : <section className="prototype-card prototype-gauge-card prototype-domain-summary">
            <PrototypeCardTitle action={<span className={`prototype-mode-tag is-${data.data_mode}`}>{data.data_mode === "demo" ? "演示口径" : "实时"}</span>}>{domainName}业务概览</PrototypeCardTitle>
            <div className="prototype-domain-summary-main"><strong>{domain === "electricity" ? formatNumber(peakLoad) : data.kpis.resources}</strong><span>{domain === "electricity" ? "MW · 区域受控负荷峰值" : "项 · 当前可见目录资源"}</span></div>
            <div className="prototype-gauge-facts"><span><small>当前域</small><b>{domainName}</b></span><span><small>可见规则</small><b>{data.kpis.rules}<em> 条</em></b></span><span><small>连接状态</small><b>受控</b></span></div>
            <div className="prototype-gauge-footnote">当前主体不属于煤炭域，不展示煤炭库存指标；非电力演示数据需由对应企业连接器提供。</div>
          </section>}
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
