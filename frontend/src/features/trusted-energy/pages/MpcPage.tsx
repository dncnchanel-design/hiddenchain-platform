import { useEffect, useRef, useState } from "react";
import { ArrowRight, CheckCircle2, Cpu, Link2, Network, Radio, RefreshCw, ShieldCheck, TerminalSquare } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError, createIdempotencyKey, shortHash } from "../../../api";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, Progress, RemoteState, StatusBadge, SurfaceHeader } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { controlComputation, loadComputation, loadComputationEvents, loadComputations, type ComputationDetailPayload, type ComputationEvent, type ComputationListPayload, type ComputationAction } from "../trusted-space-api";
import { ALGORITHM_LABELS, ROLE_IN_TASK_LABELS, STAGE_LABELS, labelForCode } from "../../../types";
import { routeForView, trustedEntityId } from "../types";
import { capabilityLabel } from "../trusted-space-labels";

function statusLabel(value: string) {
  return ({ RUNNING: "执行中", PENDING: "待开始", QUEUED: "排队中", SUCCEEDED: "已完成", SUCCESS: "已完成", FAILED: "失败", CANCELLED: "已取消", COMPLETED: "已完成", BLOCKED: "已阻断" } as Record<string, string>)[value] || labelForCode(value, "未知状态");
}

function capabilityTone(value?: string) {
  return value === "BLOCKED" ? "danger" as const : value === "ADAPTER" || value === "DEMO" ? "warning" as const : "success" as const;
}

function outputModeLabel(value: unknown) {
  return value === "AGGREGATE_ONLY" ? "只返回聚合结果" : value === "AGGREGATED_AND_COMPUTE_ONLY" ? "聚合结果 + 仅计算回执" : "受控结果（以后端登记为准）";
}

