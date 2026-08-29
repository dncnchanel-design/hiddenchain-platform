# 隐链明算源代码注释与技术实现说明

版本：`0.2.0`
适用：Windows 10/11 评委 Demo、Docker Compose 本地部署

本文是交付包中的源代码注释文档，用于回答三个问题：

1. 每个源码目录和关键文件负责什么；
2. 一次数据授权、可信执行和结算任务如何在前后端之间流转；
3. 哪些能力是真实可运行的，哪些能力只提供本地适配或演示边界。

本文不替代部署手册。安装、启动、登录、停止和故障排查请阅读 `JUDGE_DEPLOYMENT.md`。

## 1. 建议阅读顺序

如果评委只需要快速理解系统，可以按下面顺序阅读：

1. `docker-compose.yml`：了解系统由哪些服务组成；
2. `install-windows.ps1`：了解 Windows 部署和健康检查；
3. `backend/app/main.py`：了解后端启动、路由注册和健康接口；
4. `backend/app/routers/`：了解 API 按业务边界如何拆分；
5. `backend/app/services/workflow.py`：了解可信任务胶囊（TTC）状态机；
6. `backend/app/services/trust_execution.py`：了解规则冻结和受控执行；
7. `backend/app/services/formal_evidence.py`、`evidence_outbox.py`：了解证据和审计；
8. `connector/app/main.py`：了解主体侧本地连接器和原始数据边界；
9. `frontend/src/main.tsx`、`App.tsx`、`routes.tsx`：了解前端入口和路由；
10. `frontend/src/features/trusted-energy/`：了解可信数据空间的完整页面和交互；
11. `policy/hiddenchain.rego`：了解通用访问和用途策略；
12. `backend/tests/`、`connector/tests/`、`frontend/src/*.test.*`：通过测试核对实现行为。

## 2. 系统边界与运行结构

```text
浏览器
  │
  ▼
frontend/              React + Vite + Nginx 静态前端
  │ /api 同源反向代理
  ▼
backend/app/           FastAPI API、权限、工作流和确定性执行服务
  │                     │
  │                     ├─ SQLite 持久化运行账本
  │                     ├─ OPA 策略服务
  │                     └─ connector/app/ 各能源主体本地节点
  ▼
policy/                OPA/Rego 与能源执行策略
```

系统中心业务 API 保存数据引用、承诺、规则、结果、证据和审计信息；主体侧连接器保存或读取主体本地数据。
中心后端不通过普通业务接口返回主体 Vault 原始记录。

## 3. 顶层交付文件

| 文件 | 责任 | 阅读重点 |
| --- | --- | --- |
| `JUDGE_DEPLOYMENT.md` | Windows 部署手册 | 环境要求、一键部署、账户、验收和排错 |
| `SOURCE_CODE_GUIDE.md` | 源代码注释文档 | 本文，负责源码结构和技术实现导读 |
| `install-windows.ps1` | Windows 安装入口 | Docker 检查、Demo 密钥、Compose 启动和健康轮询 |
| `docker-compose.yml` | Demo 服务编排 | OPA、后端、前端、连接器和运行时服务 |
| `docker-compose.production.yml` | 生产参考编排 | 生产环境变量、反向代理和 profile |
| `Dockerfile` | 顶层镜像入口 | 构建整体运行上下文 |
| `production.env.example` | 生产配置模板 | 生产密钥和外部服务配置的占位说明 |
| `.dockerignore` | Docker 构建边界 | 排除缓存、虚拟环境、数据库和敏感运行时文件 |
| `.github/workflows/` | GitHub CI 门禁 | 仅保留工作流 YAML，供安全固定版本检查和发布验证复现 |
| `policy/` | 策略文件 | OPA/Rego 访问策略和能源执行约束 |
| `demo-data/` | 合成数据 | 评审可复核的输入、模拟结果和期望结果 |
| `deploy/` | 生产代理配置 | Caddy 反向代理配置 |

## 4. 后端实现说明

### 4.1 应用入口和基础设施

