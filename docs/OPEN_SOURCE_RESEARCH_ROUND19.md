# 开源研究第 19 轮：OpenAPI 规范验证

本轮补齐 API 契约的静态规范门禁。已有 Schemathesis 会对真实路由做确定性请求和响应契约测试，但它不能替代对 FastAPI 导出文档本身进行 OpenAPI 规范校验；本轮将官方 Python 校验器加入同一条 API Contract Tests 工作流。

## 选型核验

- 项目：[python-openapi/openapi-spec-validator](https://github.com/python-openapi/openapi-spec-validator)
- 用途：校验 OpenAPI 2.0、3.0 和 3.1 文档的结构与规范约束，并提供 CLI 与 Python 包接口。
- 状态：截至 2026-08-16，仓库未归档，GitHub API 显示 2026-08-10 有更新；最新发布为 `0.9.0`。
- 许可：Apache-2.0；CI 固定 `openapi-spec-validator==0.9.0`。
- 选择原因：与现有 Schemathesis 形成互补，直接验证运行中的 `/api/openapi.json`，比只检查静态路由或手写字段更接近实际部署契约。

## 本轮落地

- `.github/workflows/api-contract.yml`：在启动本地 FastAPI 后下载实际生成的 OpenAPI 文档，使用 `python -m openapi_spec_validator` 做规范验证，再运行已有 Schemathesis 确定性契约测试。
- 校验依赖只安装在 GitHub Actions，不加入 `backend/requirements.txt`，不进入 Render 运行时和业务请求路径。
- OpenAPI 文档只在 CI 临时目录中处理，不上传业务数据，也不向线上网站发送测试请求。

## 安全边界

1. 规范验证只检查 API 描述文档，不授予数据目录、隐私计算、审计或结算权限；实际授权仍由 JWT、OPA 和可信执行控制器负责。
2. CI 使用本地测试进程生成的文档，避免把模糊测试流量发送到生产站点。
3. Schemathesis 继续负责无副作用公开路由的行为和响应测试；OpenAPI Spec Validator 负责文档规范一致性，两者失败原因可独立定位。

## 验证

- 本地可用 `python -m openapi_spec_validator` 校验生成的 `/api/openapi.json`。
- GitHub API Contract Tests 在 PR、`main` push、每周计划任务和手工触发时同时运行规范校验与 Schemathesis。
