import { useMemo, useRef, useState } from "react";
import { Check, ChevronRight, ClipboardList, LockKeyhole, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { ApiError, prepareIdempotencyKey, type IdempotencyKeyRecord } from "../../../api";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, RemoteState, StatusBadge, SurfaceHeader } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { useTrustedSpaceContext } from "../trusted-space-context";
import { loadUsageRequest, loadUsageRequests, transitionUsageRequest, type UsageRequest, type UsageRequestAction } from "../trusted-space-api";

function actionLabel(action: string) {
  return ({ review: "领取审查", approve: "批准", reject: "拒绝", withdraw: "撤回", revoke: "撤销" } as Record<string, string>)[action] || action;
}
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
    (signal) => loadUsageRequests({ inbox: view === "inbox", page, pageSize: 12 }, signal),
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

  return <PageFrame title="授权记录" description="查看真实使用申请，提供方只可处理自己资产的入站请求。" action={<Button variant="secondary" onClick={() => void listRemote.reload()} busy={listRemote.refreshing}><RefreshCw size={14} />刷新</Button>}>
    <div className="trusted-detail-grid">
      <div className="trusted-detail-main">
        <Card>
          <CardHeader><SurfaceHeader title={view === "inbox" ? "待授权申请" : "我的申请"} description={view === "inbox" ? "来源于当前组织所拥有资产的入站申请" : "当前主体可见的申请记录"} action={<div className="trusted-submit-actions"><Button variant={view === "inbox" ? "primary" : "secondary"} size="sm" disabled={!canReview} onClick={() => switchView("inbox")}>待我审核</Button><Button variant={view === "outbound" ? "primary" : "secondary"} size="sm" onClick={() => switchView("outbound")}>我的申请</Button></div>} /></CardHeader>
          <CardContent>
            <RemoteState loading={listRemote.loading} error={listRemote.error} onRetry={() => void listRemote.reload()} empty={!listRemote.loading && !listRemote.error && !listRemote.data?.items.length} emptyLabel="暂无授权记录" />
            {!listRemote.loading && !listRemote.error && Boolean(listRemote.data?.items.length) && <div className="trusted-task-list">{listRemote.data?.items.map((item) => <button type="button" className="trusted-task-row" key={item.request_id} onClick={() => selectRequest(item.request_id)}><span className="trusted-task-icon"><ClipboardList size={15} /></span><span className="trusted-task-copy"><strong>{item.asset.asset_name || item.asset.asset_code || item.request_id}</strong><small><code>{item.request_id}</code> · {item.applicant.org_name} → {item.provider.org_name}</small></span><span className="trusted-task-state"><StatusBadge value={item.status} /><small className="trusted-muted">V{item.state_version}</small></span><ChevronRight size={14} /></button>)}</div>}
            {listRemote.data && <div className="trusted-step-footer" aria-label="授权记录分页"><span>第 {listRemote.data.page} 页 · 共 {listRemote.data.total} 条</span><div><Button variant="secondary" size="sm" disabled={!canGoPrevious || listRemote.loading} onClick={() => updatePage(page - 1)}>上一页</Button><Button variant="secondary" size="sm" disabled={!canGoNext || listRemote.loading} onClick={() => updatePage(page + 1)}>下一页</Button></div></div>}
          </CardContent>
        </Card>
      </div>
      <div className="trusted-detail-side">
        <Card>
          <CardHeader><SurfaceHeader title="申请详情" description="动作由后端 actions 与当前 If-Match 版本共同决定" /></CardHeader>
          <CardContent>
            {detailRemote.loading && <RemoteState loading />}
            {!detailRemote.loading && detailRemote.error && <RemoteState error={detailRemote.error} onRetry={() => void detailRemote.reload()} />}
            {!detailRemote.loading && !detailRemote.error && !detail && <RemoteState empty emptyLabel="选择一条申请查看详情" />}
            {detail && <div className="trusted-definition-list"><div><dt>申请编号</dt><dd><code>{detail.request_id}</code></dd></div><div><dt>资产</dt><dd><strong>{detail.asset.asset_name || detail.asset.asset_code || "—"}</strong><small><code>{detail.asset.asset_id}</code></small></dd></div><div><dt>申请方</dt><dd>{detail.applicant.org_name}<small>{detail.applicant.did}</small></dd></div><div><dt>提供方</dt><dd>{detail.provider.org_name}<small>{detail.provider.did}</small></dd></div><div><dt>用途 / 方式</dt><dd>{detail.purpose} / {detail.usage_mode}</dd></div><div><dt>期限 / 策略</dt><dd>{detail.duration_days} 日<small>{detail.duration_policy?.source || "服务端策略"} · {detail.duration_policy?.policy_version || "—"}</small></dd></div><div><dt>提交时间</dt><dd>{formatTime(detail.submitted_at)}</dd></div><div><dt>状态 / 版本</dt><dd><StatusBadge value={detail.status} /> <code>V{detail.state_version}</code></dd></div><div><dt>真实性</dt><dd><Badge tone="warning">{detail.capability?.signature || "NOT_PROVIDED"}</Badge><small>{detail.capability?.external_anchor || "BLOCKED"}</small></dd></div></div>}
          </CardContent>
        </Card>
        {detail && <Card>
          <CardHeader><CardTitle>可执行动作</CardTitle></CardHeader>
          <CardContent><div className="trusted-option-grid"><Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="审批/拒绝/撤销理由（必要时填写）" aria-label="申请动作理由" />{actionError && <p role="alert" className="trusted-muted">{actionError}</p>}<div className="trusted-submit-actions">{detail.actions.map((action) => <Button key={action} variant={action === "reject" || action === "revoke" ? "danger" : "primary"} size="sm" busy={busyAction === action} onClick={() => void performAction(action as UsageRequestAction)}>{action === "approve" ? <Check size={14} /> : action === "reject" || action === "revoke" ? <X size={14} /> : <ShieldCheck size={14} />}{actionLabel(action)}</Button>)}</div><small className="trusted-muted"><LockKeyhole size={13} /> 操作失败时保留当前表单，可修正理由或刷新版本后重试。</small></div></CardContent>
        </Card>}
      </div>
    </div>
  </PageFrame>;
}
