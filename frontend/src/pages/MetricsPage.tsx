import { RefreshCw } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, formatNumber } from "../api";
import { Button, EmptyState, ErrorState, LoadingState, Metric, Notice, PageHeader, Surface } from "../components/ui";
import { useRemote } from "../hooks";

type TechnicalMetric = {
  code: string;
  value: number | null;
  unit: string;
  window_start: string;
  window_end: string;
  cutoff_at: string | null;
  source: string;
  freshness: "FRESH" | "STALE" | "UNKNOWN" | string;
  null_reason: string | null;
};

type MetricsSummary = {
  measurement_scope: string;
  generated_at: string;
  security_boundary: string;
  metrics: TechnicalMetric[];
};

const metricNames: Record<string, string> = {
  AGENT_EVENT_COUNT: "能力事件数",
  LOCAL_COMPUTE_DURATION_MS: "本地受控计算耗时",
  EVIDENCE_RECORD_COUNT: "证据记录数",
  PRIVACY_ANALYSIS_MS: "用电分析耗时",
  EVIDENCE_VERIFY_RATE_PCT: "证据核验率",
  ACTIVE_NODE_COUNT: "活跃主体节点",
  VALID_IDENTITY_COUNT: "有效身份登记",
  ENABLED_AGENT_TOOL_COUNT: "启用工具",
  ACTIVE_AGENT_PERMISSION_COUNT: "有效工具权限",
  METRIC_SAMPLE_COUNT: "窗口内指标样本",
};

const unitLabels: Record<string, string> = { ms: "毫秒", percent: "%", count: "项" };
const nullReasonLabels: Record<string, string> = { NO_MEASUREMENT: "尚无实测记录", OUTSIDE_WINDOW: "最近记录已超出统计窗口" };
const sourceLabels: Record<string, string> = {
  metric_records_24h_average: "近 24 小时指标记录",
  local_subject_nodes: "主体节点登记",
  did_identities: "身份登记",
  agent_tools: "工具登记",
  agent_permissions: "工具权限登记",
  metric_records: "指标记录",
};
const environmentLabels: Record<string, string> = { test: "测试环境", demo: "演示环境", development: "开发环境", production: "生产环境" };

function metricValue(item: TechnicalMetric) {
  return item.value === null ? "—" : `${formatNumber(item.value, 2)}${item.unit === "percent" ? "%" : item.unit === "ms" ? " ms" : ""}`;
}

function MetricChart({ title, rows, unit }: { title: string; rows: TechnicalMetric[]; unit: string }) {
  const measuredRows = rows.filter((item) => item.value !== null).map((item) => ({ ...item, name: metricNames[item.code] || item.code }));
  const denseAxis = measuredRows.length > 4;
  return <Surface title={title} meta={unitLabels[unit] || unit}>
    {measuredRows.length ? <>
      <div className="chart-block"><ResponsiveContainer width="100%" height={denseAxis ? 270 : 230}><BarChart data={measuredRows} margin={{ top: 8, right: 12, bottom: denseAxis ? 46 : 12, left: 0 }}><CartesianGrid stroke="var(--chart-grid)" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 10, fill: "var(--chart-axis)" }} interval="preserveStartEnd" angle={denseAxis ? -28 : 0} textAnchor={denseAxis ? "end" : "middle"} height={denseAxis ? 68 : 30} /><YAxis tick={{ fontSize: 11, fill: "var(--chart-axis)" }} /><Tooltip formatter={(value) => [`${formatNumber(value as number, 2)} ${unitLabels[unit] || unit}`, "实测聚合"]} /><Bar dataKey="value" fill="var(--chart-series-brand)" /></BarChart></ResponsiveContainer></div>
      <p className="muted">文本摘要：{measuredRows.map((item) => `${item.name} ${metricValue(item)}`).join("；")}。</p>
    </> : <EmptyState title="当前统计窗口暂无该单位的实测记录" />}
    {rows.some((item) => item.value === null) && <p className="muted">未显示：{rows.filter((item) => item.value === null).map((item) => `${metricNames[item.code] || item.code}（${nullReasonLabels[item.null_reason || ""] || "原因未登记"}）`).join("；")}。</p>}
  </Surface>;
}

export function MetricsPage() {
  const { data, loading, refreshing, error, reload } = useRemote<MetricsSummary>((signal) => api("/metrics/summary", { signal, timeoutMs: 12000, cache: "no-store" }), []);

  if (loading) return <LoadingState label="正在加载运行指标" variant="page" />;
  if (error || !data) return <ErrorState message={error || "运行指标加载失败"} retry={reload} />;

  const featured = data.metrics.slice(0, 5);
  return <>
    <PageHeader title="运行监控" actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>} />
    <Notice tone="info"><strong>测量范围：</strong>{environmentLabels[data.measurement_scope] || data.measurement_scope || "未登记"}。{data.security_boundary}</Notice>
    <div className="metrics-grid five">
      {featured.map((item) => <Metric key={item.code} label={metricNames[item.code] || item.code} value={metricValue(item)} meta={item.value === null ? nullReasonLabels[item.null_reason || ""] || "当前无可靠测量" : `${item.freshness === "FRESH" ? "窗口内实测" : "状态待核查"} · ${sourceLabels[item.source] || "已登记技术来源"}`} />)}
    </div>
    {!data.metrics.length && <EmptyState title="暂无技术指标" description="指标采集尚未形成可用记录，请稍后刷新。" />}
    {data.metrics.length > 0 && <div className="metrics-chart-grid">
      <MetricChart title="数量类技术指标" rows={data.metrics.filter((item) => item.unit === "count")} unit="count" />
      <MetricChart title="比例类技术指标" rows={data.metrics.filter((item) => item.unit === "percent")} unit="percent" />
      <MetricChart title="耗时类技术指标" rows={data.metrics.filter((item) => item.unit === "ms")} unit="ms" />
    </div>}
  </>;
}
