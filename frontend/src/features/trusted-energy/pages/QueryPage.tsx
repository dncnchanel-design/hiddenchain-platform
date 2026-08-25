import { useState } from "react";
import { PrototypeCardTitle } from "../components/PrototypePageFrame";
import { PageFrame } from "../components/PageFrame";
import { askPrototypeQuery, type PrototypeQueryPayload } from "../trusted-space-api";

const EXAMPLES = [
  "查一下6月份各地区的电网负荷，用于运行监测",
  "6月电力交易的成交均价和成交量，用于市场监测",
  "各行业每天的用电量统计，用于负荷预测",
  "6月电力交易成交明细，卖家都是谁",
  "7月风电和光伏的出力情况，做趋势分析",
  "寒潮期间电力负荷和风光出力叠加分析，供应有没有缺口？",
];

function QueryOutput({ data }: { data: PrototypeQueryPayload }) {
  const denied = data.decision.action === "deny";
  const trend = data.result?.trend || [];
  const maxTrend = Math.max(...trend.map((item) => item.value), 1);
  return <section className="prototype-card prototype-query-output">
    <PrototypeCardTitle>问数结果 <span className="prototype-inline-state">身份 {data.identity?.did || "未登记"} 已验证 · 原始数据未返回</span></PrototypeCardTitle>
    <div className="prototype-pipeline">{data.plan.map((item, index) => <div className={`prototype-pipeline-step ${denied && index >= 2 ? "is-blocked" : "is-done"}`} key={`${item.stage}-${index}`}>{index + 1}. {item.stage}</div>)}</div>
    <div className="prototype-decision"><span className={`prototype-action-badge is-${data.decision.action}`}>{data.decision.label}</span><div><div>资源 <code>{data.resource_name || "未识别"}</code> · 函数 <code>{data.function_name || "未识别"}</code></div><p>裁决理由：{data.decision.reason}</p></div></div>
    {denied ? <div className="prototype-deny-message">⛔ {data.decision.reason}。先完成数据提供方授权，再提交计算。</div> : data.result ? <><div className="prototype-query-result"><div><span>聚合结果</span><strong>{data.result.value}</strong></div><div><span>样本数量</span><strong>{data.result.record_count}</strong></div><div><span>返回范围</span><strong>受控汇总</strong></div></div>{trend.length > 1 ? <div className="prototype-query-trend"><div className="prototype-query-trend-header"><strong>结果趋势</strong><span>{trend.length} 个受控数据点 · 单位随数据资源定义</span></div><div className="prototype-query-bars" role="img" aria-label="问数结果趋势图">{trend.map((item) => <div className="prototype-query-bar" key={`${item.label}-${item.value}`}><span style={{ height: `${Math.max(8, item.value / maxTrend * 100)}%` }} title={`${item.label}：${item.value}`} /><small>{item.label}</small></div>)}</div></div> : <div className="prototype-query-proof"><span>结果依据</span><strong>后端仅返回一个聚合值，未登记可绘制的时间序列。</strong></div>}</> : <div className="prototype-empty">暂无可交付结果</div>}
    <div className="prototype-audit-id">审计存证 #{data.audit_id || "未写入"} · {data.identity?.name || "当前主体"}</div>
  </section>;
}

export function QueryPage() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<PrototypeQueryPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function ask() {
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setError("");
    try {
      setResult(await askPrototypeQuery(text));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "问数请求失败");
    } finally {
      setBusy(false);
    }
  }

  return <PageFrame title="智能数据查询" description="先解析能源域、资源和固定函数，再按授权输出受控结果。" className="prototype-query-page">
    <section className="prototype-card prototype-query-entry">
      <PrototypeCardTitle>智能数据查询</PrototypeCardTitle>
      <p className="prototype-query-intro">输入业务问题后，系统会先识别能源域、数据资源和固定函数，再按当前授权决定“汇总返回、仅计算不出域或阻断”。</p>
      <div className="prototype-chat-input"><input value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void ask(); }} placeholder="用自然语言描述你的数据需求，例如：查一下6月份各地区的电网负荷，用于运行监测" /><button type="button" disabled={busy || !question.trim()} onClick={() => void ask()}>{busy ? "处理中…" : "发送"}</button></div>
      <div className="prototype-query-examples" aria-label="快捷提问">{EXAMPLES.map((item) => <button type="button" key={item} onClick={() => setQuestion(item)}>{item}</button>)}</div>
    </section>
    {error && <div className="prototype-error" role="alert">{error}</div>}
    {result && <QueryOutput data={result} />}
  </PageFrame>;
}
