# 环境矩阵

## 行为差异

| 控制项 | development | test | production |
| --- | --- | --- | --- |
| `APP_ENV` | `development` | `test` | `production` |
| 自动测试夹具 | 可开启 | 可开启 | 强制关闭 |
| `/api/auth/test-users` | 可用 | 可用 | 404 |
| 验收文件导入并运行 | 可用 | 可用 | 404 |
| 测试异常注入 | 可用 | 可用 | 404 |
| 跨能源固定样例 | 可用 | 可用 | 404 |
| 测试计算延迟 | 可配置 | 可配置 | 必须为 0 |
| OPA 本地回退 | 可用 | 可用 | 必须关闭 |
| 默认本地密钥 | 允许 | 允许 | 拒绝启动 |
| localhost / `*` CORS | 允许 | 允许 | 拒绝启动 |
| 环境标签 | 开发环境 | 测试环境 | 默认不显示 |
| 数据库夹具扫描 | 不阻断 | 不阻断 | 发现即拒绝启动 |
| 静态生产构建门禁 | 可手动 | CI 可运行 | 镜像构建强制运行 |

## 推荐数据隔离

- 三个环境使用不同数据库、Vault 路径、密钥、域名和 OPA 实例。
- 不把 development/test 数据库复制到 production；生产守卫只拒绝，不负责清洗。
- production 首次启动使用空白库，再通过正式身份接入或受审计迁移导入主体与规则。
- 测试账户密码只存在于 `backend/app/seed.py` 和测试上下文，不得作为生产初始账户策略。

## 发布检查

1. 运行 `backend/scripts/check_production.py`。
2. 运行 `pnpm --dir frontend check:production`。
3. 运行全部后端和前端测试。
4. 用 `.env.production` 执行 `docker compose ... config`，确认必填变量已解析。
5. 在隔离生产库启动，确认 `/api/health` 的 `environment` 为 `production`。
