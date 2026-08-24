import { useMemo, useState } from "react";
import { Check, CheckCircle2, Circle, Download, FileCheck2, GitCommitHorizontal, RefreshCw, ScanSearch, ShieldCheck } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError, formatDate, shortHash } from "../../../api";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, RemoteState, StatusBadge, SurfaceHeader, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { downloadAudit, loadAudit, loadAuditTask, type AuditListPayload, type AuditRecord, type AuditTaskPayload } from "../trusted-space-api";
import { ACTION_LABELS, RECORD_TYPE_LABELS, STAGE_LABELS, TARGET_TYPE_LABELS, labelForCode } from "../../../types";
import { routeForView, trustedEntityId } from "../types";

function taskIdFor(record: AuditRecord) {
  const detailTask = record.details && typeof record.details.task_id === "string" ? record.details.task_id : undefined;
  return detailTask || (record.target_type?.toLowerCase().includes("task") ? record.target_id : undefined);
}

function recordTitle(record: AuditRecord) {
  if (record.record_type === "AUDIT_REPORT") return labelForCode(record.details?.title, "审计报告");
  return ACTION_LABELS[record.action_code || ""] || TARGET_TYPE_LABELS[record.target_type || ""] || labelForCode(record.action_code || record.target_type, "审计记录");
}

function transitionNodes(detail: AuditTaskPayload) {
  return detail.transitions.map((item, index) => {
    const rawState = String(item.to_state || item.state || "");
    const state = labelForCode(rawState, "未知状态");
    const trigger = item.trigger_code ? ACTION_LABELS[String(item.trigger_code)] || labelForCode(item.trigger_code, "登记动作") : "真实状态转移";
    return { id: String(item.transition_id || `${rawState || "state"}-${index}`), label: state, detail: String(item.reason || trigger), time: formatDate(typeof item.occurred_at === "string" ? item.occurred_at : null), done: true };
  });
}

