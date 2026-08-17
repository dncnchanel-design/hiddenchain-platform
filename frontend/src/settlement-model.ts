import { ALGORITHM_LABELS, type JsonRecord, type RoleCode } from "./types";

export type TaskTab = "todo" | "created" | "running" | "exception" | "completed";
export type TaskTone = "default" | "blue" | "green" | "amber" | "red";
export type ChainState = "complete" | "current" | "blocked" | "pending";
export type TrustedChainContext = {
  uploads?: JsonRecord[];
  agreements?: JsonRecord[];
  jobs?: JsonRecord[];
  results?: JsonRecord[];
  evidence?: JsonRecord[];
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
  if (["EXCEPTION", "INVALID", "REJECTED"].includes(status) || Number(task.open_anomaly_count || 0) > 0 || task.risk_level === "HIGH") return "exception";
  if (status === "AUDITED") return "completed";
  if (status === "DRAFT" || (status === "READY" && role === "EXCHANGE") || ownConfirmationPending(task, role, orgId)) return "todo";
  if (task.creator_org_id === orgId && role === "EXCHANGE") return "created";
  return "running";
}

export function taskNextAction(task: JsonRecord, role: RoleCode, orgId?: string) {
  const status = String(task.status || "");
  const blockers = Array.isArray(task.blocking_conditions) ? task.blocking_conditions.filter(Boolean) : [];
  if (["EXCEPTION", "INVALID", "REJECTED"].includes(status)) return { label: "查看失败原因", responsible: "交易中心", blocker: blockers[0] || "任务执行未完成" };
  if (Number(task.open_anomaly_count || 0) > 0 || task.risk_level === "HIGH") return { label: "复核风险事件", responsible: "监管方", blocker: blockers[0] || "存在待处置风险" };
  if (status === "DRAFT") {
    if (!task.readiness?.preflight_passed) return { label: "补齐算前条件", responsible: "数据提供方 / 交易中心", blocker: task.readiness?.preflight_blockers?.[0] || blockers[0] || "算前检查未通过" };
    return role === "EXCHANGE"
      ? { label: "启动结算", responsible: "交易中心", blocker: "" }
      : { label: "等待交易中心启动", responsible: "交易中心", blocker: "" };
  }
  if (status === "READY") return role === "EXCHANGE"
    ? { label: "启动结算", responsible: "交易中心", blocker: "" }
    : { label: "等待交易中心启动", responsible: "交易中心", blocker: "" };
  if (["PENDING_CONFIRMATION", "PARTIALLY_CONFIRMED"].includes(status)) {
    if (ownConfirmationPending(task, role, orgId)) return { label: "确认本方结果", responsible: role === "GENERATOR" ? "发电企业" : "售电企业", blocker: "" };
    return { label: "等待其余主体确认", responsible: "未确认参与方", blocker: blockers.find((item: string) => item.includes("未确认")) || "" };
  }
  if (status === "AUDITED") return { label: "查看结算闭环", responsible: "已完成", blocker: "" };
  return { label: "查看当前进度", responsible: task.current_stage || "系统处理", blocker: blockers[0] || "" };
}

export function trustedChain(task: JsonRecord, context: TrustedChainContext = {}): TrustedChainStep[] {
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
      completedAt: rule?.updated_at || rule?.created_at, evidenceCount: evidenceOf("AUTHORIZATION_BUNDLE").length, path: `/rules?task_id=${task.task_id}`,
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
