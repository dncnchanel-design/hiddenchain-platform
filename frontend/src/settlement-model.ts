import {
  ALGORITHM_LABELS,
  TTC_ABNORMAL_STATES,
  type JsonRecord,
  type RoleCode,
  type TaskNextAction,
} from "./types";

export type TaskTab = "todo" | "created" | "running" | "exception" | "completed";
export type TaskTone = "default" | "blue" | "green" | "amber" | "red";
export type ChainState = "complete" | "current" | "blocked" | "pending";
export type TrustedChainContext = {
  uploads?: JsonRecord[];
  agreements?: JsonRecord[];
  jobs?: JsonRecord[];
  results?: JsonRecord[];
  evidence?: JsonRecord[];
  viewerRole?: RoleCode;
};
export type TrustedChainStep = {
  code: string;
  title: string;
  state: ChainState;
  detail: string;
  owner: string;
  completedAt?: string | null;
  evidenceCount: number;
  abnormal: boolean;
  path: string;
};
export type TaskActionView = {
  code: string;
  label: string;
  responsible: string;
  blocker: string;
  blocked: boolean;
  reasons: string[];
  authoritative: boolean;
};

type NormalizedTransition = {
  attemptId: string;
  attemptNo: number;
  sequenceNo: number;
  fromState: string | null;
  toState: string;
  triggerCode: string;
  transitionHash: string;
  occurredAt: string | null;
  actorDid: string | null;
  agentDid: string | null;
  reason: string | null;
  evidenceRefs: string[];
  sourceIndex: number;
};

const TTC_STATE_LABELS: Record<string, string> = {
  INIT: "任务初始化",
  IDENTITY_VERIFIED: "身份验证通过",
  DATA_AUTHORIZED: "数据授权通过",
  RULE_FROZEN: "规则与执行快照冻结",
  COMPUTE_EXEC: "受控计算执行",
  RESULT_CONFIRM: "多方结果确认",
  AUDIT_GATE: "审计闸门",
  EVIDENCE_STAGE: "证据归集",
  EVIDENCE_ANCHOR: "证据锚定",
  ARCHIVED: "闭环归档",
  REJECTED: "可信任务已拒绝",
  FAILED: "可信任务执行失败",
  INTERRUPTED: "可信任务已中断",
  REWORK: "可信任务返工",
  HUMAN_REVIEW: "可信任务人工复核",
  ANCHOR_RETRY: "证据锚定重试",
  CANCELLED: "可信任务已取消",
  EXPIRED: "可信任务已过期",
};
const TTC_ABNORMAL_STATE_SET = new Set<string>(TTC_ABNORMAL_STATES);

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
}

function authoritativeNextAction(task: JsonRecord): TaskActionView | null {
  if (!isRecord(task.next_action)) return null;
  const code = nonEmptyString(task.next_action.code);
  const label = nonEmptyString(task.next_action.label);
  if (!code || !label) return null;
  const action = task.next_action as TaskNextAction & JsonRecord;
  const reasons = stringList(action.reasons);
  return {
    code,
    label,
    responsible: nonEmptyString(action.responsible) || "平台可信状态机",
    blocker: reasons[0] || "",
    blocked: Boolean(action.blocked),
    reasons,
    authoritative: true,
  };
}

function fallbackAction(label: string, responsible: string, blocker = "", code = "VIEW_PROGRESS"): TaskActionView {
  const reasons = blocker ? [blocker] : [];
  return { code, label, responsible, blocker, blocked: reasons.length > 0, reasons, authoritative: false };
}

function normalizeTransitions(value: unknown): NormalizedTransition[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, index) => {
    if (!isRecord(item)) return [];
    const toState = nonEmptyString(item.to_state);
    if (!toState) return [];
    const refs = stringList(item.evidence_refs ?? item.evidence_ids);
    const sequence = Number(item.sequence_no ?? item.sequence ?? index + 1);
    const attempt = Number(item.attempt_no ?? 1);
    const attemptNo = Number.isFinite(attempt) && attempt > 0 ? attempt : 1;
    return [{
      attemptId: nonEmptyString(item.attempt_id) || `attempt-${attemptNo}`,
      attemptNo,
      sequenceNo: Number.isFinite(sequence) ? sequence : index + 1,
      fromState: nonEmptyString(item.from_state),
      toState,
      triggerCode: nonEmptyString(item.trigger_code ?? item.trigger) || "STATE_TRANSITION",
      transitionHash: nonEmptyString(item.transition_hash) || "",
      occurredAt: nonEmptyString(item.occurred_at ?? item.transitioned_at ?? item.created_at),
      actorDid: nonEmptyString(item.actor_did),
      agentDid: nonEmptyString(item.agent_did),
      reason: nonEmptyString(item.reason),
      evidenceRefs: refs,
      sourceIndex: index,
    }];
  }).sort((left, right) => (
    left.attemptNo - right.attemptNo
    || left.sequenceNo - right.sequenceNo
    || left.sourceIndex - right.sourceIndex
  ));
}

