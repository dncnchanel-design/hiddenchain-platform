import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, Check, ClipboardList, FileClock, ListChecks, Logs, ShieldCheck } from "lucide-react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, formatDate, prepareIdempotencyKey, type IdempotencyKeyRecord } from "../../../api";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, Dialog, DialogContent, DialogDescription, DialogTitle, Input, Progress, RemoteState, Select, StatusBadge, SurfaceHeader, Timeline } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { loadTtc, loadTtcEvents, loadTtcList, transitionTtc, type TtcDetailPayload, type TtcEvent, type TtcListPayload } from "../trusted-space-api";
import { ACTION_LABELS, TTC_STATE_LABELS, labelForCode } from "../../../types";
import { routeForView, trustedEntityId } from "../types";

function stateLabel(value: string) {
  return ({ INIT: "初始化", IDENTITY_VERIFY: "身份校验", DATA_AUTH: "数据授权", RULE_FROZEN: "规则冻结", COMPUTE_EXEC: "受控计算", RESULT_CONFIRM: "结果确认", EVIDENCE_ANCHOR: "证据锚定", ARCHIVED: "已归档", HUMAN_REVIEW: "人工复核", REWORK: "返工", INTERRUPTED: "已中断", CANCELLED: "已取消" } as Record<string, string>)[value] || TTC_STATE_LABELS[value] || labelForCode(value, "未知状态");
}
function statusLabel(value: string) {
  return ({ RUNNING: "执行中", PENDING: "待开始", SUCCEEDED: "已完成", ACTIVE: "已启用", COMPLETED: "已完成" } as Record<string, string>)[value] || labelForCode(value, "未知状态");
}

function eventTimeline(detail: TtcDetailPayload) {
  return detail.transitions.map((event, index) => ({
    id: event.transition_id,
    label: stateLabel(event.to_state),
    detail: `${ACTION_LABELS[event.trigger_code] || labelForCode(event.trigger_code, "登记动作")} · ${event.reason || "无理由"}`,
    time: formatDate(event.occurred_at),
    state: index === detail.transitions.length - 1 && !["ARCHIVED", "CANCELLED", "INTERRUPTED"].includes(detail.task.ttc_state) ? "current" as const : "done" as const,
  }));
}

function eventText(event: TtcEvent) {
  const details = event.details || {};
  const detailText = typeof details.reason === "string" ? details.reason : typeof details.action_code === "string" ? details.action_code : "真实事件";
  return `${labelForCode(event.kind, "任务事件")} · ${stateLabel(event.state || "")} · ${ACTION_LABELS[detailText] || labelForCode(detailText, "真实事件")}`;
}

