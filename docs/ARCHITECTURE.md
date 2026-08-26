# 系统架构

## 运行结构

```text
Browser / React
      ↓ same-origin /api
FastAPI + JWT/RBAC
      ├─ 结算任务与结果确认
      ├─ 数据目录、DataRef 与本地 Vault
      ├─ OPA 用途策略（production 远程、失败即拒绝）
      ├─ 本地受控确定性计算
      ├─ 外部主体连接器签名计算与不出域证明
      ├─ 本地证据台账与审计记录
      ├─ 可选 FISCO BCOS 证据锚定适配器
      └─ SQLite（单实例默认）/ 可迁移数据库
```

## 业务对象

`SettlementTask` 是聚合根，通过 `task_id` 关联参与方、数据上传、数据空间协议、规则、计算作业、结果、签名、证据、审计报告、Agent 事件与异常。

前端围绕任务中心、五步创建和统一详情组织这些对象。后端独立执行角色与组织范围校验，不依赖前端隐藏。

## 数据边界

- `DataUpload` 在业务库保存 DataRef、Schema、质量、摘要、承诺和接入元数据。
- 本地 Vault 保存输入载荷；结算 API 返回汇总结果而非 Vault 原始记录。
- 当前部署仍是同一应用/主机边界，不能据此声明跨主体物理不出域。
- 受控问数可调用独立主体连接器：平台核验连接器签名、请求哈希、聚合输出范围和不出域声明后，才标记 `cross_domain_non_export_verified=true`。这证明的是已登记连接器的可核验软件声明，不等同于 TEE 远程证明或恶意模型安全。
- 生产若要升级为更强的跨主体安全声明，仍需要独立主体数据面、出站控制和第三方/硬件可核验证明。

## 计算与证据

- `LocalControlledComputeAdapter`：`LOCAL_CONTROLLED_SETTLEMENT_V1`，应用进程内确定性计算，不是 MPC/TEE。
- 外部主体连接器：返回连接器签名的聚合结果和不出域证明；平台不接收原始记录，但当前证明边界是连接器软件声明。
- `LocalEvidenceLedgerAdapter`：`LOCAL_EVIDENCE_LEDGER_V1`，数据库顺序号与哈希摘要，不是区块链共识；配置 FISCO BCOS RPC、签名中继和合约后，outbox 才切换到 `FISCO_BCOS_EVIDENCE_ANCHOR_V1` 并核验交易回执。
- OPA 对用途、算法、执行环境、输出模式和使用次数作裁决；production 禁止本地回退。
- 外部 PSI/MPC、TEE、联邦学习、秘密共享和同态加密条目按实际运行边界标记；当前 Paillier/秘密分享分析是单主机实验，不能作为跨域不出域证明。

## 部署边界

默认 production Compose 是单实例 FastAPI、Nginx、OPA 与 SQLite 卷。多副本生产必须补充 PostgreSQL、迁移工具、共享限流、集中观测、高可用与灾备。完整说明见 [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md)。