function statePath(state: string, taskId: string, viewerRole?: RoleCode): string {
  const query = `?task_id=${encodeURIComponent(taskId)}`;
  const taskPath = `/settlements/${taskId}`;
  const canReview = viewerRole !== undefined && ["EXCHANGE", "REGULATOR", "ADMIN"].includes(viewerRole);
  if (state === "IDENTITY_VERIFIED") return viewerRole === "ADMIN" ? "/system" : taskPath;
  if (state === "DATA_AUTHORIZED") return `/data-space${query}`;
  if (state === "RULE_FROZEN") return canReview ? `/rules${query}` : taskPath;
  if (state === "COMPUTE_EXEC") return `/compute${query}`;
  if (state === "RESULT_CONFIRM") return `/results${query}`;
  if (state === "AUDIT_GATE") return canReview ? `/audit${query}` : taskPath;
  if (["EVIDENCE_STAGE", "EVIDENCE_ANCHOR", "ANCHOR_RETRY"].includes(state)) return `/evidence${query}`;
  return taskPath;
}

function authoritativeTrustedChain(task: JsonRecord, viewerRole?: RoleCode): TrustedChainStep[] | null {
  const transitions = normalizeTransitions(task.trusted_chain);
  if (!transitions.length) return null;
  const taskId = String(task.task_id || "");
  const taskTtcState = isRecord(task.ttc) ? nonEmptyString(task.ttc.state) : null;
  return transitions.map((transition, index) => {
    const last = index === transitions.length - 1;
    const abnormal = TTC_ABNORMAL_STATE_SET.has(transition.toState);
    const isArchived = (taskTtcState || transition.toState) === "ARCHIVED";
    const hashHint = transition.transitionHash ? ` · 转换哈希 ${transition.transitionHash.slice(0, 10)}…` : "";
    return {
      code: `${transition.toState}:${transition.attemptId}:${transition.attemptNo}:${transition.sequenceNo}:${transition.transitionHash || transition.sourceIndex}`,
      title: TTC_STATE_LABELS[transition.toState] || transition.toState,
      state: last && abnormal ? "blocked" : last && !isArchived ? "current" : "complete",
      detail: `${transition.reason || transition.triggerCode}${hashHint}`,
      owner: transition.agentDid || transition.actorDid || "平台可信状态机",
      completedAt: transition.occurredAt,
      evidenceCount: transition.evidenceRefs.length + (transition.transitionHash ? 1 : 0),
      abnormal,
      path: statePath(transition.toState, taskId, viewerRole),
    };
  });
}

export const TASK_STATUS_META: Record<string, { label: string; tone: TaskTone }> = {
  DRAFT: { label: "待准备", tone: "default" },
  READY: { label: "待执行", tone: "blue" },
  RUNNING: { label: "执行中", tone: "blue" },
  PENDING_CONFIRMATION: { label: "待双方确认", tone: "amber" },
  PARTIALLY_CONFIRMED: { label: "部分已确认", tone: "amber" },
  AUDITED: { label: "已完成", tone: "green" },
  EXCEPTION: { label: "异常", tone: "red" },
  REJECTED: { label: "已驳回", tone: "red" },
  INVALID: { label: "已失效", tone: "red" },
};

export function taskStatusLabel(status: unknown) {
  const value = String(status || "UNKNOWN");
  return TASK_STATUS_META[value]?.label || value;
}

function ownConfirmationPending(task: JsonRecord, role: RoleCode, orgId?: string) {
  if (!orgId || !["GENERATOR", "RETAILER"].includes(role)) return false;
  const required = Number(task.confirmation_summary?.required_count || 0);
  if (!required) return false;
  return !(task.confirmation_summary?.confirmed_org_ids || []).includes(orgId);
}

