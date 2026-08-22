import { useMemo, useState } from "react";
import { ArrowLeft, CheckCircle2, Eye, FilePlus2, RefreshCw, XCircle } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api, post } from "../api";
import { useAuth } from "../auth";
import { Button, ConfirmDialog, DataTable, DateTimeText, DetailDrawer, ErrorState, Field, IdText, LoadingState, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { REPORT_TEMPLATE_LABELS, type JsonRecord } from "../types";

export function ReportsPage() {
  const { session } = useAuth();
  const [searchParams] = useSearchParams();
  const linkedTaskId = searchParams.get("task_id") || "";
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [taskId, setTaskId] = useState(linkedTaskId);
  const [confirmGenerate, setConfirmGenerate] = useState(false);
  const [decisionTarget, setDecisionTarget] = useState<JsonRecord | null>(null);
  const [decision, setDecision] = useState<"APPROVE" | "REJECT">("APPROVE");
  const [opinion, setOpinion] = useState("");
  const [confirmDecision, setConfirmDecision] = useState(false);
  const [busy, setBusy] = useState(false);
  const [decisionBusy, setDecisionBusy] = useState("");
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<"success" | "warning">("success");
  const canGenerate = ["REGULATOR", "ADMIN"].includes(session!.user.role_code);
  const loader = async (signal?: AbortSignal) => {
    const request = { signal, timeoutMs: 12000, cache: "no-store" as RequestCache };
    const [reports, tasks] = await Promise.all([api<JsonRecord[]>("/audit/reports", request), api<JsonRecord[]>("/settlement/tasks", request)]);
    return { reports, tasks };
  };
  const { data, loading, refreshing, error, reload } = useRemote(loader, []);
  const audited = useMemo(() => data?.tasks.filter((item) => item.status === "AUDITED") || [], [data]);
  const linkedTask = data?.tasks.find((item) => item.task_id === linkedTaskId);
  const selectedTask = audited.find((item) => item.task_id === taskId) || linkedTask;
  const visibleReports = linkedTaskId ? data?.reports.filter((item) => item.task_id === linkedTaskId) || [] : data?.reports || [];

  async function generate() {
    if (!taskId) return;
    setBusy(true);
    setMessage("");
    try {
      await post("/audit/reports", { task_id: taskId, template_code: "REGULATORY_AUDIT_V1" });
      setMessageTone("success");
      setMessage("审计报告已生成。");
      await reload();
    } catch (reason) {
      setMessageTone("warning");
      setMessage(reason instanceof Error ? reason.message : "生成失败");
    } finally {
      setBusy(false);
    }
  }

  function openDecision(target: JsonRecord, nextDecision: "APPROVE" | "REJECT") {
    setDecisionTarget(target);
    setDecision(nextDecision);
    setOpinion("");
    setConfirmDecision(false);
    setMessage("");
  }

  async function submitDecision() {
    if (!decisionTarget || opinion.trim().length < 2) return;
    setDecisionBusy(decisionTarget.report_id);
    setMessage("");
    try {
      await post(`/audit/reports/${decisionTarget.report_id}/decision`, {
        decision,
        opinion: opinion.trim(),
      });
      setMessageTone("success");
      setMessage(decision === "APPROVE" ? "审计报告已批准。" : "审计报告已驳回，任务将进入返工流程。");
      setDecisionTarget(null);
      setOpinion("");
      await reload();
    } catch (reason) {
      setMessageTone("warning");
      setMessage(reason instanceof Error ? reason.message : "报告审核失败，请重试");
    } finally {
      setDecisionBusy("");
      setConfirmDecision(false);
    }
  }

  if (loading) return <LoadingState label="正在加载审计报告" variant="page" />;
  if (error || !data) return <ErrorState message={error || "报告加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader title="审计报告" actions={<>{linkedTaskId && <Link className="button button-secondary" to={`/settlements/${linkedTaskId}`}><ArrowLeft size={16} />返回结算任务</Link>}<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button></>} />
      {linkedTaskId && linkedTask && visibleReports[0]?.status === "GENERATED" && <Notice tone="warning">受控计算已完成，当前处于审计关口。监管方需要在本页批准或驳回报告；批准后，参与主体才能完成最终结果确认。</Notice>}
      {linkedTaskId && linkedTask && visibleReports[0]?.status === "APPROVED" && <Notice tone="success">审计关口已通过。请返回任务详情，按责任方继续完成结果确认或查看闭环证据。</Notice>}
      {linkedTaskId && linkedTask && !visibleReports.length && <Notice tone="info">当前任务尚未生成审计报告。请先完成受控计算，系统会基于本次执行尝试自动形成报告。</Notice>}
      {canGenerate && !linkedTaskId && <Surface title="补充生成审计报告">
        <p className="muted report-generator-note">主审计报告会在受控计算完成后自动生成；此处仅用于对已归档任务补充生成一份报告。</p>
        <div className="report-generator"><label className="field"><span>已审计任务</span><select value={taskId} onChange={(event) => setTaskId(event.target.value)}><option value="">请选择</option>{audited.map((item) => <option key={item.task_id} value={item.task_id}>{item.capsule_id} · {item.task_name}</option>)}</select></label><Button icon={FilePlus2} variant="primary" busy={busy} disabled={!taskId} onClick={() => setConfirmGenerate(true)}>生成报告</Button></div>
      </Surface>}
      {message && <Notice tone={messageTone}>{message}</Notice>}
      <Surface title="报告列表" meta={`${visibleReports.length} 份`}>
        <DataTable
          keyField="report_id" rows={visibleReports} label="审计报告列表"
          columns={[
            { key: "report_title", label: "报告名称", minWidth: 220, render: (row) => <button className="table-link" type="button" onClick={() => setSelected(row)}>{row.report_title || "—"}</button> },
            { key: "task_id", label: "关联任务", minWidth: 150, render: (row) => <Link className="text-link" to={`/settlements/${row.task_id}`}><IdText value={row.task_id} /></Link> },
            { key: "template_code", label: "报告模板", minWidth: 140, render: (row) => REPORT_TEMPLATE_LABELS[row.template_code] || row.template_code || "—" },
            { key: "evidence_refs_json", label: "证据引用", align: "right", render: (row) => `${row.evidence_refs_json?.length ?? 0} 项` },
            { key: "report_hash", label: "报告摘要", minWidth: 150, render: (row) => <IdText value={row.report_hash} /> },
            { key: "risk_level", label: "风险结论", render: (row) => <StatusTag value={row.risk_level} /> },
            { key: "status", label: "审核状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "created_at", label: "生成时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
            { key: "action", label: "操作", sortable: false, hideable: false, sticky: "right", minWidth: 240, render: (row) => <div className="inline-actions">{row.status === "GENERATED" && canGenerate && <><Button icon={CheckCircle2} onClick={() => openDecision(row, "APPROVE")}>批准</Button><Button icon={XCircle} variant="danger" onClick={() => openDecision(row, "REJECT")}>驳回</Button></>}<Button icon={Eye} onClick={() => setSelected(row)}>查看</Button></div> },
          ]}
        />
      </Surface>

      {selected && <DetailDrawer title={selected.report_title || "审计报告"} onClose={() => setSelected(null)} footer={<Button onClick={() => setSelected(null)}>关闭</Button>}>
        <div className="detail-grid"><div><span>报告编号</span><IdText value={selected.report_id} /></div><div><span>关联任务</span><Link className="text-link" to={`/settlements/${selected.task_id}`}><IdText value={selected.task_id} /></Link></div><div><span>报告摘要</span><IdText value={selected.report_hash} /></div><div><span>风险结论</span><StatusTag value={selected.risk_level} /></div><div><span>审核状态</span><StatusTag value={selected.status} /></div><div><span>生成时间</span><DateTimeText value={selected.created_at} /></div><div><span>证据引用</span><strong>{selected.evidence_refs_json?.length ?? 0} 项</strong></div></div>
        <div className="detail-section"><h3>报告正文</h3><pre className="report-content">{selected.report_content || "—"}</pre></div>
        <details className="secondary-details"><summary>查看证据引用</summary><ul className="plain-list">{(selected.evidence_refs_json || []).map((item: string) => <li key={item}><IdText value={item} /></li>)}</ul></details>
      </DetailDrawer>}

      <ConfirmDialog
        open={confirmGenerate} title="生成审计报告" objectName={selectedTask?.task_name || selectedTask?.task_id || "—"} currentState={selectedTask?.status}
        consequence="系统将基于该任务当前保存的证据引用生成一份新的监管审计报告并写入报告记录。"
        confirmLabel="确认生成" busy={busy} onCancel={() => setConfirmGenerate(false)} onConfirm={async () => { await generate(); setConfirmGenerate(false); }}
      />
      {decisionTarget && !confirmDecision && <Modal title={decision === "APPROVE" ? "批准审计报告" : "驳回审计报告"} onClose={() => setDecisionTarget(null)} footer={<><Button onClick={() => setDecisionTarget(null)}>取消</Button><Button variant={decision === "REJECT" ? "danger" : "primary"} disabled={opinion.trim().length < 2} onClick={() => setConfirmDecision(true)}>下一步</Button></>}>
        <div className="detail-grid"><div><span>报告名称</span><strong>{decisionTarget.report_title || "—"}</strong></div><div><span>当前状态</span><StatusTag value={decisionTarget.status} /></div><div><span>风险结论</span><StatusTag value={decisionTarget.risk_level} /></div></div>
        <Field label="审核意见" hint={decision === "APPROVE" ? "说明核验范围与批准依据" : "说明驳回原因与需要返工的事项"}><textarea maxLength={500} value={opinion} onChange={(event) => setOpinion(event.target.value)} /></Field>
      </Modal>}
      <ConfirmDialog
        open={confirmDecision} title={decision === "APPROVE" ? "确认批准审计报告" : "确认驳回审计报告"}
        objectName={decisionTarget?.report_title || decisionTarget?.report_id || "—"} currentState={decisionTarget?.status}
        consequence={decision === "APPROVE" ? "批准结论和审核意见将以当前监管主体的去中心化身份标识签名并写入审计证据，随后允许完成多方结果确认。" : "驳回结论和审核意见将写入审计证据，关联任务进入返工流程，不能继续完成本次结算。"}
        confirmLabel={decision === "APPROVE" ? "确认批准" : "确认驳回"} danger={decision === "REJECT"}
        busy={Boolean(decisionTarget && decisionBusy === decisionTarget.report_id)} onCancel={() => setConfirmDecision(false)} onConfirm={submitDecision}
      />
    </>
  );
}