export function AuditCenterPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const taskId = trustedEntityId(location.pathname, "audit");
  const [page, setPage] = useState(1);
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState<"json" | "csv" | "">("");
  const listRemote = useRemote<AuditListPayload | null>((signal) => taskId ? Promise.resolve(null) : loadAudit({ page, pageSize: 50 }, signal), [taskId, page]);
  const detailRemote = useRemote<AuditTaskPayload | null>((signal) => taskId ? loadAuditTask(taskId, signal) : Promise.resolve(null), [taskId]);
  const detail = detailRemote.data;
  const nodes = useMemo(() => detail ? transitionNodes(detail) : [], [detail]);
  const list = listRemote.data;

  async function exportRecords(format: "json" | "csv") {
    setExportError("");
    setExporting(format);
    try {
      const payload = await downloadAudit(format);
      const url = URL.createObjectURL(payload.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = payload.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setExportError(error instanceof ApiError ? error.message : "审计导出失败，请重试。");
    } finally {
      setExporting("");
    }
  }

  if (!taskId) {
    return <PageFrame title="审计存证" action={<div className="trusted-submit-actions"><Button variant="secondary" busy={exporting === "json"} onClick={() => exportRecords("json")}><Download size={14} />结构化数据导出</Button><Button variant="secondary" busy={exporting === "csv"} onClick={() => exportRecords("csv")}><Download size={14} />表格数据导出</Button><Button variant="secondary" onClick={listRemote.reload} busy={listRemote.refreshing}><RefreshCw size={14} />刷新</Button></div>}>
      {exportError && <p className="trusted-inline-status" role="alert">{exportError}</p>}
      {listRemote.loading && !list && <RemoteState loading />}
      {listRemote.error && !list && <RemoteState error={listRemote.error} onRetry={() => void listRemote.reload()} />}
      {list && !list.items.length && <RemoteState empty emptyLabel="当前主体暂无可见审计记录" />}
      {list && list.items.length > 0 && <Card className="trusted-audit-list"><CardHeader><SurfaceHeader title="审计记录" description="服务端按组织与角色范围返回日志和审计报告" action={<Badge tone="info">第 {list.page} 页 · 共 {list.total} 条</Badge>} /></CardHeader><CardContent><div className="trusted-audit-items">{list.items.map((record) => { const targetTask = taskIdFor(record); return <button className="trusted-audit-item" type="button" key={`${record.record_type}-${record.record_id}`} disabled={!targetTask} onClick={() => targetTask && navigate(routeForView("audit", targetTask))}><div><strong><code>{record.record_id}</code></strong><StatusBadge value={record.result || "已记录"} /></div><span>{recordTitle(record)}</span><small>{formatDate(record.occurred_at)} · {TARGET_TYPE_LABELS[record.target_type || ""] || labelForCode(record.target_type, "未登记对象")}</small>{targetTask && <small><code>任务 {targetTask}</code></small>}</button>; })}</div><div className="trusted-submit-actions"><Button variant="link" size="sm" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>上一页</Button><Button variant="link" size="sm" disabled={page * list.page_size >= list.total} onClick={() => setPage((value) => value + 1)}>查看更多任务</Button></div></CardContent></Card>}
    </PageFrame>;
  }

  return <PageFrame title="审计存证" back={routeForView("audit")} action={<Button variant="secondary" onClick={detailRemote.reload} busy={detailRemote.refreshing}><RefreshCw size={14} />刷新</Button>}>
    {detailRemote.loading && !detail && <RemoteState loading />}
    {detailRemote.error && !detail && <RemoteState error={detailRemote.error} onRetry={() => void detailRemote.reload()} />}
    {detail && <>
      <Card className="trusted-task-banner"><CardContent><div><small>任务编号</small><strong><code>{detail.task.task_id}</code></strong></div><div><small>任务名称</small><strong>{detail.task.task_name || "—"}</strong></div><div><small>可信任务状态</small><StatusBadge value={detail.task.ttc_state || detail.task.status || "未登记"} /></div><div><small>状态版本</small><strong>V{detail.task.state_version ?? "—"}</strong></div><div><small>能力来源</small><Badge tone="info">{labelForCode(detail.source_of_truth, "审计日志与审计报告")}</Badge></div></CardContent></Card>
      <div className="trusted-audit-layout"><div className="trusted-audit-detail"><Card><CardHeader><SurfaceHeader title="审计链" description="节点、时间戳和理由只来自可信任务状态转移记录" action={<ScanSearch size={16} />} /></CardHeader><CardContent>{nodes.length ? <div className="trusted-audit-graph">{nodes.map((node, index) => <div className="trusted-audit-node-wrap" key={node.id}><div className="trusted-audit-node"><span><Check size={14} /></span><strong>{node.label}</strong><small>{node.detail}</small><time>{node.time}</time></div>{index < nodes.length - 1 && <i className="trusted-audit-link is-done" />}</div>)}</div> : <RemoteState empty emptyLabel="暂无状态转移节点" />}<div className="trusted-audit-source"><span><GitCommitHorizontal size={15} />审计日志</span><code>{detail.audit_chain.length} 条</code><Badge tone="info">后端记录</Badge></div></CardContent></Card>
      <Card><CardHeader><SurfaceHeader title="日志与报告" description="服务端报告状态、风险评级和哈希，不由前端生成通过结论" action={<FileCheck2 size={16} />} /></CardHeader><CardContent className="trusted-table-wrap"><Table><TableHeader><TableRow><TableHead>类型</TableHead><TableHead>记录</TableHead><TableHead>结果</TableHead><TableHead>摘要/哈希</TableHead><TableHead>时间</TableHead></TableRow></TableHeader><TableBody>{detail.audit_chain.map((record) => <TableRow key={`log-${record.record_id}`}><TableCell>{RECORD_TYPE_LABELS.AUDIT_LOG}</TableCell><TableCell><code>{ACTION_LABELS[record.action_code || ""] || labelForCode(record.action_code, "审计动作")}</code></TableCell><TableCell><StatusBadge value={record.result || "已记录"} /></TableCell><TableCell>{record.target_id || "—"}</TableCell><TableCell>{formatDate(record.occurred_at)}</TableCell></TableRow>)}{detail.reports.map((report) => <TableRow key={`report-${String(report.record_id)}`}><TableCell>{RECORD_TYPE_LABELS.AUDIT_REPORT}</TableCell><TableCell>{String(report.title || report.report_title || report.record_id)}</TableCell><TableCell><StatusBadge value={String(report.status || "未登记")} /></TableCell><TableCell><code>{shortHash(String(report.report_hash || ""))}</code></TableCell><TableCell>—</TableCell></TableRow>)}{!detail.audit_chain.length && !detail.reports.length && <TableRow><TableCell colSpan={5}>暂无审计日志或报告</TableCell></TableRow>}</TableBody></Table></CardContent></Card></div><div className="trusted-audit-detail"><Card><CardHeader><SurfaceHeader title="审计结论" description="只展示后端报告与证据状态" action={<CheckCircle2 size={23} />} /></CardHeader><CardContent><div className="trusted-audit-conclusion"><span className="trusted-pass-mark"><CheckCircle2 size={23} /></span><div><span>后端报告状态</span><strong>{detail.reports.length ? labelForCode(detail.reports[0].status, "未登记") : "暂无报告"}</strong><small>{detail.reports.length ? `风险等级：${labelForCode(detail.reports[0].risk_level, "未评级")}` : "不会由前端生成通过结论"}</small></div><Badge tone={detail.reports.length ? "info" : "warning"}>真实记录</Badge></div><div className="trusted-audit-facts"><div><span><ShieldCheck size={14} />审计记录</span><strong>{detail.audit_chain.length}</strong></div><div><span><Circle size={14} />状态节点</span><strong>{detail.transitions.length}</strong></div><div><span><Circle size={14} />证据记录</span><strong>{detail.evidence.length}</strong></div></div><div className="trusted-submit-actions"><Button variant="secondary" disabled={!detail.allowed_actions?.includes("export_json")} onClick={() => exportRecords("json")}><Download size={14} />查看完整报告</Button><Button variant="secondary" disabled={!detail.allowed_actions?.includes("export_csv")} onClick={() => exportRecords("csv")}><Download size={14} />表格数据导出</Button></div>{exportError && <p className="trusted-inline-status" role="alert">{exportError}</p>}</CardContent></Card><Card><CardHeader><SurfaceHeader title="证据索引" description="无链回执时保持待锚定边界" action={<GitCommitHorizontal size={16} />} /></CardHeader><CardContent><div className="trusted-evidence-list">{detail.evidence.map((evidence) => <div key={evidence.evidence_id}><span>{STAGE_LABELS[evidence.stage || ""] || labelForCode(evidence.stage, "证据")}</span><code>{shortHash(evidence.evidence_hash)}</code>{evidence.tx_hash ? <code>{shortHash(evidence.tx_hash)}</code> : <Badge tone="warning">待锚定</Badge>}<StatusBadge value={evidence.status || "未登记"} /></div>)}{!detail.evidence.length && <span className="trusted-muted">暂无证据索引</span>}</div></CardContent></Card></div></div>
    </>}
  </PageFrame>;
}
