# 开源调研与落地记录（Round 11）

本轮把 OpenAPI 契约从“能生成文档”推进到“能对真实路由做属性测试”，新增 CI-only 的 Schemathesis 检查。

## 选型与核验

| 项目 | 许可证 / 状态 | 核验结果 | 落地方式 |
|---|---|---|---|
| [schemathesis/schemathesis](https://github.com/schemathesis/schemathesis) | MIT；未归档；GitHub API 显示 2026-08-14 有更新；最新 release 为 [v4.24.3](https://github.com/schemathesis/schemathesis/releases/tag/v4.24.3) | 面向 OpenAPI/GraphQL 的属性测试工具，可检查响应 schema、状态码、HTTP 方法覆盖和资源可用性 | 新增 `.github/workflows/api-contract.yml`，固定 4.24.3，在隔离本地 API 进程上生成确定性契约用例 |

## 代码与流程改进

- 工作流安装后端依赖和 Schemathesis，启动本地 Uvicorn，只选择无副作用的 `/api/health` 与 `/api/auth/demo-users` 路由。
- 使用 `--phases examples,coverage`、`--max-examples 2` 和 `--generation-deterministic`，让 CI 结果可重复且由 Schemathesis 自动禁用生成数据库；本地实测生成 16 个用例并全部通过。
- JUnit 与 Uvicorn 日志作为 14 天 Actions artifact 保存，失败时可复盘，不写入业务数据库或用户响应。
- workflow 的 checkout、setup-python、upload-artifact 均固定到 40 位 commit，延续仓库供应链安全约束。

## 安全边界

1. 这是 CI-only 测试依赖，不进入生产镜像和后端运行时依赖。
2. 只测试无副作用公开路由，不自动登录、不上传数据、不调用结算、隐私计算、Vault 或连接器读取路径。
3. OpenAPI schema 只从本地测试进程读取；不会向线上网站发送模糊测试流量。
4. Schemathesis 与现有 pytest/Hypothesis 是互补关系：前者从公开 API 契约覆盖方法与响应边界，后者验证领域不变量和业务状态机。

## 验证

- 本地：启动 `uvicorn app.main:app` 后运行 `st run ... --include-path-regex '^/api/(health|auth/demo-users)$'`，16 个确定性用例通过。
- GitHub：PR、`main` push 和每周计划任务运行 API Contract Tests，并保留 JUnit/log artifact。
