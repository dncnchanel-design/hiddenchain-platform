export type RoleCode = "GENERATOR" | "RETAILER" | "COAL_ENTERPRISE" | "HEAT_ENTERPRISE" | "GAS_ENTERPRISE" | "OIL_ENTERPRISE" | "EXCHANGE" | "REGULATOR" | "ADMIN";

export interface UserProfile {
  user_id: string;
  org_id: string;
  username: string;
  display_name: string;
  role_code: RoleCode;
  status: string;
  last_login_at?: string | null;
}

export interface SessionPayload {
  user: UserProfile;
  org: Record<string, unknown>;
  did: Record<string, unknown>;
  menus: Array<{ code: string; path: string; roles: RoleCode[] }>;
  field_scopes: Record<string, string>;
}

export const TTC_NORMAL_STATES = [
  "INIT",
  "IDENTITY_VERIFIED",
  "DATA_AUTHORIZED",
  "RULE_FROZEN",
  "COMPUTE_EXEC",
  "RESULT_CONFIRM",
  "AUDIT_GATE",
  "EVIDENCE_STAGE",
  "EVIDENCE_ANCHOR",
  "ARCHIVED",
] as const;

export const TTC_ABNORMAL_STATES = [
  "REJECTED",
  "FAILED",
  "INTERRUPTED",
  "REWORK",
  "HUMAN_REVIEW",
  "ANCHOR_RETRY",
  "CANCELLED",
  "EXPIRED",
] as const;

export type NormalTtcState = (typeof TTC_NORMAL_STATES)[number];
export type AbnormalTtcState = (typeof TTC_ABNORMAL_STATES)[number];
export type TtcState = NormalTtcState | AbnormalTtcState | (string & {});

export interface TtcDescriptor {
  capsule_id: string | null;
  state: TtcState;
  state_version: number;
  current_attempt: number;
  execution_snapshot_id: string | null;
  execution_snapshot_hash: string | null;
  authoritative: boolean;
}

export interface TaskNextAction {
  code: string;
  label: string;
  blocked: boolean;
  reasons: string[];
  responsible?: string | null;
}

export interface TrustedTransition {
  attempt_id: string;
  attempt_no: number;
  sequence_no: number;
  from_state: TtcState | null;
  to_state: TtcState;
  trigger_code: string;
  transition_hash: string;
  occurred_at: string;
  actor_did?: string | null;
  agent_did?: string | null;
  reason?: string | null;
  trace_id?: string | null;
  evidence_refs?: string[];
}

export type ResultConfirmationDecision = "APPROVE" | "REJECT";

export interface ResultConfirmationCommand {
  decision: ResultConfirmationDecision;
  opinion: string;
}

/** Stable additive contract for settlement APIs. Legacy fields remain available. */
export interface SettlementTask {
  task_id: string;
  status: string;
  current_stage?: string | null;
  ttc?: TtcDescriptor | null;
  allowed_actions?: string[];
  next_action?: TaskNextAction | null;
  trusted_chain?: TrustedTransition[];
  [key: string]: unknown;
}

export type JsonRecord = Record<string, any>;

export const ROLE_LABELS: Record<RoleCode, string> = {
  GENERATOR: "发电企业",
  RETAILER: "售电企业",
  COAL_ENTERPRISE: "煤炭企业",
  HEAT_ENTERPRISE: "热能企业",
  GAS_ENTERPRISE: "天然气企业",
  OIL_ENTERPRISE: "石油企业",
  EXCHANGE: "交易中心",
  REGULATOR: "监管方",
  ADMIN: "平台运维",
};