| 文件 | 实现职责 | 关键注释关注点 |
| --- | --- | --- |
| `backend/app/main.py` | 创建 FastAPI 应用、注册路由、启动迁移、健康检查 | 启动顺序、Demo/生产边界、就绪条件 |
| `backend/app/config.py` | 读取环境变量和运行时配置 | production fail-closed、连接器密钥、功能开关 |
| `backend/app/database.py` | 创建 SQLite 引擎、会话和数据库健康检查 | 数据库文件位置、连接生命周期 |
| `backend/app/migrations.py` | 执行版本化迁移并记录迁移状态 | 不伪造历史可信轨迹、迁移就绪条件 |
| `backend/app/models.py` | SQLAlchemy 数据库模型 | 组织、用户、任务、授权、证据和审计关系 |
| `backend/app/schemas.py` | Pydantic 请求/响应结构 | 字段约束、枚举、输入拒绝和输出脱敏 |
| `backend/app/test_schemas.py` | 导入批次和测试资产结构 | Excel 数据导入的严格字段边界 |
| `backend/app/security.py` | 密码哈希、JWT、签名、摘要和规范化 JSON | 密钥不落盘、签名校验和令牌边界 |
| `backend/app/production.py` | 生产环境启动前检查 | 禁止生产模式使用 Demo 账户、旧数据和不安全设置 |
| `backend/app/seed.py` | 初始化基础组织、用户、权限和身份 | 仅作为受控初始化，不代表真实生产组织数据 |
| `backend/app/demo_seed.py` | 初始化 Demo 目录、授权、连接器和可信结算任务 | 全部使用合成数据，预置任务处于待主体确认状态 |
| `backend/app/trust_models.py` | 可信空间和 TTC 领域模型 | 可信任务、身份、策略和证据状态的领域表达 |
| `backend/app/version.py` | 版本、能力标签和功能状态 | `REAL`、`LOCAL_REAL`、`ADAPTER`、`DEMO`、`BLOCKED` 的真实边界 |

### 4.2 API 路由边界

路由层只负责 HTTP 边界、认证依赖、参数校验和响应组织；具体业务规则由 `services/` 中的服务实现。

| 文件 | API 领域 | 主要功能 |
| --- | --- | --- |
| `backend/app/routers/auth.py` | 身份认证 | 密码登录、DID 登录、会话和退出 |
| `backend/app/routers/data.py` | 数据资产 | 上传、数据引用、质量、版本和承诺 |
| `backend/app/routers/energy.py` | 能源业务 | 能源主体、指标和资源数据 |
| `backend/app/routers/trade.py` | 结算交易 | 任务、规则、结算结果和确认 |
| `backend/app/routers/execution.py` | 可信执行 | 受控查询、执行任务和计算结果 |
| `backend/app/routers/trusted_query.py` | 受控查询 | 自然语言转换、查询校验和连接器执行 |
| `backend/app/routers/trust_space.py` | 可信数据空间 | 目录、资产、授权、合同、身份和结果 |
| `backend/app/routers/trust_domain.py` | 可信域 | TTC 状态、规则冻结、算法和快照 |
| `backend/app/routers/trust.py` | 可信链路 | 可信证据、代理和兼容能力 |
| `backend/app/routers/evidence.py` | 证据 | 证据批次、锚定、验证和回执 |
| `backend/app/routers/audit.py` | 审计 | 审计记录、报告和审计视图 |
| `backend/app/routers/assistant.py` | 智能助手 | 会话、建议、计划和受控工具调用 |
| `backend/app/routers/prototype.py` | 原型看板 | 综合演示数据和原型视图 |
| `backend/app/routers/system.py` | 系统运维 | 系统状态、配置、指标和运行信息 |
| `backend/app/routers/test_support.py` | 测试支持 | 测试辅助能力，不作为生产功能入口 |

### 4.3 业务服务

