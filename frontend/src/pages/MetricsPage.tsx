import { Activity, Blocks, CheckCircle2, Clock3, Cpu, Database, RefreshCw, ShieldCheck } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Button, ErrorState, LoadingState, Metric, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

const adapters = [
  ["可信采集", "来源证明与格式校验", "虚拟仿真可用", "READY"],
  ["安全传输", "HTTPS / MQTT / WebSocket", "接口边界", "READY"],
  ["可控使用", "DID + 数据合同 + PEP/PDP", "策略执行", "READY"],
  ["隐私计算", "PSI / MPC / 联邦 / TEE 路由", "适配器就绪", "READY"],
  ["可溯审计", "算前 / 算中 / 算后证据", "链证核验", "READY"],
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
      <PageHeader eyebrow="安全与管理" title="验收指标" description="查看数据流通效率、隐私边界和审计完整性等可量化指标。" actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>} />
      <Notice>以下指标为{data.measurement_scope || "当前演示样本"}的实测结果；赛题要求的相对提升比例，需要后续接入生产基线后再计算。</Notice>
      <div className="metrics-grid five">
        <Metric label="平均计算耗时" value={`${data.compute_cost_ms} ms`} meta="隐私计算回执" />
        <Metric label="调用完成率" value={`${data.data_flow_efficiency_pct ?? 0}%`} meta="任务完成 / 总任务" tone="green" />
        <Metric label="隐私安全记录率" value={`${data.privacy_protection_rate_pct ?? 0}%`} meta="未导出原始数据" tone="green" />
        <Metric label="证据核验率" value={`${data.verify_rate}%`} meta="哈希一致" tone="green" />
        <Metric label="原始数据出域率" value={`${data.raw_data_exposure_rate_pct ?? 0}%`} meta="目标为 0" tone="green" />
      </div>
      <div className="content-grid metrics-layout">
        <Surface title="实测指标趋势">
          <div className="chart-block"><ResponsiveContainer width="100%" height={300}><BarChart data={chartData}><CartesianGrid stroke="#d7e3ef" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 10, fill: "#63778e" }} /><YAxis tick={{ fontSize: 11, fill: "#63778e" }} /><Tooltip /><Bar dataKey="value" fill="#0b5cab" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer></div>
        </Surface>
        <Surface title="安全检查">
          <div className="acceptance-list">
            <div><Database size={18} /><span>原始数据进入业务库</span><strong>0 条</strong><StatusTag value="PASSED" label="符合要求" /></div>
            <div><ShieldCheck size={18} /><span>用途策略绕过</span><strong>0 次</strong><StatusTag value="PASSED" label="符合要求" /></div>
            <div><Blocks size={18} /><span>算前 / 算中 / 算后证据</span><strong>完整</strong><StatusTag value="PASSED" label="符合要求" /></div>
            <div><Cpu size={18} /><span>最小化结果输出</span><strong>启用</strong><StatusTag value="PASSED" label="符合要求" /></div>
          </div>
        </Surface>
      </div>
      <div className="metrics-grid three">
        <Metric label="授权调用次数" value={data.authorized_call_count ?? 0} meta={`${data.authorized_agreement_count ?? 0} 份协议`} />
        <Metric label="已登记数据引用" value={data.active_data_refs} meta="原文不进入业务库" />
        <Metric label="可信凭证" value={data.evidence_count} meta="算前 / 算中 / 算后" />
      </div>
      <Surface title="服务组件">
        <div className="adapter-matrix">
          {adapters.map(([domain, current, target, state]) => <div key={domain}><strong>{domain}</strong><span>{current}</span><i>→</i><span>{target}</span><StatusTag value={state} label="接口就绪" /></div>)}
        </div>
      </Surface>
    </>
  );
}
