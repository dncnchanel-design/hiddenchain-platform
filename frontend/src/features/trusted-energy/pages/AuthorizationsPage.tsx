import { useMemo, useRef, useState } from "react";
import { Check, ChevronRight, ClipboardList, LockKeyhole, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { ApiError, prepareIdempotencyKey, type IdempotencyKeyRecord } from "../../../api";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, RemoteState, StatusBadge, SurfaceHeader } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { useTrustedSpaceContext } from "../trusted-space-context";
import { loadUsageRequest, loadUsageRequests, transitionUsageRequest, type UsageRequest, type UsageRequestAction } from "../trusted-space-api";
import { actionLabel, capabilityLabel, externalAnchorLabel, policySourceLabel, policyVersionLabel, purposeLabel, requestStatusLabel, signatureLabel, usageModeLabel } from "../trusted-space-labels";

function formatTime(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN", { hour12: false });
}

export function AuthorizationsPage() {
  const { context } = useTrustedSpaceContext();
  const [searchParams, setSearchParams] = useSearchParams();
  const canReview = context?.role_capabilities.can_review_inbound_requests === true;
  const view = searchParams.get("view") === "inbox" || searchParams.get("view") === "outbound"
    ? searchParams.get("view") as "inbox" | "outbound"
    : canReview ? "inbox" : "outbound";
  const page = Math.max(1, Number(searchParams.get("page") || "1") || 1);
  const selectedId = searchParams.get("request");
  const listRemote = useRemote(
    (signal) => loadUsageRequests({ inbox: view === "inbox", mine: view === "outbound", page, pageSize: 12 }, signal),
    [view, page],
  );
  const selectedFromList = useMemo(() => listRemote.data?.items.find((item) => item.request_id === selectedId) || null, [listRemote.data, selectedId]);
  const detailRemote = useRemote(
    (signal) => selectedId ? loadUsageRequest(selectedId, signal) : Promise.resolve<UsageRequest | null>(null),
    [selectedId],
  );
  const detail = detailRemote.data || selectedFromList;
  const [reason, setReason] = useState("");
  const [busyAction, setBusyAction] = useState<UsageRequestAction | null>(null);
  const [actionError, setActionError] = useState("");
  const idempotencyKeys = useRef<Record<string, IdempotencyKeyRecord>>({});

  function switchView(next: "inbox" | "outbound") {
    setSearchParams({ view: next, page: "1" });
    setReason("");
    setActionError("");
  }

  function selectRequest(requestId: string) {
    const next = new URLSearchParams(searchParams);
    next.set("view", view);
    next.set("request", requestId);
    setSearchParams(next);
    setReason("");
    setActionError("");
  }

  function updatePage(nextPage: number) {
    const next = new URLSearchParams(searchParams);
    next.set("view", view);
    next.set("page", String(Math.max(1, nextPage)));
    next.delete("request");
    setSearchParams(next);
  }

  async function performAction(action: UsageRequestAction) {
    if (!detail) return;
    if ((action === "approve" || action === "reject") && !reason.trim()) {
      setActionError("批准或拒绝必须填写理由。");
      return;
    }
    setBusyAction(action);
    setActionError("");
    try {
      const fingerprint = `${detail.request_id}:${detail.state_version}:${action}:${reason.trim()}`;
      const key = prepareIdempotencyKey(idempotencyKeys.current[fingerprint], `usage-${action}`, fingerprint);
      idempotencyKeys.current[fingerprint] = key;
      await transitionUsageRequest(detail.request_id, action, reason.trim(), {
        ifMatch: `"${detail.state_version}"`,
        idempotencyKey: key.key,
      });
      setReason("");
      await Promise.all([listRemote.reload(), detailRemote.reload()]);
      window.dispatchEvent(new Event("trusted-energy:data-refresh"));
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : "操作失败，请重试。");
    } finally {
      setBusyAction(null);
    }
  }

  const canGoPrevious = page > 1;
  const canGoNext = Boolean(listRemote.data && page * listRemote.data.page_size < listRemote.data.total);
  const isInbox = view === "inbox";
  const pageDescription = isInbox ? "处理其他主体对本组织资产发起的使用申请。" : "查看当前主体提交的申请、审核状态与授权结果。";

  return <PageFrame title="授权记录" description={pageDescription} action={<Button variant="secondary" onClick={() => void listRemote.reload()} busy={listRemote.refreshing}><RefreshCw size={14} />刷新</Button>}>
    <div className="trusted-detail-grid">
      <div className="trusted-detail-main">
        <Card>
          <CardHeader><SurfaceHeader title={isInbox ? "待审核申请" : "我的申请"} description={isInbox ? "需要本组织处理的入站申请" : "由当前主体提交的申请记录"} action={<div className="trusted-submit-actions"><Button aria-pressed={isInbox} variant={isInbox ? "primary" : "secondary"} size="sm" disabled={!canReview} onClick={() => switchView("inbox")}>待我审核</Button><Button aria-pressed={!isInbox} variant={!isInbox ? "primary" : "secondary"} size="sm" onClick={() => switchView("outbound")}>我的申请</Button></div>} /></CardHeader>
          <CardContent>
            <RemoteState loading={listRemote.loading} error={listRemote.error} onRetry={() => void listRemote.reload()} empty={!listRemote.loading && !listRemote.error && !listRemote.data?.items.length} emptyLabel={isInbox ? "暂无待审核申请" : "暂无本人申请记录"} />
            {!listRemote.loading && !listRemote.error && Boolean(listRemote.data?.items.length) && <div className="trusted-task-list">{listRemote.data?.items.map((item) => <button type="button" className="trusted-task-row" key={item.request_id} onClick={() => selectRequest(item.request_id)}><span className="trusted-task-icon"><ClipboardList size={15} /></span><span className="trusted-task-copy"><strong>{item.asset.asset_name || item.asset.asset_code || "未命名资产"}</strong><small><code>{item.request_id}</code> · {isInbox ? `申请方：${item.applicant.org_name}` : `提供方：${item.provider.org_name}`}</small><small>{purposeLabel(item.purpose)} · {usageModeLabel(item.usage_mode)}</small></span><span className="trusted-task-state"><StatusBadge value={requestStatusLabel(item.status)} /><small className="trusted-muted">状态版本 {item.state_version}</small></span><ChevronRight size={14} /></button>)}</div>}
            {listRemote.data && <div className="trusted-step-footer" aria-label="授权记录分页"><span>第 {listRemote.data.page} 页 · 共 {listRemote.data.total} 条</span><div><Button variant="secondary" size="sm" disabled={!canGoPrevious || listRemote.loading} onClick={() => updatePage(page - 1)}>上一页</Button><Button variant="secondary" size="sm" disabled={!canGoNext || listRemote.loading} onClick={() => updatePage(page + 1)}>下一页</Button></div></div>}
          </CardContent>
        </Card>
      </div>
      <div className="trusted-detail-side">
        <Card>
          <CardHeader><SurfaceHeader title={isInbox ? "审核详情" : "申请详情"} description={isInbox ? "核对用途、范围和期限后处理申请。" : "查看申请当前状态、审核结果和授权期限。"} /></CardHeader>
          <CardContent>
            {detailRemote.loading && <RemoteState loading />}
            {!detailRemote.loading && detailRemote.error && <RemoteState error={detailRemote.error} onRetry={() => void detailRemote.reload()} />}
            {!detailRemote.loading && !detailRemote.error && !detail && <RemoteState empty emptyLabel="选择一条申请查看详情" />}
            {detail && <div className="trusted-definition-list"><div><dt>申请编号</dt><dd><code>{detail.request_id}</code></dd></div><div><dt>资产</dt><dd><strong>{detail.asset.asset_name || detail.asset.asset_code || "—"}</strong><small><code>{detail.asset.asset_id}</code></small></dd></div><div><dt>申请方</dt><dd>{detail.applicant.org_name}<small>{detail.applicant.did}</small></dd></div><div><dt>提供方</dt><dd>{detail.provider.org_name}<small>{detail.provider.did}</small></dd></div><div><dt>用途 / 方式</dt><dd>{purposeLabel(detail.purpose)}<small>{usageModeLabel(detail.usage_mode)}</small></dd></div><div><dt>期限 / 策略</dt><dd>{detail.duration_days} 日<small>{policySourceLabel(detail.duration_policy?.source)} · {policyVersionLabel(detail.duration_policy?.policy_version)}</small></dd></div><div><dt>提交时间</dt><dd>{formatTime(detail.submitted_at)}</dd></div><div><dt>状态 / 版本</dt><dd><StatusBadge value={requestStatusLabel(detail.status)} /> <span className="trusted-muted">状态版本 {detail.state_version}</span></dd></div><div><dt>能力状态</dt><dd><Badge tone="warning">{capabilityLabel(detail.capability?.decision)}</Badge><small>{signatureLabel(detail.capability?.signature)} · {externalAnchorLabel(detail.capability?.external_anchor)}</small></dd></div>{detail.decision_reason && <div><dt>处理意见</dt><dd>{detail.decision_reason}</dd></div>}{detail.revocation_reason && <div><dt>撤销原因</dt><dd>{detail.revocation_reason}</dd></div>}</div>}
          </CardContent>
        </Card>
        {detail && detail.actions.length > 0 && <Card>
          <CardHeader><CardTitle>{isInbox ? "审核操作" : "申请操作"}</CardTitle></CardHeader>
          <CardContent><div className="trusted-option-grid"><Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder={isInbox ? "填写审核意见（批准或拒绝必填）" : "填写撤回或撤销原因（可选）"} aria-label={isInbox ? "审核意见" : "申请处理原因"} />{actionError && <p role="alert" className="trusted-muted">{actionError}</p>}<div className="trusted-submit-actions">{detail.actions.map((action) => <Button key={action} variant={action === "reject" || action === "revoke" ? "danger" : "primary"} size="sm" busy={busyAction === action} onClick={() => void performAction(action as UsageRequestAction)}>{action === "approve" ? <Check size={14} /> : action === "reject" || action === "revoke" ? <X size={14} /> : <ShieldCheck size={14} />}{actionLabel(action, view, detail.status)}</Button>)}</div><small className="trusted-muted"><LockKeyhole size={13} /> {isInbox ? "批准或拒绝必须填写明确理由；操作依据当前状态版本提交。" : "申请提交后可在提供方处理前撤回；已授权申请可由有权主体撤销。"}</small></div></CardContent>
        </Card>}
        {detail && detail.actions.length === 0 && <Card><CardHeader><CardTitle>当前无可执行操作</CardTitle></CardHeader><CardContent><p className="trusted-muted">当前角色只能查看这条记录，后续处理由对应责任主体完成。</p></CardContent></Card>}
      </div>
    </div>
  </PageFrame>;
}