export function TtcPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const routeTaskId = trustedEntityId(location.pathname, "ttc");
  const listPage = Math.max(1, Number(searchParams.get("page") || "1") || 1);
  const listStatus = searchParams.get("status") || "";
  const listRemote = useRemote<TtcListPayload | null>(
    (signal) => routeTaskId ? Promise.resolve(null) : loadTtcList({ page: listPage, pageSize: 12, status: listStatus || undefined }, signal),
    [routeTaskId, listPage, listStatus],
  );
  const selectedTaskId = routeTaskId;
  const remote = useRemote<TtcDetailPayload | null>((signal) => selectedTaskId ? loadTtc(selectedTaskId, signal) : Promise.resolve(null), [selectedTaskId]);
  const detail = remote.data;
  const listPayload = listRemote.data;
  const listItems = listPayload?.items ?? [];
  const [logsOpen, setLogsOpen] = useState(false);
  const [logRetryNonce, setLogRetryNonce] = useState(0);
  const [logItems, setLogItems] = useState<TtcEvent[]>([]);
  const [logError, setLogError] = useState("");
  const [logLoading, setLogLoading] = useState(false);
  const cursorRef = useRef<string | undefined>(undefined);
  const [transitionReason, setTransitionReason] = useState("");
  const [transitionError, setTransitionError] = useState("");
  const [transitionBusy, setTransitionBusy] = useState(false);
  const idempotencyKeys = useRef<Record<string, IdempotencyKeyRecord>>({});

  useEffect(() => {
    if (!logsOpen || !selectedTaskId) return undefined;
    let active = true;
    let timer: number | undefined;
    const controller = new AbortController();
    cursorRef.current = undefined;
    const poll = async () => {
      if (!active) return;
      setLogLoading(true);
      try {
        const payload = await loadTtcEvents(selectedTaskId, { cursor: cursorRef.current, limit: 50 }, controller.signal);
        if (!active) return;
        setLogItems((previous) => {
          const known = new Set(previous.map((item) => item.event_id));
          return [...previous, ...payload.items.filter((item) => !known.has(item.event_id))];
        });
        const offset = Number(cursorRef.current || 0) || 0;
        cursorRef.current = payload.next_cursor || String(offset + payload.items.length);
        setLogError("");
        timer = window.setTimeout(() => void poll(), 1_500);
      } catch (error) {
        if (!active || (error instanceof DOMException && error.name === "AbortError") ) return;
        setLogError(error instanceof ApiError ? error.message : "实时日志读取失败");
        timer = window.setTimeout(() => void poll(), 4_000);
      } finally {
        if (active) setLogLoading(false);
      }
    };
    void poll();
    return () => {
      active = false;
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [logRetryNonce, logsOpen, selectedTaskId]);

  const timeline = useMemo(() => detail ? eventTimeline(detail) : [], [detail]);
  const transitionActions = (detail?.allowed_actions || []).filter((action) => action.startsWith("transition:"));

  async function runTransition(target: string) {
    if (!detail || !selectedTaskId || !transitionReason.trim()) {
      setTransitionError("执行状态动作前请填写理由。");
      return;
    }
    setTransitionBusy(true);
    setTransitionError("");
    const fingerprint = `${selectedTaskId}:${detail.task.state_version}:${target}:${transitionReason.trim()}`;
    const key = prepareIdempotencyKey(idempotencyKeys.current[fingerprint], "ttc-transition", fingerprint);
    idempotencyKeys.current[fingerprint] = key;
    try {
      await transitionTtc(selectedTaskId, { to_state: target, trigger: "TRUSTED_SPACE_UI", reason: transitionReason.trim(), attempt_id: detail.attempts.at(-1)?.attempt_id }, { ifMatch: `"${detail.task.state_version}"`, idempotencyKey: key.key });
      setTransitionReason("");
      await remote.reload();
    } catch (error) {
      setTransitionError(error instanceof ApiError ? error.message : "状态转换失败，请刷新后重试");
    } finally {
      setTransitionBusy(false);
    }
  }

  function updateListParam(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.set("page", "1");
    setSearchParams(next);
  }

  const canGoPrevious = listPage > 1;
  const canGoNext = Boolean(listPayload && listPage * listPayload.page_size < listPayload.total);
  return <PageFrame title="可信任务详情" description={detail ? `沿状态机追踪真实任务 ${detail.task.task_id} 的主体、授权、受控计算和证据节点。` : "读取真实可信任务与状态机记录。"} back={routeForView("workbench")} action={<>{detail && <StatusBadge value={statusLabel(detail.task.status)} />}<Button variant="secondary" disabled={!selectedTaskId} onClick={() => setLogsOpen(true)}><Logs size={14} />实时日志</Button></>}>
    {!routeTaskId && listRemote.loading && !listPayload && <RemoteState loading />}
    {!routeTaskId && listRemote.error && !listPayload && <RemoteState error={listRemote.error} onRetry={() => void listRemote.reload()} />}
    {!routeTaskId && listPayload && <>
      <Card className="trusted-filter-card"><CardContent><div className="trusted-filter-row"><Select label="状态筛选" value={listStatus} onChange={(event) => updateListParam("status", event.target.value)} options={[{ value: "", label: "全部状态" }, { value: "RUNNING", label: "执行中" }, { value: "PENDING", label: "待开始" }, { value: "HUMAN_REVIEW", label: "人工复核" }, { value: "COMPUTE_EXEC", label: "受控计算" }, { value: "SUCCEEDED", label: "已完成" }, { value: "FAILED", label: "失败" }, { value: "ARCHIVED", label: "已归档" }]} /><span className="trusted-filter-summary">共 {listPayload.total} 条真实任务</span><Button variant="secondary" size="sm" onClick={() => void listRemote.reload()} disabled={listRemote.refreshing}>刷新</Button></div></CardContent></Card>
      {listPayload.empty_state && <RemoteState empty emptyLabel="当前主体暂无可见 TTC 任务" />}
      {!listPayload.empty_state && <Card className="trusted-table-surface"><CardHeader><SurfaceHeader title="可信任务列表" description="先选择真实任务，再进入详情；页面不会自动替你选中第一条。" /></CardHeader><CardContent><div className="trusted-task-list">{listItems.map((task) => <button className="trusted-task-row" key={task.task_id} type="button" onClick={() => navigate(routeForView("ttc", task.task_id))}><span className="trusted-task-icon"><Activity size={15} /></span><span className="trusted-task-copy"><strong>{task.task_name}</strong><small><code>{task.task_id}</code> · {labelForCode(task.current_stage, "") || stateLabel(task.ttc_state)}</small></span><span className="trusted-task-state"><StatusBadge value={statusLabel(task.status)} /><small>V{task.state_version}</small></span></button>)}</div><div className="trusted-step-footer" aria-label="可信任务分页"><span>第 {listPage} 页 · 共 {listPayload.total} 条</span><div><Button variant="secondary" size="sm" disabled={!canGoPrevious || listRemote.loading} onClick={() => updateListParam("page", String(listPage - 1))}>上一页</Button><Button variant="secondary" size="sm" disabled={!canGoNext || listRemote.loading} onClick={() => updateListParam("page", String(listPage + 1))}>下一页</Button></div></div></CardContent></Card>}
      {listRemote.refreshing && <div className="trusted-inline-status" role="status">正在刷新可信任务列表…</div>}
    </>}
    {routeTaskId && remote.loading && !detail && <RemoteState loading />}
    {routeTaskId && remote.error && !detail && <RemoteState error={remote.error} onRetry={() => void remote.reload()} />}
    {detail && <>
      <Card className="trusted-task-banner"><CardContent><div><small>任务编号</small><strong><code>{detail.task.task_id}</code></strong></div><div><small>任务名称</small><strong>{detail.task.task_name}</strong></div><div><small>当前状态</small><strong>{stateLabel(detail.task.ttc_state)}</strong></div><div><small>当前尝试</small><strong>{detail.task.current_attempt ?? "—"}</strong></div><div><small>状态版本</small><strong><code>V{detail.task.state_version}</code></strong></div><div><small>能力来源</small><Badge tone="warning">{labelForCode(detail.source_of_truth, "结算任务记录")}</Badge></div></CardContent></Card>
      <Card className="trusted-state-card"><CardHeader><SurfaceHeader title="状态轨迹" description="只展示后端持久化的状态转移，不补造未发生节点" action={<Badge tone="info" dot>{stateLabel(detail.task.ttc_state)}</Badge>} /></CardHeader><CardContent>{timeline.length ? <div className="trusted-state-tracker">{timeline.map((event, index) => <div className={`trusted-state-node trusted-state-${event.state}`} key={event.id}><span className="trusted-state-marker">{event.state === "done" ? <Check size={13} /> : <Activity size={13} />}</span><strong>{event.label}</strong><small>{event.time}</small>{index < timeline.length - 1 && <i className="trusted-state-connector" />}</div>)}</div> : <RemoteState empty emptyLabel="暂无状态转移记录" />}</CardContent></Card>
      <div className="trusted-ttc-grid"><Card><CardHeader><SurfaceHeader title="节点事件" description="真实状态转移与时间戳" action={<FileClock size={16} />} /></CardHeader><CardContent>{timeline.length ? <Timeline events={timeline} /> : <RemoteState empty emptyLabel="暂无节点事件" />}</CardContent></Card><Card><CardHeader><SurfaceHeader title="任务属性" description="事实字段、规则冻结与执行快照" action={<ClipboardList size={16} />} /></CardHeader><CardContent><dl className="trusted-definition-list"><div><dt>任务类型</dt><dd>{labelForCode(detail.task.capsule_id, "—")}</dd></div><div><dt>当前阶段</dt><dd>{labelForCode(detail.task.current_stage, "") || stateLabel(detail.task.ttc_state)}</dd></div><div><dt>执行快照</dt><dd><code>{detail.task.execution_snapshot_id || "未登记"}</code></dd></div><div><dt>快照哈希</dt><dd><code>{detail.task.execution_snapshot_hash || "—"}</code></dd></div><div><dt>尝试记录</dt><dd>{detail.attempts.length}</dd></div><div><dt>参与方</dt><dd>{detail.participants.length}</dd></div></dl><Progress value={detail.task.phase_progress_estimate?.value ?? 0} label={detail.task.phase_progress_estimate?.label || "阶段估算（非实时执行进度）"} /><small className="trusted-muted">来源：{labelForCode(detail.task.phase_progress_estimate?.source, "状态阶段估算")}</small></CardContent></Card></div>
      <Card><CardHeader><SurfaceHeader title="当前责任" description="系统动作仅在后端明确返回可用动作时启用" action={<ListChecks size={16} />} /></CardHeader><CardContent><div className="trusted-next-action"><span className="trusted-next-icon"><ShieldCheck size={17} /></span><div><strong>{stateLabel(detail.task.ttc_state)}</strong><p>{detail.transitions.at(-1)?.reason || "暂无最近状态理由；前端不会自行推进状态。"}</p></div><div className="trusted-submit-actions">{transitionActions.map((action) => <Button key={action} variant="primary" busy={transitionBusy} onClick={() => void runTransition(action.slice("transition:".length))}>推进至 {stateLabel(action.slice("transition:".length))}</Button>)}{!transitionActions.length && <Button variant="secondary" disabled title="后端当前只返回查看权限，状态推进需由系统服务端完成">状态推进不可用</Button>}</div></div>{transitionActions.length > 0 && <div className="trusted-option-grid"><Input value={transitionReason} onChange={(event) => setTransitionReason(event.target.value)} placeholder="状态转移理由" aria-label="状态转移理由" />{transitionError && <p className="trusted-muted" role="alert">{transitionError}</p>}</div>}</CardContent></Card>
    </>}
    <Dialog open={logsOpen} onOpenChange={setLogsOpen}><DialogContent className="energy-log-dialog"><DialogTitle>实时任务日志</DialogTitle><DialogDescription>打开后轮询真实任务事件；关闭即停止请求。</DialogDescription>{logLoading && !logItems.length && <RemoteState loading />}{logError && <RemoteState error={logError} onRetry={() => { setLogError(""); setLogRetryNonce((value) => value + 1); }} />}{!logError && !logLoading && !logItems.length && <RemoteState empty emptyLabel="暂无实时事件" />}<div className="trusted-log-stream">{logItems.map((event) => <div key={event.event_id}><time>{formatDate(event.occurred_at)}</time><code>{eventText(event)}</code></div>)}</div><Button variant="secondary" onClick={() => setLogsOpen(false)}>关闭</Button></DialogContent></Dialog>
  </PageFrame>;
}