| 文件 | 实现职责 |
| --- | --- |
| `backend/app/services/workflow.py` | TTC 任务状态机、前置条件、允许动作、重试和结算流程。 |
| `backend/app/services/trust_execution.py` | 规则冻结、受控工具白名单、执行编排和执行快照。 |
| `backend/app/services/trust_space.py` | 可信空间目录、身份、合同、任务 payload 和可见性。 |
| `backend/app/services/trust_domain.py` | 可信域身份、策略、合同、TTC 快照和状态转换。 |
| `backend/app/services/data_usage_requests.py` | 数据使用申请、授权范围、状态、可见性和幂等。 |
| `backend/app/services/local_data_boundary.py` | 组织、权限、主体和数据规则的本地边界匹配。 |
| `backend/app/services/vault.py` | 主体本地数据引用、承诺和 Vault 原始数据边界。 |
| `backend/app/services/asset_registry.py` | 上传内容到数据资产的登记、版本和状态管理。 |
| `backend/app/services/excel_upload.py` | Excel 表头、类型、行数据和业务字段校验。 |
| `backend/app/services/query_translation.py` | 将自然语言转换为受控查询，并进行字段、范围和用途校验。 |
| `backend/app/services/assistant.py` | 智能助手计划、工具权限、只读查询和任务建议。 |
| `backend/app/services/tool_catalog.py` | 工具目录、权限、能力和就绪状态登记。 |
| `backend/app/services/notifications.py` | 站内通知生成、查询、阅读状态和任务提醒。 |
| `backend/app/services/formal_evidence.py` | 证据封存、批次、适配器选择、回执和对账。 |
| `backend/app/services/evidence_outbox.py` | 规范化摘要、Merkle 批次、事务 Outbox 和幂等锚定。 |
| `backend/app/services/policy_registry.py` | 版本化保存协商后的数据使用策略。 |
| `backend/app/services/algorithm_registry.py` | 算法名称、版本、摘要和使用状态。 |
| `backend/app/services/adapters.py` | 电网、结算、策略、证据和智能体等能力适配。 |
| `backend/app/services/common.py` | 追踪 ID、审计序列化和公共业务工具。 |
| `backend/app/services/correlation.py` | 请求关联 ID、链路追踪和状态关联。 |

### 4.4 数据空间和开源协议适配

| 文件 | 实现职责 |
| --- | --- |
| `backend/app/services/dataspace.py` | Dataspace Protocol、DCAT 和 ODRL 目录投影。 |
| `backend/app/services/dataspace_schema.py` | 数据空间目录的本地 Schema。 |
| `backend/app/services/datapackage.py` | Frictionless Data Package 描述。 |
| `backend/app/services/odcs_connector.py` | ODCS 3.1 数据合同和目录投影。 |
| `backend/app/services/arrow_connector.py` | Arrow 数据结构和元信息适配。 |
| `backend/app/services/duckdb_connector.py` | DuckDB 本地分析元数据适配。 |
| `backend/app/services/credentials.py` | JSON-LD 和可验证凭证适配。 |
| `backend/app/services/did_login.py` | DID 挑战、钱包地址、身份绑定和登录恢复。 |
| `backend/app/services/lineage.py` | 脱敏数据血缘和 OpenLineage 事件。 |
| `backend/app/services/llm.py` | 可选大模型解释和查询转换；不可用时保持受控失败。 |

### 4.5 隐私、计算、存证和可观测性

| 文件 | 实现职责 | 当前边界 |
| --- | --- | --- |
| `backend/app/services/privacy.py` | OpenDP 差分隐私适配 | `LOCAL_REAL` |
| `backend/app/services/mpc.py` | 加法秘密分享等 MPC 实验 | 单主机本地实验 |
| `backend/app/services/paillier.py` | Paillier 密钥、加密和聚合 | 单主机本地实验 |
| `backend/app/services/privacy_protocols.py` | PSI 类协议和联邦平均 | 本地协议实现 |
| `backend/app/services/privacy_attestation.py` | 连接器隐私证明签名校验 | 校验不外传声明 |
| `backend/app/services/fisco_bcos.py` | FISCO BCOS 锚定和回执适配 | 可选适配，不是默认外部链共识 |
| `backend/app/services/prometheus.py` | Prometheus 指标采集和输出 | 本地运行指标 |
| `backend/app/services/observability.py` | OpenTelemetry 设置和状态 | 可选可观测性 |
| `backend/app/services/rate_limit.py` | 登录限流和速率控制 | 登录安全闸门 |

### 4.6 能源与凭据服务

| 文件 | 实现职责 |
| --- | --- |
| `backend/app/services/solar.py` | 光伏计算能力和状态适配。 |
| `backend/app/services/credentials.py` | 主体凭据和 JSON-LD 数据结构。 |
| `backend/app/services/asset_registry.py` | 电力、煤炭、热能、天然气、石油等数据资产统一登记。 |

## 5. 主体侧连接器

`connector/app/main.py` 是主体侧本地 HTTP 节点。不同 Compose 服务通过 `ENERGY_DOMAIN` 启动为电力、煤炭、热能、天然气、石油、售电或交易中心主体。

连接器的设计重点不是把原始数据上传到中心，而是：

