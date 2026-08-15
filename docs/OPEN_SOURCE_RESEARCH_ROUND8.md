# 第八轮 GitHub 开源项目筛选与落地记录

调研时间：2026-08-16（北京时间）。本轮回到可信数据空间协议主线，优先复用 IDSA 的 Dataspace Protocol 规范，而不是把 Eclipse EDC 的 Java 控制面和数据面整体搬入单机 MVP。

## 本轮直接落地

| 项目 | GitHub 快照 | 落地内容 | 部署代价 |
| --- | --- | --- | --- |
| [International-Data-Spaces-Association/ids-specification](https://github.com/International-Data-Spaces-Association/ids-specification) | 未归档；Apache-2.0；2024-1 release；仓库 2026-07-22 有更新；Dataspace Protocol 规范与 JSON Schema | 新增 `/api/data/catalog/dataspace`，把现有 connector 元数据映射为 `dcat:Catalog`、`dcat:Dataset`、`dcat:DataService` 和 `odrl:Offer`；内置协议字段契约校验 | 低；不新增运行时依赖，不接入 EDC Java 服务 |

## 协议映射

| 本地能力 | Dataspace Protocol 2024-1 字段 | 安全处理 |
| --- | --- | --- |
| 数据产品目录 | `dcat:Catalog` / `dcat:Dataset` | 仅发布产品 ID、语义引用、标题、关键字和协议版本 |
| 连接器入口 | `dcat:DataService` / `dcat:endpointURL` | 只给 `connector://` URI，不给 Vault 路径或原始 HTTP 源站 |
| 用途限制 | `odrl:hasPolicy` / `odrl:permission` / `odrl:constraint` | 映射允许用途和传输协议；真实调用仍必须再次经过 OPA |
| 参与方 | `dspace:participantId` / `odrl:assigner` | 使用平台/主体 DID 或受控 participant URI，不输出用户身份详情 |

## 重点候选与取舍

- [eclipse-edc/Connector](https://github.com/eclipse-edc/Connector)：Apache-2.0、Java、近期维护活跃，适合下一阶段真实 control plane/data plane；当前保留为 `DataSpaceConnectorAdapter` 替换点，避免为演示引入 Java 服务、数据库和密钥治理。
- [gridstatus/gridstatus](https://github.com/gridstatus/gridstatus)：BSD-3-Clause、Python、提供北美 ISO/RTO 数据；依赖 PDF/XML/Plotly 且区域不匹配当前国内能源演示，继续作为经外部数据审批后接入的公共数据连接器候选。
- [w3c/odrl](https://github.com/w3c/odrl)：社区规范仓库近期有活动，但 GitHub 许可证字段未明确；本轮使用 IDSA 规范中引用的 ODRL 字段，不复制未核验许可证的仓库代码或上下文文件。

## 代码落地点

- `backend/app/services/dataspace.py`：构造可互操作的 2024-1 catalog projection，生成确定性 descriptor hash，并校验 context、catalog type、dataset、policy 和 service 的稳定字段。
- `backend/app/routers/data.py`：新增 `GET /api/data/catalog/dataspace`，沿用现有角色隔离和目录过滤。
- `backend/app/main.py`：健康检查暴露协议适配器状态。
- `backend/tests/test_open_source_integrations.py`：验证协议目录结构、schema validation 和无 Vault/原始负荷字段。

## 安全边界

1. 该接口是协议目录投影，不是数据转移接口；不会读取 Vault payload，也不会因为发布 catalog 就授予访问权。
2. `schema_validation` 只覆盖当前稳定且可本地判断的 2024-1 字段，不能替代完整 JSON Schema、SHACL、EDC 协商或参与方身份验证。
3. 所有 `dcat:endpointURL` 必须是受控 connector URI；原始数据读取、用途检查、使用次数和结果审计仍由现有连接器、OPA 和可信执行闭环负责。
4. ODRL policy 是跨数据空间互操作描述，不是第二个运行时 PDP；服务端仍以 OPA 的 fail-closed 决策为授权依据。

## 本轮结论

系统现在同时有本地 HCDS-1.0 连接器语义、Frictionless/Arrow 目录互操作和 IDSA Dataspace Protocol 2024-1 的 DCAT/ODRL 协议投影，下一阶段可以把 EDC 或其他真实 connector 接到同一适配器边界，而不改变隐私、策略和审计闸门。
