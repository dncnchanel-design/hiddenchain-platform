# 可信执行说明

本文件说明 `0.2.0` 的实际可信边界。历史入口 [TRUSTED_EXECUTION_MODEL.md](TRUSTED_EXECUTION_MODEL.md) 仍保留；如其中的旧能力描述与本文不一致，以运行时 `/api/version`、`/api/health` 和当前实现证据为准。

## 已实现的本地可信闭环

| 能力 | 真实状态 | 边界 |
| --- | --- | --- |
| TTC 状态机 | `LOCAL_REAL` | 持久化 Attempt、转移记录、状态版本和非法跳转拒绝 |
| Rule Freeze | `LOCAL_REAL` | 每次 Attempt 固化规则、策略、合同、数据、算法、参数和单位，快照受更新/删除事件保护 |
| 确定性结算 | `LOCAL_REAL` | `LOCAL_CONTROLLED_SETTLEMENT_V1`，单服务进程内执行 |
| Agent Tool 控制 | `LOCAL_REAL` | Agent DID、Tool 登记、显式权限和 Tool-call 记录；无任意数据库/文件系统/链访问 |
| A/B/C 证据与 Merkle | `LOCAL_REAL` | A 类强制锚定，B 类按风险/审批/监管条件锚定，C 类链下保留并纳入证据根 |
| 事务 Outbox | `LOCAL_REAL` | 业务结果与待发布事件同事务；支持幂等、重试、过期锁恢复与死信 |
| MPC 求和 | `LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST` | 真实有限域加法秘密分享，仅整数求和；所有份额共存一个 Python 进程 |

TTC 正常路径为：

`INIT → IDENTITY_VERIFIED → DATA_AUTHORIZED → RULE_FROZEN → COMPUTE_EXEC → RESULT_CONFIRM → AUDIT_GATE → EVIDENCE_STAGE → EVIDENCE_ANCHOR → ARCHIVED`

异常路由显式状态承载，包括 `REJECTED`、`FAILED`、`INTERRUPTED`、`REWORK`、`HUMAN_REVIEW`、`ANCHOR_RETRY`、`CANCELLED` 和 `EXPIRED`。`REWORK` 会创建新 Attempt 和新版本执行快照，不会改写旧快照。历史任务若没有 Attempt，迁移后状态为 `LEGACY_UNMIGRATED`，不伪造旧 TTC 转移或证据。

## 仍不得宣称的能力

| 能力 | 状态 | 原因 |
| --- | --- | --- |
| Eclipse EDC | `ADAPTER` | 仅有 Dataspace Protocol/策略/合同映射，无 EDC Java 控制面或数据面节点 |
| TEE 及远程证明 | `BLOCKED` | 无可证明硬件运行时、证书链和密钥释放服务 |
| 区块链锚定 | `DEMO` | `LOCAL_HASH_ANCHOR_DEMO_V1` 只产生确定性本地哈希回执，无共识、独立时间戳或外部终局性 |
| 跨主体生产 MPC | `BLOCKED` | 无独立运营节点、认证传输、恶意方/串谋防护和分布式密钥管理 |
| 跨域不出域证明 | `BLOCKED` | 单主机执行与 API 最小披露不能代替独立数据面证明 |

证据、快照、回执和 API 最小披露可用于一致性、回放与追溯，但不可由此推导出硬件隔离、外部共识或跨域生产隐私保护。