1. 在主体侧保存或读取本地合成数据；
2. 根据中心下发的受控查询返回允许的聚合结果；
3. 返回签名、摘要和隐私证明；
4. 拒绝未授权字段、未授权用途和原始数据导出请求。

相关文件：

| 文件 | 用途 |
| --- | --- |
| `connector/app/main.py` | 连接器 API、主体数据边界、签名结果和聚合接口。 |
| `connector/Dockerfile` | 构建连接器镜像；默认服务端口为 `8000`。 |
| `connector/requirements.txt` | 连接器运行依赖。 |
| `connector/tests/test_connector.py` | 连接器权限、签名、聚合和不外传测试。 |

## 6. 前端实现说明

### 6.1 前端入口和基础层

| 文件 | 实现职责 |
| --- | --- |
| `frontend/src/main.tsx` | 挂载 React、路由、品牌配置和认证上下文。 |
| `frontend/src/App.tsx` | 应用根组件、页面布局和全局状态入口。 |
| `frontend/src/routes.tsx` | 页面路由和懒加载。 |
| `frontend/src/api.ts` | API 请求、错误处理、格式化、金额和百分比显示。 |
| `frontend/src/auth.tsx` | 登录用户、会话恢复和认证上下文。 |
| `frontend/src/access.ts` | 角色、权限和页面访问控制。 |
| `frontend/src/hooks.ts` | 远程数据读取、刷新和命令轮询。 |
| `frontend/src/types.ts` | 前端共享类型。 |
| `frontend/src/settlement-model.ts` | 结算计算和业务展示模型。 |
| `frontend/src/branding.tsx` | 产品配置和品牌上下文。 |
| `frontend/src/brand-theme.ts` | 品牌颜色、字体和主题变量。 |
| `frontend/src/components/layout.tsx` | 通用导航、布局和页面框架。 |
| `frontend/src/components/ui.tsx` | 通用按钮、卡片、表格和标签。 |
| `frontend/src/components/TrustedExecutionReviewPanel.tsx` | 可信执行任务审核和确认面板。 |
| `frontend/src/styles.css` | 全局样式。 |
| `frontend/src/ethereum.d.ts` | 浏览器钱包对象的 TypeScript 类型声明。 |

### 6.2 传统业务页面

`frontend/src/pages/` 保留平台总览、结算、数据、审计、监控和运维页面：

| 文件 | 页面用途 |
| --- | --- |
| `OverviewPage.tsx` | 平台总览。 |
| `SettlementPage.tsx` | 结算任务列表。 |
| `SettlementCreatePage.tsx` | 创建结算任务。 |
| `SettlementDetailPage.tsx` | 结算任务详情。 |
| `DataSpacePage.tsx` | 数据空间和原型入口。 |
| `ExcelUploadPage.tsx` | Excel 数据导入。 |
| `ResultsPage.tsx` | 结算和计算结果。 |
| `EvidencePage.tsx` | 证据和存证。 |
| `AuditPage.tsx` | 审计视图。 |
| `ReportsPage.tsx` | 报告视图。 |
| `RulesPage.tsx` | 策略和规则。 |
| `ComputePage.tsx` | 隐私计算和计算任务。 |
| `AgentsPage.tsx` | 智能体和工具。 |
| `AnomaliesPage.tsx` | 异常和风险。 |
| `LoginPage.tsx` | 登录。 |
| `SystemPage.tsx` | 系统运行和运维。 |
| `MetricsPage.tsx` | 指标。 |
| `LogsPage.tsx` | 日志。 |
| `StatusPages.tsx` | 403、404、会话过期和服务不可用。 |
| `TrustedExecutionPage.tsx` | 可信执行任务。 |
| `WorkbenchPage.tsx` | 传统工作台。 |

### 6.3 可信能源数据空间模块

目录 `frontend/src/features/trusted-energy/` 是当前可信数据空间的主要交互模块。

