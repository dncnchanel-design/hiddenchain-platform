import { useMemo, useRef, useState } from "react";
import { Check, FileSignature, LockKeyhole, MessageSquareText, Paperclip, RefreshCw, X } from "lucide-react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, formatDate, prepareIdempotencyKey, shortHash, type IdempotencyKeyRecord } from "../../../api";
import { useRemote } from "../../../hooks";
import { Button, Card, CardContent, CardHeader, CardTitle, Divider, Input, RemoteState, StatusBadge, SurfaceHeader, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Textarea, Timeline } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { loadContract, loadContracts, postContractAction, type ContractAction, type ContractDetailPayload, type ContractListItem, type ContractListPayload } from "../trusted-space-api";
import { labelForCode } from "../../../types";
import { routeForView, trustedEntityId } from "../types";
import { purposeLabel } from "../trusted-space-labels";

function contractStatus(value: string) {
  return ({ ACTIVE: "已生效", NEGOTIATED: "协商中", PENDING: "待确认", REJECTED: "已拒绝", REVOKED: "已撤销", EXPIRED: "已过期" } as Record<string, string>)[value] || labelForCode(value, "未知状态");
}

function orgName(org: ContractListItem["provider"]) {
  return org?.org_name || org?.org_id || "未登记组织";
}

function timelineFor(detail: ContractDetailPayload) {
  return detail.timeline.map((event, index) => ({
    id: event.event_id,
    label: labelForCode(event.event_type, "协商事件"),
    detail: `${contractStatus(event.from_state)} → ${contractStatus(event.to_state)}`,
    time: formatDate(event.created_at),
    state: index === detail.timeline.length - 1 && detail.agreement?.state !== "ACTIVE" ? "current" as const : "done" as const,
  }));
}

