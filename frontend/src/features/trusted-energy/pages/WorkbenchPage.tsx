import { Activity, ArrowRight, Database, FileCheck2, Link2, Map as MapIcon, Search, ShieldCheck, UsersRound } from "lucide-react";
import { Link } from "react-router-dom";
import { useRemote } from "../../../hooks";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { RemoteState } from "../components/ui-primitives";
import { VisibleModuleBoundary } from "../components/VisibleModuleBoundary";
import { loadPrototypeDashboard, type PrototypeDashboardPayload } from "../trusted-space-api";

const ACTION_NAMES: Record<string, string> = { allow: "直接提供", deny: "禁止提供", aggregate: "汇总提供", delay: "延迟提供", compute_only: "仅计算不出域" };
const KPI_ICONS = [Database, ShieldCheck, UsersRound, Link2, Search];
type WorkbenchChartsModule = typeof import("../components/WorkbenchCharts");

let workbenchChartsPromise: Promise<WorkbenchChartsModule> | undefined;

function loadWorkbenchCharts() {
  workbenchChartsPromise ||= import("../components/WorkbenchCharts").catch((error) => {
    workbenchChartsPromise = undefined;
    throw error;
  });
  return workbenchChartsPromise;
}

function formatTime(value: string) {
  return value.includes("T") ? value.slice(11, 16) : value.slice(-5);
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

function actionData(data: PrototypeDashboardPayload) {
  return Object.entries(data.action_counts).filter(([, value]) => value > 0).map(([key, value]) => ({ name: ACTION_NAMES[key] || key, value, key }));
}

function preloadPrimaryAction(path: string) {
  if (path === "/trusted-space/mpc/new") void import("../../../pages/SettlementCreatePage").catch(() => undefined);
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
      <Link className="prototype-role-focus-action" to={view.primary_action.path} onMouseEnter={() => preloadPrimaryAction(view.primary_action.path)} onFocus={() => preloadPrimaryAction(view.primary_action.path)}>{view.primary_action.label}<ArrowRight size={14} /></Link>
    </div>
  </section>;
}

export function WorkbenchPage() {
  const remote = useRemote(loadPrototypeDashboard, []);
  const data = remote.data;
  const isRegionalMap = data?.view.visualization === "regional_map";
  const index = isRegionalMap ? Math.max(0, (data?.map.days.length || 1) - 1) : 0;

  const pieData = data ? actionData(data) : [];
  const totalActions = pieData.reduce((sum, item) => sum + item.value, 0);

  return <PrototypePageFrame>
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    {data && <>
      <RoleFocusPanel view={data.view} notice={data.data_notice} dataMode={data.data_mode} dataStatus={data.metric.status} />
      <div className="prototype-kpi-grid">{data.view.kpis.map((item, itemIndex) => { const Icon = KPI_ICONS[itemIndex] ?? Database; return <div className={`prototype-kpi-card${itemIndex > 3 ? " is-success" : ""}`} key={item.label}><div className="prototype-kpi-icon"><Icon size={17} strokeWidth={1.8} /></div><div className="prototype-kpi-label"><span>{item.label}</span><small>{item.meta}</small></div><strong>{item.value}</strong></div>; })}</div>

      <div className="prototype-dashboard-layout">
        <section className="prototype-card prototype-dashboard-map-card">
          <div className="prototype-card-heading"><div><PrototypeCardTitle>{isRegionalMap ? <MapIcon className="prototype-card-icon" size={18} strokeWidth={1.8} /> : <Activity className="prototype-card-icon" size={18} strokeWidth={1.8} />}{data.view.visual_title}</PrototypeCardTitle><div className="prototype-dashboard-subline">{data.view.visual_subtitle}</div>{isRegionalMap && <div className="prototype-dashboard-legend"><span><i className="is-line" />区域受控汇总</span><span><i className="is-line" />城市天数标注</span></div>}</div><span className="prototype-day-badge">{isRegionalMap ? data.map.days[index] || "—" : data.metric.latest_date || "—"}</span></div>
          {isRegionalMap
            ? <VisibleModuleBoundary loader={loadWorkbenchCharts} className="prototype-map" ariaLabel={`${data.view.visual_title}地图正在加载`} renderLoaded={({ DashboardMap }) => <DashboardMap data={data.map} index={index} metricLabel={data.view.visual_value_label} metricUnit={data.view.visual_value_unit} ariaLabel={`${data.view.visual_title}地图`} />} />
            : <VisibleModuleBoundary loader={loadWorkbenchCharts} className="prototype-echart-trend" ariaLabel={`${data.view.visual_title}趋势图正在加载`} renderLoaded={({ SubjectTrendChart }) => <SubjectTrendChart points={data.metric.trend} label={data.metric.label} unit={data.metric.unit} ariaLabel={`${data.view.visual_title}趋势图`} />} />}
        </section>
        <aside className="prototype-dashboard-side">
          <SubjectMetricCard metric={data.metric} />
          <section className="prototype-card prototype-feed-card"><PrototypeCardTitle><FileCheck2 className="prototype-card-icon" size={18} strokeWidth={1.8} />实时审计流</PrototypeCardTitle><div className="prototype-feed-list">{data.audit.length ? data.audit.map((item) => <div className="prototype-feed-item" key={item.id}><i className={`is-${item.action}`} /><span><b>{item.action_name}</b> · {item.subject} · {item.resource}</span><time>{formatTime(item.ts)}</time></div>) : <div className="prototype-empty">暂无审计记录</div>}</div></section>
        </aside>
      </div>

      <div className="prototype-dashboard-bottom">
        <section className="prototype-card prototype-chart-card"><PrototypeCardTitle><Activity className="prototype-card-icon" size={18} strokeWidth={1.8} />策略命中分布</PrototypeCardTitle>{pieData.length ? <VisibleModuleBoundary loader={loadWorkbenchCharts} className="prototype-echart-pie" ariaLabel="策略命中分布图正在加载" renderLoaded={({ ActionPieChart }) => <ActionPieChart values={pieData} />} /> : <div className="prototype-empty">暂无策略命中记录</div>}<div className="prototype-card-caption prototype-chart-caption">共 {totalActions} 次裁决</div></section>
        <section className="prototype-card prototype-chart-card"><PrototypeCardTitle><UsersRound className="prototype-card-icon" size={18} strokeWidth={1.8} />跨主体协同轨迹</PrototypeCardTitle><div className="prototype-timeline">{data.timeline.length ? data.timeline.map((item) => <div key={item.id}><i className="prototype-timeline-marker" aria-hidden="true" /><time>{formatTime(item.ts)}</time><span><b>{item.resource}</b><small>{item.subject}</small></span></div>) : <div className="prototype-empty">暂无跨主体协同记录</div>}</div></section>
      </div>
    </>}
  </PrototypePageFrame>;
}
