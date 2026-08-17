import { RefreshCw } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, formatNumber, formatPercent } from "../api";
import { Button, EmptyState, ErrorState, LoadingState, Metric, Notice, PageHeader, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

const metricNames: Record<string, string> = {
  SCENARIO_COUPLING_COUNT: "场景协同数",
  AGENT_EVENT_COUNT: "能力事件数",
  VERIFY_RATE: "证据核验率",
  CHAIN_EVIDENCE_COUNT: "凭证数量",
  MPC_DURATION_MS: "历史计算耗时",
  LOCAL_COMPUTE_DURATION_MS: "本地受控计算耗时",
  EVIDENCE_RECORD_COUNT: "证据记录数",
  PRIVACY_ANALYSIS_MS: "用电分析耗时",
};

const unitLabels: Record<string, string> = { ms: "毫秒", percent: "%", count: "次" };

function MetricChart({ title, rows, unit }: { title: string; rows: JsonRecord[]; unit: string }) {
  return <Surface title={title} meta={unitLabels[unit] || unit}>
    {rows.length ? <div className="chart-block"><ResponsiveContainer width="100%" height={230}><BarChart data={rows} margin={{ top: 8, right: 12, bottom: 12, left: 0 }}><CartesianGrid stroke="#e2e8ee" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 10, fill: "#63778e" }} interval={0} /><YAxis tick={{ fontSize: 11, fill: "#63778e" }} /><Tooltip formatter={(value) => [`${formatNumber(value as number, 2)} ${unitLabels[unit] || unit}`, "平均值"]} /><Bar dataKey="value" fill="#1769aa" /></BarChart></ResponsiveContainer></div> : <EmptyState title="暂无该单位的实测记录" />}
  </Surface>;
}

export function MetricsPage() {
  const { data, loading, refreshing, error, reload } = useRemote<JsonRecord>((signal) => api("/metrics/summary", { signal, timeoutMs: 12000, cache: "no-store" }), []);

  if (loading) return <LoadingState label="正在加载运行指标" variant="page" />;
  if (error || !data) return <ErrorState message={error || "运行指标加载失败"} retry={reload} />;

  const aggregates = Object.values((data.series || []).reduce((acc: Record<string, JsonRecord>, item: JsonRecord) => {
    const key = item.metric_code;
    if (!acc[key]) acc[key] = { code: key, name: metricNames[key] || key, unit: item.metric_unit, total: 0, count: 0 };
    acc[key].total += Number(item.metric_value || 0);
    acc[key].count += 1;
    acc[key].value = acc[key].total / acc[key].count;
    return acc;
  }, {})) as JsonRecord[];
  const hasComputeSample = aggregates.some((item) => ["LOCAL_COMPUTE_DURATION_MS", "MPC_DURATION_MS"].includes(item.code));
  const hasVerifySample = aggregates.some((item) => item.code === "VERIFY_RATE") || Number(data.evidence_count) > 0;

  return (
    <>
      <PageHeader title="运行监控" actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>} />
      <Notice tone="info"><strong>测量范围：</strong>{data.measurement_scope || "—"}。{data.baseline_note || ""}</Notice>
      <div className="metrics-grid five">
        <Metric label="平均计算耗时" value={hasComputeSample ? `${formatNumber(data.compute_cost_ms, 2)} ms` : "—"} />
        <Metric label="任务完成率" value={formatPercent(data.data_flow_efficiency_pct)} />
        <Metric label="隐私安全记录率" value={formatPercent(data.privacy_protection_rate_pct)} tone="green" />
        <Metric label="证据核验率" value={hasVerifySample ? formatPercent(data.verify_rate) : "—"} tone="green" />
        <Metric label="原始数据出域率" value={data.raw_data_exposure_rate_pct === null || data.raw_data_exposure_rate_pct === undefined ? "—" : formatPercent(data.raw_data_exposure_rate_pct)} />
      </div>

      <div className="metrics-chart-grid">
        <MetricChart title="数量类指标" rows={aggregates.filter((item) => item.unit === "count")} unit="count" />
        <MetricChart title="比例类指标" rows={aggregates.filter((item) => item.unit === "percent")} unit="percent" />
        <MetricChart title="耗时类指标" rows={aggregates.filter((item) => item.unit === "ms")} unit="ms" />
      </div>

      <div className="metrics-grid three">
        <Metric label="已消费授权调用" value={data.authorized_call_count ?? 0} meta={`${data.authorized_agreement_count ?? 0} 份协议`} />
        <Metric label="已登记数据引用" value={data.active_data_refs ?? 0} />
        <Metric label="审计凭证" value={data.evidence_count ?? 0} />
      </div>
    </>
  );
}
