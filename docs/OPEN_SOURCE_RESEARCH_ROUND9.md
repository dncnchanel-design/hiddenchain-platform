# 开源调研与落地记录（Round 9）

本轮把 Dataspace Protocol 目录的“字段存在性检查”升级为可重复的离线 JSON Schema 校验，并同步到网站数据目录页面。

## 选型与核验

| 项目 | 许可证 / 状态 | 核验结果 | 落地方式 |
|---|---|---|---|
| [python-jsonschema/jsonschema](https://github.com/python-jsonschema/jsonschema) | MIT；未归档；GitHub API 显示 2026-08-15 仍有更新；最新 release 为 [v4.26.0](https://github.com/python-jsonschema/jsonschema/releases/tag/v4.26.0) | Python JSON Schema Draft 2019-09 validator；本地环境已存在，但此前只是 Frictionless 的传递依赖 | 直接固定 `jsonschema==4.26.0`，在 Dataspace Protocol 目录边界执行离线 profile 校验 |
| [IDSA Dataspace Protocol 2024-1 catalog schema](https://github.com/International-Data-Spaces-Association/ids-specification/tree/2024-1/catalog/message/schema) | 上游规范仓库 Apache-2.0；2024-1 release | 官方 catalog/dataset schema 含远程 `$ref`，直接在线解析会扩大运行时网络和供应链边界 | 提取稳定字段形成小型本地 profile；保留 `dspace:transportType` 扩展，不在生产请求中下载 schema/context |

## 代码改进

- `backend/app/services/dataspace_schema.py`：定义稳定的 catalog、dataset、DataService、distribution、ODRL Offer/Permission/Constraint 本地 profile；不设置 `additionalProperties=false`，为协议扩展保留兼容性。
- `backend/app/services/dataspace.py`：使用 `Draft201909Validator` 生成确定性错误路径，同时保留协议 context/type、dataset、policy 和 service 的业务安全检查。
- `frontend/src/pages/DataSpacePage.tsx`：拉取已保护的 `/api/data/catalog/dataspace`，展示协议版本、数据集数、descriptor hash、本地校验结果和“不出域”边界。
- `backend/tests/test_open_source_integrations.py`：增加缺少 `odrl:hasPolicy` 时的 profile 回归测试，并检查 health 暴露的校验模式。

## 安全边界

1. 这是离线本地 profile，不是对全部 JSON-LD、SHACL 或 EDC 协商流程的替代；协议扩展仍需由真实参与方协商后再扩展 profile。
2. 不使用 `jsonschema` 的默认远程引用解析；生产请求不读取远程 URL，`@context` 只作为协议标识返回。
3. profile 只验证目录元数据、ODRL 用途和受控 connector URI；不会打开 `vault://`、读取原始 payload，也不会授予访问权。
4. ODRL 仍是互操作描述，OPA 的 fail-closed 决策仍是运行时授权依据。

## 验证

- 本地：`python -m pytest -q`、`python -m compileall -q app`、`python -m pip check`。
- 前端：`pnpm build`。
- GitHub：PR 必须通过 Backend Tests、OSV-Scanner、Trivy、OPA、SBOM、GitHub Actions Security 与 OpenSSF Scorecard。