export function MpcPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const routeJobId = trustedEntityId(location.pathname, "mpc");
  const [statusFilter, setStatusFilter] = useState("");
  const [listPage, setListPage] = useState(1);
  const listRemote = useRemote<ComputationListPayload | null>((signal) => routeJobId ? Promise.resolve(null) : loadComputations({ page: listPage, pageSize: 12, status: statusFilter || undefined }, signal), [routeJobId, listPage, statusFilter]);
  const selectedJobId = routeJobId;
  const remote = useRemote<ComputationDetailPayload | null>((signal) => selectedJobId ? loadComputation(selectedJobId, signal) : Promise.resolve(null), [selectedJobId]);
  const detail = remote.data;
  const [logsEnabled, setLogsEnabled] = useState(false);
  const [logRetryNonce, setLogRetryNonce] = useState(0);
  const [logItems, setLogItems] = useState<ComputationEvent[]>([]);
  const [logError, setLogError] = useState("");
  const [controlBusy, setControlBusy] = useState<ComputationAction | "">("");
  const [controlError, setControlError] = useState("");
  const cursorRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!logsEnabled || !selectedJobId) return undefined;
    let active = true;
    let timer: number | undefined;
    const controller = new AbortController();
    cursorRef.current = undefined;
    const poll = async () => {
      if (!active) return;
      try {
        const payload = await loadComputationEvents(selectedJobId, { cursor: cursorRef.current, limit: 50 }, controller.signal);
        if (!active) return;
        setLogItems((previous) => {
          const known = new Set(previous.map((item) => item.sequence_no));
          return [...previous, ...payload.items.filter((item) => !known.has(item.sequence_no))];
        });
        const offset = Number(cursorRef.current || 0) || 0;
        cursorRef.current = payload.next_cursor || String(offset + payload.items.length);
        setLogError("");
        timer = window.setTimeout(() => void poll(), 1_500);
      } catch (error) {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) return;
        setLogError(error instanceof ApiError ? error.message : "计算日志读取失败");
        timer = window.setTimeout(() => void poll(), 4_000);
      }
    };
    void poll();
    return () => {
      active = false;
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [logRetryNonce, logsEnabled, selectedJobId]);

  async function runControl(action: ComputationAction) {
    if (!detail || controlBusy) return;
    setControlBusy(action);
    setControlError("");
    try {
      await controlComputation(detail.job.job_id, action, action === "cancel" ? "用户请求取消计算" : "用户请求重试计算", {
        ifMatch: String(detail.job.state_version),
        idempotencyKey: createIdempotencyKey(`compute-${action}-${detail.job.job_id}`),
      });
      await remote.reload();
      await listRemote.reload();
    } catch (error) {
      setControlError(error instanceof ApiError ? error.message : "计算控制动作未完成，请刷新后重试");
    } finally {
      setControlBusy("");
    }
  }

  const fallbackLoading = !routeJobId && listRemote.loading && !listRemote.data;
  const fallbackError = !routeJobId && listRemote.error && !listRemote.data ? listRemote.error : "";
  return <PageFrame title="隐私计算" description={detail ? `查看真实计算任务 ${detail.job.job_id} 的参与方、固定算法、输出边界和回执。` : "查看授权后的固定算法计算任务与能力边界。"} back={detail ? routeForView("ttc", detail.job.task_id) : routeForView("workbench")} action={detail ? <Badge tone={capabilityTone(detail.external_execution.capability_state)} dot>{capabilityLabel(detail.external_execution.capability_state)}</Badge> : <Button variant="secondary" onClick={listRemote.reload} busy={listRemote.refreshing}><RefreshCw size={14} />刷新</Button>}>
    {fallbackLoading && <RemoteState loading />}
    {fallbackError && <RemoteState error={fallbackError} onRetry={() => void listRemote.reload()} />}
    {remote.loading && !detail && !fallbackLoading && !fallbackError && <RemoteState loading />}
    {remote.error && !detail && <RemoteState error={remote.error} onRetry={() => void remote.reload()} />}
    {!selectedJobId && !fallbackLoading && !fallbackError && <RemoteState empty emptyLabel="当前主体暂无可见计算任务" />}
    {listRemote.data && !routeJobId && !detail && <Card><CardHeader><SurfaceHeader title="计算任务列表" description="从真实隐私计算任务记录中选择任务" action={<select aria-label="按计算状态筛选" value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setListPage(1); }}><option value="">全部状态</option><option value="QUEUED">排队中</option><option value="RUNNING">执行中</option><option value="SUCCESS">已完成</option><option value="FAILED">失败</option><option value="CANCELLED">已取消</option></select>} /></CardHeader><CardContent>{listRemote.data.items.length ? <div className="trusted-task-list">{listRemote.data.items.map((job) => <button type="button" className="trusted-task-row" key={job.job_id} onClick={() => navigate(routeForView("mpc", job.job_id))}><span className="trusted-task-icon"><Network size={15} /></span><span className="trusted-task-copy"><strong>{job.task_name || job.job_id}</strong><small><code>{job.job_id}</code> · {statusLabel(job.status)}</small></span><StatusBadge value={statusLabel(job.status)} /></button>)}</div> : <RemoteState empty emptyLabel="当前筛选下暂无计算任务" />}<div className="trusted-submit-actions"><Button variant="secondary" size="sm" disabled={listPage <= 1} onClick={() => setListPage((value) => Math.max(1, value - 1))}>上一页</Button><span className="trusted-muted">第 {listRemote.data.page} 页 · 共 {listRemote.data.total} 项</span><Button variant="secondary" size="sm" disabled={listPage * listRemote.data.page_size >= listRemote.data.total} onClick={() => setListPage((value) => value + 1)}>下一页</Button></div></CardContent></Card>}
    {detail && <>
      <div className="trusted-mpc-alert"><ShieldCheck size={16} /><div><strong>能力边界提示</strong><span>参与方、回执和日志来自后端任务登记；外部多方安全计算或可信执行环境未配置时，保持“适配器能力”或“已阻断”，不推断生产连接。</span></div><Badge tone={capabilityTone(detail.external_execution.capability_state)}>{capabilityLabel(detail.external_execution.capability_state)}</Badge></div>
      <Card className="trusted-computation-explain"><CardHeader><SurfaceHeader title="这次计算做了什么" description="把算法、输入边界和输出范围直接展示出来" action={<ShieldCheck size={16} />} /></CardHeader><CardContent><dl className="trusted-definition-grid"><div><dt>计算方式</dt><dd>{detail.external_execution.capability_state === "BLOCKED" ? "前置条件未满足，未执行" : "企业侧本地受控计算"}</dd></div><div><dt>固定算法</dt><dd>{ALGORITHM_LABELS[detail.job.algorithm_code] || "已登记固定算法"}</dd></div><div><dt>输出范围</dt><dd>{outputModeLabel(detail.job.privacy_guarantees.output_mode)}</dd></div><div><dt>原始记录</dt><dd>{detail.job.privacy_guarantees.api_raw_records_returned === false ? "不返回" : "以回执登记为准"}</dd></div><div><dt>跨域边界</dt><dd>{detail.job.privacy_guarantees.cross_domain_non_export_verified === true ? "已核验不出域" : "未宣称跨域不出域"}</dd></div><div><dt>可复核依据</dt><dd>{detail.snapshot ? "规则快照 + 输入哈希 + 计算回执" : "暂未登记规则快照"}</dd></div></dl></CardContent></Card>
      <Card className="trusted-task-banner"><CardContent><div><small>任务编号</small><strong><code>{detail.job.job_id}</code></strong></div><div><small>关联可信任务</small><strong><code>{detail.job.task_id}</code></strong></div><div><small>算法</small><strong>{ALGORITHM_LABELS[detail.job.algorithm_code] || labelForCode(detail.job.algorithm_code, "未登记算法")}</strong></div><div><small>状态</small><StatusBadge value={statusLabel(detail.job.status)} /></div><div><small>进度</small><strong>{detail.job.progress}%</strong></div><div><small>适配器</small><Badge tone="warning">{detail.job.adapter_code ? labelForCode(detail.job.adapter_code, "已配置适配器") : "未配置适配器"}</Badge></div></CardContent></Card>
      <div className="trusted-mpc-grid"><Card className="trusted-topology-card"><CardHeader><SurfaceHeader title="参与方拓扑" description="仅展示真实任务参与方登记" action={<Network size={16} />} /></CardHeader><CardContent>{detail.participants.length ? <><div className="trusted-topology">{detail.participants.map((party, index) => <div className={`trusted-party-card trusted-party-party-${index + 1}`} key={party.org_id}><span className="trusted-party-icon"><Cpu size={16} /></span><strong>{party.organization?.org_name || party.org_id}</strong><small>{ROLE_IN_TASK_LABELS[party.role_in_task] || labelForCode(party.role_in_task, "任务参与方")}</small><code>{party.org_id}</code><StatusBadge value={party.data_status || "未登记"} /></div>)}<div className="trusted-mpc-core"><span><Network size={18} /></span><strong>受控计算节点</strong><small>{detail.external_execution.adapter_code ? labelForCode(detail.external_execution.adapter_code, "已配置适配器") : "未配置适配器"}</small><Badge tone={capabilityTone(detail.external_execution.capability_state)}>{capabilityLabel(detail.external_execution.capability_state)}</Badge></div></div><div className="trusted-topology-legend"><span><i className="trusted-dot trusted-dot-success" />真实登记</span><span><i className="trusted-dot trusted-dot-warning" />能力边界</span></div></> : <RemoteState empty emptyLabel="当前任务未登记参与方；跨域执行已阻断" />}</CardContent></Card><Card className="trusted-mpc-log-card"><CardHeader><SurfaceHeader title="实时计算日志" description="通过游标轮询真实日志接口" action={<TerminalSquare size={16} />} /></CardHeader><CardContent><div className="trusted-log-stream trusted-log-compact">{detail.job.logs.map((line, index) => <div key={`job-${index}-${line}`}><time>任务日志</time><code>{line}</code></div>)}{logItems.map((event) => <div key={`event-${event.sequence_no}`}><time>#{event.sequence_no}</time><code>{event.detail}</code><CheckCircle2 size={13} /></div>)}{!detail.job.logs.length && !logItems.length && <span className="trusted-muted">暂无日志记录</span>}</div><div className="trusted-mpc-progress"><Progress value={detail.job.progress} label={`计算进度 ${detail.job.progress}%`} /><span>{detail.job.duration_ms ? `${detail.job.duration_ms} 毫秒` : "持续时间未登记"}</span></div><div className="trusted-submit-actions"><Button variant={logsEnabled ? "primary" : "secondary"} disabled={!detail.allowed_actions?.includes("poll_logs")} title={detail.allowed_actions?.includes("poll_logs") ? "开启/关闭真实游标轮询" : "后端未返回日志轮询能力"} onClick={() => setLogsEnabled((value) => !value)}><Radio size={14} />{logsEnabled ? "停止日志订阅" : "订阅本地日志"}</Button>{logError && <Button variant="link" size="sm" onClick={() => { setLogError(""); setLogRetryNonce((value) => value + 1); setLogsEnabled(true); }}>重试日志</Button>}</div></CardContent></Card></div>
      <Card><CardHeader><SurfaceHeader title="参与方回执" description="回执哈希与链锚定状态来自真实证据记录；没有链上交易哈希时保持未锚定" action={<Link2 size={16} />} /></CardHeader><CardContent><div className="trusted-receipt-table">{detail.receipts.map((receipt) => <div key={receipt.evidence_id}><span><strong>{STAGE_LABELS[receipt.stage] || labelForCode(receipt.stage, "证据阶段")}</strong><small>{labelForCode(receipt.biz_type, "业务对象")} · {receipt.biz_id}</small></span><code>{shortHash(receipt.evidence_hash)}</code><span>{receipt.tx_hash ? <code>{shortHash(receipt.tx_hash)}</code> : <Badge tone="warning">未锚定</Badge>}</span><StatusBadge value={receipt.status} /><ArrowRight size={14} /></div>)}{!detail.receipts.length && <RemoteState empty emptyLabel="暂无真实计算回执" />}</div></CardContent></Card>
      <Card><CardHeader><SurfaceHeader title="计算控制" description="仅在后端明确开放可用动作时提供写操作" /></CardHeader><CardContent><div className="trusted-submit-actions"><Button variant="secondary" busy={controlBusy === "retry"} disabled={!detail.allowed_actions?.includes("retry") || Boolean(controlBusy)} title={detail.allowed_actions?.includes("retry") ? "执行后端重试动作" : detail.action_reasons?.retry || "后端未返回重试能力"} onClick={() => runControl("retry")}>重试计算</Button><Button variant="danger" busy={controlBusy === "cancel"} disabled={!detail.allowed_actions?.includes("cancel") || Boolean(controlBusy)} title={detail.allowed_actions?.includes("cancel") ? "执行后端取消动作" : detail.action_reasons?.cancel || "后端未返回取消能力"} onClick={() => runControl("cancel")}>取消计算</Button><span className="trusted-muted">{controlError || detail.action_reasons?.retry || detail.action_reasons?.cancel || "当前没有可执行控制动作"}</span><span className="trusted-muted">可信执行环境：{detail.external_execution.tee_attestation === "VERIFIED" ? "已提供远程证明" : "未配置"} · 跨域参与方：{detail.external_execution.cross_domain_participants.length}</span></div></CardContent></Card>
    </>}
  </PageFrame>;
}
