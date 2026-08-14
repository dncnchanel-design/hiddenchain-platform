# 第四轮开源与标准边界核查

调研时间：2026-08-14。本轮补充检查数据空间标准、身份信任组件和安全计算运行时，重点确认哪些能力可以复用，哪些能力不能被误认为“拿来即生产”。

| 项目/规范 | 维护与许可快照 | 能直接复用的内容 | 不适合直接引入的部分 |
| --- | --- | --- | --- |
| [International-Data-Spaces-Association/ids-specification](https://github.com/International-Data-Spaces-Association/ids-specification) | Dataspace Protocol 2024-1 稳定规范；Apache-2.0 | Catalog、ODRL 使用控制、合同协商、Transfer Process 的消息/状态机模型 | 它是互操作规范，不是可直接部署的策略引擎、数据库或隐私计算平台 |
| [eclipse-edc/IdentityHub](https://github.com/eclipse-edc/IdentityHub) | Eclipse EDC 体系；Apache-2.0；Java | Participant identity、凭证、信任框架与 DID/VC 适配边界 | 引入会带来 Java/EDC 运行时，不能绕过当前的 `CallerIdentity` 与人工确认闸门 |
| [eclipse-edc/DataDashboard](https://github.com/eclipse-edc/DataDashboard) | EDC Management API 演示前端；Apache-2.0 | 数据目录、连接器管理、控制面仪表盘的交互参考 | 仓库明确定位为演示代码，不能作为生产前端或审计证据界面 |
| [secretflow/spu](https://github.com/secretflow/spu) | SecretFlow 安全计算运行时；Apache-2.0 | MPC/安全设备抽象、可测量计算能力的 `ComputeAdapter` 设计参考 | 官方明确不建议直接用于生产；必须由 SecretFlow/Kuscia 或企业 TEE 运行时承担部署、隔离和运维 |

## 对本项目的最终取舍

1. **协议层**：将 DataSpace Protocol/ODRL 的目录、用途、合同和转移状态映射到现有 `DataContract`、`PolicyDecision` 和 `DataSpaceReceipt`，不替换 `TrustworthyExecutionController`。
2. **身份层**：未来可将 EDC IdentityHub 或企业 DID/VC 服务接到 `CallerIdentity.from_user` 的验证边界，当前 MVP 继续使用可测试的 DID/VC 模拟实现。
3. **计算层**：未来可在 `ComputeAdapter` 后接 SecretFlow/Kuscia/TEE，输入仍须经过确定性策略裁决，输出仍须经过 `ResultAuditor`、结果哈希和人工确认。
4. **交互层**：DataDashboard 只作为数据空间控制台参考；本项目的审计页必须继续突出双层可信和证据核对，而不是把目录浏览做成“聊天式 AI 入口”。

这轮核查没有改变 MVP 结论：**基于现有系统改造**最稳妥；直接采用 EDC/SecretFlow 全栈会扩大部署、依赖和审计边界，自己重写协议/身份/计算基础设施则会失去标准兼容性。
