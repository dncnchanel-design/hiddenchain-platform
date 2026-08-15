# 第五轮 GitHub 开源项目筛选与落地记录

调研时间：2026-08-15（北京时间）。本轮目标是继续提升“可信数据调用 + 隐私计算 + 可溯审计”主链，同时保持当前 Python/FastAPI + React/TypeScript MVP 的可运行性。项目维护状态、许可证和仓库活跃度以本轮 GitHub API 快照为准，后续正式发布前仍需再次核验。

## 本轮直接落地

| 项目 | GitHub 快照 | 落地内容 | 部署代价 |
| --- | --- | --- | --- |
| [opendp/opendp](https://github.com/opendp/opendp) | 未归档；MIT 许可证；2026-08-14 有提交；Rust + Python 绑定 | `OpenDPAdapter` 对用户负荷群组执行有界求和 + Laplace 差分隐私输出，记录 epsilon、边界、组合次数和后处理标记 | 低；Python 运行时增加一个有 ABI wheel 的依赖 |
| [open-telemetry/opentelemetry-python](https://github.com/open-telemetry/opentelemetry-python) | 未归档；Apache-2.0；2026-08-15 有提交；Python | 可选 FastAPI 自动追踪；现有 `AuditLog.trace_id` 在有活动 span 时自动复用 OTel trace ID；支持 OTLP HTTP 或控制台导出 | 低；默认关闭，不需要改业务请求 |
| [OpenLineage/OpenLineage](https://github.com/OpenLineage/OpenLineage) | 未归档；Apache-2.0；2026-08-15 有提交；标准 JSON Schema | 生成标准 RunEvent JSONL；仅写数据产品标识、承诺、哈希、策略哈希和安全标记，不写 Vault 路径或原始记录；审计接口可按 run 查询 | 低；默认写持久化 runtime 卷，可选 HTTP collector |
| [google/osv-scanner](https://github.com/google/osv-scanner) + [google/osv-scanner-action](https://github.com/google/osv-scanner-action) | 未归档；Apache-2.0；2026-08-14/08-07 有更新；支持 Python、Node、容器等依赖扫描 | 新增 `.github/workflows/osv-scanner.yml`，固定到 v2.5.0 对应提交，同时覆盖 PR 增量和定期全量扫描 | 低；只影响 GitHub Actions，不改运行时 |
| [anchore/syft](https://github.com/anchore/syft) + [anchore/sbom-action](https://github.com/anchore/sbom-action) | 未归档；Apache-2.0；Syft 2026-08-14 有提交，SBOM Action 2026-08-14 有提交 | 新增 `.github/workflows/sbom.yml`，生成 CycloneDX JSON SBOM 并作为短期 GitHub Actions artifact 保存，便于依赖审计和发布前核验 | 低；只影响 GitHub Actions，不进入业务请求路径 |
| [aquasecurity/trivy](https://github.com/aquasecurity/trivy) + [aquasecurity/trivy-action](https://github.com/aquasecurity/trivy-action) | 未归档；Apache-2.0；Trivy 2026-08-14 有提交，Action 2026-08-14 有提交 | 新增 `.github/workflows/trivy.yml`，审计依赖漏洞、密钥、IaC 配置和许可证，并保留 14 天 JSON artifact | 低；当前为报告型扫描，不把偶发历史漏洞直接变成发布阻断 |
| [zizmorcore/zizmor](https://github.com/zizmorcore/zizmor) + [zizmorcore/zizmor-action](https://github.com/zizmorcore/zizmor-action) | 未归档；MIT；zizmor 2026-08-13 有提交，Action 2026-08-15 有提交 | 新增 `.github/workflows/zizmor.yml`，审计 GitHub Actions 的不安全权限、浮动依赖和供应链配置 | 低；仅扫描工作流文件，使用固定 action 提交 |
| [prometheus/client_python](https://github.com/prometheus/client_python) | 未归档；Apache-2.0；v0.26.0 于 2026-07-24 发布，2026-08-13 有提交 | 新增专用 registry、低基数 HTTP middleware 和受角色保护的 `/api/metrics/prometheus`，用于接入 Prometheus/Grafana | 低；只输出方法、路由模板、状态和耗时，不输出业务 ID、查询参数或请求体 |
| [pvlib/pvlib-python](https://github.com/pvlib/pvlib-python) | 未归档；BSD-3-Clause；v0.15.2 于 2026-06-16 发布，2026-08-10 有提交 | 新增 `/api/energy/solar/evaluate`，计算太阳位置和组件面辐照度，并以输入哈希关联新能源资源校核 | 中；依赖 pandas/scipy 生态，作为可替换能源模型，不越过隐私和电网安全闸门 |

## 重点候选与取舍

| 项目 | 维护/许可证快照 | 可复用方向 | 当前决定 |
| --- | --- | --- | --- |
| [eclipse-edc/Connector](https://github.com/eclipse-edc/Connector) | 未归档；Apache-2.0；2026-08-11 有提交；Java | Dataspace Protocol、控制面/数据面 SPI、资产/合同/策略对象 | 继续作为 `DataSpaceConnectorAdapter` 的协议替换候选，不引入 Java 全栈 |
| [eclipse-edc/IdentityHub](https://github.com/eclipse-edc/IdentityHub) | 未归档；Apache-2.0；2026-08-15 有提交；Java | Participant identity、DID/VC 与信任框架 | 后续接入企业身份服务，当前保留 `CallerIdentity` 可测试边界 |
| [eclipse-tractusx/tractusx-edc](https://github.com/eclipse-tractusx/tractusx-edc) | 未归档；Apache-2.0；2026-08-14 有提交；Java | 双 Connector、数据平面、Vault/PostgreSQL/Helm 部署经验 | 适合部署试验环境，暂不进入单机 MVP |
| [secretflow/secretflow](https://github.com/secretflow/secretflow) / [secretflow/spu](https://github.com/secretflow/spu) | 未归档；Apache-2.0；SecretFlow 2026-04 有代码提交，2026-08 仍有仓库活动 | MPC、联邦学习、安全设备抽象 | 继续通过 `ComputeAdapter` 替换；不在演示环境引入 Kuscia 多方集群 |
| [OpenMined/PySyft](https://github.com/OpenMined/PySyft) | 未归档；Apache-2.0；2026-08-14 有提交 | 数据留在主方、审批后执行受控作业 | 借鉴“数据主方批准”交互，不替代现有监管人工复核 |
| [open-policy-agent/opa](https://github.com/open-policy-agent/opa) | 未归档；Apache-2.0；2026-08-14 有提交 | Rego PDP、策略输入/决策哈希、fail-closed 生产配置 | 已接入，继续作为用途控制主引擎 |
| [e2nIEE/pandapower](https://github.com/e2nIEE/pandapower) | 未归档；2026-08-14 有提交；GitHub API 许可证字段需发布前复核 | 三母线潮流和安全闸门 | 已接入，保留 `PANDAPOWERGridAdapter` 替换边界 |
| [powsybl/powsybl-core](https://github.com/powsybl/powsybl-core) | 未归档；MPL-2.0；2026-08-14 有提交；Java | 更强的电力系统分析框架 | 后续生产电网适配候选，当前不替换 pandapower |
| [PyPSA/PyPSA](https://github.com/PyPSA/PyPSA) | 未归档；MIT；2026-08-15 有提交；Python | 多区域能源系统规划和优化 | 可用于规划类场景，和当前“可信调用执行层”边界不同，暂不引入 |
| [walt-id/waltid-identity](https://github.com/walt-id/waltid-identity) | 未归档；Apache-2.0；2026-08-15 有提交；Kotlin | DID/VC 钱包、签发与验证 | 适合身份生产化，但会引入独立服务和密钥治理，暂缓 |
| [codenotary/immudb](https://github.com/codenotary/immudb) | 未归档；GitHub API 许可证字段为 NOASSERTION；2026-08-03 有提交 | 不可篡改 SQL/KV 审计存储与历史验证 | 先不引入；许可证和运维边界需单独尽调，当前哈希链足够支撑 MVP |
| [cerbos/cerbos](https://github.com/cerbos/cerbos) / [openfga/openfga](https://github.com/openfga/openfga) | 未归档；Apache-2.0；2026-08-13/15 有活动 | 集中式授权、关系型权限模型 | 与现有 OPA + DID/VC 重叠，暂不增加第二套授权源 |
| [FederatedAI/FATE](https://github.com/FederatedAI/FATE) | 未归档；Apache-2.0；2024-11-19 有代码提交，仓库问题活动较新 | 工业级联邦学习编排 | 维护信号弱于 SecretFlow/OpenDP，本轮只列为替代候选 |
| [aquasecurity/trivy](https://github.com/aquasecurity/trivy) / [aquasecurity/trivy-action](https://github.com/aquasecurity/trivy-action) | 未归档；Apache-2.0；Trivy 2026-08-14 有提交，Action 2026-08-14 有提交 | 文件系统、镜像、IaC、密钥和漏洞扫描 | 与 OSV/SBOM 有交集；保留为下一轮容器镜像和部署配置扫描候选，避免本轮引入过重 CI 门禁 |

## 代码落地点

- `backend/app/services/privacy.py`：OpenDP 适配器；DP 运行时不可用时对差分隐私请求 fail-closed。
- `backend/app/services/observability.py`：OTel 可选 FastAPI tracing，默认不开启。
- `backend/app/services/lineage.py`：OpenLineage 2.0.2 RunEvent 生成、JSONL 持久化、可选 HTTP 推送和按 run 查询。
- `backend/app/services/common.py`、`workflow.py`、`trust_execution.py`：审计和可信执行与 lineage/trace 关联。
- `backend/app/routers/audit.py`：`GET /api/audit/lineage/{run_id}`，只返回脱敏血缘事件。
- `.github/workflows/osv-scanner.yml`：依赖漏洞扫描，使用固定提交，避免浮动 action tag。
- `.github/workflows/sbom.yml`：使用 Syft 生成 CycloneDX SBOM artifact，使用固定提交，避免浮动 action tag。
- `.github/workflows/trivy.yml`、`.github/workflows/zizmor.yml`：分别审计运行时依赖/部署配置和 Actions 供应链，均固定 action 提交。
- `backend/app/services/prometheus.py`、`backend/app/services/solar.py`、`backend/app/routers/energy.py`：分别提供低基数 Prometheus 指标和 pvlib 新能源资源计算接口。
- `backend/requirements.txt`、`.env.example`、`production.env.example`、Compose 文件：运行时和部署配置。

## 安全边界

1. OpenDP 只处理授权后的群组曲线；输入先按配置上界裁剪，输出再做非负/上限后处理，绝不返回单户曲线。
2. OpenLineage 只接收产品 ID、承诺、摘要哈希和结果哈希；禁止把 `data_ref`、Vault 内容、用户标识或原始负荷序列写入事件。
3. OpenTelemetry 默认关闭；开启后只导出路由、耗时、状态和 trace 关联，不把请求体作为业务证据发送。
4. OSV-Scanner 只扫描依赖清单、锁文件和容器/仓库元数据，不把业务数据上传到扫描器；当前仓库未启用 GitHub Code Scanning，因此保留 JSON/SARIF artifact，不上传 Security 代码扫描面板。
5. SBOM 工作流只上传依赖组件清单，不包含 `backend/runtime`、业务上传文件或请求数据；artifact 默认只保留 14 天。
6. Trivy 当前设置为报告型扫描（`exit-code: 0`），避免历史依赖告警阻断演示发布；转生产前应按团队风险门槛改为关键/高危阻断并处理例外。
7. Prometheus 指标使用专用 registry 和路由模板标签，且端点需要监管或管理员 token；不得把数据产品 ID、DID、查询参数或原始负荷放入 labels。
8. pvlib 只输出太阳几何和辐照度派生结果，输入通过哈希关联；它不能替代 pandapower 的电网安全校核、OPA 策略或人工确认。
9. EDC、SecretFlow、walt.id、immudb 等重型能力仍必须经过真实部署、许可证、密钥管理和故障演练后才能进入生产边界；它们不能绕过 OPA、结果审计或人工确认。

## 本轮结论

当前最稳妥的路线仍然是“基于现有系统改造”：用 OpenDP 补齐差分隐私，用 OpenLineage + OpenTelemetry + Prometheus 补齐可观测性和血缘，用 pvlib + pandapower 补齐能源模型和电网安全校核，用 OSV-Scanner + Syft + Trivy + zizmor 把依赖、部署和工作流供应链安全纳入 GitHub 流程；EDC/SecretFlow/真实 DID 服务保留为适配器替换路线，不因追求开源数量而扩大部署和审计风险。
