const REQUEST_STATUS_LABELS: Record<string, string> = {
  DRAFT: "草稿",
  SUBMITTED: "已提交",
  UNDER_REVIEW: "审核中",
  APPROVED: "已授权",
  REJECTED: "已拒绝",
  REVOKED: "已撤销",
  EXPIRED: "已过期",
};

const PURPOSE_LABELS: Record<string, string> = {
  SETTLEMENT_ANALYSIS: "结算分析",
  SETTLEMENT_AUDIT: "结算审计",
  CROSS_CHECK: "交叉核验",
  MODEL_TRAINING: "模型训练",
  AUDIT_REVIEW: "审计复核",
  CONTROLLED_OTHER: "其他受控用途",
  REGULATORY_CROSS_ENERGY_REVIEW: "能源监管",
  REGULATORY_EMERGENCY_RESPONSE: "应急处置",
  POWER_SETTLEMENT: "电力结算",
  GRID_SECURITY_CHECK: "电网安全校核",
  VPP_AGGREGATION: "虚拟电厂聚合",
  CROSS_ENERGY_TREND: "跨域能源趋势分析",
};

const USAGE_MODE_LABELS: Record<string, string> = {
  MPC_AGGREGATE: "多方安全聚合计算",
  MASKED_QUERY: "脱敏查询",
  RULE_MATCH: "规则匹配",
  READ_ONLY_REFERENCE: "只读引用",
};

const CAPABILITY_LABELS: Record<string, string> = {
  REAL: "真实能力",
  LOCAL_REAL: "本地真实能力",
  LOCAL_REAL_DETERMINISTIC: "本地确定性能力",
  LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST: "本地主机受控实验",
  ADAPTER: "适配器能力",
  AVAILABLE_IN_LOCAL_ADAPTER: "本地适配器可用",
  DEMO: "演示能力",
  BLOCKED: "已阻断",
  NOT_PROVIDED: "未提供",
  NOT_CONFIGURED: "未配置",
};

const POLICY_SOURCE_LABELS: Record<string, string> = {
  SERVER_DEFAULT_POLICY: "服务端默认策略",
  DATA_USAGE_REQUEST: "使用申请策略",
};

function mappedLabel(value: string | null | undefined, labels: Record<string, string>, fallback: string) {
  const normalized = value?.trim();
  return normalized ? labels[normalized] || fallback : fallback;
}

export function requestStatusLabel(value: string | null | undefined) {
  return mappedLabel(value, REQUEST_STATUS_LABELS, "未核验状态");
}

export function purposeLabel(value: string | null | undefined) {
  return mappedLabel(value, PURPOSE_LABELS, "受控业务用途");
}

export function usageModeLabel(value: string | null | undefined) {
  return mappedLabel(value, USAGE_MODE_LABELS, "受控处理方式");
}

export function capabilityLabel(value: string | null | undefined) {
  return mappedLabel(value, CAPABILITY_LABELS, "未登记能力");
}

export function policySourceLabel(value: string | null | undefined) {
  return mappedLabel(value, POLICY_SOURCE_LABELS, "服务端策略");
}

export function policyVersionLabel(value: string | null | undefined) {
  const normalized = value?.trim();
  if (!normalized) return "当前生效版本";
  const versionMatch = normalized.match(/_V(\d+)$/i);
  return versionMatch ? `第 ${versionMatch[1]} 版` : "当前生效版本";
}

export function signatureLabel(value: string | null | undefined) {
  return value === "NOT_PROVIDED" ? "未提供数字签名" : value ? "已提供数字签名" : "未核验签名";
}

export function externalAnchorLabel(value: string | null | undefined) {
  return value === "BLOCKED" ? "未配置外部锚定" : value === "NOT_PROVIDED" ? "未提供外部锚定" : value ? "已记录外部锚定" : "未核验外部锚定";
}

export function sensitivityLabel(value: string | null | undefined) {
  return ({ L1: "一级", L2: "二级", L3: "三级", L4: "四级" } as Record<string, string>)[value || ""] || "未分级";
}

export function actionLabel(action: string, view?: "inbox" | "outbound", status?: string | null) {
  if (action === "review") return "开始审核";
  if (action === "approve") return "批准授权";
  if (action === "reject") return "拒绝申请";
  if (action === "withdraw") return "撤回申请";
  if (action === "revoke") return view === "outbound" && status !== "APPROVED" ? "撤回申请" : "撤销授权";
  return "执行操作";
}
