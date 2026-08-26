# FISCO BCOS 证据锚定接口

## 当前状态

平台已经提供 `FISCO_BCOS_EVIDENCE_ANCHOR_V1` 适配器，但只有在以下配置同时存在时才会选择它：

- `FISCO_BCOS_RPC_URL`
- `FISCO_BCOS_RELAY_URL`
- `FISCO_BCOS_GROUP_ID`
- `FISCO_BCOS_NODE_ID`
- `FISCO_BCOS_CONTRACT_ADDRESS`

未配置或配置不完整时，系统选择 `LOCAL_HASH_ANCHOR_DEMO_V1`，批次状态为 `ANCHORED_DEMO`，不会生成伪造的链上交易哈希。

## 签名中继契约

`FISCO_BCOS_RELAY_URL` 必须是独立运行的签名中继/提交服务。平台 POST 以下 JSON，并要求中继按 `idempotency_key` 幂等：

```json
{
  "operation": "ANCHOR_EVIDENCE_ROOT_V1",
  "batch_id": "…",
  "merkle_root": "64 位 SHA-256",
  "payload_hash": "64 位 SHA-256",
  "idempotency_key": "…",
  "event_type": "EVIDENCE_ROOT_READY",
  "aggregate_type": "EVIDENCE_BATCH",
  "aggregate_id": "…",
  "group_id": "group0",
  "node_id": "…",
  "contract_address": "…"
}
```

中继返回 `transaction_hash`（或 `tx_hash`）以及可选的 `receipt`。如果没有直接返回回执，平台使用 FISCO JSON-RPC `getTransactionReceipt` 回读。只有交易哈希匹配、状态为成功、且存在非负区块高度时，平台才把 outbox 事件标记为 `PUBLISHED`，并把批次标记为 `ANCHORED`。

平台不接收、不保存 FISCO 私钥；私钥必须留在签名中继或 HSM/KMS 边界内。单笔交易回执证明交易已被节点接受并写入指定网络，不自动等于完整治理共识或长期终局性证明。
