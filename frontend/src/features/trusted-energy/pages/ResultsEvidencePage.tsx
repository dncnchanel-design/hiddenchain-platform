import { useMemo, useRef, useState } from "react";
import { BadgeCheck, Blocks, Check, Copy, Hash, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, prepareIdempotencyKey, shortHash, type IdempotencyKeyRecord } from "../../../api";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, MetricBand, RemoteState, StatusBadge, SurfaceHeader, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Textarea } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { confirmResult, loadResult, loadResults, verifyEvidence, type ResultDetailPayload, type ResultListPayload } from "../trusted-space-api";
import { routeForView, trustedEntityId } from "../types";

function resultStatus(value: string) {
  return ({ CONFIRMED: "已确认", UNCONFIRMED: "待确认", PENDING: "待确认", REJECTED: "已拒绝" } as Record<string, string>)[value] || value || "未登记";
}

function scalar(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function resultRows(value: Record<string, unknown> | null | undefined) {
  return Object.entries(value || {}).filter(([, item]) => item === null || ["string", "number", "boolean"].includes(typeof item)).slice(0, 8);
}

export function ResultsEvidencePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const resultId = trustedEntityId(location.pathname, "results");
  const page = Math.max(1, Number(searchParams.get("page") || "1") || 1);
  const listRemote = useRemote<ResultListPayload | null>((signal) => resultId ? Promise.resolve(null) : loadResults({ page, pageSize: 12 }, signal), [resultId, page]);
  const detailRemote = useRemote<ResultDetailPayload | null>((signal) => resultId ? loadResult(resultId, signal) : Promise.resolve(null), [resultId]);
  const detail = detailRemote.data;
  const [decision, setDecision] = useState<"APPROVE" | "REJECT">("APPROVE");
  const [opinion, setOpinion] = useState("");
  const [actionError, setActionError] = useState("");
  const [copyState, setCopyState] = useState("");
  const [busy, setBusy] = useState(false);
  const [verifyState, setVerifyState] = useState<Record<string, string>>({});
  const idempotencyKeys = useRef<Record<string, IdempotencyKeyRecord>>({});
  const metrics = useMemo(() => {
    if (!detail) return [];
    return resultRows(detail.result.result).slice(0, 4).map(([label, value], index) => ({
      label,
      value: scalar(value),
      detail: detail.result.result_scope || "后端结果摘要",
      tone: (["brand", "info", "success", "warning"] as const)[index] || "brand",
    }));
  }, [detail]);
  const allowedActions = detail?.allowed_actions || [];
  const taskVersion = detail?.task.state_version || 1;

  function updatePage(nextPage: number) {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(Math.max(1, nextPage)));
    setSearchParams(next);
  }

  async function copyValue(label: string, value: string) {
    if (value === "—") return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(value);
      setCopyState(`${label}已复制`);
    } catch {
      setCopyState(`${label}复制失败，请检查浏览器剪贴板权限`);
    }
  }

  async function submitDecision() {
    if (!detail || !allowedActions.includes("confirm_result")) return;
    if (!opinion.trim()) {
      setActionError("提交结果结论前请填写意见。");
      return;
    }
    setActionError("");
    setBusy(true);
    const fingerprint = `${detail.result.result_id}:${taskVersion}:${decision}:${opinion.trim()}`;
    const key = prepareIdempotencyKey(idempotencyKeys.current[fingerprint], "result-confirm", fingerprint);
    idempotencyKeys.current[fingerprint] = key;
    try {
      await confirmResult(detail.result.result_id, { decision, opinion: opinion.trim() }, { ifMatch: `"${taskVersion}"`, idempotencyKey: key.key });
      setOpinion("");
      await detailRemote.reload();
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : "结果确认失败，请刷新后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function verify(evidenceId: string) {
    setVerifyState((current) => ({ ...current, [evidenceId]: "核验中…" }));
    try {
      const payload = await verifyEvidence(evidenceId);
      setVerifyState((current) => ({ ...current, [evidenceId]: payload.matched ? "哈希匹配" : "核验未通过" }));
    } catch (error) {
      setVerifyState((current) => ({ ...current, [evidenceId]: error instanceof ApiError ? error.message : "核验失败" }));
    }
  }

  if (!resultId) {
    const canGoPrevious = page > 1;
    const canGoNext = Boolean(listRemote.data && page * listRemote.data.page_size < listRemote.data.total);
    return <PageFrame title="计算结果与存证" description="从当前主体可见的真实结果列表进入摘要、签名与证据详情。" action={<Button variant="secondary" onClick={() => void listRemote.reload()} busy={listRemote.refreshing}><RefreshCw size={14} />刷新</Button>}>
      {listRemote.loading && !listRemote.data && <RemoteState loading />}
      {listRemote.error && !listRemote.data && <RemoteState error={listRemote.error} onRetry={() => void listRemote.reload()} />}
      {listRemote.data && !listRemote.data.items.length && <RemoteState empty emptyLabel="当前主体暂无可见计算结果" />}
      {listRemote.data && listRemote.data.items.length > 0 && <Card><CardHeader><SurfaceHeader title="结果列表" description="结果 ID、哈希和确认状态来自 settlement_results" action={<Badge tone="info">第 {listRemote.data.page} 页 · 共 {listRemote.data.total} 条</Badge>} /></CardHeader><CardContent className="trusted-table-wrap"><Table><TableHeader><TableRow><TableHead>结果 ID</TableHead><TableHead>任务</TableHead><TableHead>结果范围</TableHead><TableHead>ResultHash</TableHead><TableHead>状态</TableHead><TableHead>动作</TableHead></TableRow></TableHeader><TableBody>{listRemote.data.items.map((item) => <TableRow key={item.result_id}><TableCell><code>{item.result_id}</code></TableCell><TableCell><code>{item.task_id}</code></TableCell><TableCell>{item.result_scope || "—"}</TableCell><TableCell><code>{shortHash(item.result_hash)}</code></TableCell><TableCell><StatusBadge value={resultStatus(item.confirm_status)} /></TableCell><TableCell><Button variant="link" size="sm" onClick={() => navigate(routeForView("results", item.result_id))}>查看结果</Button></TableCell></TableRow>)}</TableBody></Table><div className="trusted-step-footer" aria-label="结果列表分页"><span>第 {listRemote.data.page} 页 · 共 {listRemote.data.total} 条</span><div><Button variant="secondary" size="sm" disabled={!canGoPrevious || listRemote.loading} onClick={() => updatePage(page - 1)}>上一页</Button><Button variant="secondary" size="sm" disabled={!canGoNext || listRemote.loading} onClick={() => updatePage(page + 1)}>下一页</Button></div></div></CardContent></Card>}
    </PageFrame>;
  }

  return <PageFrame title="计算结果与存证" description={detail ? `结果 ${detail.result.result_id} 的摘要、签名和证据记录来自真实后端。` : "读取真实结果与存证记录。"} back={routeForView("results")} action={<><>{detail && <StatusBadge value={resultStatus(detail.result.confirm_status)} />}</><Button variant="secondary" onClick={() => void detailRemote.reload()} busy={detailRemote.refreshing}><RefreshCw size={14} />刷新</Button></>}>
    {detailRemote.loading && !detail && <RemoteState loading />}
    {detailRemote.error && !detail && <RemoteState error={detailRemote.error} onRetry={() => void detailRemote.reload()} />}
    {detail && <>
      <div className="trusted-result-notice"><Badge tone={detail.capability_state === "DEMO" ? "warning" : "info"}>{detail.capability_state || "后端登记"}</Badge><span>{detail.source_of_truth || "settlement_results/signatures/blockchain_evidence"}。未返回的链上字段不会由前端补造。</span></div>
      {copyState && <p className="trusted-inline-status" role="status" aria-live="polite">{copyState}</p>}
      {metrics.length > 0 && <MetricBand items={metrics} />}
      <div className="trusted-result-grid"><Card><CardHeader><SurfaceHeader title="结果摘要" description="只展示 settlement_results.result_json 中的真实字段" action={<BadgeCheck size={16} />} /></CardHeader><CardContent className="trusted-table-wrap"><Table><TableHeader><TableRow><TableHead>指标</TableHead><TableHead>结果</TableHead><TableHead>来源</TableHead></TableRow></TableHeader><TableBody>{resultRows(detail.result.result).map(([label, value]) => <TableRow key={label}><TableCell>{label}</TableCell><TableCell><strong className="trusted-result-number">{scalar(value)}</strong></TableCell><TableCell><Badge tone="info">后端结果</Badge></TableCell></TableRow>)}{!resultRows(detail.result.result).length && <TableRow><TableCell colSpan={3}>后端未登记结构化结果摘要</TableCell></TableRow>}</TableBody></Table></CardContent></Card><Card><CardHeader><SurfaceHeader title="可信验证" description="真实 ResultHash、签名与输入关联" action={<Hash size={16} />} /></CardHeader><CardContent><div className="trusted-hash-list"><div><span>ResultHash</span><code>{shortHash(detail.result.result_hash)}</code><Button variant="link" size="sm" disabled={!detail.result.result_hash} aria-label="复制 ResultHash" onClick={() => void copyValue("ResultHash", detail.result.result_hash || "—")}><Copy size={13} />复制</Button><Badge tone={detail.result.result_hash ? "success" : "warning"}>{detail.result.result_hash ? "已登记" : "缺失"}</Badge></div><div><span>任务 ID</span><code>{detail.result.task_id}</code><Button variant="link" size="sm" aria-label="复制任务 ID" onClick={() => void copyValue("任务 ID", detail.result.task_id)}><Copy size={13} />复制</Button></div><div><span>确认状态</span><StatusBadge value={resultStatus(detail.result.confirm_status)} /></div><div><span>状态版本</span><code>V{taskVersion}</code></div></div><div className="trusted-divider-spacer" /><div className="trusted-signature-list">{detail.signatures.map((signature) => <div key={signature.signature_id}><span><strong>{signature.target_type || "签名"}</strong><small>{signature.signer_did || signature.signer_org_id || "未登记签署主体"}</small></span><code>{shortHash(signature.target_hash)}</code><StatusBadge value={signature.verify_status || "未验证"} /></div>)}{!detail.signatures.length && <span className="trusted-muted">暂无签名记录</span>}</div></CardContent></Card></div>
      <Card><CardHeader><SurfaceHeader title="证据与链路" description="外部链锚定缺失时明确显示待锚定，不显示伪造 TxHash/块高" action={<Blocks size={16} />} /></CardHeader><CardContent><div className="trusted-chain-record">{detail.evidence.map((evidence) => <div key={evidence.evidence_id}><div><small>{evidence.stage || "证据"}</small><strong><code>{evidence.evidence_id}</code></strong></div><div><small>证据哈希</small><code>{shortHash(evidence.evidence_hash)}</code></div><div><small>链状态</small>{evidence.tx_hash ? <code>{shortHash(evidence.tx_hash)}</code> : <Badge tone="warning">待锚定</Badge>}</div>{evidence.block_height !== null && evidence.block_height !== undefined && evidence.tx_hash && <div><small>区块高度</small><strong>{evidence.block_height}</strong></div>}<StatusBadge value={evidence.status || "未登记"} /><Button variant="secondary" size="sm" onClick={() => void verify(evidence.evidence_id)}><ShieldCheck size={14} />核验证据</Button>{verifyState[evidence.evidence_id] && <span className="trusted-muted" role="status">{verifyState[evidence.evidence_id]}</span>}</div>)}{!detail.evidence.length && <RemoteState empty emptyLabel="暂无单条链证据记录" />}</div><div className="trusted-divider-spacer" /><div className="trusted-chain-record">{detail.formal_evidence.map((batch) => <div key={batch.batch_id}><div><small>证据批次</small><strong><code>{batch.batch_id}</code></strong></div><div><small>Merkle Root</small><code>{shortHash(batch.merkle_root)}</code></div><div><small>Outbox</small><span>{batch.outbox.length} 条 · {batch.status || "未登记"}</span></div><div><small>Anchor</small><span>{batch.anchors.length ? batch.anchors.map((anchor) => anchor.transaction_hash ? shortHash(anchor.transaction_hash) : "待锚定").join("、") : "未登记"}</span></div></div>)}{!detail.formal_evidence.length && <span className="trusted-muted">暂无正式证据批次</span>}</div></CardContent></Card>
      <Card><CardHeader><SurfaceHeader title="结果结论" description="只有后端返回 confirm_result 才能提交；动作经过 If-Match 与幂等保护" action={<Check size={16} />} /></CardHeader><CardContent><div className="trusted-submit-actions"><Button variant={decision === "APPROVE" ? "primary" : "secondary"} disabled={!allowedActions.includes("confirm_result") || busy} onClick={() => setDecision("APPROVE")}>确认通过</Button><Button variant={decision === "REJECT" ? "danger" : "secondary"} disabled={!allowedActions.includes("confirm_result") || busy} onClick={() => setDecision("REJECT")}><X size={14} />提出异议</Button><span className="trusted-muted">{allowedActions.includes("confirm_result") ? `当前版本 V${taskVersion}` : "当前角色或任务状态不可提交结论"}</span></div><Textarea value={opinion} onChange={(event) => setOpinion(event.target.value)} placeholder="填写结果结论意见" aria-label="结果结论意见" disabled={!allowedActions.includes("confirm_result")} />{actionError && <p className="trusted-muted" role="alert">{actionError}</p>}<div className="trusted-submit-actions"><Button variant="primary" busy={busy} disabled={!allowedActions.includes("confirm_result") || !opinion.trim()} onClick={() => void submitDecision()}>提交{decision === "APPROVE" ? "确认" : "异议"}</Button><span className="trusted-muted">结果确认会产生真实签名与审计副作用；不可撤回。</span></div></CardContent></Card>
    </>}
  </PageFrame>;
}
