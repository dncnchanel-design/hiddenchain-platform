import { useState } from "react";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { askPrototypeQuery, type PrototypeQueryPayload } from "../trusted-space-api";

const EXAMPLES = [
  "查一下6月份各地区的电网负荷，用于运行监测",
  "6月电力交易的成交均价和成交量，用于市场监测",
  "各行业每天的用电量统计，用于负荷预测",
  "6月电力交易成交明细，卖家都是谁",
  "7月风电和光伏的出力情况，做趋势分析",
  "寒潮期间电力负荷和电煤库存叠加分析，供应有没有缺口？",
];

function QueryOutput({ data }: { data: PrototypeQueryPayload }) {
  const denied = data.decision.action === "deny";
  return <section className="prototype-card prototype-query-output">
    <PrototypeCardTitle>调用链路 <span className="prototype-inline-state">身份 {data.identity?.did || "未登记"} 已验证 ✓</span></PrototypeCardTitle>
    <div className="prototype-pipeline">{data.plan.map((item, index) => <div className={`prototype-pipeline-step ${denied && index >= 2 ? "is-blocked" : "is-done"}`} key={`${item.stage}-${index}`}>{index + 1}. {item.stage}</div>)}</div>
    <div className="prototype-decision"><span className={`prototype-action-badge is-${data.decision.action}`}>{data.decision.label}</span><div><div>资源 <code>{data.resource_name || "未识别"}</code> · 函数 <code>{data.function_name || "未识别"}</code></div><p>裁决理由：{data.decision.reason}</p></div></div>
    {denied ? <div className="prototype-deny-message">⛔ {data.decision.reason}</div> : data.result ? <div className="prototype-query-result"><div><span>计算结果</span><strong>{data.result.value}</strong></div><div><span>样本数量</span><strong>{data.result.record_count}</strong></div><div><span>返回范围</span><strong>聚合结果</strong></div></div> : <div className="prototype-empty">暂无可交付结果</div>}
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

  return <PrototypePageFrame className="prototype-query-page">
    <section className="prototype-card prototype-query-entry">
      <PrototypeCardTitle>对话式问数</PrototypeCardTitle>
      <div className="prototype-chat-input"><input value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void ask(); }} placeholder="用自然语言描述你的数据需求，例如：查一下6月份各地区的电网负荷，用于运行监测" /><button type="button" disabled={busy || !question.trim()} onClick={() => void ask()}>{busy ? "处理中…" : "发送"}</button></div>
      <div className="prototype-query-examples" aria-label="快捷提问">{EXAMPLES.map((item) => <button type="button" key={item} onClick={() => setQuestion(item)}>{item}</button>)}</div>
    </section>
    {error && <div className="prototype-error" role="alert">{error}</div>}
    {result && <QueryOutput data={result} />}
  </PrototypePageFrame>;
}
