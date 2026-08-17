# 可信执行说明

本文件保留旧链接兼容。当前权威说明是 [TRUSTED_EXECUTION_MODEL.md](TRUSTED_EXECUTION_MODEL.md)。

本版本真实执行边界：

- 结算：`LOCAL_CONTROLLED_SETTLEMENT_V1`，应用进程内确定性计算。
- 证据：`LOCAL_EVIDENCE_LEDGER_V1`，数据库哈希台账。
- API 原始记录：不返回。
- MPC、TEE、远程证明、区块链存证、跨域不出域证明：未配置或未提供，不得据此作生产声明。
