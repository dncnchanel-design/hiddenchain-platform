# 第三轮开源项目筛选记录

调研时间：2026-08-14。此轮重点检查数据空间连接器、隐私计算运行时和“数据留在提供方域内”的作业模式，目标仍是为当前 Python/FastAPI + React/TypeScript MVP 提供可替换适配器，不改变确定性策略、结果复核和审计留痕主链路。

## GitHub 快照与结论

| 项目 | GitHub 快照 | 部署/改造判断 | 可复用边界 | 当前决定 |
| --- | --- | --- | --- | --- |
| [eclipse-tractusx/tractusx-edc](https://github.com/eclipse-tractusx/tractusx-edc) | 未归档；2026-08-14 仍有提交；Apache-2.0；约 88 stars | 高：控制平面、数据平面、PostgreSQL、Vault、Docker/Helm | 合同协商、数据平面传输、连接器健康状态 | 后续作为 `DataSpaceConnectorAdapter` 候选，不进入 MVP 核心 |
| [eclipse-edc/Connector](https://github.com/eclipse-edc/Connector) | 未归档；2026-08-11 有提交；Apache-2.0；约 419 stars | 高：Java 组件库，不是开箱即用的业务应用 | DSP、资产/合同/策略模型、控制平面与数据平面 SPI | 只借鉴接口边界，暂不引入整套 Java 运行时 |
| [secretflow/secretflow](https://github.com/secretflow/secretflow) | 未归档；2026-04-24 有提交；Apache-2.0；约 2.7k stars | 高：依赖 SPU/Kuscia 等隐私计算组件，安装和多方编排复杂 | MPC、联邦分析、TEE/安全设备抽象、隐私算法适配 | 后续接入 `ComputeAdapter`，不替换当前确定性执行控制器 |
| [secretflow/secretpad](https://github.com/secretflow/secretpad) | 未归档；Apache-2.0；约 76 stars | 高：基于 Kuscia 的隐私计算 Web 平台，运行时依赖较重 | 多方任务编排、数据集/作业/审批交互参考 | 借鉴作业审批与结果回执，不直接部署到 MVP |
| [OpenMined/PySyft](https://github.com/OpenMined/PySyft) | 未归档；2026-08-14 有提交；Apache-2.0；约 9.9k stars | 中高：数据主方审批作业，适合研究/私有部署，不是能源节点标准接口 | 数据留在主方、显式授权、受控作业、仅返回批准结果 | 借鉴“提供方确认后执行”的交互，接到审计复核模型 |

## 对当前系统的落地影响

1. **连接器层保持轻量**：`ElectricityNode`、`CoalNode`、`OilGasNode` 继续只暴露标准化受控接口。未来接 EDC 时，连接器只负责合同/传输协商，不能绕过 `DynamicPolicyEngine` 或人工复核闸门。
2. **计算层保持可替换**：当前 `SIMULATED_TEE` 和 pandapower 适配器继续用于可运行 MVP；SecretFlow/SPU/Kuscia 只能实现 `ComputeAdapter`，输入仍是策略裁决后的 `QueryIntent`，输出仍要经过 `ResultAuditor` 和结果哈希。
3. **审批层继续做差异化能力**：PySyft 的“数据主方批准作业”与本项目的“自动核验通过后由监管方确认结果”可以互补，但不能把审计确认简化成聊天式 AI 同意。
4. **最小部署路径不变**：单体 FastAPI + 本地规则/模拟链 + React 运营控制台；真实数据空间连接器、隐私计算集群和联盟链均通过边界替换，不在 MVP 阶段引入 PostgreSQL/Vault/Kuscia/Java 全家桶。

## 结论

第三轮仍然支持“基于现有项目改造”，而不是直接采用某个开源平台或重写。可直接复用的是协议模型、控制平面/数据平面分层、提供方审批作业和隐私计算适配器思想；核心的双层可信闭环——**安全边界不越权、计算结果可复算并经审计确认**——继续由本项目的确定性策略引擎、结果审核器和链上留痕负责。