export const STATUS_LABELS: Record<string, string> = {
  UNKNOWN: "未知",
  ACTIVE: "已启用",
  VALID: "有效",
  REAL: "真实能力",
  LOCAL_REAL: "本地真实能力",
  LOCAL_REAL_DETERMINISTIC: "本地确定性能力",
  LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST: "单主机受控实验",
  AVAILABLE_IN_LOCAL_ADAPTER: "本地适配接入可用",
  PASS: "通过",
  PASSED: "已通过",
  SUCCESS: "成功",
  SUCCEEDED: "已完成",
  CONFIRMED: "已确认",
  AUDITED: "已审计",
  HEALTHY: "正常",
  RESOLVED: "已处理",
  GENERATED: "已生成",
  PERMIT: "已授权",
  READY: "已就绪",
  BATCH: "批处理",
  MINUTE: "分钟级",
  REAL_TIME: "实时",
  NEGOTIATED: "已协商",
  CONSUMED: "已使用",
  REJECTED: "已拒绝",
  LOW: "低风险",
  L2: "一般敏感",
  L3: "敏感",
  L4: "高度敏感",
  UNCONFIRMED: "待确认",
  NOT_REQUIRED: "无需确认",
  PENDING_CONFIRMATION: "待双方确认",
  PARTIALLY_CONFIRMED: "部分已确认",
  DRAFT: "待准备",
  PENDING: "待处理",
  RUNNING: "执行中",
  PROCESSING: "处理中",
  IN_PROGRESS: "进行中",
  CURRENT: "当前",
  EXCEPTION: "异常",
  REWORK: "返工处理中",
  ARCHIVED: "已归档",
  HUMAN_REVIEW: "人工复核",
  INTERRUPTED: "已中断",
  ANCHOR_RETRY: "重试证据锚定",
  MEDIUM: "中风险",
  REVIEW_REQUIRED: "待复核",
  FAILED: "失败",
  DENY: "未通过",
  DENIED: "已拦截",
  HIGH: "高风险",
  OPEN: "待处置",
  INVALID: "无效",
  REVOKED: "已撤销",
  RECORDED: "已记录",
  NOT_CONFIGURED: "未配置",
  UNVERIFIED: "未核验",
  MISSING: "缺失",
  SURPLUS: "有余量",
  GAP: "存在缺口",
  SKIPPED: "已跳过",
  NOT_PROVIDED: "未提供",
  ADAPTER: "适配接入",
  DEMO: "演示能力",
  DEMO_NO_CONSENSUS: "演示台账，未接入共识网络",
  BLOCKED: "已阻断",
  QUEUED: "排队中",
  CANCELLED: "已取消",
  COMPLETED: "已完成",
  UNDER_REVIEW: "审核中",
  SUBMITTED: "已提交",
  EXPIRED: "已过期",
  APPROVED: "已授权",
  ACTIVE_CONTRACT: "合同已生效",
  TEST: "测试环境",
  INFO: "信息",
  USER: "用户",
  AUDIT_EXPORT: "审计导出",
  AUDIT_LOG: "审计日志",
  AUDIT_REPORT: "审计报告",
  AUDIT_REPORT_APPROVE: "批准审计报告",
  AUDIT_REPORT_REJECT: "驳回审计报告",
  AGGREGATED: "聚合输出",
  K_ANONYMIZED: "匿名化输出",
  DIFFERENTIAL_PRIVACY: "差分隐私输出",
};

export const STAGE_LABELS: Record<string, string> = {
  PRE_COMPUTE: "算前授权",
  IN_COMPUTE: "算中回执",
  POST_COMPUTE: "算后结果",
  TRUST_EXECUTION: "可信执行",
};

export const EVIDENCE_TYPE_LABELS: Record<string, string> = {
  AUTHORIZATION_BUNDLE: "授权凭证",
  COMPUTE_RECEIPT: "计算回执",
  SETTLEMENT_RESULT: "结果回执",
  AUDIT_REPORT: "审计报告",
  TRUST_EXECUTION: "执行回执",
  TRUSTED_EXECUTION: "执行回执",
  RESULT_CONFIRMATION: "结果确认记录",
};

export const MESSAGE_TYPE_LABELS: Record<string, string> = {
  TaskContext: "任务上下文",
  DataPermit: "数据许可",
  RulePackage: "使用规则",
  GridSecurityGate: "安全校核",
  ComputeReceipt: "计算回执",
  AuditBundle: "审计证据包",
  ReportArtifact: "报告凭证",
  DeepSeekAgentAnalysis: "能力模块分析",
  AuditExplanation: "审计解释",
};

export const AGENT_LABELS: Record<string, string> = {
  ORCHESTRATOR: "任务编排",
  DATA_ACCESS: "数据调用",
  RULE_CONTRACT: "规则校验",
  SECURE_SETTLEMENT: "隐私计算",
  AUDIT_RISK: "风险审计",
  REPORT_EXPLAIN: "报告生成",
};