export function ContractPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const contractId = trustedEntityId(location.pathname, "contracts");
  const page = Math.max(1, Number(searchParams.get("page") || "1") || 1);
  const listState = searchParams.get("state") || "";
  const listRemote = useRemote<ContractListPayload | null>((signal) => contractId ? Promise.resolve(null) : loadContracts({ page, pageSize: 12, state: listState || undefined }, signal), [contractId, page, listState]);
  const detailRemote = useRemote<ContractDetailPayload | null>((signal) => contractId ? loadContract(contractId, signal) : Promise.resolve(null), [contractId]);
  const detail = detailRemote.data;
  const list = listRemote.data;
  const [activeAction, setActiveAction] = useState<ContractAction>("comment");
  const [message, setMessage] = useState("");
  const [termsText, setTermsText] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const idempotencyKeys = useRef<Record<string, IdempotencyKeyRecord>>({});
  const latestVersion = detail?.events[detail.events.length - 1]?.state_version || 0;
  const allowedActions = detail?.allowed_actions || [];
  const timeline = useMemo(() => detail ? timelineFor(detail) : [], [detail]);

  function updatePage(nextPage: number) {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(Math.max(1, nextPage)));
    setSearchParams(next);
  }

  function updateListParam(key: "state", value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    next.set("page", "1");
    setSearchParams(next);
  }

  async function submitAction() {
    if (!detail || !allowedActions.includes(activeAction)) return;
    if (["comment", "counter", "reject"].includes(activeAction) && !message.trim()) {
      setActionError("此协商动作必须填写消息或理由。");
      return;
    }
    setActionError("");
    setBusy(true);
    const fingerprint = `${detail.contract.contract_id}:${latestVersion}:${activeAction}:${message.trim()}:${termsText.trim()}`;
    const key = prepareIdempotencyKey(idempotencyKeys.current[fingerprint], `contract-${activeAction}`, fingerprint);
    idempotencyKeys.current[fingerprint] = key;
    try {
      await postContractAction(detail.contract.contract_id, activeAction, {
        message: message.trim(),
        terms: termsText.trim() ? { note: termsText.trim() } : {},
        attachments: [],
      }, { ifMatch: `"${latestVersion}"`, idempotencyKey: key.key });
      setMessage("");
      setTermsText("");
      await detailRemote.reload();
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : "协商动作失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  if (!contractId) {
    const canGoPrevious = page > 1;
    const canGoNext = Boolean(list && page * list.page_size < list.total);
    return <PageFrame title="合同协商" description="从当前主体可见的真实合同列表进入协商详情。" action={<Button variant="secondary" onClick={() => void listRemote.reload()} busy={listRemote.refreshing}><RefreshCw size={14} />刷新</Button>}>
      {listRemote.loading && !list && <RemoteState loading />}
      {listRemote.error && !list && <RemoteState error={listRemote.error} onRetry={() => void listRemote.reload()} />}
      {list && !list.items.length && <RemoteState empty emptyLabel="当前主体暂无可见合同或协商记录" />}
      {list && list.items.length > 0 && <Card><CardHeader><SurfaceHeader title="合同与协商列表" description="组织范围与动作权限由后端返回" action={<div className="trusted-submit-actions"><select aria-label="按合同状态筛选" value={listState} onChange={(event) => updateListParam("state", event.target.value)}><option value="">全部状态</option><option value="ACTIVE">已生效</option><option value="NEGOTIATED">协商中</option><option value="PENDING">待确认</option><option value="REJECTED">已拒绝</option><option value="REVOKED">已撤销</option><option value="EXPIRED">已过期</option></select><BadgePage page={list.page} total={list.total} /></div>} /></CardHeader><CardContent className="trusted-table-wrap"><Table><TableHeader><TableRow><TableHead>合同</TableHead><TableHead>双方</TableHead><TableHead>用途</TableHead><TableHead>状态</TableHead><TableHead>版本</TableHead><TableHead>动作</TableHead></TableRow></TableHeader><TableBody>{list.items.map((item) => <TableRow key={item.contract_id}><TableCell><code>{item.contract_id}</code></TableCell><TableCell>{orgName(item.provider)} → {orgName(item.consumer)}</TableCell><TableCell>{purposeLabel(item.purpose)}</TableCell><TableCell><StatusBadge value={contractStatus(item.agreement_state || item.status)} /></TableCell><TableCell>第 {item.latest_event_version} 版</TableCell><TableCell><Button variant="link" size="sm" onClick={() => navigate(routeForView("contract", item.contract_id))}>查看协商</Button></TableCell></TableRow>)}</TableBody></Table><div className="trusted-step-footer" aria-label="合同列表分页"><span>第 {list.page} 页 · 共 {list.total} 条</span><div><Button variant="secondary" size="sm" disabled={!canGoPrevious || listRemote.loading} onClick={() => updatePage(page - 1)}>上一页</Button><Button variant="secondary" size="sm" disabled={!canGoNext || listRemote.loading} onClick={() => updatePage(page + 1)}>下一页</Button></div></div></CardContent></Card>}
    </PageFrame>;
  }

  return <PageFrame title="合同协商" description={detail ? `围绕用途、处理方式、结果范围和存证口径保留合同 ${detail.contract.contract_id} 的真实协商轨迹。` : "读取真实合同与协商轨迹。"} back={routeForView("contract")} action={<Button variant="secondary" onClick={() => void detailRemote.reload()} busy={detailRemote.refreshing}><RefreshCw size={14} />刷新</Button>}>
    {detailRemote.loading && !detail && <RemoteState loading />}
    {detailRemote.error && !detail && <RemoteState error={detailRemote.error} onRetry={() => void detailRemote.reload()} />}
    {detail && <>
      <Card className="trusted-contract-meta"><CardContent><div><small>合同编号</small><strong><code>{detail.contract.contract_id}</code></strong></div><div><small>提供方</small><strong>{orgName(detail.contract.provider)}</strong><code>{detail.agreement?.provider_did || "未配置去中心化身份标识"}</code></div><div><small>申请方</small><strong>{orgName(detail.contract.consumer)}</strong><code>{detail.agreement?.consumer_did || "未配置去中心化身份标识"}</code></div><div><small>协商状态</small><StatusBadge value={contractStatus(detail.agreement?.state || detail.contract.status)} /></div></CardContent></Card>
      <div className="trusted-contract-grid"><Card><CardHeader><SurfaceHeader title="协商时间轴" description="节点状态与时间戳来自合同事件持久化记录" action={<LockKeyhole size={16} />} /></CardHeader><CardContent>{timeline.length ? <Timeline events={timeline} /> : <RemoteState empty emptyLabel="暂无协商事件" />}</CardContent></Card><Card><CardHeader><SurfaceHeader title="合同基本信息" description="条款与数据引用只展示后端登记内容" action={<FileSignature size={16} />} /></CardHeader><CardContent><dl className="trusted-definition-list"><div><dt>用途</dt><dd>{purposeLabel(detail.contract.purpose)}</dd></div><div><dt>关联任务</dt><dd><code>{detail.contract.task_id || "未关联"}</code></dd></div><div><dt>协议状态</dt><dd>{contractStatus(detail.agreement?.state || "")}</dd></div><div><dt>协议版本</dt><dd><code>{detail.agreement?.protocol_version || "—"}</code></dd></div><div><dt>策略哈希</dt><dd><code>{shortHash(detail.contract.policy_hash || detail.agreement?.negotiated_policy_hash)}</code></dd></div><div><dt>有效期</dt><dd>{formatDate(detail.contract.valid_from)} — {formatDate(detail.contract.expires_at)}</dd></div></dl><Divider /><div className="trusted-contract-attachments">{detail.contract.data_refs.map((reference) => <div key={String(reference.asset_id)}><Paperclip size={14} /><span>资产引用 <code>{String(reference.asset_id || "—")}</code></span><Button variant="link" size="sm" disabled={!reference.asset_id} onClick={() => navigate(routeForView("asset", String(reference.asset_id)))}>查看资产</Button></div>)}{!detail.contract.data_refs.length && <span className="trusted-muted">暂无资产引用</span>}</div></CardContent></Card></div>
      <Card><CardHeader><SurfaceHeader title="当前条款" description="协商动作可更新条款摘要；不会直接执行计算或下载附件" /></CardHeader><CardContent><div className="trusted-contract-conditions">{Object.entries(detail.contract.terms || {}).map(([key, value]) => <div key={key}><span><Check size={14} />{labelForCode(key, "条款项")}</span><strong>{typeof value === "object" ? JSON.stringify(value) : String(value)}</strong></div>)}{!Object.keys(detail.contract.terms || {}).length && <div><span><Check size={14} />条款</span><strong>暂无结构化条款</strong></div>}</div></CardContent></Card>
      <Card><CardHeader><SurfaceHeader title="协商事件" description="附件仅允许已登记引用元数据，不提供未经登记的下载" /></CardHeader><CardContent><div className="trusted-task-list">{detail.events.map((event) => <div className="trusted-task-row" key={event.event_id}><span className="trusted-task-icon"><MessageSquareText size={15} /></span><span className="trusted-task-copy"><strong>{labelForCode(event.event_type, "协商事件")} · {orgName(event.actor)}</strong><small>{formatDate(event.created_at)} · 第 {event.state_version} 版 · {event.message || "无消息"}</small>{event.attachment_metadata.map((attachment, index) => <small key={`${event.event_id}-attachment-${index}`}><Paperclip size={12} />附件引用：{String(attachment.file_ref || attachment.evidence_id || attachment.upload_id || "未登记")}</small>)}</span><code>{shortHash(event.event_hash)}</code></div>)}{!detail.events.length && <RemoteState empty emptyLabel="暂无事件" />}</div></CardContent></Card>
      <Card><CardHeader><CardTitle>回复协商</CardTitle></CardHeader><CardContent><div className="trusted-option-grid"><div className="trusted-submit-actions">{(["comment", "counter", "accept", "reject"] as ContractAction[]).map((action) => <Button key={action} variant={action === "reject" ? "danger" : action === activeAction ? "primary" : "secondary"} size="sm" disabled={!allowedActions.includes(action) || busy} onClick={() => setActiveAction(action)}>{action === "accept" ? <Check size={14} /> : action === "reject" ? <X size={14} /> : <MessageSquareText size={14} />}{({ comment: "回复", counter: "反报价", accept: "接受", reject: "拒绝" } as Record<ContractAction, string>)[action]}</Button>)}</div><Textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder={activeAction === "accept" ? "可填写接受说明（可选）" : "填写协商消息或理由"} aria-label="协商消息" /><Input value={termsText} onChange={(event) => setTermsText(event.target.value)} placeholder="条款摘要（可选，将以 note 字段保存）" aria-label="条款摘要" />{actionError && <p role="alert" className="trusted-muted">{actionError}</p>}<div className="trusted-submit-actions"><Button variant="primary" busy={busy} disabled={!allowedActions.includes(activeAction)} onClick={() => void submitAction()}><MessageSquareText size={14} />提交 {activeAction === "comment" ? "回复" : "动作"}</Button><span className="trusted-muted">按当前状态版本校验 V{latestVersion} · 附件上传需先登记受控引用</span></div></div></CardContent></Card>
    </>}
  </PageFrame>;
}

function BadgePage({ page, total }: { page: number; total: number }) {
  return <span className="trusted-muted">第 {page} 页 · 共 {total} 条</span>;
}
