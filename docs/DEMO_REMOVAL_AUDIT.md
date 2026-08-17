# 测试与演示污染移除审计

审计目标不是删除所有测试资产，而是确保它们无法进入或伪装成 production 事实。

## 逐项审计记录

| 发现位置 | 原内容/风险 | 类型 | 处理方法 | production 可访问 | 验证结果 |
| --- | --- | --- | --- | --- | --- |
| `backend/app/seed.py` | 固定机构、账号、任务与业务数据 | C：Fixture | 改为 `seed_test_fixtures`，仅 development/test 动态导入；镜像物理删除 | 否 | production 启动与镜像门禁通过 |
| `backend/app/routers/auth.py` | 默认测试账号查询 | B/E：测试与调试入口 | 移至 `routers/test_support.py` 并按环境条件注册 | 否 | production OpenAPI 无 `/api/auth/test-users` |
| `backend/app/routers/trade.py` | 验收导入、自动运行与模拟计算模式 | B/C/E | 导入接口移至 test support；正式 Schema 只接受 `LOCAL_CONTROLLED` | 否 | production 404；非法模式返回 422 |
| `backend/app/routers/audit.py` | 异常注入入口 | E：研发调试入口 | 移至 test support；生产只保留真实风险查询与处置 | 否 | production OpenAPI 无注入路径 |
| `backend/app/routers/trust.py` | 固定可信执行示例 | D/E：占位与调试 | 移至 test support；正式查询在能力未配置时返回 503 | 否 | production OpenAPI 无示例路径 |
| `backend/app/services/adapters.py` | Mock 命名及隐含外部能力已接入 | D：占位能力 | 更名为本地真实边界；候选 MPC/TEE 标记 `NOT_CONFIGURED`、不可执行 | 仅真实本地能力 | 生产源码门禁通过 |
| `backend/app/services/workflow.py` | 模拟执行、虚假 TEE/链式成功语义 | D：虚假成功风险 | 改为应用进程内确定性结算、未提供远程证明、本地证据台账 | 否 | 回执测试核对真实能力标志 |
| `frontend/src` | 硬编码产品、机构、环境与测试入口 | A/B/E：品牌与调试混杂 | 统一读取 `/api/public/config`；测试操作由能力标志控制 | 否 | 白标测试与前端 production guard 通过 |
| `demo-data/` | 历史模拟输入与结果 | C：历史 Fixture | 保留为明确标注的非生产快照；Docker context 排除；导入端点 production 404 | 否 | `.dockerignore` 与 production 路由测试通过 |
| `start-*-demo.ps1`、旧答辩文档 | 旧比赛/离线启动流程 | B：历史开发资产 | 归档并标记非生产，不进入 production Compose | 否 | Compose 配置不引用这些脚本 |
| `blockchain_evidence`、`chain_code` | 历史表名可能被理解为已上链 | D：兼容占位 | 数据库字段保留兼容；UI 与文档统一称“证据台账”，不声称区块链确认 | 否（链能力） | 文案扫描与可信执行模型通过 |
| `docker-compose.production.yml` | 密钥、CORS、OPA 可能回退到本地默认 | E：生产配置风险 | 密钥和 HTTPS Origin 必填；OPA 本地回退关闭；环境校验 fail-closed | 不适用 | Compose 解析与配置测试通过 |

## 已完成

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 环境显式分层 | 已完成 | `APP_ENV` 只接受 development/test/production |
| production 自动灌数 | 已移除 | `TEST_FIXTURE_SEED=false` 且启动校验 |
| production 默认账户入口 | 已移除 | `/api/auth/test-users` 返回 404；生产镜像不含 `test_support.py` |
| production 验收导入 | 已移除 | `/api/settlement/import-and-run` 返回 404；生产镜像不含导入 Schema |
| production 失败注入 | 已移除 | `/api/anomalies/inject` 返回 404；生产镜像不含失败注入路由 |
| 模拟计算请求模式 | 已移除 | 正式任务 Schema 只接受 `LOCAL_CONTROLLED` |
| Mock 适配器命名 | 已移除 | 本地身份、策略、计算和证据适配器使用真实边界命名 |
| “区块链/TEE/MPC 已实现”表述 | 已移除 | UI 与权威文档明确 `NOT_CONFIGURED/NOT_PROVIDED` |
| production 配置回退 | 已移除 | 密钥、CORS、OPA 和环境标签 fail-closed |
| production 数据库污染 | 已阻断 | 启动扫描测试主体、任务、账户和历史适配器记录 |
| 前端白标硬编码 | 已移除 | `/api/public/config` 运行时注入 |
| 构建门禁 | 已完成 | 后端 Python 与前端 Node 检查均由 Dockerfile 强制执行 |

## 有意保留的非生产资产

| 资产 | 保留原因 | 隔离方式 |
| --- | --- | --- |
| `backend/app/seed.py` | 自动化与角色验收 | 仅在 fixture flag 开启时动态导入；production stage 物理删除 |
| `backend/app/routers/test_support.py`、`backend/app/test_schemas.py` | 自动化验收接口与请求模型 | development/test 条件注册；production stage 物理删除 |
| `backend/tests/` | 回归测试 | 不复制进生产镜像 |
| `demo-data/` | 历史验收样例 | 根 `.dockerignore` 排除；production 导入端点 404 |
| `start-*-demo.ps1`、`stop-*-demo.ps1` | 旧比赛/离线流程 | 不属于 production Compose；文档标记非生产 |
| `docs/*DEMO*`、早期研究文档 | 历史记录 | 非权威；权威边界以本文件和生产文档为准 |
| 数据表 `blockchain_evidence` 与字段 `chain_code` | 兼容已有数据库结构 | UI 统一称“证据台账”；生产只允许本地证据后端代码 |

## 防回归

- `backend/scripts/check_production.py` 检查 Compose、启动验证、请求 Schema、能力诚实标志与前端白标入口。
- `frontend/scripts/check-production.mjs` 拒绝生产可见的演示文案、构建时 demo/mock 开关和登录页默认凭据。
- `backend/tests/test_production_readiness.py` 验证安全配置可启动、不安全配置失败、数据库污染失败和测试账户端点隐藏。
- production 启动不会自动删除污染记录，避免不可恢复的数据操作。
