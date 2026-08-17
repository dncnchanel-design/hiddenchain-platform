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
      ├─ 本地证据台账与审计记录
      └─ SQLite（单实例默认）/ 可迁移数据库
```

## 业务对象

`SettlementTask` 是聚合根，通过 `task_id` 关联参与方、数据上传、数据空间协议、规则、计算作业、结果、签名、证据、审计报告、Agent 事件与异常。

前端围绕任务中心、五步创建和统一详情组织这些对象。后端独立执行角色与组织范围校验，不依赖前端隐藏。

## 数据边界

- `DataUpload` 在业务库保存 DataRef、Schema、质量、摘要、承诺和接入元数据。
- 本地 Vault 保存输入载荷；结算 API 返回汇总结果而非 Vault 原始记录。
- 当前部署仍是同一应用/主机边界，不能据此声明跨主体物理不出域。
- 生产需要外部数据空间连接器、独立主体数据面和可核验证明后，才可升级该声明。

## 计算与证据

- `LocalControlledComputeAdapter`：`LOCAL_CONTROLLED_SETTLEMENT_V1`，应用进程内确定性计算，不是 MPC/TEE。
- `LocalEvidenceLedgerAdapter`：`LOCAL_EVIDENCE_LEDGER_V1`，数据库顺序号与哈希摘要，不是区块链共识。
- OPA 对用途、算法、执行环境、输出模式和使用次数作裁决；production 禁止本地回退。
- 外部 PSI/MPC、TEE、联邦学习、秘密共享和同态加密条目只作为 `NOT_CONFIGURED` 候选方案。

## 部署边界

默认 production Compose 是单实例 FastAPI、Nginx、OPA 与 SQLite 卷。多副本生产必须补充 PostgreSQL、迁移工具、共享限流、集中观测、高可用与灾备。完整说明见 [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md)。