| 子目录/文件 | 实现职责 |
| --- | --- |
| `layout/TrustedSpaceShell.tsx` | 可信空间整体布局、侧边栏和导航。 |
| `components/PageFrame.tsx` | 页面通用框架。 |
| `components/PrototypePageFrame.tsx` | 原型页面通用框架。 |
| `components/AgentSheet.tsx` | 智能助手侧面板。 |
| `components/NotificationCenter.tsx` | 通知中心。 |
| `components/QueryResultChart.tsx` | 查询结果图表。 |
| `components/TrustedHelpPanel.tsx` | 可信空间帮助面板。 |
| `components/ui-primitives.tsx` | 模块内基础 UI。 |
| `pages/CatalogPage.tsx` | 数据资产目录。 |
| `pages/AssetPassportPage.tsx` | 数据资产护照。 |
| `pages/ApplyPage.tsx` | 数据使用申请。 |
| `pages/AuthorizationsPage.tsx` | 授权管理。 |
| `pages/ContractPage.tsx` | 数据合同。 |
| `pages/IdentityPage.tsx` | 组织、身份和 DID。 |
| `pages/ConnectorPage.tsx` | 连接器状态。 |
| `pages/QueryPage.tsx` | 受控查询。 |
| `pages/MpcPage.tsx` | 多方安全计算。 |
| `pages/ResultsEvidencePage.tsx` | 结果和可信证据。 |
| `pages/AuditCenterPage.tsx` | 审计中心。 |
| `pages/StrategyCenterPage.tsx` | 策略中心。 |
| `pages/TtcPage.tsx` | TTC 状态和时间线。 |
| `pages/WorkbenchPage.tsx` | 可信数据空间工作台。 |
| `trusted-space-api.ts` | 可信空间 API 客户端。 |
| `trusted-space-context.tsx` | 可信空间共享状态。 |
| `assistant-state.ts` | 智能助手状态机。 |
| `query-chart.ts` | 查询结果图表数据转换。 |
| `trusted-space-labels.ts` | 状态、标签和业务术语。 |
| `trusted-space-ui.ts` | UI 辅助函数。 |
| `types.ts`、`utils.ts` | 模块类型和公共工具。 |

## 7. 一次可信结算任务的调用链

### 7.1 创建和授权

```text
前端 SettlementCreatePage / ApplyPage
  → frontend/src/api.ts
  → backend/app/routers/trade.py 或 trust_space.py
  → data_usage_requests.py / policy_registry.py
  → 组织、角色、用途、算法、期限和调用次数校验
  → 生成待确认的授权和 TTC 任务
```

### 7.2 规则冻结和执行

```text
前端 QueryPage / TrustedExecutionPage
  → trusted_query.py / execution.py
  → query_translation.py
  → trust_execution.py
  → policy/hiddenchain.rego + energy_execution_policy.json
  → 冻结规则、合同、数据引用、算法、参数和单位
  → 调用主体侧 connector/app/main.py
```

### 7.3 结果、确认和审计

```text
主体连接器返回允许的聚合结果和签名证明
  → 后端验证签名、组织边界和输出模式
  → 生成平台汇总结果与主体可见结果
  → 主体确认本组织结果
  → formal_evidence.py / evidence_outbox.py
  → Merkle 批次、事务 Outbox、审计事件和本地哈希回执
  → ResultsEvidencePage / AuditCenterPage 展示
```

## 8. TTC 状态机

一次可信任务按照以下顺序推进：

```text
INIT
  → IDENTITY_VERIFIED
  → DATA_AUTHORIZED
  → RULE_FROZEN
  → COMPUTE_EXEC
  → RESULT_CONFIRM
  → AUDIT_GATE
  → EVIDENCE_STAGE
  → EVIDENCE_ANCHOR
  → ARCHIVED
```

状态转换由 `backend/app/services/workflow.py` 和 `backend/app/services/trust_domain.py` 控制。每个动作都要经过：

1. 当前状态是否允许该动作；
2. 当前用户、组织和主体身份是否匹配；
3. 授权、合同、策略和数据引用是否完整；
4. 执行参数、算法版本和单位是否已经冻结；
5. 失败或重试是否写入审计记录。

没有 TTC Attempt 的旧任务会被标记为 `LEGACY_UNMIGRATED`，不能被当作已完成规则冻结、受控计算或证据锚定的新任务。

## 9. 数据、权限和隐私边界

### 9.1 权限边界

- API 通过认证依赖读取当前用户、组织和角色；
- 后端同时检查角色权限、组织归属、主体身份和任务参与关系；
- 发电方、售电方等主体只能确认本组织结果；
- 监管方可以查看证据、异常和审计，但不能修改主体数据；
- 管理员可以查看平台运维信息，但不因此获得主体 Vault 原始记录。

### 9.2 原始数据边界

