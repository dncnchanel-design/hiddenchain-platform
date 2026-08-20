# 隐链明算

面向能源可信数据空间的数据授权、受控计算、结果确认与审计追溯平台。当前服务版本为 `0.2.0`。

## 当前可用范围

系统已形成以可信任务胶囊（TTC）为权威状态主线的本地闭环：

`INIT → IDENTITY_VERIFIED → DATA_AUTHORIZED → RULE_FROZEN → COMPUTE_EXEC → RESULT_CONFIRM → AUDIT_GATE → EVIDENCE_STAGE → EVIDENCE_ANCHOR → ARCHIVED`

- 交易中心通过五步向导创建任务，前置条件不足时保存任务并显示阻塞项。
- 发电与售电主体维护本组织数据引用，只能查看和确认本方结果。
- 监管方复核证据、异常与报告；管理员维护组织、身份、指标和日志。
- 数据、规则、计算、结果、证据、审计、异常和报告均可按 `task_id` 返回任务详情。
- Rule Freeze 为每次执行尝试固化规则、策略、合同、数据、算法、参数与单位引用，生成不可变执行快照与摘要。
- 六类 Agent 只能通过登记的受控 Tool 及显式有效权限调用领域服务；官方数值由确定性服务生成。
- A/B/C 证据记录通过域分离 SHA-256 Merkle 批次归集，业务结果与待发布 Outbox 记录在同一数据库事务中持久化。
- 产品名、Logo、客户、运营方、建设方、版权、支持信息和登录公告支持运行时白标。
- 前端已接入后端权威 TTC、允许动作、下一步、快照与证据状态；导航、布局、色彩、字体和视觉层级未重设计。

## 能力边界

本版本执行 `LOCAL_CONTROLLED_SETTLEMENT_V1` 单服务进程确定性结算。证据层新增 `SHA256_BINARY_DS_V1` Merkle 批次和事务 Outbox，但当前锚定适配器仍为 `LOCAL_HASH_ANCHOR_DEMO_V1`，不具备链网络共识或外部终局性。API 不返回 Vault 原始记录。

加法秘密分享求和已实现真实的有限域份额拆分、汇总和重构，精确状态为 `LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST`。所有份额仍共存于同一主机进程，因而不是跨主体生产 MPC 或数据不出域证明。Eclipse EDC 为 `ADAPTER`，TEE 为 `BLOCKED`，区块链共识为 `DEMO`。详见 [可信执行说明](docs/TRUSTED_EXECUTION.md) 和 [运维手册](docs/TRUSTED_EXECUTION_RUNBOOK.md)。

版本化迁移不会伪造历史可信轨迹。没有 TTC Attempt 的旧任务会标记为 `LEGACY_UNMIGRATED`，不能被当作已经完成 Rule Freeze、受控计算或锚定的新 TTC。

## 环境

| 环境 | 用途 | 测试夹具/账户 | 策略回退 | 生产门禁 |
| --- | --- | --- | --- | --- |
| `development` | 本地开发 | 允许 | 允许 | 否 |
| `test` | 自动化与验收 | 允许 | 允许 | 否 |
| `production` | 正式部署 | 禁止 | 禁止 | 是 |

生产启动会校验密钥、CORS、OPA、环境标签和数据库内容；发现测试账户、测试任务或历史模拟适配器记录时拒绝启动，不会自动删除数据。

`render.yaml` 固定使用 Render Free、`APP_ENV=test`、SQLite、测试夹具和 OPA 本地回退，仅用于 review/test，不得称为生产环境。

## 本地测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
pnpm test
pnpm build
```

`development/test` 的固定账户与夹具只用于测试，入口 `/api/auth/test-users` 在 production 返回 404。

## 生产构建

```bash
cp production.env.example .env.production
# 填写独立密钥、公开 HTTPS Origin 与品牌配置
docker compose --env-file .env.production -f docker-compose.production.yml build
docker compose --env-file .env.production -f docker-compose.production.yml up -d
```

后端镜像构建会运行 `backend/scripts/check_production.py`，前端镜像构建会运行 `pnpm check:production`。任一生产边界被破坏即构建失败。完整步骤见 [生产部署](docs/PRODUCTION_DEPLOYMENT.md) 与 [生产就绪检查](docs/PRODUCTION_READINESS.md)。

## 主要目录

```text
backend/app/              FastAPI、RBAC、工作流与本地适配器
backend/app/migrations.py 版本化、校验和就绪状态迁移账本
backend/tests/            核心闭环、权限和生产门禁测试
frontend/src/             React 业务与管理界面
policy/                   OPA 策略包
demo-data/                仅 development/test 的历史验收样例
docs/                     产品、权限、环境、部署与审计文档
```

## 文档入口

- [结算工作流](docs/SETTLEMENT_WORKFLOW.md)
- [角色与路由矩阵](docs/ROLE_ROUTE_MATRIX.md)
- [环境矩阵](docs/ENVIRONMENT_MATRIX.md)
- [白标配置](docs/WHITE_LABEL_GUIDE.md)
- [测试/演示污染移除审计](docs/DEMO_REMOVAL_AUDIT.md)
- [可信执行模型](docs/TRUSTED_EXECUTION_MODEL.md)
- [可信执行说明](docs/TRUSTED_EXECUTION.md)
- [可信执行运维手册](docs/TRUSTED_EXECUTION_RUNBOOK.md)
- [生产就绪检查](docs/PRODUCTION_READINESS.md)
