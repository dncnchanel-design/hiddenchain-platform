# 隐链明算

面向电力交易结算的数据授权、受控计算、结果确认与审计追溯平台。

## 当前可用范围

系统已经形成以结算任务为主线的闭环：

`任务创建 → 主体确认 → 数据就绪 → 规则授权 → 本地受控计算 → 结果生成 → 双边确认 → 审计完成`

- 交易中心通过五步向导创建任务，前置条件不足时保存任务并显示阻塞项。
- 发电与售电主体维护本组织数据引用，只能查看和确认本方结果。
- 监管方复核证据、异常与报告；管理员维护组织、身份、指标和日志。
- 数据、规则、计算、结果、证据、审计、异常和报告均可按 `task_id` 返回任务详情。
- 产品名、Logo、客户、运营方、建设方、版权、支持信息和登录公告支持运行时白标。

## 能力边界

本版本执行 `LOCAL_CONTROLLED_SETTLEMENT_V1` 单进程确定性结算，并把摘要写入 `LOCAL_EVIDENCE_LEDGER_V1` 本地数据库证据台账。API 不返回 Vault 原始记录。

这不等于真实 MPC、TEE、区块链存证或跨主体不出域证明。相关方案仅作为 `NOT_CONFIGURED` 候选项展示，未接入外部运行时和证明前不会显示为已实现。详见 [可信执行模型](docs/TRUSTED_EXECUTION_MODEL.md)。

## 环境

| 环境 | 用途 | 测试夹具/账户 | 策略回退 | 生产门禁 |
| --- | --- | --- | --- | --- |
| `development` | 本地开发 | 允许 | 允许 | 否 |
| `test` | 自动化与验收 | 允许 | 允许 | 否 |
| `production` | 正式部署 | 禁止 | 禁止 | 是 |

生产启动会校验密钥、CORS、OPA、环境标签和数据库内容；发现测试账户、测试任务或历史模拟适配器记录时拒绝启动，不会自动删除数据。

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
- [生产就绪检查](docs/PRODUCTION_READINESS.md)
