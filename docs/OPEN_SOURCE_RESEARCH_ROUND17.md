# 开源研究第 17 轮：SlowAPI 登录限流

## 选型核验

- 项目：[laurentS/slowapi](https://github.com/laurentS/slowapi)
- 用途：Starlette/FastAPI 路由级限流，底层使用 `limits`，支持内存和 Redis 存储。
- 状态：截至 2026-08-16，仓库未归档，近期仍有提交；GitHub 最新发布为 `v0.1.10`。
- 许可：MIT；PyPI 可安装版本固定为 `slowapi==0.1.10`。
- 选择原因：比在业务代码中手写计数器更容易保持窗口算法和 429 响应一致，且只需给登录函数增加 `Request` 参数，不改动可信执行链路。

## 本轮落地

- `backend/app/services/rate_limit.py`：建立 SlowAPI 限流器，默认使用单实例内存存储；通过 `RATE_LIMIT_STORAGE_URI` 可切换 `redis://`/`rediss://`，不把连接串写入健康检查。
- `backend/app/routers/auth.py`：对 `POST /api/auth/login` 按来源地址施加默认 `10/minute` 限制；超限返回 HTTP 429。
- `backend/app/main.py`：注册 SlowAPI 的标准超限处理器，并在 `/api/health` 暴露版本、开关、存储模式和保护路由等非敏感状态。
- `backend/app/config.py`：增加 `RATE_LIMIT_ENABLED`、`RATE_LIMIT_STORAGE_URI` 和 `AUTH_LOGIN_RATE_LIMIT` 配置；默认保护演示环境，生产多副本应配置共享 Redis 存储。
- `backend/tests/test_open_source_integrations.py`：验证健康状态、前 10 次失败登录仍为认证失败、第 11 次命中 429，且响应不含原始数据。

## 安全边界

- 限流 key 使用来源地址，避免把用户名、密码或请求体写入限流存储。
- 只保护登录入口，不对健康检查、数据空间元数据、隐私计算和审计接口施加隐式全局限流，避免破坏现有业务语义。
- 内存存储只适合单实例离线演示；Render/生产水平扩展时必须配置 Redis，否则每个实例会各自计数。
- 429 结果由 SlowAPI 统一生成；数据库审计仍由登录路由处理，限流发生在路由函数之前时不会把攻击者请求写入审计库。
