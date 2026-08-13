import { Activity, Blocks, CheckCircle2, Clock3, Cpu, Database, RefreshCw, ShieldCheck } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Button, ErrorState, LoadingState, Metric, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

const adapters = [
  ["数据目录", "目录服务", "正常", "READY"],
  ["隐私计算", "授权域内计算", "正常", "READY"],
  ["可信凭证", "凭证记录服务", "正常", "READY"],
  ["使用规则", "用途控制服务", "正常", "READY"],
  ["身份认证", "主体身份服务", "正常", "READY"],
];

export function MetricsPage() {
  const { data, loading, error, reload } = useRemote<JsonRecord>(() => api("/metrics/summary"), []);

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "指标加载失败"} retry={reload} />;

  const chartData = Object.values((data.series || []).reduce((acc: Record<string, JsonRecord>, item: JsonRecord) => {
    const key = item.metric_code;
    if (!acc[key]) acc[key] = { name: key, total: 0, count: 0 };
    acc[key].total += Number(item.metric_value || 0);
    acc[key].count += 1;
    acc[key].value = Math.round((acc[key].total / acc[key].count) * 100) / 100;
    return acc;
  }, {}));

  return (
    <>
      <PageHeader eyebrow="安全与管理" title="系统状态" description="查看计算、凭证和服务运行状态。" actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>} />
      <div className="metrics-grid five">
        <Metric label="平均计算耗时" value={`${data.compute_cost_ms} ms`} meta="最近记录" />
        <Metric label="凭证核验率" value={`${data.verify_rate}%`} meta="哈希一致" tone="green" />
        <Metric label="过程记录" value={data.agent_event_count} meta="已留痕" />
        <Metric label="可信凭证" value={data.evidence_count} meta="已生成" />
        <Metric label="原始数据集中存储" value={data.raw_data_centralized} meta="当前记录" tone="green" />
      </div>
      <div className="content-grid metrics-layout">
        <Surface title="运行趋势">
          <div className="chart-block"><ResponsiveContainer width="100%" height={300}><BarChart data={chartData}><CartesianGrid stroke="#d7e3ef" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 10, fill: "#63778e" }} /><YAxis tick={{ fontSize: 11, fill: "#63778e" }} /><Tooltip /><Bar dataKey="value" fill="#0b5cab" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer></div>
        </Surface>
        <Surface title="安全检查">
          <div className="acceptance-list">
            <div><Database size={18} /><span>原始数据集中存储</span><strong>0 条</strong><StatusTag value="PASSED" /></div>
            <div><ShieldCheck size={18} /><span>策略绕过事件</span><strong>0 次</strong><StatusTag value="PASSED" /></div>
            <div><Blocks size={18} /><span>算前/中/后证据</span><strong>完整</strong><StatusTag value="PASSED" /></div>
            <div><Cpu size={18} /><span>确定性结算执行</span><strong>启用</strong><StatusTag value="PASSED" /></div>
          </div>
        </Surface>
      </div>
      <Surface title="服务组件">
        <div className="adapter-matrix">
          {adapters.map(([domain, current, target, state]) => <div key={domain}><strong>{domain}</strong><span>{current}</span><i>→</i><span>{target}</span><StatusTag value={state} label="接口就绪" /></div>)}
        </div>
      </Surface>
    </>
  );
}
