import { useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, Database, FileCheck2, Gavel, Network, Play, RefreshCw, ShieldCheck, UsersRound } from "lucide-react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, post, prepareIdempotencyKey, type IdempotencyKeyRecord } from "../api";
import { useAuth } from "../auth";
import { AmountText, Button, ConfirmDialog, DateTimeText, EmptyState, ErrorState, IdText, LoadingState, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { taskNextAction, taskStatusLabel, trustedChain } from "../settlement-model";
import { ALGORITHM_LABELS, type JsonRecord, type ResultConfirmationCommand } from "../types";

type DetailData = {
  task: JsonRecord;
  uploads: JsonRecord[];
  agreements: JsonRecord[];
  jobs: JsonRecord[];
  results: JsonRecord[];
  evidence: JsonRecord[];
  reports: JsonRecord[];
  timeline: JsonRecord | null;
};

export function SettlementDetailPage() {
  const { taskId = "" } = useParams();
  const location = useLocation();
  const { session } = useAuth();
  const role = session!.user.role_code;
  const orgId = session!.user.org_id;
  const canReview = ["EXCHANGE", "REGULATOR", "ADMIN"].includes(role);
  const locationState = location.state as { created?: boolean; etag?: string } | null;
  const taskEtagRef = useRef<string | undefined>(locationState?.etag);
  const commandKeysRef = useRef<Record<string, IdempotencyKeyRecord>>({});
  const [view, setView] = useState<"business" | "technical">("business");
  const [confirmAction, setConfirmAction] = useState<"run" | "confirm" | null>(null);
  const [actionError, setActionError] = useState("");
  const { data, loading, refreshing, error, reload } = useRemote(async (signal): Promise<DetailData> => {
    const options = { signal, cache: "no-store" as RequestCache };
    const taskOptions = {
      ...options,
      onResponseMetadata: (metadata: { etag?: string }) => {
        if (metadata.etag) taskEtagRef.current = metadata.etag;
      },
    };
    const [task, uploads, agreements, jobs, results, evidence, reports, timeline] = await Promise.all([
      api<JsonRecord>(`/settlement/tasks/${taskId}`, taskOptions),
      api<JsonRecord[]>(`/data/uploads?task_id=${encodeURIComponent(taskId)}`, options),
      api<JsonRecord[]>(`/data/agreements?task_id=${encodeURIComponent(taskId)}`, options),
      api<JsonRecord[]>(`/privacy/jobs?task_id=${encodeURIComponent(taskId)}`, options),
      api<JsonRecord[]>(`/settlement/results?task_id=${encodeURIComponent(taskId)}`, options),
      api<JsonRecord[]>(`/chain/evidence?task_id=${encodeURIComponent(taskId)}`, options),
      canReview ? api<JsonRecord[]>("/audit/reports", options).then((items) => items.filter((item) => item.task_id === taskId)) : Promise.resolve([]),
      canReview ? api<JsonRecord>(`/audit/timeline/${taskId}`, options) : Promise.resolve(null),
    ]);
    return { task, uploads, agreements, jobs, results, evidence, reports, timeline };
  }, [taskId, canReview]);

  const ownResult = useMemo(() => data?.results.find((item) => item.org_id === orgId), [data?.results, orgId]);
  if (loading) return <LoadingState label="正在读取结算任务" variant="page" />;
  if (error || !data) return <ErrorState message={error || "结算任务加载失败"} retry={reload} />;

  const task = data.task;
  const nextAction = taskNextAction(task, role, orgId);
  const chain = trustedChain(task, { ...data, viewerRole: role });
  const ttcState = String(task.ttc?.state || task.ttc_state || "");
  const cannotRunTtc = ["REJECTED", "CANCELLED", "EXPIRED", "ARCHIVED"].includes(ttcState);
  const allowedActions = Array.isArray(task.allowed_actions) ? task.allowed_actions : [];
  const backendAllowsRun = !task.ttc?.authoritative || allowedActions.some((action: string) => ["RUN_SETTLEMENT", "RETRY_SETTLEMENT"].includes(action));
  const runnableBusinessState = task.status === "READY" || allowedActions.includes("RUN_SETTLEMENT");
  const canRun = role === "EXCHANGE" && runnableBusinessState && task.readiness?.preflight_passed && !cannotRunTtc && backendAllowsRun;
  const canConfirm = ["GENERATOR", "RETAILER"].includes(role) && ownResult?.confirm_status === "UNCONFIRMED";
  const verification = task.verification_profile || {};
  const summaryResult = data.results.find((item) => item.result_scope === "SUMMARY");

  async function executeAction() {
    setActionError("");
    try {
      if (confirmAction === "run") {
        const payload = { compute_mode: "LOCAL_CONTROLLED", algorithm_code: "CONTROLLED_SETTLEMENT_V1" };
        const fingerprint = JSON.stringify({ taskId, payload, etag: taskEtagRef.current });
        commandKeysRef.current.run = prepareIdempotencyKey(commandKeysRef.current.run, `settlement-run:${taskId}`, fingerprint);
        await post(`/settlement/tasks/${taskId}/run`, payload, {
          idempotencyKey: commandKeysRef.current.run.key,
          ifMatch: taskEtagRef.current,
          onResponseMetadata: (metadata) => {
            if (metadata.etag) taskEtagRef.current = metadata.etag;
          },
        });
      } else if (confirmAction === "confirm" && ownResult) {
        const payload: ResultConfirmationCommand = { decision: "APPROVE", opinion: "同意结算结果" };
        const fingerprint = JSON.stringify({ resultId: ownResult.result_id, resultHash: ownResult.result_hash, payload, etag: taskEtagRef.current });
        commandKeysRef.current.confirm = prepareIdempotencyKey(commandKeysRef.current.confirm, `result-confirm:${ownResult.result_id}`, fingerprint);
        await post(`/results/${ownResult.result_id}/confirm`, payload, {
          idempotencyKey: commandKeysRef.current.confirm.key,
          ifMatch: taskEtagRef.current,
          onResponseMetadata: (metadata) => {
            if (metadata.etag) taskEtagRef.current = metadata.etag;
          },
        });
      }
      setConfirmAction(null);
      await reload();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "操作失败");
      setConfirmAction(null);
    }
  }

  return (
    <>
      <PageHeader
        title={task.task_name}
        actions={<>
          <Link className="button button-secondary" to="/settlements"><ArrowLeft size={16} />返回任务中心</Link>
          <Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>
          {canRun && <Button icon={Play} variant="primary" onClick={() => setConfirmAction("run")}>启动结算</Button>}
          {canConfirm && <Button icon={CheckCircle2} variant="primary" onClick={() => setConfirmAction("confirm")}>确认本方结果</Button>}
        </>}
      />

      {Boolean(locationState?.created) && <Notice tone="success">结算任务已创建，当前状态与待办如下。</Notice>}
      {actionError && <Notice tone="warning">{actionError}</Notice>}

      <Surface className="task-identity-surface">
        <div className="task-identity-row">
          <div><span>业务状态</span><StatusTag value={task.status} label={taskStatusLabel(task.status)} /></div>
          <div><span>当前环节</span><strong>{task.current_stage || "—"}</strong></div>
          <div><span>交易批次</span><IdText value={task.trade_batch_no} /></div>
          <div><span>结算周期</span><strong>{task.period_start} 至 {task.period_end}</strong></div>
          <div><span>风险等级</span><StatusTag value={task.risk_level} /></div>
          <div><span>任务编号</span><IdText value={task.capsule_id || task.task_id} /></div>
          <div><span>发起机构</span><strong>{task.creator_org_name || "—"}</strong></div>
          <div><span>当前责任方</span><strong>{nextAction.responsible}</strong></div>
          <div><span>更新时间</span><DateTimeText value={task.updated_at || task.created_at} /></div>
        </div>
        <div className="task-next-action"><span>下一步</span><strong>{nextAction.label}</strong><em>{nextAction.responsible}</em>{nextAction.blocker && <small>{nextAction.blocker}</small>}</div>
      </Surface>

      {task.blocking_conditions?.length > 0 && <div className="task-blockers" role="alert"><AlertTriangle size={19} /><div><strong>当前阻断项</strong><ul>{task.blocking_conditions.map((item: string) => <li key={item}>{item}</li>)}</ul></div></div>}

      <Surface title="可信执行链" meta="按任务事实生成">
        <ol className="trusted-chain">
          {chain.map((item, index) => <li key={item.code} className={`chain-${item.state}`}><span className="chain-index">{index + 1}</span><Link to={item.path}><strong>{item.title}</strong><small>{item.detail}</small><span className="chain-metadata"><span>执行主体：{item.owner}</span><span>完成时间：{item.completedAt ? <DateTimeText value={item.completedAt} /> : "未记录"}</span><span>关联证据：{item.evidenceCount} 项</span><span>异常：{item.abnormal ? "是" : "未关联"}</span></span></Link><StatusTag value={item.state === "complete" ? "PASSED" : item.state === "blocked" ? "BLOCKED" : item.state === "current" ? "CURRENT" : "PENDING"} label={{ complete: "已完成", current: "当前", blocked: "受阻", pending: "待处理" }[item.state]} /></li>)}
        </ol>
      </Surface>

      <div className="detail-view-tabs" role="tablist" aria-label="任务详情视图">
        <button type="button" role="tab" aria-selected={view === "business"} className={view === "business" ? "active" : ""} onClick={() => setView("business")}>业务视图</button>
        <button type="button" role="tab" aria-selected={view === "technical"} className={view === "technical" ? "active" : ""} onClick={() => setView("technical")}>技术详情</button>
      </div>

      {view === "business" ? <div className="task-detail-grid">
        <Surface title="参与主体" className="span-2">
          <div className="participant-records">{task.participants?.map((participant: JsonRecord) => <div key={participant.participant_id || participant.org_id}><UsersRound size={17} /><div><strong>{participant.org_name || participant.org_id}</strong><span>{participant.role_in_task === "GENERATOR" ? "发电企业" : "售电企业"}</span></div><StatusTag value={participant.confirm_status} /></div>)}</div>
        </Surface>
        <Surface title="数据与授权">
          <AssociationList icon={Database} empty="尚无任务数据引用" items={data.uploads.map((item) => ({ id: item.upload_id, title: item.label, meta: `${assetTypeLabel(item.asset_type)} · ${item.validation_status === "PASSED" ? "质量校验通过" : "待完成质量校验"}`, path: `/data-space?task_id=${taskId}` }))} />
          <AssociationList icon={ShieldCheck} empty="尚未生成用途授权" items={data.agreements.map((item) => ({ id: item.agreement_id, title: `${purposeLabel(item.requested_purpose)} · ${item.state === "ACTIVE" ? "已授权" : "待授权"}`, meta: `${item.provider_org_name || item.provider_org_id} → ${item.consumer_org_name || item.consumer_org_id}`, path: `/data-space?task_id=${taskId}` }))} />
        </Surface>
        <Surface title="规则与计算">
          <AssociationList icon={Gavel} empty="未绑定规则" items={task.rule ? [{ id: task.rule.rule_id, title: `${task.rule.rule_version} · ${task.rule.rule_name}`, meta: task.rule.status === "ACTIVE" ? "规则已锁定" : "规则尚未启用", path: `/rules?task_id=${taskId}` }] : []} />
          <AssociationList icon={Network} empty="尚未执行计算" items={data.jobs.map((item) => ({ id: item.job_id, title: `${ALGORITHM_LABELS[item.algorithm_code] || "受控结算计算"} · ${item.status === "SUCCESS" ? "已完成" : "执行中"}`, meta: "输出范围：聚合结算结果", path: `/compute?task_id=${taskId}` }))} />
        </Surface>
        <Surface title="结算结果" id="business-summary">
          {summaryResult ? <div className="settlement-result-summary"><div><span>结算电量</span><strong>{summaryResult.result_json?.settlement_energy_mwh ?? "—"} MWh</strong></div><div><span>应结金额</span><AmountText value={summaryResult.result_json?.payable_amount_yuan} /></div><div><span>结果摘要</span><IdText value={summaryResult.result_hash} /></div></div> : <EmptyState title="尚未生成结算结果" />}
          {data.results.length > 0 && <Link className="section-link" to={`/results?task_id=${taskId}`}>查看全部结果 <FileCheck2 size={14} /></Link>}
        </Surface>
        <Surface title="证据与审计">
          <AssociationList icon={ShieldCheck} empty="尚无证据记录" items={data.evidence.map((item) => ({ id: item.evidence_id, title: `${evidenceStageLabel(item.stage)} · ${evidenceTypeLabel(item.biz_type)}`, meta: `台账状态：${item.status === "VALID" ? "有效" : item.status === "CONFIRMED" ? "已确认" : "待核验"}`, path: `/evidence?task_id=${taskId}` }))} />
          {canReview && <div className="section-links"><Link to={`/audit?task_id=${taskId}`}>审计复核</Link><Link to={`/reports?task_id=${taskId}`}>审计报告（{data.reports.length}）</Link><Link to={`/anomalies?task_id=${taskId}`}>风险事件（{task.open_anomaly_count || 0}）</Link></div>}
        </Surface>
      </div> : <div className="task-detail-grid technical-detail-grid">
        <Surface title="执行边界">
          <dl className="technical-facts">
            <div><dt>执行适配器</dt><dd>{verification.compute_adapter || task.compute_summary?.adapter_code || "NOT_PROVIDED"}</dd></div>
            <div><dt>执行环境</dt><dd>{data.jobs[0]?.execution_attestation_json?.runtime || "NOT_PROVIDED"}</dd></div>
            <div><dt>远程证明</dt><dd><StatusTag value={data.jobs[0]?.execution_attestation_json?.attestation_status || "NOT_PROVIDED"} /></dd></div>
            <div><dt>接口返回原始记录</dt><dd>{verification.api_raw_records_returned === false ? "否" : "未记录"}</dd></div>
            <div><dt>跨域不出域证明</dt><dd><StatusTag value={verification.cross_domain_non_export_verified ? "PASSED" : "UNVERIFIED"} /></dd></div>
            <div><dt>隐私协议证明</dt><dd><StatusTag value={verification.privacy_compute_protocol_verified ? "PASSED" : "UNVERIFIED"} /></dd></div>
          </dl>
        </Surface>
        <Surface title="哈希与回执">
          <dl className="technical-facts">
            <div><dt>规则哈希</dt><dd><IdText value={task.rule?.rule_hash} /></dd></div>
            <div><dt>计算输出哈希</dt><dd><IdText value={task.compute_summary?.output_hash} /></dd></div>
            <div><dt>结果哈希</dt><dd><IdText value={summaryResult?.result_hash} /></dd></div>
            <div><dt>证据后端</dt><dd>{verification.evidence_ledger || "NOT_PROVIDED"}</dd></div>
            <div><dt>证据记录</dt><dd>{task.evidence_count || 0} 项</dd></div>
            <div><dt>最近更新</dt><dd><DateTimeText value={task.updated_at || task.created_at} /></dd></div>
          </dl>
        </Surface>
        {data.timeline && <Surface title="审计时间线" className="span-2"><div className="compact-timeline">{data.timeline.events?.map((item: JsonRecord, index: number) => <div key={`${item.reference}-${index}`}><span /><DateTimeText value={item.time} /><strong>{item.title}</strong><StatusTag value={item.status} /></div>)}</div></Surface>}
      </div>}

      <ConfirmDialog
        open={Boolean(confirmAction)}
        title={confirmAction === "run" ? "启动结算" : "确认本方结算结果"}
        objectName={task.task_name}
        currentState={taskStatusLabel(task.status)}
        consequence={confirmAction === "run" ? "系统将按当前数据承诺、授权协议和规则版本执行本地受控结算，生成结果与证据记录。" : "确认后将记录本主体签名；双方均确认后，任务进入已完成状态。"}
        confirmLabel={confirmAction === "run" ? "确认启动" : "确认结果"}
        onCancel={() => setConfirmAction(null)}
        onConfirm={executeAction}
      />
    </>
  );
}

