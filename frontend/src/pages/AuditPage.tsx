import { useMemo, useState } from "react";
import { ArrowLeft, FileSearch, RefreshCw, SearchCheck } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api, post } from "../api";
import { AuditTimeline, Button, DataTable, DateTimeText, ErrorState, FilterBar, IdText, LoadingState, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { AGENT_LABELS, EVIDENCE_TYPE_LABELS, MESSAGE_TYPE_LABELS, STAGE_LABELS, type JsonRecord } from "../types";

const checks = [
  { code: "RULE_TRACE", label: "规则版本可追溯性", question: "规则版本能否追溯？" },
  { code: "EVIDENCE_INTEGRITY", label: "证据一致性", question: "是否存在证据篡改？" },
  { code: "RAW_BOUNDARY", label: "原始数据边界", question: "原始数据是否被读取？" },
  { code: "SIGNATURE_COMPLETENESS", label: "多方签名完整性", question: "多方签名是否完整？" },
] as const;

const confidenceLabels: Record<string, string> = {
  HIGH: "高",
  MEDIUM: "中",
  LOW: "低",
};

function eventTitle(event: JsonRecord) {
  const title = String(event.title || "").split(" · ");
  if (event.kind === "EVIDENCE_RECORD") return `${STAGE_LABELS[title[0]] || title[0]} · ${EVIDENCE_TYPE_LABELS[title[1]] || title[1]}`;
  if (event.kind === "AGENT_EVENT") return `${AGENT_LABELS[title[0]] || title[0]} · ${MESSAGE_TYPE_LABELS[title[1]] || title[1]}`;
  return event.title || "审计事件";
}

export function AuditPage() {
  const [searchParams] = useSearchParams();
  const linkedTaskId = searchParams.get("task_id") || "";
  const [taskId, setTaskId] = useState(linkedTaskId);
  const [checkCode, setCheckCode] = useState<(typeof checks)[number]["code"]>("RULE_TRACE");
  const [answer, setAnswer] = useState<JsonRecord | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState("");
  const tasks = useRemote<JsonRecord[]>((signal) => api("/settlement/tasks", { signal, timeoutMs: 12000, cache: "no-store" }), []);
  const effectiveTaskId = taskId || tasks.data?.[0]?.task_id || "";
  const timeline = useRemote<JsonRecord | null>((signal) => effectiveTaskId ? api(`/audit/timeline/${effectiveTaskId}`, { signal, timeoutMs: 12000, cache: "no-store" }) : Promise.resolve(null), [effectiveTaskId]);

  const currentCheck = checks.find((item) => item.code === checkCode) || checks[0];
  const events = useMemo(() => (timeline.data?.events || []).map((event: JsonRecord) => ({
    id: String(event.reference || `${event.kind}-${event.time}`),
    title: eventTitle(event),
    time: <DateTimeText value={event.time} />,
    status: event.status,
    meta: <IdText value={event.reference} length={8} />,
  })), [timeline.data]);

  async function runCheck() {
    if (!effectiveTaskId) return;
    setChecking(true);
    setCheckError("");
    setAnswer(null);
    try {
      setAnswer(await post("/agent/query", { task_id: effectiveTaskId, question: currentCheck.question }));
    } catch (reason) {
      setCheckError(reason instanceof Error ? reason.message : "辅助解释生成失败");
    } finally {
      setChecking(false);
    }
  }

  if (tasks.loading) return <LoadingState label="正在加载审计任务" variant="page" />;
  if (tasks.error || !tasks.data) return <ErrorState message={tasks.error || "任务加载失败"} retry={tasks.reload} />;

  return (
    <>
      <PageHeader title="审计与复核" actions={<>{linkedTaskId && <Link className="button button-secondary" to={`/settlements/${linkedTaskId}`}><ArrowLeft size={16} />返回结算任务</Link>}<Button icon={RefreshCw} busy={tasks.refreshing || timeline.refreshing} onClick={async () => { await Promise.all([tasks.reload(), timeline.reload()]); }}>刷新</Button></>} />
      <FilterBar>
        <label><span>审计对象</span><select value={effectiveTaskId} disabled={Boolean(linkedTaskId)} onChange={(event) => { setTaskId(event.target.value); setAnswer(null); }}>{tasks.data.map((item) => <option key={item.task_id} value={item.task_id}>{item.capsule_id} · {item.task_name}</option>)}</select></label>
        {timeline.data?.task && <><div className="filter-status"><span>当前状态</span><StatusTag value={timeline.data.task.status} /></div><div className="filter-status"><span>风险等级</span><StatusTag value={timeline.data.task.risk_level} /></div></>}
      </FilterBar>

      <div className="audit-layout">
        <Surface title="事件时间线" meta={`${events.length} 条`}>
          {timeline.loading ? <LoadingState /> : timeline.error ? <ErrorState message={timeline.error} retry={timeline.reload} /> : <AuditTimeline events={events} />}
        </Surface>
        <Surface title="证据辅助解释">
          <div className="structured-audit-check">
            <label className="field"><span>解释主题</span><select value={checkCode} onChange={(event) => { setCheckCode(event.target.value as typeof checkCode); setAnswer(null); }}>{checks.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></label>
            <div className="audit-check-description"><FileSearch size={18} /><div><strong>{currentCheck.label}</strong><span>解释范围基于当前任务的规则、过程记录与审计凭证。</span></div></div>
            <Notice tone="warning">该功能通过生成式能力或证据模板提供辅助说明，不构成确定性核验、审批或合规结论。请以事件链、签名和凭证核验结果为准。</Notice>
            <Button icon={SearchCheck} variant="primary" busy={checking} disabled={!effectiveTaskId} onClick={runCheck}>生成辅助解释</Button>
            {checkError && <Notice tone="warning">{checkError}</Notice>}
            {answer && <div className="audit-check-result"><header><strong>辅助解释</strong><StatusTag value={answer.fallback ? "MEDIUM" : "INFO"} label={answer.fallback ? "模板降级" : "生成说明"} /></header><div className="audit-answer-meta"><div><span>置信度</span><strong>{confidenceLabels[String(answer.confidence || "")] || "未标注"}</strong></div><div><span>证据引用</span><strong>{answer.grounded ? "已关联" : "未关联"}</strong></div><div><span>生成方式</span><strong>{answer.fallback ? "结构化模板" : "生成式能力"}</strong></div></div><p>{answer.answer || "—"}</p>{answer.boundary && <div className="audit-answer-boundary"><strong>能力边界</strong><span>{String(answer.boundary)}</span></div>}<DataTable keyField="evidence_id" rows={answer.citations || []} empty="未引用具体凭证" label="辅助解释引用凭证" columns={[
              { key: "stage", label: "阶段", render: (row) => STAGE_LABELS[row.stage] || row.stage || "—" },
              { key: "evidence_id", label: "凭证编号", render: (row) => <IdText value={row.evidence_id} /> },
              { key: "tx_hash", label: "台账记录摘要", render: (row) => <IdText value={row.tx_hash} /> },
            ]} /></div>}
          </div>
        </Surface>
      </div>
    </>
  );
}
