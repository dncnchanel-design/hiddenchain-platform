# 隐链明算 MVP 技术架构：可信数据调用与隐私计算

平台的核心能力是“可信数据调用”和“隐私计算”；能源电力交易只是当前最完整的验证场景。所有场景都应复用数据产品目录、用途控制、计算策略和可验证回执，而不是把平台建模成单一交易系统。

赛题验收主线固定为：`可信采集 → 安全传输 → 可控使用 → 隐私计算 → 可溯审计`。系统首页和验证页按这条主线组织，交易金额、结算结果只作为场景输出。

## 1. 代码边界

平台把 Agent 控制面与确定性执行面分开：

- Agent 控制面负责意图识别、任务编排、受控工具调用、异常联动和报告解释。
- 确定性执行面负责身份验证、策略判定、规则 DSL 执行、MPC 计算、哈希、签名和存证。
- Agent 只处理 `TaskContext`、`DataPermit`、`RulePackage`、`ComputeReceipt` 和 `AuditBundle`，不接收企业原始明细。
- 业务数据库只保存 `DataRef`、摘要、承诺、策略哈希、结果哈希和证据索引；演示原文存放在各组织独立的本地 Vault 目录。
- 四场景的原始数据不在业务层拼接；只有授权计算沙箱能解析域内引用，Agent 接收的是场景摘要和可验证回执。

## 2. 分层映射

| 层级 | 代码位置 | 当前实现 | 生产替换点 |
| --- | --- | --- | --- |
| 用户层 | `frontend/src` | React 18 模块界面、角色菜单 | 国网统一门户/移动端 |
| 业务层 | `backend/app/routers` | 结算、隐私分析、审计 REST API | 微服务与 API 网关 |
| Agent 层 | `services/workflow.py` | 四类能源专业 Agent + 编排/报告 Agent | Agent Runtime/工作流引擎 |
| 可信数据空间层 | `services/adapters.py`、`routers/data.py`、`routers/trade.py` | HCDS-1.0 轻量 Connector、来源/传输元数据、数据产品目录、合同协商、PEP/PDP 使用控制和 ComputeReceipt 关联；底层计算/链仍为可替换适配器 | EDC Connector + OPA + 企业数据网关 |
| 隐私计算层 | `AdaptivePrivacyRouter`、`MockPrivacyComputeAdapter` | 场景策略路由、本地多方域模拟、确定性结算 | SecretFlow/FL/HEU/TEE 多节点部署 |
| 区块链层 | `MockBlockchainAdapter` | 交易哈希、区块高度、证据核验 | FISCO BCOS 证据合约 |
| 数据层 | `models.py`、`services/vault.py` | SQLite + 组织域 Vault | PostgreSQL + 企业数据网关 |
| 基础设施层 | Docker Compose | 单机可运行原型 | K8s、密码机、监控告警 |

## 3. 四场景耦合

1. 新能源消纳：`RENEWABLE_FORECAST` 与发电计量承诺形成预测风险摘要，供市场任务引用。
2. 电力市场交易：交易规则经 RAG 引用、DSL 固化和人工签署后形成 `RulePackage`。
3. 虚拟电厂运营：`VPP_RESOURCE` 在隐私沙箱内聚合，仅输出可调容量和偏差修正量。
4. 电网调度：`GRID_CONSTRAINT` 不出调度域，结算前对剩余偏差执行安全闸门；不通过则终止结算。

四场景以 `trade_batch_no` 对齐，以 `capsule_id` 关联身份、许可、计算和证据，形成“预测 -> 市场 -> 响应 -> 校核 -> 结算”的业务闭环。

## 4. 六 Agent 标准消息

1. `ORCHESTRATOR`（四场景可信编排）：用户请求 -> `TaskContext` / 跨场景 `TaskDAG`。
2. `DATA_ACCESS`（新能源消纳）：预测、计量 DataRef、主体 DID -> 风险摘要 / `DataPermit`。
3. `RULE_CONTRACT`（市场交易）：交易批次、规则、许可 -> `RulePackage` / `RuleHash`。
4. `SECURE_SETTLEMENT`（虚拟电厂协同）：可调资源承诺、规则包 -> 响应计划 / `ComputeReceipt` / 结算结果。
5. `AUDIT_RISK`（电网调度与监管）：调度边界承诺、回执、证据 -> 安全校核 / `AuditBundle`。
6. `REPORT_EXPLAIN`（可信报告）：四场景结果、审计包 -> 带证据引用的 `ReportArtifact`。

