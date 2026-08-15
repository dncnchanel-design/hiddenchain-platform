# 开源调研与落地记录（Round 15）

本轮引入 Open Data Contract Standard（ODCS）v3.1.0 的数据合同投影，让能源目录同时具备 Frictionless、Dataspace Protocol 和数据合同标准的可互操作描述。

## 选型与核验

| 项目 | 许可证 / 状态 | 核验结果 | 落地方式 |
|---|---|---|---|
| [bitol-io/open-data-contract-standard](https://github.com/bitol-io/open-data-contract-standard) | Apache-2.0；未归档；GitHub API 显示 2026-08-05 仍有更新 | 仓库包含 ODCS v3.1.0 JSON Schema，并将 `DataContract`、`servers`、`schema`、`customProperties` 等字段标准化 | `OpenDataContractAdapter` 生成脱敏能源数据产品合同，并执行仓库内固定的 v3.1.0 required-fields/privacy profile |

## 代码与流程改进

- `backend/app/services/odcs_connector.py`：把已脱敏目录字段映射为 ODCS `DataContract` descriptor；每个合同仅发布字段类型、连接器入口、用途和敏感级别，不写入 DataRef、Vault URI 或原始值。
- `backend/app/services/datapackage.py`：Frictionless package 的 `custom.hiddenchain.odcs_contracts` 返回合同列表、合同指纹和本地 profile 校验结果。
- `backend/app/main.py`、`backend/app/routers/trade.py`、`frontend/src/pages/DataSpacePage.tsx`：健康状态、协议能力和数据目录页面同步展示 ODCS 版本。
- `backend/tests/test_open_source_integrations.py`：验证合同数量、v3.1.0 字段、隐私边界和校验状态。

## 安全边界

1. 只使用仓库内的 ODCS 字段映射和 required-fields/privacy profile，不在请求路径中联网拉取第三方 schema。
2. `servers` 只发布 `connector://` 入口，未发布本地文件路径、数据库凭据或 Vault 地址。
3. `customProperties.hiddenchainRawDataExposed` 固定为 `false`；ODCS 描述不授予访问权，真实用途授权仍由 OPA 执行。
4. 数据合同的 `contract_hash` 和 `contracts_hash` 只对描述性元数据做指纹，不能被当作原始数据证明。

## 验证

- 本地：开放集成测试验证 ODCS 合同投影，随后运行全量后端测试、覆盖率、编译检查、`pip check` 和前端构建。
- GitHub：主干现有 Backend Tests、Schemathesis、Bandit、OSV、Trivy、SBOM、OPA、SHACL 和 Actions 安全流程继续覆盖该标准投影。
