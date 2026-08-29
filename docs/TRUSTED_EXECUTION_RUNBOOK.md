# 可信执行运维手册

适用版本：`0.2.0`。本手册管理项目内的本地可信执行机制，不把外部 EDC、TEE、链网络或生产数据基础设施写成已就绪。

## 启动前

1. 确认 `APP_ENV`、数据库、OPA 和密钥均属于目标环境。
2. 以项目本地工具执行构建、生产门禁与测试；不全局安装依赖。
3. 启动时应用会按迁移账本顺序执行代码中全部已登记版本；当前应用到的版本以 `/api/health/ready` 返回的迁移状态为准。迁移账本未应用、有待执行版本、出现未知版本或 checksum 不匹配时，就绪检查不应通过。
4. 不得把 `LEGACY_UNMIGRATED` 任务作为新 TTC 继续执行；需经明确业务处置新建 TTC/Attempt，不补造历史转移、快照或证据。

## 健康与版本检查

| 端点 | 用途 | 成功标准 |
| --- | --- | --- |
| `GET /api/version` | 服务版本、API 合同版本、构建 SHA 与能力标签 | `service_version=0.2.0`；发布时 `build_sha` 与目标 commit 一致 |
| `GET /api/health/live` | 进程存活 | HTTP 200 且 `status=UP` |
| `GET /api/health/ready` | 迁移、OPA 和 Agent Tool 目录就绪 | HTTP 200 且三项检查均 `READY`；任一未就绪则 HTTP 503 |
| `GET /api/health` | 组件与能力边界 | MPC 为单主机实验，EDC/TEE/锚定标签不被放大 |

production 不允许 OPA 本地回退。远程 OPA 不可用时，`/api/health/ready` 必须是 `NOT_READY`，不得绕过。

## TTC 操作要点

- 任务详情中的 `ttc.state`、`state_version`、`allowed_actions` 和 `next_action` 由后端权威生成。
- 状态变更使用 `If-Match`/`ETag` 做乐观并发控制；创建和执行使用 `Idempotency-Key` 防止重放绑定到不同请求。
- 从 `DATA_AUTHORIZED` 进入 `RULE_FROZEN`/计算前，必须持久化且校验不可变执行快照。
- 正常 TTC 状态只能由所属领域服务推进；人工端点只接受 `HUMAN_REVIEW`、`REWORK`、`INTERRUPTED` 和 `CANCELLED` 等明确人工目标。
- 主体 DID、Agent DID、策略/合同有效期、Tool 权限或快照完整性校验失败时必须 fail-closed。

## 证据与 Outbox

1. 证据类型必须映射到 A/B/C 显式类别；未知类型 fail-closed。
2. 批次使用 `SHA256_BINARY_DS_V1` 封存。原始敏感数据不应进入证据项或 Outbox 载荷。
3. 业务结果、证据批次和 Outbox 须在同一数据库事务中提交。锚定处理在事务后执行，失败不回写或撤销已确认业务结果。
4. 本地工作器通过 `POST /api/evidence/outbox/process` 按需处理，仅允许监管/管理角色。状态为 `PENDING`、`PROCESSING`、`RETRY_WAIT`、`PUBLISHED` 或 `DEAD_LETTER`。
5. `PUBLISHED` 在当前本地适配器中只表示已产生 `CONFIRMED_DEMO` 哈希回执，不表示链上共识确认。

Outbox 错误按指数退避进入 `RETRY_WAIT`；载荷/完整性错误或达到最大尝试次数后进入 `DEAD_LETTER`。处理前应核对 `payload_hash`、Merkle 根和批次引用，不得通过修改已封存证据来“修复”。

## MPC 运行边界

`GET /api/privacy/mpc/status` 应显示 `LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST`、`cross_domain_production_privacy=false` 和 `independent_nodes=false`。当前只支持有界整数求和；小数缩放由调用方负责。生产不得注入确定性伪随机源；该入口只能在显式测试标志下使用。

## 部署边界

`render.yaml` 定义一个平台与七个主体连接器，共八个 Free plan 公开 review 服务。平台使用 `APP_ENV=demo`、SQLite、`TEST_FIXTURE_SEED=false`，仅显式开启 demo 目录/业务种子与 OPA 本地回退；七个连接器显式开启确定性合成数据。其数据持久性、弹性、隔离、密钥管理和外部可信运行时均不满足生产门禁，不得标注为 production。

外部 PostgreSQL、Redis、MinIO、Milvus、EDC 节点、TEE 证明和链网络均需独立部署、凭证和验收证据。未提供时保持 `BLOCKED`/`ADAPTER`/`DEMO`。