所有 Agent 调用记录 `agent_did`、工具名、输入哈希、输出哈希与签名值。

## 5. 场景感知隐私路由

| 场景 | 主策略 | 辅助策略 | 当前 MVP |
| --- | --- | --- | --- |
| 新能源与负荷联合预测 | 联邦学习 | 差分隐私输出 | 生成可验证 ComputePlan，算法适配器待替换 |
| 电力市场联合结算 | PSI + MPC | 确定性规则引擎 | 可运行秘密共享语义模拟 |
| 虚拟电厂资源聚合 | 秘密共享 + 同态加密 | 差分隐私输出 | 可运行聚合模拟，单户数据不返回 |
| 实时调度安全校核 | TEE 机密计算 | 策略沙箱 | 可运行边界闸门模拟，潮流模型待接入 |

`AdaptivePrivacyRouter` 根据场景、敏感等级、参与主体数量和时延要求生成 `ComputePlan` 与 `plan_hash`。路由结果属于强制执行参数，不是页面推荐文案。

## 6. 四链融合

- DID 身份链：主体与 Agent 的 VC、能力令牌和签名身份。
- 隐私计算链：`DataPermit`、输入承诺、`ComputePlan`、`ComputeReceipt`。
- 区块链存证链：计算前、计算中、计算后的证据哈希和交易索引。
- 智能体协作链：Agent DID、工具名、输入输出哈希和签名调用事件。

四链通过 `capsule_id` 和证据引用建立关系，不把身份、计算、存证和 Agent 当成互不相干的技术模块。

## 7. 可信验证胶囊

`capsule_id` 是跨层关联主键。一个胶囊聚合：参与主体 DID、数据许可、RuleHash、输入承诺、计算回执、场景结果、多方签名、三阶段链上证据、异常事件和审计报告。

三阶段证据：

- `PRE_COMPUTE`：主体身份、授权策略、RuleHash、输入承诺。
- `IN_COMPUTE`：算法标识、输入哈希、输出哈希、执行证明。
- `POST_COMPUTE`：结果哈希、多方签名、合约状态、报告哈希。

## 8. 可信数据空间增强闭环

本版按 IDS-RAM、ODS-RAM 和国内“三统一”要求补充了可运行的轻量连接器边界：

1. `GET /api/data/catalog` 发布数据产品元数据、语义标识、Schema、质量和用途限制，不发布原始明细。
2. 结算工作流为每个提供方生成 DataContract，并通过 `DataSpaceConnectorAdapter.negotiate` 完成提供方/使用方 DID、算法、用途、期限和数据产品 ID 的协议协商。
3. `DataSpaceConnectorAdapter.enforce` 按 PEP/PDP 思路检查主体、用途、胶囊、算法、执行环境、输出模式、有效期和使用次数。
4. 计算完成后生成带协议 ID、使用决定、输入承诺、输出哈希和原始数据导出标记的 DataSpace receipt，并写入三阶段证据。

导入文件还可为每类数据声明 `ingress`：来源类型、接入层（终端/边缘/云端/业务）、HTTPS/MQTT/WebSocket 协议、TLS 版本和来源证明。导入接口先完成整份清单校验，再写入主体域 Vault；后续计算或安全闸门失败时，数据库记录与新写入的 Vault 原文一并回滚。

新增 `data_space_agreements` 表用于保存协议状态：`OFFERED → NEGOTIATED → ACTIVE → CONSUMED`。这让“访问控制”与“访问后使用控制”区分开来，也为后续替换真实 EDC/OPA 保留稳定接口。

> 当前仍是标准对齐参考实现：`MockPrivacyComputeAdapter`、`MockBlockchainAdapter` 和 `MockDidAdapter` 的替换边界没有被伪装成生产节点。

## 9. 数据库实体

核心表由 SQLAlchemy 在启动时创建：`organizations`、`users`、`did_identities`、`data_uploads`、`settlement_rules`、`settlement_tasks`、`task_participants`、`data_contracts`、`data_space_agreements`、`privacy_compute_jobs`、`settlement_results`、`signatures`、`blockchain_evidence`、`agent_events`、`audit_logs`、`audit_reports`、`anomaly_events`、`privacy_analysis_jobs`、`metric_records`。

表结构详情可直接查看 `backend/app/models.py`，API 请求字段在 `backend/app/schemas.py`。