export const SCENARIO_LABELS: Record<string, string> = {
  CROSS_SCENARIO: "跨场景协同",
  RENEWABLE_CONSUMPTION: "新能源消纳",
  MARKET_TRADING: "市场交易验证",
  VPP_OPERATION: "虚拟电厂协同",
  GRID_DISPATCH: "电网安全校核",
  REGULATORY_REPORT: "可信报告",
  MARKET_SETTLEMENT: "市场结算",
  RENEWABLE_FORECAST: "新能源预测",
  VPP_AGGREGATION: "虚拟电厂聚合",
  GRID_SECURITY_CHECK: "电网安全检查",
};

export const ALGORITHM_LABELS: Record<string, string> = {
  CONTROLLED_SETTLEMENT_V1: "本地受控结算",
  LOCAL_CONTROLLED_SETTLEMENT_V1: "本地受控结算",
  ADAPTIVE_MARKET_SETTLEMENT_V2: "自适应结算计算",
  PRIVACY_LOAD_ANALYSIS_V1: "用电隐私分析",
  FEDERATED_LEARNING: "联邦学习",
  PSI_MPC: "隐私集合求交与多方安全计算",
  TEE_CONFIDENTIAL_COMPUTE: "可信执行环境机密计算",
  DIFFERENTIAL_PRIVACY_OUTPUT: "差分隐私输出",
  DETERMINISTIC_RULE_ENGINE: "确定性规则引擎",
  SECRET_SHARING_HE: "秘密共享与同态加密",
  POLICY_SANDBOX: "策略沙箱",
};

export const UNIFIED_REQUIREMENT_LABELS: Record<string, string> = {
  UNIFIED_CATALOG_ID: "统一目录标识",
  UNIFIED_IDENTITY_REGISTRATION: "统一身份登记",
  UNIFIED_INTERFACE_REQUIREMENTS: "统一接口要求",
};

export const TOOL_LABELS: Record<string, string> = {
  WorkflowEngine: "任务编排",
  TaskStateStore: "任务状态",
  CapabilityGateway: "能力网关",
  EDCAdapter: "数据空间连接器",
  ForecastFeatureAdapter: "预测特征服务",
  DataCatalog: "数据目录",
  PolicyEngine: "用途策略引擎",
  RuleRAG: "规则检索",
  DSLValidator: "规则校验",
  OPAAdapter: "策略执行",
  MarketRuleEngine: "市场规则引擎",
  SigningGate: "签名闸门",
  PSIAdapter: "隐私求交",
  CommitmentJoin: "承诺匹配",
  LocalControlledCompute: "本地受控计算",
  VPPResourceAdapter: "资源聚合",
  DeterministicEngine: "确定性计算",
  GridBoundaryAdapter: "调度边界",
  SecurityGate: "安全闸门",
  EvidenceGraph: "证据图谱",
  LocalEvidenceLedger: "本地证据台账",
  RiskRuleEngine: "风险规则",
  ReportTemplate: "报告模板",
  CitationRAG: "证据检索",
  CredentialService: "凭证服务",
};

export const RESULT_SCOPE_LABELS: Record<string, string> = {
  ORG: "主体结果",
  SUMMARY: "汇总结果",
};

export const ROLE_IN_TASK_LABELS: Record<string, string> = {
  GENERATOR: "发电方",
  RETAILER: "用电方",
};

export const ACTION_LABELS: Record<string, string> = {
  LOGIN: "登录平台",
  CHECK_DATA_SPACE_USAGE_CONTROL: "检查数据使用控制",
  CREATE_RULE_PACKAGE: "创建使用规则",
  ACTIVATE_RULE_PACKAGE: "启用规则版本",
  CREATE_SETTLEMENT_TASK: "创建结算任务",
  CONFIRM_SETTLEMENT_RESULT: "确认结果回执",
  RUN_PRIVACY_LOAD_ANALYSIS: "运行隐私分析",
  VERIFY_CHAIN_EVIDENCE: "核验证据台账",
  INVOKE_DEEPSEEK_AGENT: "调用受控能力",
  RUN_TRUSTED_SETTLEMENT_WORKFLOW: "执行可信验证闭环",
  GENERATE_AUDIT_REPORT: "生成审计报告",
  AGENT_AUDIT_QUERY: "发起证据检索",
  INJECT_TEST_ANOMALY: "测试环境新增风险事件",
  RESOLVE_ANOMALY: "处理风险事件",
  UPLOAD_DATA_REFERENCE: "登记数据引用",
  SIGN_DATA_COMMITMENT: "签署数据承诺",
  REVIEW_INBOUND_AUTHORIZATIONS: "审核入站授权",
  VIEW_AUTHORIZATIONS: "查看授权记录",
  VIEW_PENDING_AUDIT: "查看待审计事项",
  REVIEW_AUDIT_EVIDENCE: "审核审计凭证",
  CREATE_SETTLEMENT: "发起结算任务",
  VIEW_RUNTIME_STATUS: "查看运行状态",
  REQUEST_USAGE: "申请数据使用",
  CONFIRM_OWN_RESULT: "确认本方结果",
  VIEW_SYSTEM_CAPABILITIES: "查看系统能力",
  VIEW_OWN_ASSETS: "查看本方资产",
  VIEW_ALL_ASSETS: "查看全部资产",
  EXPORT_AUDIT_RECORDS: "导出审计记录",
  REVIEW_AUDIT_REPORT: "审核审计报告",
};