export function taskTabFor(task: JsonRecord, role: RoleCode, orgId?: string): TaskTab {
  const status = String(task.status || "");
  const ttcState = isRecord(task.ttc) ? nonEmptyString(task.ttc.state) : nonEmptyString(task.ttc_state);
  if ((ttcState !== null && TTC_ABNORMAL_STATE_SET.has(ttcState)) || ["EXCEPTION", "INVALID", "REJECTED"].includes(status) || Number(task.open_anomaly_count || 0) > 0 || task.risk_level === "HIGH") return "exception";
  if (status === "AUDITED") return "completed";
  if (status === "DRAFT" || (status === "READY" && role === "EXCHANGE") || ownConfirmationPending(task, role, orgId)) return "todo";
  if (task.creator_org_id === orgId && role === "EXCHANGE") return "created";
  return "running";
}

export function taskNextAction(task: JsonRecord, role: RoleCode, orgId?: string) {
  const backendAction = authoritativeNextAction(task);
  if (backendAction) return backendAction;
  const status = String(task.status || "");
  const blockers = Array.isArray(task.blocking_conditions) ? task.blocking_conditions.filter(Boolean) : [];
  if (["EXCEPTION", "INVALID", "REJECTED"].includes(status)) return fallbackAction("查看失败原因", "交易中心", blockers[0] || "任务执行未完成", "VIEW_FAILURE");
  if (Number(task.open_anomaly_count || 0) > 0 || task.risk_level === "HIGH") return fallbackAction("复核风险事件", "监管方", blockers[0] || "存在待处置风险", "REVIEW_RISK");
  if (status === "DRAFT") {
    if (!task.readiness?.preflight_passed) return fallbackAction("补齐算前条件", "数据提供方 / 交易中心", task.readiness?.preflight_blockers?.[0] || blockers[0] || "算前检查未通过", "COMPLETE_PREFLIGHT");
    return role === "EXCHANGE"
      ? fallbackAction("启动结算", "交易中心", "", "RUN_SETTLEMENT")
      : fallbackAction("等待交易中心启动", "交易中心", "", "WAIT_FOR_RUN");
  }
  if (status === "READY") return role === "EXCHANGE"
    ? fallbackAction("启动结算", "交易中心", "", "RUN_SETTLEMENT")
    : fallbackAction("等待交易中心启动", "交易中心", "", "WAIT_FOR_RUN");
  if (["PENDING_CONFIRMATION", "PARTIALLY_CONFIRMED"].includes(status)) {
    if (ownConfirmationPending(task, role, orgId)) return fallbackAction("确认本方结果", role === "GENERATOR" ? "发电企业" : "售电企业", "", "CONFIRM_RESULT");
    return fallbackAction("等待其余主体确认", "未确认参与方", blockers.find((item: string) => item.includes("未确认")) || "", "WAIT_FOR_CONFIRMATION");
  }
  if (status === "AUDITED") return fallbackAction("查看结算闭环", "已完成", "", "VIEW_ARCHIVE");
  return fallbackAction("查看当前进度", task.current_stage || "系统处理", blockers[0] || "", "VIEW_PROGRESS");
}