function assetTypeLabel(value: unknown) {
  return ({ GENERATION_DATA: "发电计量数据", RETAIL_DATA: "售电履约数据", USER_LOAD_CURVE: "用户负荷数据" } as Record<string, string>)[String(value)] || "任务数据";
}

function purposeLabel(value: unknown) {
  return ({ POWER_SETTLEMENT: "电力结算", MARKET_SETTLEMENT: "市场结算" } as Record<string, string>)[String(value)] || "任务约定用途";
}

function evidenceStageLabel(value: unknown) {
  return ({ PRE_AUTH: "算前授权", COMPUTE: "算中回执", POST_RESULT: "算后结果", AUDIT: "审计归档" } as Record<string, string>)[String(value)] || "执行阶段";
}

function evidenceTypeLabel(value: unknown) {
  return ({ AUTHORIZATION_BUNDLE: "授权凭证", COMPUTE_RECEIPT: "计算回执", SETTLEMENT_RESULT: "结算结果", RESULT_CONFIRMATION: "结果确认", AUDIT_REPORT: "审计报告" } as Record<string, string>)[String(value)] || "证据记录";
}

function AssociationList({ icon: Icon, items, empty }: { icon: React.ElementType; items: Array<{ id: string; title: string; meta: string; path: string }>; empty: string }) {
  if (!items.length) return <EmptyState title={empty} />;
  return <div className="association-list">{items.map((item) => <Link key={item.id} to={item.path}><Icon size={16} /><div><strong>{item.title}</strong><span>{item.meta}</span></div><IdText value={item.id} length={7} copyable={false} /></Link>)}</div>;
}
