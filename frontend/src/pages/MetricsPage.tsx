import { RefreshCw } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Button, ErrorState, LoadingState, Metric, PageHeader, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

const metricNames: Record<string, string> = {
  SCENARIO_COUPLING_COUNT: "场景协同数",
  AGENT_EVENT_COUNT: "能力事件数",
  VERIFY_RATE: "证据核验率",
  CHAIN_EVIDENCE_COUNT: "凭证数量",
  MPC_DURATION_MS: "调用计算耗时",
  PRIVACY_ANALYSIS_MS: "用电分析耗时",
};

export function MetricsPage() {
  const { data, loading, error, reload } = useRemote<JsonRecord>(() => api("/metrics/summary"), []);

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "指标加载失败"} retry={reload} />;

  const chartData = Object.values((data.series || []).reduce((acc: Record<string, JsonRecord>, item: JsonRecord) => {
    const key = item.metric_code;
    if (!acc[key]) acc[key] = { name: metricNames[key] || key, total: 0, count: 0 };
    acc[key].total += Number(item.metric_value || 0);
    acc[key].count += 1;
    acc[key].value = Math.round((acc[key].total / acc[key].count) * 100) / 100;
    return acc;
  }, {}));

  return (
    <>
      <PageHeader title="验收指标" actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>} />
      <div className="metrics-grid five">
        <Metric label="平均计算耗时" value={`${data.compute_cost_ms} ms`} />
        <Metric label="调用完成率" value={`${data.data_flow_efficiency_pct ?? 0}%`} tone="green" />
        <Metric label="隐私安全记录率" value={`${data.privacy_protection_rate_pct ?? 0}%`} tone="green" />
        <Metric label="证据核验率" value={`${data.verify_rate}%`} tone="green" />
        <Metric label="原始数据出域率" value={`${data.raw_data_exposure_rate_pct ?? 0}%`} tone="green" />
      </div>
      <Surface title="实测指标趋势">
        <div className="chart-block"><ResponsiveContainer width="100%" height={300}><BarChart data={chartData}><CartesianGrid stroke="#d7e3ef" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 10, fill: "#63778e" }} /><YAxis tick={{ fontSize: 11, fill: "#63778e" }} /><Tooltip /><Bar dataKey="value" fill="#0b5cab" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer></div>
      </Surface>
      <div className="metrics-grid three">
        <Metric label="授权调用次数" value={data.authorized_call_count ?? 0} meta={`${data.authorized_agreement_count ?? 0} 份协议`} />
        <Metric label="已登记数据引用" value={data.active_data_refs} />
        <Metric label="可信凭证" value={data.evidence_count} />
      </div>
    </>
  );
}
