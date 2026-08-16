export type RoleCode = "GENERATOR" | "RETAILER" | "EXCHANGE" | "REGULATOR" | "ADMIN";

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
  access_token?: string;
  user: UserProfile;
  org: Record<string, unknown>;
  did: Record<string, unknown>;
  menus: Array<{ code: string; path: string; roles: RoleCode[] }>;
  field_scopes: Record<string, string>;
}

export type JsonRecord = Record<string, any>;

export const ROLE_LABELS: Record<RoleCode, string> = {
  GENERATOR: "发电企业",
  RETAILER: "售电企业",
  EXCHANGE: "交易中心",
  REGULATOR: "监管方",
  ADMIN: "系统管理员",
};

export const STATUS_LABELS: Record<string, string> = {
  UNKNOWN: "未知",
  ACTIVE: "已启用",
  VALID: "有效",
  PASSED: "已通过",
  SUCCESS: "成功",
  CONFIRMED: "已确认",
  AUDITED: "已审计",
  HEALTHY: "正常",
  RESOLVED: "已处理",
  GENERATED: "已生成",
  PERMIT: "已授权",
  READY: "可用",
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
  DRAFT: "待准备",
  PENDING: "待处理",
  AUTHORIZED: "已授权",
  COMPUTING: "计算中",
  EVIDENCED: "已存证",
  RUNNING: "运行中",
  MEDIUM: "中风险",
  REVIEW_REQUIRED: "待复核",
  FAILED: "失败",
  DENY: "未通过",
  HIGH: "高风险",
  OPEN: "待处置",
  INVALID: "无效",
  REVOKED: "已撤销",
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
  ADAPTIVE_MARKET_SETTLEMENT_V2: "自适应结算计算",
  SETTLEMENT_MPC_V1: "隐私结算计算",
  PRIVACY_LOAD_ANALYSIS_V1: "用电隐私分析",
  FEDERATED_LEARNING: "联邦学习",
  DIFFERENTIAL_PRIVACY_OUTPUT: "差分隐私输出",
  PSI_MPC: "隐私求交与联合计算",
  DETERMINISTIC_RULE_ENGINE: "确定性规则引擎",
  SECRET_SHARING_HE: "秘密共享与同态加密",
  TEE_CONFIDENTIAL_COMPUTE: "可信执行环境计算",
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
  MPCAdapter: "联合计算",
  VPPResourceAdapter: "资源聚合",
  DeterministicEngine: "确定性计算",
  GridBoundaryAdapter: "调度边界",
  SecurityGate: "安全闸门",
  EvidenceGraph: "证据图谱",
  FISCOAdapter: "存证适配器",
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
  CREATE_SETTLEMENT_TASK: "创建验证任务",
  CONFIRM_SETTLEMENT_RESULT: "确认结果回执",
  RUN_PRIVACY_LOAD_ANALYSIS: "运行隐私分析",
  VERIFY_CHAIN_EVIDENCE: "核验链上证据",
  INVOKE_DEEPSEEK_AGENT: "调用受控能力",
  RUN_TRUSTED_SETTLEMENT_WORKFLOW: "执行可信验证闭环",
  GENERATE_AUDIT_REPORT: "生成审计报告",
  AGENT_AUDIT_QUERY: "发起证据检索",
  INJECT_DEMO_ANOMALY: "新增风险事件",
  RESOLVE_ANOMALY: "处理风险事件",
  UPLOAD_DATA_REFERENCE: "登记数据引用",
  SIGN_DATA_COMMITMENT: "签署数据承诺",
};

export const TARGET_TYPE_LABELS: Record<string, string> = {
  USER: "用户",
  DATA_UPLOAD: "数据引用",
  DATA_SPACE_AGREEMENT: "数据调用协议",
  SETTLEMENT_RULE: "使用规则",
  SETTLEMENT_TASK: "验证任务",
  SETTLEMENT_RESULT: "结果回执",
  PRIVACY_ANALYSIS_JOB: "隐私分析",
  BLOCKCHAIN_EVIDENCE: "链上证据",
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