export function trustedChain(task: JsonRecord, context: TrustedChainContext = {}): TrustedChainStep[] {
  const backendChain = authoritativeTrustedChain(task, context.viewerRole);
  if (backendChain) return backendChain;
  const readiness = task.readiness || {};
  const rule = task.rule;
  const authorization = task.authorization_summary || {};
  const compute = task.compute_summary;
  const confirmation = task.confirmation_summary || {};
  const complete = task.status === "AUDITED";
  const failed = ["EXCEPTION", "INVALID", "REJECTED"].includes(String(task.status));
  const uploads = context.uploads || [];
  const agreements = context.agreements || [];
  const jobs = context.jobs || [];
  const results = context.results || [];
  const evidence = context.evidence || [];
  const latestTime = (records: JsonRecord[]) => records.map((item) => item.updated_at || item.created_at).filter(Boolean).sort().at(-1);
  const evidenceOf = (...types: string[]) => evidence.filter((item) => types.includes(String(item.biz_type)));
  const taskPath = `/settlements/${task.task_id || ""}`;
  const participantNames = (task.participants || []).map((item: JsonRecord) => item.org_name || item.org_id).filter(Boolean).join("、") || "参与主体";
  const drafts = [
    {
      code: "DATA", title: "可信数据接入", done: Boolean(readiness.preflight_passed), blocked: Boolean(readiness.preflight_blockers?.length),
      detail: `${readiness.ready_data_count || 0}/${readiness.required_data_count || 0} 份数据承诺`, owner: participantNames,
      completedAt: latestTime(uploads), evidenceCount: evidenceOf("AUTHORIZATION_BUNDLE").length, path: `/data-space?task_id=${task.task_id}`,
    },
    {
      code: "AUTH", title: "数据空间授权", done: Number(authorization.authorized_count || 0) > 0, blocked: failed,
      detail: `${authorization.authorized_count || 0} 份有效协议`, owner: task.creator_org_name || "交易中心",
      completedAt: latestTime(agreements), evidenceCount: evidenceOf("AUTHORIZATION_BUNDLE").length, path: `/data-space?task_id=${task.task_id}`,
    },
    {
      code: "RULE", title: "结算规则锁定", done: rule?.status === "ACTIVE", blocked: Boolean(rule && rule.status !== "ACTIVE"),
      detail: rule ? `${rule.rule_version} · ${rule.status === "ACTIVE" ? "已锁定" : "尚未启用"}` : "未绑定有效规则", owner: task.creator_org_name || "交易中心",
      completedAt: rule?.updated_at || rule?.created_at, evidenceCount: evidenceOf("AUTHORIZATION_BUNDLE").length, path: statePath("RULE_FROZEN", String(task.task_id || ""), context.viewerRole),
    },
    {
      code: "COMPUTE", title: "受控结算计算", done: compute?.status === "SUCCESS", blocked: failed,
      detail: compute ? `${ALGORITHM_LABELS[String(compute.adapter_code)] || "受控结算计算"} · ${compute.status === "SUCCESS" ? "已完成" : "执行中"}` : "尚未执行", owner: "平台受控计算服务",
      completedAt: latestTime(jobs), evidenceCount: evidenceOf("COMPUTE_RECEIPT").length, path: `/compute?task_id=${task.task_id}`,
    },
    {
      code: "VERIFY", title: "结算结果核验", done: Number(task.result_count || results.length) > 0 && evidenceOf("SETTLEMENT_RESULT").length > 0, blocked: failed,
      detail: Number(task.result_count || results.length) > 0 ? `${task.result_count || results.length} 项结果已生成` : "尚无可核验结果", owner: "平台结果核验服务",
      completedAt: latestTime(results), evidenceCount: evidenceOf("SETTLEMENT_RESULT", "AUDIT_REPORT").length, path: `/results?task_id=${task.task_id}`,
    },
    {
      code: "CONFIRM", title: "多方结果确认", done: Number(confirmation.required_count || 0) > 0 && Number(confirmation.remaining_count || 0) === 0, blocked: failed,
      detail: `${confirmation.confirmed_count || 0}/${confirmation.required_count || 0} 方已确认`, owner: participantNames,
      completedAt: Number(confirmation.remaining_count || 0) === 0 ? latestTime(results) : undefined, evidenceCount: evidenceOf("RESULT_CONFIRMATION").length, path: `/results?task_id=${task.task_id}`,
    },
    {
      code: "SETTLE", title: "结算完成", done: complete, blocked: failed,
      detail: complete ? "双方确认完成" : "等待多方确认", owner: task.creator_org_name || "交易中心",
      completedAt: complete ? task.updated_at : undefined, evidenceCount: evidenceOf("RESULT_CONFIRMATION").length, path: `${taskPath}#business-summary`,
    },
    {
      code: "ARCHIVE", title: "凭证归档与审计追溯", done: complete && evidence.length > 0, blocked: failed,
      detail: `${task.evidence_count || evidence.length || 0} 项证据记录`, owner: "平台证据服务",
      completedAt: complete ? latestTime(evidence) : undefined, evidenceCount: evidence.length, path: `/evidence?task_id=${task.task_id}`,
    },
  ];
  const currentIndex = drafts.findIndex((item) => !item.done);
  return drafts.map((item, index) => ({
    ...item,
    state: item.done ? "complete" : index === currentIndex ? item.blocked ? "blocked" : "current" : "pending",
    abnormal: Boolean(item.blocked || (failed && index >= currentIndex)),
  }));
}
