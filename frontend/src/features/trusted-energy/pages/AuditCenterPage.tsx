import { ArrowLeft, ChevronLeft, ChevronRight, FileCheck2, RefreshCw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useRemote } from "../../../hooks";
import { labelForCode } from "../../../types";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { RemoteState } from "../components/ui-primitives";
import {
  loadAudit,
  loadAuditTask,
  type AuditRecord,
} from "../trusted-space-api";
import { routeForView, trustedEntityId } from "../types";
import { auditDetailForRoute, auditListForRoute, type AuditRouteRemoteData } from "../audit-route-state";

const PAGE_SIZE = 20;

function formatDate(value?: string | null) {
  if (!value) return "未登记时间";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function shortValue(value?: string | null) {
  if (!value) return "未登记";
  return value.length > 28 ? `${value.slice(0, 14)}…${value.slice(-10)}` : value;
}

function taskIdForRecord(item: AuditRecord) {
  const detailTaskId = item.details?.task_id;
  if (typeof detailTaskId === "string" && detailTaskId) return detailTaskId;
  return item.target_type === "SETTLEMENT_TASK" ? item.target_id || undefined : undefined;
}

function AuditItem({ item, onOpenTask }: { item: AuditRecord; onOpenTask: (taskId: string) => void }) {
  const taskId = taskIdForRecord(item);
  const content = <>
    <span className="prototype-audit-action">{labelForCode(item.action_code, item.record_type === "AUDIT_REPORT" ? "审计报告" : "审计事件")}</span>
    <span> · {labelForCode(item.result, "未登记结果")}</span>
    <small>{formatDate(item.occurred_at)} · 记录编号 <code title={item.record_id}>{shortValue(item.record_id)}</code></small>
    {taskId && <small>任务编号 <code title={taskId}>{shortValue(taskId)}</code></small>}
  </>;
  return taskId
    ? <button type="button" className="prototype-audit-item is-interactive" onClick={() => onOpenTask(taskId)} aria-label="打开任务审计详情">{content}</button>
    : <div className="prototype-audit-item">{content}</div>;
}

export function AuditCenterPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const taskId = trustedEntityId(location.pathname, "audit");
  const [page, setPage] = useState(1);
  const remote = useRemote<AuditRouteRemoteData>(
    (signal) => taskId
      ? loadAuditTask(taskId, signal).then((payload) => ({ kind: "detail" as const, taskId, payload }))
      : loadAudit({ page, pageSize: PAGE_SIZE }, signal).then((payload) => ({ kind: "list" as const, page, payload })),
    [taskId, page],
  );
  const list = !taskId ? auditListForRoute(remote.data, page) : null;
  const detail = taskId ? auditDetailForRoute(remote.data, taskId) : null;
  const routeData = list || detail;
  const routeError = routeData ? "" : remote.error || remote.refreshError;
  const routeLoading = !routeData && !routeError && (remote.loading || remote.refreshing);
  const totalPages = list ? Math.max(1, Math.ceil(list.total / list.page_size)) : 1;

  function openTask(nextTaskId: string) {
    navigate(routeForView("audit", nextTaskId));
  }

  return <PrototypePageFrame className="prototype-audit-page">
    <RemoteState loading={routeLoading} error={routeError} onRetry={() => void remote.reload()} />
    {routeData && remote.refreshError && <RemoteState error={remote.refreshError} onRetry={() => void remote.reload()} />}
    {!remote.loading && !remote.error && list && <section className="prototype-card prototype-audit-card">
      <div className="prototype-card-heading">
        <PrototypeCardTitle>审计与存证中心</PrototypeCardTitle>
        <div className="prototype-audit-actions"><button type="button" disabled={remote.refreshing} onClick={() => void remote.reload()}><RefreshCw size={13} />刷新</button></div>
      </div>
      <div className="prototype-audit-stats" aria-label="审计记录摘要">
        <div className="prototype-audit-stat"><b>{list.total}</b><span>授权范围内记录</span></div>
        <div className="prototype-audit-stat"><b>{list.reports.length}</b><span>本页审计报告</span></div>
        <div className="prototype-audit-stat"><b>{list.page}</b><span>当前页</span></div>
        <div className="prototype-audit-stat"><b>{totalPages}</b><span>总页数</span></div>
      </div>
      <div className="prototype-chain-status is-ok" role="status"><ShieldCheck size={17} aria-hidden="true" /> 当前仅展示本账号已获授任务范围内的真实审计记录；正式审计页保持只读。</div>
      <div className="prototype-audit-columns">
        <div><h4>审计流水</h4>{list.items.some((item) => item.record_type !== "AUDIT_REPORT") ? list.items.filter((item) => item.record_type !== "AUDIT_REPORT").map((item) => <AuditItem key={`${item.record_type}-${item.record_id}`} item={item} onOpenTask={openTask} />) : <div className="prototype-empty">当前页暂无审计流水</div>}</div>
        <div><h4>审计报告</h4>{list.reports.length ? list.reports.map((item) => <AuditItem key={item.record_id} item={item} onOpenTask={openTask} />) : <div className="prototype-empty">当前页暂无审计报告</div>}</div>
      </div>
      <div className="prototype-audit-actions" aria-label="审计记录分页">
        <button type="button" disabled={page <= 1 || remote.refreshing} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={13} />上一页</button>
        <button type="button" disabled={page >= totalPages || remote.refreshing} onClick={() => setPage((value) => value + 1)}>下一页<ChevronRight size={13} /></button>
      </div>
    </section>}

    {!remote.loading && !remote.error && detail && <section className="prototype-card prototype-audit-card">
      <div className="prototype-card-heading">
        <PrototypeCardTitle>{detail.task.task_name || "任务审计详情"}</PrototypeCardTitle>
        <div className="prototype-audit-actions">
          <button type="button" onClick={() => navigate(routeForView("audit"))}><ArrowLeft size={13} />返回审计列表</button>
          <button type="button" disabled={remote.refreshing} onClick={() => void remote.reload()}><RefreshCw size={13} />刷新</button>
        </div>
      </div>
      <div className="prototype-audit-stats" aria-label="任务审计摘要">
        <div className="prototype-audit-stat"><b>{labelForCode(detail.task.ttc_state, "未登记")}</b><span>TTC 状态</span></div>
        <div className="prototype-audit-stat"><b>{detail.audit_chain.length}</b><span>审计事件</span></div>
        <div className="prototype-audit-stat"><b>{detail.evidence.length}</b><span>存证记录</span></div>
        <div className="prototype-audit-stat"><b>{detail.execution_receipts.length}</b><span>执行回执</span></div>
      </div>
      <div className="prototype-chain-status is-ok" role="status"><FileCheck2 size={17} aria-hidden="true" /> 任务编号 <code>{detail.task.task_id}</code> · 业务状态 {labelForCode(detail.task.status, "未登记")}</div>
      <div className="prototype-audit-columns">
        <div><h4>真实证据与核验状态</h4>{detail.evidence.length ? detail.evidence.map((item) => <div className="prototype-audit-item is-chain" key={item.evidence_id}>
          <span>{labelForCode(item.stage, "存证阶段")} · {labelForCode(item.status, "未登记状态")}</span>
          <small>核验：{item.verification_status === "MATCHED" ? "摘要一致" : item.verification_status === "MISMATCH" ? "摘要不一致" : "尚无核验结论"}</small>
          <small>证据摘要 <code title={item.evidence_hash || undefined}>{shortValue(item.evidence_hash)}</code>{item.tx_hash ? <> · 外部交易回执 <code title={item.tx_hash}>{shortValue(item.tx_hash)}</code></> : " · 未返回外部链回执"}</small>
        </div>) : <div className="prototype-empty">该任务暂无存证记录</div>}</div>
        <div><h4>企业连接器执行回执</h4>{detail.execution_receipts.length ? detail.execution_receipts.map((item) => <div className="prototype-audit-item" key={item.receipt_id}>
          <span>{labelForCode(item.status, "未登记状态")} · 回执 <code title={item.receipt_id}>{shortValue(item.receipt_id)}</code></span>
          <small>{formatDate(item.executed_at)} · 节点 {item.node_code || "未登记"}</small>
          <small>请求摘要 <code title={item.request_hash || undefined}>{shortValue(item.request_hash)}</code> · 结果摘要 <code title={item.result_hash || undefined}>{shortValue(item.result_hash)}</code></small>
          <small>{item.audit_event_verified ? "审计事件指针已校验（不代表全链连续性）" : "尚无审计事件指针校验结论"}</small>
        </div>) : <div className="prototype-empty">该任务暂无企业连接器执行回执</div>}</div>
      </div>
      <div className="prototype-audit-columns">
        <div><h4>审计流水</h4>{detail.audit_chain.length ? detail.audit_chain.map((item) => <AuditItem key={item.record_id} item={item} onOpenTask={openTask} />) : <div className="prototype-empty">暂无任务审计流水</div>}</div>
        <div><h4>TTC 状态迁移</h4>{detail.transitions.length ? detail.transitions.map((item, index) => <div className="prototype-audit-item" key={String(item.transition_id || index)}><span>{labelForCode(String(item.from_state || ""), "初始状态")} → {labelForCode(String(item.to_state || ""), "未登记状态")}</span><small>{formatDate(typeof item.occurred_at === "string" ? item.occurred_at : null)}</small></div>) : <div className="prototype-empty">暂无 TTC 状态迁移记录</div>}</div>
      </div>
    </section>}
  </PrototypePageFrame>;
}