export const TARGET_TYPE_LABELS: Record<string, string> = {
  USER: "用户",
  DATA_UPLOAD: "数据引用",
  DATA_SPACE_AGREEMENT: "数据调用协议",
  SETTLEMENT_RULE: "使用规则",
  SETTLEMENT_TASK: "结算任务",
  SETTLEMENT_RESULT: "结果回执",
  PRIVACY_ANALYSIS_JOB: "隐私分析",
  BLOCKCHAIN_EVIDENCE: "证据台账记录",
  AGENT: "能力模块",
  AUDIT_REPORT: "审计报告",
  ANOMALY_EVENT: "风险事件",
};

export const REPORT_TEMPLATE_LABELS: Record<string, string> = {
  REGULATORY_AUDIT_V1: "监管审计模板",
};

export const FIELD_SCOPE_LABELS: Record<string, string> = {
  OWN_ORG_ONLY: "仅当前主体",
  AUTHORIZED_ALL: "全部授权主体",
  FULL: "完整证据范围",
  ROLE_SCOPED: "按角色可见",
  NONE: "不可访问",
};

export const ASSET_TYPE_LABELS: Record<string, string> = {
  GENERATION_DATA: "发电计量数据",
  RETAIL_DATA: "售电履约数据",
  RENEWABLE_FORECAST: "新能源预测数据",
  USER_LOAD_CURVE: "用户负荷曲线",
  VPP_RESOURCE: "虚拟电厂资源",
  GRID_CONSTRAINT: "调度安全边界",
  COAL_INVENTORY: "煤炭库存",
  POWER_THERMAL_OUTPUT: "火电出力",
  GRID_LOAD: "电网负荷",
  OIL_GAS_SUPPLY: "油气供应",
  ELECTRICITY_METRIC: "电力数据",
  COAL_METRIC: "煤炭数据",
  HEAT_METRIC: "热能数据",
  GAS_METRIC: "天然气数据",
  OIL_METRIC: "石油数据",
};

export const CAPABILITY_LABELS: Record<string, string> = {
  REAL: "真实能力",
  LOCAL_REAL: "本地真实能力",
  LOCAL_REAL_DETERMINISTIC: "本地确定性能力",
  LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST: "单主机受控实验",
  AVAILABLE_IN_LOCAL_ADAPTER: "本地适配接入可用",
  ADAPTER: "适配接入",
  DEMO: "演示能力",
  DEMO_NO_CONSENSUS: "演示台账，未接入共识网络",
  BLOCKED: "已阻断",
  NOT_CONFIGURED: "未配置",
  NOT_PROVIDED: "未提供",
};

export const RECORD_TYPE_LABELS: Record<string, string> = {
  AUDIT_LOG: "审计日志",
  AUDIT_REPORT: "审计报告",
  AUDIT_EXPORT: "审计导出",
};

export const TTC_STATE_LABELS: Record<string, string> = {
  INIT: "已创建",
  IDENTITY_VERIFIED: "身份已核验",
  DATA_AUTHORIZED: "数据已授权",
  RULE_FROZEN: "规则已冻结",
  COMPUTE_EXEC: "受控计算",
  RESULT_CONFIRM: "结果确认",
  AUDIT_GATE: "审计关口",
  EVIDENCE_STAGE: "证据归档",
  EVIDENCE_ANCHOR: "证据锚定",
  ARCHIVED: "已归档",
  REJECTED: "已拒绝",
  FAILED: "执行失败",
  INTERRUPTED: "已中断",
  REWORK: "返工处理中",
  HUMAN_REVIEW: "人工复核",
  ANCHOR_RETRY: "重试证据锚定",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
};

