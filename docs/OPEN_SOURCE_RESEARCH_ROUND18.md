# 开源研究第 18 轮：ASGI 请求关联 ID

## 选型核验

- 项目：[snok/asgi-correlation-id](https://github.com/snok/asgi-correlation-id)
- 用途：为 ASGI/FastAPI 请求读取或生成关联 ID，并在响应中返回 `X-Request-ID`。
- 状态：截至 2026-08-16，仓库未归档，近期仍有提交；GitHub 最新发布为 `v5.0.1`。
- 许可：MIT；PyPI 版本固定为 `asgi-correlation-id==5.0.1`，仅依赖当前已有的 Starlette。
- 选择原因：系统已有 OpenTelemetry 可选 trace 和数据库审计 `trace_id`，该中间件补上客户端可见、可传递的请求边界，便于跨接口排查，不引入新的采集后端。

## 本轮落地

- `backend/app/main.py`：加入 `CorrelationIdMiddleware`，允许跨源客户端读取 `X-Request-ID`，健康检查公开非敏感能力状态。
- `backend/app/services/correlation.py`：固定组件版本、请求头名称和 32 位十六进制校验状态；不回显请求原文。
- `backend/app/services/common.py`：在 OpenTelemetry trace 不可用时，优先复用当前请求关联 ID，再回退到本地随机 trace ID。
- `backend/tests/test_open_source_integrations.py`：验证自动生成、合法 32 位 ID 传播和非法原始字符串拒绝，确保请求 ID 不成为未校验的输入回显通道。

## 安全边界

- 关联 ID 仅用于可观测性和审计串联，不参与 JWT、DID、OPA 或用途授权决策。
- 中间件接受符合 UUID 兼容格式的 32 位十六进制值；非法或过长值会被丢弃并重新生成，避免把任意用户输入原样写入响应/日志。
- 不记录请求体、查询参数、数据产品 ID 或原始能源数据；健康检查只返回组件能力元数据。
