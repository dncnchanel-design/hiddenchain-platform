# 开源项目调研与本次改造依据

调研时间：2026-08-14。目标是为“面向能源云多主体数据共享的可信智能执行层”寻找可直接复用的能力，同时保持当前 MVP 的 Python/FastAPI + React/TypeScript 架构，不把系统重写成某个大型 IoT 平台。

## 结论先行

当前阶段继续基于本项目改造最合适：

1. 可信策略、DID/VC、审计留痕、结果复核属于本赛题的差异化能力，现成平台无法直接替代。
2. ThingsBoard、OpenEMS、Grafana、Superset 可以借鉴信息架构和可视化交互，但整体引入会带来 Java/插件/时序库/多租户/集群等额外部署成本。
3. PowSyBl 适合作为后续电力潮流/安全分析适配器，不适合现在替换现有 pandapower MVP。
4. 本轮前端已经采用“能源运营控制台”模式：深色控制平面、状态带、数据面板、事件时间线和人工复核；自然语言/解释服务退到可选工具位。

## 项目对比

| 项目 | 维护信号（调研快照） | 部署与改造成本 | 可复用方向 | 本项目决策 |
| --- | --- | --- | --- | --- |
| [OpenEMS/openems](https://github.com/OpenEMS/openems) | AGPL-3.0；约 1.5k stars；2026-08-13 仍有提交 | 高：Edge、Backend、UI、设备适配器组成完整能源栈 | 能源流中心图、设备/储能状态卡、Edge/Cloud 分层 | 借鉴布局，不直接引入 AGPL 代码 |
| [openremote/openremote](https://github.com/openremote/openremote) | 约 1.8k stars；2026-08-13 仍有提交；仓库 API 未给出明确 SPDX | 高：IoT、资产、规则、身份和设备接入一体化 | 资产树、规则、告警、边缘设备管理 | 只借鉴资产/规则导航，暂不引入整栈 |
| [thingsboard/thingsboard](https://github.com/thingsboard/thingsboard) | Apache-2.0；约 22k stars；2026-08-13 仍有提交 | 中高：Java 服务、时序/消息组件和多租户能力较重 | SCADA 仪表盘、设备/告警/趋势分层、规则链、Gateway | 借鉴控制台布局和告警模型 |
| [grafana/grafana](https://github.com/grafana/grafana) | AGPL-3.0；约 76k stars；2026-08-14 仍有提交 | 中：独立部署快，但要接入数据源、权限和面板管理 | 可组合面板、时间范围、状态/日志/指标联动 | 借鉴面板密度和状态表达，不嵌入 Grafana |
| [apache/superset](https://github.com/apache/superset) | Apache-2.0；约 74k stars；2026-08-14 仍有提交 | 高：Python Web、元数据数据库、缓存/异步任务和前端构建 | 报表、筛选器、可视化探索、数据集权限 | 仅借鉴报表和过滤器，不替换当前前端 |
| [powsybl/powsybl-core](https://github.com/powsybl/powsybl-core) / [open-loadflow](https://github.com/powsybl/powsybl-open-loadflow) | MPL-2.0；2026-08-13 仍有提交 | 中高：Java/Maven，电力模型和算法接入需专业建模 | 潮流、灵敏度、安全分析适配器 | 作为后续计算插件候选 |
| [OpenLEADR/openleadr-rs](https://github.com/OpenLEADR/openleadr-rs) | Apache/MIT 信息以仓库声明为准；2026-08-13 仍有提交 | 中：Rust 服务 + PostgreSQL + Docker；协议侧部署独立 | OpenADR VTN/VEN、需求响应事件与资源授权 | 作为未来需求响应连接器候选，不进入当前核心链路 |
| [GRIDAPPSD/GOSS-GridAPPS-D](https://github.com/GRIDAPPSD/GOSS-GridAPPS-D) / [gridappsd-viz](https://github.com/GRIDAPPSD/gridappsd-viz) | 未在 API 快照中给出统一 SPDX；2026-08-10/02-19 仍有提交 | 高：Java 消息总线、CIM/拓扑模型、Docker 运行时 | 配电网拓扑、仿真应用、可视化工作台 | 借鉴拓扑与设备状态表达，不引入整套运行时 |
| [Grid2op/grid2op](https://github.com/Grid2op/grid2op) | MPL-2.0；2026-06-19 有提交、2026-08-11 有仓库更新 | 中：Python 仿真测试环境，不是面向业务用户的生产控制台 | 潮流安全场景、调度动作、策略回归与压力测试 | 作为后续安全策略测试夹具 |
| [bbartling/OpenADR-2B-PyServer](https://github.com/bbartling/OpenADR-2B-PyServer) | MIT；仓库已于 2025-12-25 归档 | 低到中，但维护风险已不可接受 | OpenADR Web 控制台示例 | 排除，不作为依赖或生产基线 |

维护状态以上述 GitHub 仓库页面和 API 在调研时间的公开信息为准；stars、issue 数和最近提交只用于判断活跃度，不等同于项目质量保证。

### 第二轮筛选结论

- **协议适配优先**：OpenLEADR 只放在 `EnergyNode`/需求响应连接器边界，不能越过当前策略引擎和人工确认闸门。
- **拓扑计算隔离**：GridAPPS-D、Grid2Op 的模型或测试能力可以服务电力安全校核，但原始拓扑仍留在电力主体域，结果只回到 `ComputeReceipt` 和审计凭证。
- **维护优先于“看起来能跑”**：已归档的 OpenADR Web 服务不纳入候选；大型 Java/CIM 栈不作为 MVP 的直接依赖。

## 从公开平台提炼的界面模式

- OpenEMS：把生产、负荷、储能、并网等能源流放在一个中心视图，周围用小型实时指标补充上下文。
- ThingsBoard SCADA：以设备/子系统/告警为一级导航，中心是状态和趋势，操作按钮只出现在对应设备卡片，不把聊天当作主入口。
- Grafana：面板可组合、时间范围和状态筛选优先，指标、日志和事件形成同一条观察链。
- Superset：筛选条件、数据集权限和报表发布状态清楚分层，适合审计报表而不是实时控制。

因此，本项目本轮选择：

```text
能源运营域
  ├─ 控制平面：主体、策略版本、服务状态、原始数据边界
  ├─ 数据平面：数据目录、汇总指标、趋势、计算回执
  └─ 证据平面：事件时间线、哈希、DID 签名、人工确认、链上凭证
```

自然语言和解释服务仍保留为受控能力，但不再承担主导航、主指标或主视觉焦点；确定性策略和人工审计确认是主流程。

## 当前改造落点

- `frontend/src/components/layout.tsx`：隐藏重复的门户级导航，保留单一控制顶栏和深色运营侧栏。
- `frontend/src/styles.css`：增加 operations console v2 视觉层，统一状态带、指标卡、证据面板、响应式规则。
- `frontend/src/pages/OverviewPage.tsx`：增加安全边界、计算复核、链上队列状态带。
- `frontend/src/pages/AgentsPage.tsx`：将“智能协助”重命名为“能力编排”，显示任务、链路、哈希和签名，而不是聊天/模型能力。
- `frontend/src/pages/AuditPage.tsx`：将“审计助手”重命名为“受控检索”，强调证据索引和复核结果。

## 后续候选路线

1. 近期：继续使用当前页面与后端接口，补充跨能源趋势卡、策略命中解释和人工确认队列。
2. 中期：把 `EnergyNodeRegistry` 的节点接口映射到 OpenEMS/ThingsBoard Gateway 风格的标准适配器，但不把原始数据汇聚到平台库。
3. 算法增强：用 PowSyBl 或成熟潮流引擎替换特定电网安全计算适配器，保持现有 `ComputeReceipt`、结果哈希和审计接口不变。
4. 报表增强：只在审计报表需要时引入 Superset/Grafana 的导出或嵌入能力，避免为 MVP 引入整套运行时依赖。
