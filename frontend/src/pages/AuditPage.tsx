import { useEffect, useState } from "react";
import { Bot, Blocks, FileSearch, MessageSquareText, RefreshCw, Send, ShieldCheck } from "lucide-react";
import { api, formatDate, post, shortHash } from "../api";
import { Button, CodeValue, ErrorState, LoadingState, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

const kindIcons: Record<string, React.ElementType> = { AGENT_EVENT: Bot, CHAIN_EVIDENCE: Blocks, ANOMALY: ShieldCheck };

export function AuditPage() {
  const [taskId, setTaskId] = useState("");
  const [question, setQuestion] = useState("本次结算是否完整可信？");
  const [answer, setAnswer] = useState<JsonRecord | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState("");
  const tasks = useRemote<JsonRecord[]>(() => api("/settlement/tasks"), []);
  const timeline = useRemote<JsonRecord | null>(() => taskId ? api(`/audit/timeline/${taskId}`) : Promise.resolve(null), [taskId]);

  useEffect(() => {
    if (!taskId && tasks.data?.length) setTaskId(tasks.data[0].task_id);
  }, [taskId, tasks.data]);

  async function ask() {
    if (!taskId || !question.trim()) {
      setAskError("请选择审计对象并输入问题。");
      return;
    }
    setAsking(true);
    setAskError("");
    try {
      setAnswer(await post("/agent/query", { task_id: taskId, question }));
    } catch (reason) {
      setAskError(reason instanceof Error ? reason.message : "审计问答失败");
    } finally {
      setAsking(false);
    }
  }

  if (tasks.loading) return <LoadingState />;
  if (tasks.error || !tasks.data) return <ErrorState message={tasks.error || "任务加载失败"} retry={tasks.reload} />;

  return (
    <>
      <PageHeader eyebrow="监管审计" title="全过程可信审计" description="以可信交易胶囊重建身份、许可、规则、计算、签名和链上证据关系，不依赖业务原始明细。" actions={<Button icon={RefreshCw} onClick={() => { void tasks.reload(); void timeline.reload(); }}>刷新</Button>} />
      <div className="filter-bar">
        <label><span>审计对象</span><select value={taskId} onChange={(event) => { setTaskId(event.target.value); setAnswer(null); }}>{tasks.data.map((item) => <option key={item.task_id} value={item.task_id}>{item.capsule_id} · {item.task_name}</option>)}</select></label>
        {timeline.data?.task && <><div><span>当前状态</span><StatusTag value={timeline.data.task.status} /></div><div><span>风险等级</span><StatusTag value={timeline.data.task.risk_level} /></div><div><span>原始数据</span><StatusTag value="SUCCESS" label="未进入审计域" /></div></>}
      </div>
      <div className="audit-layout">
        <Surface title="证据时间线" note={`${timeline.data?.events?.length || 0} 个可追溯事件`}>
          {timeline.loading ? <LoadingState /> : timeline.error ? <ErrorState message={timeline.error} retry={timeline.reload} /> : (
            <div className="audit-timeline">
              {(timeline.data?.events || []).map((event: JsonRecord) => {
                const Icon = kindIcons[event.kind] || FileSearch;
                return <div key={event.reference}><div className={`timeline-icon kind-${event.kind.toLowerCase()}`}><Icon size={17} /></div><div><span>{formatDate(event.time)}</span><strong>{event.title}</strong><small className="mono-text">{shortHash(event.reference, 12)}</small></div><StatusTag value={event.status} /></div>;
              })}
            </div>
          )}
        </Surface>
        <Surface title="证据约束问答" note="Citation RAG 只检索规则与结构化证据">
          <div className="agent-query">
            <div className="agent-identity"><Bot size={23} /><div><strong>审计风控 Agent</strong><span>did:hiddenchain:agent:audit-risk</span></div><StatusTag value="VALID" label="凭证有效" /></div>
            <textarea value={question} maxLength={500} onChange={(event) => setQuestion(event.target.value)} rows={3} />
            <div className="suggested-questions">
              {["规则版本能否追溯？", "是否存在证据篡改？", "原始数据是否被读取？", "多方签名是否完整？"].map((item) => <button key={item} onClick={() => setQuestion(item)}>{item}</button>)}
            </div>
            <Button icon={Send} variant="primary" busy={asking} disabled={!taskId || !question.trim()} onClick={ask}>基于证据回答</Button>
            {askError && <Notice tone="warning">{askError}</Notice>}
            {answer && <div className="agent-answer"><div><MessageSquareText size={18} /><strong>审计结论</strong></div><p>{answer.answer}</p><div className="citation-list">{answer.citations.map((item: JsonRecord) => <span key={item.evidence_id}><Blocks size={13} />{item.stage} · {shortHash(item.tx_hash, 8)}</span>)}</div><small>{answer.boundary}</small>{answer.fallback ? <small className="llm-proof llm-proof-fallback">本地模板回退：本次未调用 DeepSeek</small> : <small className="llm-proof">真实调用成功 · {answer.provider} · {answer.model} · {answer.duration_ms}ms · Token {answer.usage?.total_tokens ?? "-"} · 请求 {shortHash(answer.request_id, 12)} · 可信度 {answer.confidence}</small>}</div>}
          </div>
        </Surface>
      </div>
    </>
  );
}