export const SOURCE_OF_TRUTH_LABELS: Record<string, string> = {
  privacy_compute_jobs: "隐私计算任务记录",
  privacy_compute_jobs_task_participants: "隐私计算任务与参与方登记",
  "privacy_compute_jobs/task_participants": "隐私计算任务与参与方登记",
  "privacy_compute_jobs/ttc_attempts/task_participants": "隐私计算任务、执行尝试与参与方登记",
  audit_logs_audit_reports: "审计日志与审计报告",
  "audit_logs/audit_reports": "审计日志与审计报告",
  "blockchain_evidence/local_evidence_ledger": "区块链证据与本地证据台账",
  "settlement_results/signatures/blockchain_evidence": "结算结果、签名与区块链证据",
  organizations_users: "组织与用户记录",
  "organizations/users": "组织与用户记录",
  did_identities: "去中心化身份记录",
  data_sources: "数据源记录",
  data_assets: "数据资产记录",
  data_asset_versions: "数据资产版本记录",
  "data_assets/data_asset_versions": "数据资产与版本记录",
  "organizations/users/did_identities/data_sources": "组织、用户、身份与数据源记录",
  blockchain_anchors: "区块链锚定记录",
  ttc_state_transitions: "可信任务状态转移记录",
  settlement_tasks: "结算任务记录",
  backend: "后端登记记录",
};

export const DOMAIN_LABELS: Record<string, string> = {
  electricity: "电力",
  coal: "煤炭",
  heat: "热能",
  gas: "天然气",
  oil: "石油",
  ELECTRICITY_NODE: "电力节点",
  COAL_NODE: "煤炭节点",
  OIL_GAS_NODE: "油气节点",
  GENERATION_SIDE: "发电侧",
  RETAIL_SIDE: "售电侧",
  GRID_SIDE: "电网侧",
};

export const DATA_STATUS_LABELS: Record<string, string> = {
  PASSED: "已通过",
  VALID: "有效",
  READY: "已就绪",
  ACTIVE: "已启用",
  PENDING: "待处理",
  UNCONFIRMED: "待确认",
  NOT_PROVIDED: "未提供",
  NOT_CONFIGURED: "未配置",
};

export const TECHNICAL_TERM_LABELS: Record<string, string> = {
  API: "API",
  CSV: "CSV",
  DID: "DID",
  EDC: "数据空间连接器",
  JSON: "JSON",
  MPC: "MPC",
  PASS: "通过",
  PSI: "PSI",
  TEE: "TEE",
  TTC: "TTC",
  VC: "VC",
  VerifiableCredential: "可验证凭证",
  EnergyMarketParticipantCredential: "能源市场参与方凭证",
  AgentCapabilityCredential: "智能助手能力凭证",
  DataSpaceConnectorAdapter: "数据空间连接器适配器",
  HCDS_CONNECTOR_1_0: "HCDS 1.0 连接器",
  HCDS_CONNECTOR_WITH_OPA_V1: "HCDS 1.0 连接器与策略控制",
  "Provider Connector": "提供方连接器",
  "DID Provider": "去中心化身份服务方",
  "Trusted Energy Data & Privacy Computing Space": "能源可信数据与隐私计算空间",
};

export function labelForCode(value: unknown, fallback = "未登记") {
  const normalized = String(value ?? "").trim();
  if (!normalized) return fallback;
  return STATUS_LABELS[normalized]
    || ACTION_LABELS[normalized]
    || TARGET_TYPE_LABELS[normalized]
    || ASSET_TYPE_LABELS[normalized]
    || CAPABILITY_LABELS[normalized]
    || RECORD_TYPE_LABELS[normalized]
    || TTC_STATE_LABELS[normalized]
    || SOURCE_OF_TRUTH_LABELS[normalized]
    || DOMAIN_LABELS[normalized]
    || DATA_STATUS_LABELS[normalized]
    || TECHNICAL_TERM_LABELS[normalized]
    || (/^[A-Z][A-Z0-9_]*$/.test(normalized) ? fallback : normalized);
}
