import { useEffect, useState } from "react";
import { Blocks, FileSearch, MessageSquareText, RefreshCw, Send, ShieldCheck, Workflow } from "lucide-react";
import { api, formatDate, post, shortHash } from "../api";
import { Button, EmptyState, ErrorState, LoadingState, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { AGENT_LABELS, EVIDENCE_TYPE_LABELS, MESSAGE_TYPE_LABELS, STAGE_LABELS } from "../types";
import type { JsonRecord } from "../types";
import { TrustedExecutionReviewPanel } from "../components/TrustedExecutionReviewPanel";

const kindIcons: Record<string, React.ElementType> = { AGENT_EVENT: Workflow, CHAIN_EVIDENCE: Blocks, ANOMALY: ShieldCheck };

export function AuditPage() {
  const [taskId, setTaskId] = useState("");
  const [question, setQuestion] = useState("本次数据调用与隐私计算是否完整可信？");
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
      setAskError("请选择审计对象并输入检索问题。");
      return;
    }
    setAsking(true);
    setAskError("");
    try {
      setAnswer(await post("/agent/query", { task_id: taskId, question }));
    } catch (reason) {
      setAskError(reason instanceof Error ? reason.message : "证据检索失败");
    } finally {
      setAsking(false);
    }
  }

  if (tasks.loading) return <LoadingState />;
  if (tasks.error || !tasks.data) return <ErrorState message={tasks.error || "任务加载失败"} retry={tasks.reload} />;

  return (
    <>
      <PageHeader title="审计与复核" actions={<Button icon={RefreshCw} onClick={async () => { await Promise.all([tasks.reload(), timeline.reload()]); }}>刷新</Button>} />
      <div className="filter-bar">
        <label><span>审计对象</span><select value={taskId} onChange={(event) => { setTaskId(event.target.value); setAnswer(null); }}>{tasks.data.map((item) => <option key={item.task_id} value={item.task_id}>{item.capsule_id} · {item.task_name}</option>)}</select></label>
        {timeline.data?.task && <><div><span>当前状态</span><StatusTag value={timeline.data.task.status} /></div><div><span>风险等级</span><StatusTag value={timeline.data.task.risk_level} /></div></>}
      </div>
      <div className="audit-layout">
        <Surface title="事件时间线" meta={`${timeline.data?.events?.length || 0} 条`}>
          {timeline.loading ? <LoadingState /> : timeline.error ? <ErrorState message={timeline.error} retry={timeline.reload} /> : (
            (timeline.data?.events || []).length ? <div className="audit-timeline">
              {(timeline.data?.events || []).map((event: JsonRecord) => {
                const Icon = kindIcons[event.kind] || FileSearch;
                const title = String(event.title || "").split(" · ");
                const readableTitle = event.kind === "CHAIN_EVIDENCE"
                  ? `${STAGE_LABELS[title[0]] || title[0]} · ${EVIDENCE_TYPE_LABELS[title[1]] || title[1]}`
                  : event.kind === "AGENT_EVENT"
                    ? `${AGENT_LABELS[title[0]] || title[0]} · ${MESSAGE_TYPE_LABELS[title[1]] || title[1]}`
                    : event.title;
                return <div key={event.reference}><div className={`timeline-icon kind-${event.kind.toLowerCase()}`}><Icon size={17} /></div><div><span>{formatDate(event.time)}</span><strong>{readableTitle}</strong><small className="mono-text">{shortHash(event.reference, 12)}</small></div><StatusTag value={event.status} /></div>;
              })}
            </div> : <EmptyState title="当前任务暂无可核验事件" />
          )}
        </Surface>
        <Surface title="证据检索">
          <div className="agent-query">
            <textarea aria-label="检索问题" value={question} maxLength={500} onChange={(event) => setQuestion(event.target.value)} rows={3} />
            <div className="suggested-questions">
              {["规则版本能否追溯？", "是否存在证据篡改？", "原始数据是否被读取？", "多方签名是否完整？"].map((item) => <button key={item} onClick={() => setQuestion(item)}>{item}</button>)}
            </div>
            <Button icon={Send} variant="primary" busy={asking} disabled={!taskId || !question.trim()} onClick={ask}>检索证据</Button>
            {askError && <Notice tone="warning">{askError}</Notice>}
            {answer && <div className="agent-answer"><div><MessageSquareText size={18} /><strong>核验摘要</strong></div><p>{answer.answer}</p><div className="citation-list">{answer.citations.map((item: JsonRecord) => <span key={item.evidence_id}><Blocks size={13} />{STAGE_LABELS[item.stage] || item.stage} · {shortHash(item.tx_hash, 8)}</span>)}</div></div>}
          </div>
        </Surface>
      </div>
      <TrustedExecutionReviewPanel />
    </>
  );
}