- 中心账本保存数据引用、版本、摘要、承诺和结果；
- 原始主体数据由主体侧连接器或本地 Vault 负责；
- 查询翻译只允许进入受控字段、用途和输出模式；
- 未授权字段、原始记录导出和跨组织结果访问会被拒绝；
- `backend/app/services/local_data_boundary.py` 和 `vault.py` 是理解该边界的首要文件。

### 9.3 能力标签

| 标签 | 含义 |
| --- | --- |
| `REAL` | 在当前实现中可直接执行的能力。 |
| `LOCAL_REAL` | 本机可执行，但不是跨机构生产部署。 |
| `ADAPTER` | 提供协议或接口映射，依赖独立外部系统才能形成完整能力。 |
| `DEMO` | 用于本地评审的演示实现。 |
| `BLOCKED` | 当前未接入，系统必须明确拒绝或标记不可用。 |

当前版本的真实边界：确定性结算为单服务进程本地执行；MPC/Paillier 为单主机实验；EDC 为适配器；TEE 为 `BLOCKED`；默认区块链锚定为本地确定性哈希回执，不代表外部链共识或终局性。

## 10. 策略和证据

| 文件 | 用途 |
| --- | --- |
| `policy/hiddenchain.rego` | OPA 通用访问、主体、用途和输出策略。 |
| `policy/hiddenchain_test.rego` | OPA 策略测试。 |
| `policy/energy_execution_policy.json` | 能源执行字段、算法、输出和安全约束。 |
| `backend/app/services/policy_registry.py` | 策略版本和协商结果登记。 |
| `backend/app/services/formal_evidence.py` | 正式证据封存和证据批次。 |
| `backend/app/services/evidence_outbox.py` | 摘要、Merkle、事务 Outbox 和锚定幂等。 |
| `backend/app/services/fisco_bcos.py` | 可选 FISCO BCOS 适配，不代表默认接入真实链。 |

## 11. 测试和验证入口

### 11.1 后端和连接器

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\connector
.\.venv\Scripts\python.exe -m pytest -q
```

主要测试类别：

- `test_platform.py`：平台登录和主要 API；
- `test_trust_space_golden_path.py`：可信数据空间主流程；
- `test_trust_space_workflows.py`：授权、合同和任务工作流；
- `test_trusted_query_translation.py`：受控查询转换；
- `test_subject_isolation.py`：主体和组织隔离；
- `test_security_gates.py`：原始数据、密钥和权限安全；
- `test_evidence_outbox.py`：证据、Merkle 和 Outbox；
- `test_privacy_protocols.py`、`test_mpc.py`、`test_paillier.py`：隐私计算实验；
- `test_production_readiness.py`：生产边界和启动门禁。

### 11.2 前端

```powershell
cd frontend
pnpm lint
pnpm test
pnpm build
```

前端测试覆盖权限、API 客户端、品牌主题、轮询策略、查询图表、可信数据空间和结算模型。

## 12. 如何扩展功能

新增业务能力时，建议按照以下顺序修改：

1. 在 `backend/app/schemas.py` 定义输入和输出结构；
2. 在 `backend/app/models.py` 或迁移文件中增加持久化结构；
3. 在 `backend/app/services/` 中实现业务规则；
4. 在对应 `routers/` 中暴露最小 API；
5. 在 `policy/` 中增加用途、字段和输出约束；
6. 在 `frontend/src/features/trusted-energy/` 或 `frontend/src/pages/` 增加页面；
7. 同时增加后端、连接器或前端测试；
8. 在注释中写清输入边界、权限边界、失败行为和能力标签；
9. 运行生产门禁、完整测试和前端生产构建。

新增注释优先说明“为什么必须这样做”和“什么情况下必须拒绝”，不重复显而易见的变量名。涉及安全、隐私、状态转换、数据来源、失败重试或审计的代码必须补充注释。

## 13. 与部署手册的关系

| 文档 | 解决的问题 |
| --- | --- |
| `JUDGE_DEPLOYMENT.md` | 评委如何准备 Windows 环境、启动和使用系统。 |
| `SOURCE_CODE_GUIDE.md` | 评委如何阅读源码、理解调用链和核对技术边界。 |

两份文档、Compose 配置和源码来自同一版本工作树。Demo 密钥、数据库、日志、Docker volume、Python 虚拟环境和 `node_modules` 不属于源代码交付内容，首次运行时由评委电脑生成或创建。
