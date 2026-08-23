import { TRUSTED_BASE, type TrustedViewKey } from "./types";

export type CapabilityTruth = "REAL" | "LOCAL_REAL" | "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST" | "ADAPTER" | "DEMO" | "BLOCKED";

export type AssetRecord = {
  id: string;
  name: string;
  type: string;
  domain: string;
  sensitivity: "L1" | "L2" | "L3" | "L4";
  provider: string;
  providerDid: string;
  version: string;
  updatedAt: string;
  quality: number;
  frequency: string;
  access: string;
  format: string;
  description: string;
  status: "可申请" | "已授权" | "待复核";
};

export type TaskRecord = { id: string; type: string; title: string; status: "计算中" | "已完成" | "待开始" | "需复核"; updatedAt: string; progress: number; owner: string };
export type TimelineEvent = { id: string; label: string; detail: string; time: string; state: "done" | "current" | "pending" };
export type Participant = { id: string; name: string; role: string; did: string; status: "已连接" | "等待授权" | "受限" };
export type AuditTask = { id: string; title: string; status: "进行中" | "已完成" | "待复核"; time: string; source: string };

export const DEMO_DATA_NOTICE = "演示数据 · 本地受控环境" as const;
export const demoFixtureMetadata = {
  label: DEMO_DATA_NOTICE,
  settlement: "演示夹具，不构成生产结算",
  anchoring: "DEMO · 待接入真实 FISCO BCOS 节点",
} as const;

export const trustedModuleChecklist = [
  { key: "login", label: "登录页", path: "/login", interaction: "account-or-did-tabs" },
  { key: "workbench", label: "工作台", path: `${TRUSTED_BASE}/workbench`, interaction: "metrics-and-navigation" },
  { key: "identity", label: "身份中心", path: `${TRUSTED_BASE}/identity`, interaction: "identity-and-capability" },
  { key: "catalog", label: "数据目录", path: `${TRUSTED_BASE}/catalog`, interaction: "filters-and-application" },
  { key: "asset", label: "数据资产护照", path: `${TRUSTED_BASE}/assets/asset-power-output-001`, interaction: "tabs-and-evidence" },
  { key: "apply", label: "使用申请", path: `${TRUSTED_BASE}/apply/asset-power-output-001`, interaction: "four-step-wizard" },
  { key: "contract", label: "合同协商", path: `${TRUSTED_BASE}/contracts/con-202605-001`, interaction: "timeline-and-reply" },
  { key: "ttc", label: "TTC 任务详情", path: `${TRUSTED_BASE}/ttc/ttc-20260518-001`, interaction: "state-machine-and-log" },
  { key: "mpc", label: "MPC 计算任务", path: `${TRUSTED_BASE}/mpc/com-20260518-001`, interaction: "topology-and-progress" },
  { key: "results", label: "计算结果与存证", path: `${TRUSTED_BASE}/results/res-20260518-001`, interaction: "hashes-and-evidence" },
  { key: "audit", label: "审计中心", path: `${TRUSTED_BASE}/audit`, interaction: "audit-chain-and-pass" },
  { key: "agent", label: "Agent 助手", path: `${TRUSTED_BASE}/workbench#agent`, interaction: "global-sheet" },
] as const;

export const trustedViewRoutes: Array<{ key: TrustedViewKey; path: string; label: string; group: string }> = [
  { key: "workbench", path: `${TRUSTED_BASE}/workbench`, label: "工作台", group: "工作台" },
  { key: "identity", path: `${TRUSTED_BASE}/identity`, label: "身份中心", group: "主体与身份" },
  { key: "catalog", path: `${TRUSTED_BASE}/catalog`, label: "数据目录", group: "数据空间" },
  { key: "authorizations", path: `${TRUSTED_BASE}/authorizations`, label: "授权记录", group: "数据空间" },
  { key: "asset", path: `${TRUSTED_BASE}/assets`, label: "资产护照", group: "数据空间" },
  { key: "apply", path: `${TRUSTED_BASE}/apply`, label: "使用申请", group: "数据空间" },
  { key: "contract", path: `${TRUSTED_BASE}/contracts`, label: "合同协商", group: "协作与计算" },
  { key: "ttc", path: `${TRUSTED_BASE}/ttc`, label: "TTC 任务", group: "协作与计算" },
  { key: "mpc", path: `${TRUSTED_BASE}/mpc`, label: "MPC 计算", group: "协作与计算" },
  { key: "results", path: `${TRUSTED_BASE}/results`, label: "结果与存证", group: "证据与审计" },
  { key: "audit", path: `${TRUSTED_BASE}/audit`, label: "审计中心", group: "证据与审计" },
];
export const demoAssets: AssetRecord[] = [
  { id: "asset-power-output-001", name: "新能源出力数据", type: "电力数据", domain: "发电侧", sensitivity: "L4", provider: "东部绿能企业", providerDid: "did:energy:generator001", version: "V3.2", updatedAt: "2026-05-18 09:20", quality: 98.5, frequency: "5分钟/次", access: "MPC / 聚合", format: "JSON / CSV", description: "风光场站出力、预测曲线与结算时段汇总，面向受控计算开放聚合指标。", status: "可申请" },
  { id: "asset-load-profile-002", name: "组织负荷数据", type: "电力数据", domain: "用电侧", sensitivity: "L3", provider: "数联供电服务", providerDid: "did:energy:retailer001", version: "V2.1", updatedAt: "2026-05-17 16:40", quality: 96.8, frequency: "15分钟/次", access: "脱敏查询", format: "Parquet / CSV", description: "聚合到交易单元的负荷曲线，不暴露单一用户原始用电明细。", status: "已授权" },
  { id: "asset-metering-003", name: "区域电价核验数据", type: "交易数据", domain: "市场交易", sensitivity: "L2", provider: "东部电力交易中心", providerDid: "did:energy:trading001", version: "V1.3", updatedAt: "2026-05-16 08:15", quality: 99.1, frequency: "日终/次", access: "规则匹配", format: "JSON", description: "交易时段价格、节点归属及规则版本引用，用于结果口径复核。", status: "可申请" },
  { id: "asset-carbon-factor-004", name: "区域碳排因子", type: "核算数据", domain: "绿色核算", sensitivity: "L2", provider: "算服联合实验室", providerDid: "did:energy:carbon-lab001", version: "V1.0", updatedAt: "2026-05-15 18:32", quality: 97.6, frequency: "月度/次", access: "只读引用", format: "JSON / XLSX", description: "区域碳排放因子及来源文件摘要，支持绿色电力核验。", status: "待复核" },
];

