# 第六轮 GitHub 开源项目筛选与落地记录

调研时间：2026-08-16（北京时间）。本轮继续围绕 DID/VC 互认、可信数据空间、能源数据接口和用途控制边界筛选项目。选择标准是：仓库未归档、许可证可核验、近期有维护信号、能够在当前 FastAPI MVP 中形成可测试的替换边界，并且不把原始业务数据带出 Vault。

## 本轮直接落地

| 项目 | GitHub 快照 | 落地内容 | 部署代价 |
| --- | --- | --- | --- |
| [digitalbazaar/pyld](https://github.com/digitalbazaar/pyld) | 未归档；BSD-3-Clause；v3.1.0 于 2026-06-19 发布；2026-08-14 有提交；Python | `JsonLdCredentialAdapter` 使用 W3C JSON-LD 1.1/RDF Dataset Canonicalization 的 URDNA2015 为现有 DID/VC 生成稳定凭证指纹，并将状态、指纹和语句数纳入身份证据 | 低；增加 `PyLD==3.1.0`，上下文固定在应用内，不访问外部 URL |

## 重点候选与取舍

| 项目 | 维护/许可证快照 | 可复用方向 | 当前决定 |
| --- | --- | --- | --- |
| [gridstatus/gridstatus](https://github.com/gridstatus/gridstatus) | 未归档；BSD-3-Clause；v0.36.0；2026-08-13 有提交；Python | 通过统一 API 读取北美 ISO/RTO 的负荷、燃料结构、价格和预测 | 暂缓运行时引入；依赖 `plotly`、PDF/XML 解析和多套外部站点，且数据区域与当前国内能源演示不一致；保留为受控公共能源数据连接器候选 |
| [eclipse-edc/Connector](https://github.com/eclipse-edc/Connector) | 未归档；Apache-2.0；Java；2026-08-11 有提交 | Dataspace Protocol、资产/合同/策略和控制面/数据面 SPI | 继续作为 `DataSpaceConnectorAdapter` 的生产替换路线，不引入 Java 全栈 |
| [secretflow/secretflow](https://github.com/secretflow/secretflow) | 未归档；Apache-2.0；Python；2026-08-11 有仓库活动 | 多方安全计算、联邦学习、安全设备编排 | 继续通过 `ComputeAdapter` 替换，不在单机演示中引入 Kuscia 多方集群 |
| [openfga/openfga](https://github.com/openfga/openfga) | 未归档；Apache-2.0；Go；2026-08-15 有提交 | Zanzibar 风格关系授权 | 暂不增加第二套授权源；OPA 仍是用途控制主引擎，避免“双 PDP”产生不一致 |
| [cerbos/cerbos](https://github.com/cerbos/cerbos) | 未归档；Apache-2.0；Go；2026-08-15 有仓库活动 | 集中式属性策略决策 | 与 OPA 能力重叠，本轮不接入 |
| [walt-id/waltid-identity](https://github.com/walt-id/waltid-identity) | 未归档；Apache-2.0；Kotlin；2026-08-15 有提交 | DID/VC 钱包、签发与验证服务 | 保留为企业身份服务替换点，当前使用可测试的 `CallerIdentity` 边界 |
| [digitalbazaar/pyld](https://github.com/digitalbazaar/pyld) | 未归档；BSD-3-Clause；Python | JSON-LD 语义互操作和凭证规范化 | 已接入；仅用于证据指纹和格式互操作，不宣称完成签名验证 |

## 代码落地点

- `backend/app/services/credentials.py`：固定本地 JSON-LD context；调用 PyLD 的 URDNA2015；禁止远程 context；只返回非可逆哈希、状态和语句数。
- `backend/app/services/adapters.py`：`MockDidAdapter.verify_owner` 将凭证规范化结果放入身份证明，但保留原有 `credential_status=VALID` 作为当前 MVP 的验证闸门。
- `backend/app/services/trust_execution.py`：`CallerIdentity` 记录 `credential_hash` 与规范化状态，供可信执行审计回执关联。
- `backend/app/main.py`：`/api/health` 的 `integrations.credential_canonicalization` 返回安全能力状态。
- `backend/tests/test_open_source_integrations.py`：覆盖字段顺序变化得到同一指纹，以及远程 context 被拒绝。

## 安全边界

1. 规范化只接收数据库中的凭证 JSON，不读取 Vault 原始数据，也不把凭证正文写入审计事件。
2. 任何字符串形式的 `@context`、列表中的远程 context 或 `@import` 都被拒绝，避免通过 PyLD 触发 SSRF、供应链内容漂移或不可审计的远程语义变化。
3. 应用内固定 context 只覆盖演示所需的 VC、能源主体和 Agent 能力字段；未覆盖的生产凭证必须先完成 context 治理和兼容性测试。
4. PyLD 规范化哈希是可移植证据指纹，不等于 DID 文档解析、密钥证明验证或吊销检查；正式身份生产化仍应接入 walt.id/企业身份服务并保留当前 fail-closed 角色校验。
5. OPA、人工确认、结果审计和原始数据不出域的边界不因增加 JSON-LD 处理而改变。

## 本轮结论

在已有 OPA、OpenDP、OpenLineage、OpenTelemetry、Prometheus、pvlib、pandapower、Frictionless、Apache Arrow 和供应链安全工作流基础上，本轮优先补齐 DID/VC 的语义规范化证据，而不是重复增加授权引擎或重型数据空间服务。`gridstatus` 具备较好能源 API 价值，但其运行时依赖和区域属性需要独立的外部数据接入审批，暂不进入当前演示发布链。
