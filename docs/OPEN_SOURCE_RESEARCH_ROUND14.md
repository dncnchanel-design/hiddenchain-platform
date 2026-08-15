# 开源调研与落地记录（Round 14）

本轮把 DuckDB 引入为数据空间目录的元数据分析适配器，用于在连接器边界上给出产品分组、登记记录数和敏感产品数等摘要，不把 DuckDB 变成原始能源数据查询入口。

## 选型与核验

| 项目 | 许可证 / 状态 | 核验结果 | 落地方式 |
|---|---|---|---|
| [duckdb/duckdb](https://github.com/duckdb/duckdb) | MIT；未归档；GitHub API 显示 2026-08-14 仍有更新；最新 release 为 v1.5.5 | 嵌入式分析数据库，适合固定 SQL 的本地聚合；无需部署独立服务 | `DuckDBMetadataAdapter` 固定版本 1.5.5，使用临时内存表聚合目录元数据 |

## 代码与流程改进

- `backend/app/services/duckdb_connector.py`：只接收 `DataSpaceConnectorAdapter.catalog` 已脱敏的字段，创建内存表并执行仓库内固定 SQL；不接受请求中的 SQL，也不注册 Vault URI、业务数据库或原始 payload。
- `backend/app/services/datapackage.py`：在 Frictionless 目录结果中增加 `duckdb_analytics` 摘要和查询指纹。
- `backend/app/main.py`、`backend/app/routers/trade.py`、`frontend/src/pages/DataSpacePage.tsx`：暴露适配器健康状态并在数据目录页展示固定只读聚合能力。
- `backend/tests/test_open_source_integrations.py`：验证版本、安装状态、只读标志、分组摘要和查询指纹。

## 安全边界

1. DuckDB 连接始终是 `:memory:`，连接关闭后不留下数据库文件。
2. SQL 文本是代码常量，API 不提供任意 SQL、表名或文件路径参数。
3. 输入只包含资产类型、敏感级别、校验状态和目录登记记录数；原始 payload、`vault://` 路径、DataRef 和企业明细不进入 DuckDB。
4. 返回值只包含分组计数与固定查询指纹；OPA 仍是实际用途授权闸门，DuckDB 不改变策略判定。

## 验证

- 本地：目录集成测试覆盖 DuckDB 摘要，随后运行全量后端测试、编译检查和依赖一致性检查。
- GitHub：现有 Backend Tests、Schemathesis、Bandit、OSV、Trivy、SBOM、OPA、SHACL 和 Actions 安全流水线继续保护该改动。