export const demoTasks: TaskRecord[] = [
  { id: "TTC-20260518-001", type: "计算任务", title: "5月新能源出力结算", status: "计算中", updatedAt: "05-18 10:21", progress: 65, owner: "东部电力交易中心" },
  { id: "TTC-20260516-002", type: "MPC 任务", title: "区域负荷交叉核验", status: "已完成", updatedAt: "05-18 09:45", progress: 100, owner: "数联供电服务" },
  { id: "TTC-20260515-003", type: "证据任务", title: "月度凭证归档", status: "待开始", updatedAt: "05-18 08:33", progress: 0, owner: "审计工作组" },
  { id: "TTC-20260514-004", type: "复核任务", title: "电价规则版本确认", status: "需复核", updatedAt: "05-17 17:20", progress: 42, owner: "交易规则组" },
];

export const identityProfile = {
  subject: "东部绿能企业", role: "数据提供方", organizationId: "org-generator001", did: "did:energy:generator001",
  issuedAt: "2026-03-01 10:00:00", expiresAt: "2026-03-01 10:00:00", certificate: "EnergyCA / 2026-03-01", connector: "provider-001", connectorType: "Provider Connector",
};

export const ttcTimeline: TimelineEvent[] = [
  { id: "init", label: "Init", detail: "任务已创建", time: "2026-05-18 09:30", state: "done" },
  { id: "identity", label: "IdentityVerify", detail: "主体身份校验", time: "2026-05-18 09:31", state: "done" },
  { id: "data", label: "DataAuth", detail: "数据授权确认", time: "2026-05-18 09:32", state: "done" },
  { id: "rule", label: "RuleFrozen", detail: "规则版本冻结", time: "2026-05-18 09:33", state: "done" },
  { id: "compute", label: "ComputeExec", detail: "受控计算执行中", time: "2026-05-18 09:35", state: "current" },
  { id: "result", label: "ResultConfirm", detail: "结果待确认", time: "待执行", state: "pending" },
  { id: "audit", label: "AuditGate", detail: "审计门禁", time: "待执行", state: "pending" },
  { id: "evidence", label: "EvidenceStage", detail: "证据归档", time: "待执行", state: "pending" },
  { id: "anchor", label: "EvidenceAnchor", detail: "DEMO 锚定适配", time: "待执行", state: "pending" },
  { id: "archived", label: "Archived", detail: "归档", time: "待执行", state: "pending" },
];

export const participants: Participant[] = [
  { id: "party-a", name: "东部电力交易中心", role: "发起方 A", did: "did:energy:trading001", status: "已连接" },
  { id: "party-b", name: "东部绿能企业", role: "数据方 B", did: "did:energy:generator001", status: "已连接" },
  { id: "party-c", name: "数联供电服务", role: "核验方 C", did: "did:energy:retailer001", status: "已连接" },
];

export const auditTasks: AuditTask[] = [
  { id: "TTC-20260518-001", title: "5月新能源出力结算", status: "进行中", time: "2026-05-18 10:00", source: "本地审计样例" },
  { id: "TTC-20260516-002", title: "区域负荷交叉核验", status: "已完成", time: "2026-05-18 09:45", source: "本地审计样例" },
  { id: "TTC-20260515-003", title: "月度凭证归档", status: "已完成", time: "2026-05-18 08:33", source: "本地审计样例" },
  { id: "TTC-20260514-004", title: "电价规则版本确认", status: "待复核", time: "2026-05-17 17:20", source: "本地审计样例" },
];

export const capabilityMatrix: Array<{ name: string; truth: CapabilityTruth; note: string }> = [
  { name: "MPC 计算", truth: "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST", note: "仅当前本地主机受控实验，非生产跨域 MPC" },
  { name: "可信数据空间连接器", truth: "ADAPTER", note: "适配器边界，未连接外部生产连接器" },
  { name: "TEE 远程证明", truth: "BLOCKED", note: "未配置可信执行环境与证明链路" },
  { name: "审计哈希链", truth: "LOCAL_REAL", note: "本地追加写入哈希链，可追溯可审计" },
  { name: "外部区块链锚定", truth: "BLOCKED", note: "未接入真实外部链节点，不显示已上链" },
];
