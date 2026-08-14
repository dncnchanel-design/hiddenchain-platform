# 可信智能执行层 MVP

本次改造在现有 FastAPI、数据域 Vault、DID、OPA/规则适配器和模拟链上凭证之上增加一条“隐链明算”执行闭环。它不把煤炭、油气或电力明细汇聚到平台数据库；节点只返回经过策略裁决的汇总或计算结果。

## 代码边界

| 能力 | 实现位置 |
| --- | --- |
| 动态五类策略 | `policy/energy_execution_policy.json`、`backend/app/services/trust_execution.py:DynamicPolicyEngine` |
| 自然语言/API 意图解析 | `backend/app/services/trust_execution.py:AgenticQueryOrchestrator` |
| 电力节点 | `ElectricityNode`，读取已有 `DataUpload` 的 `DataRef` 和本地域 Vault |
| 煤炭节点 | `CoalNode`，实现 `ENERGY-NODE-1.0` 与 `coal:InventoryAggregate/v1` |
| 油气节点 | `OilGasNode`，实现同一标准接口的汇总骨架 |
| 八步控制器 | `TrustworthyExecutionController` |
| 结果审核 | `ResultAuditor`，原始字段、最小群组和反推风险检查 |
| 计算准确性复核 | `TrustedExecutionReview`、`TrustedExecutionReviewService`，自动重算与人工确认 |
| 异步留痕 | `BlockchainAuditLogger`，复用已有 `MockBlockchainAdapter` 和 `blockchain_evidence` 表 |
| REST API | `backend/app/routers/execution.py` |

## 八步闭环

控制器按照固定顺序生成 `workflow_steps`：

`INGEST -> AUTHENTICATE -> RESOLVE -> ARBITRATE -> EXECUTE -> AUDIT -> DELIVER -> LOG`

身份认证同时检查 JWT 用户、请求角色映射和组织 DID/VC 的 `credential_status=VALID`。策略引擎按 JSON 配置匹配数据类型、敏感度、消费方、用途、分组维度和请求字段；未命中的动作默认 `PROHIBIT`。

节点接口只接收 `QueryIntent + PolicyDecision`，返回 `raw_data_exposed=false` 的聚合行。计算类结果带有 `SIMULATED_TEE`、反推检查和敏感拓扑坐标不出域的控制元数据。生产环境可在不改控制器接口的前提下替换成企业数据网关、TEE 或隐私计算引擎。

## API

先用已有演示账号登录获取 Bearer Token，然后调用：

```http
GET /api/trusted-execution/example
GET /api/trusted-execution/status
GET /api/trusted-execution/policy/catalog
POST /api/trusted-execution/query
GET /api/trusted-execution/audit/{request_id}
GET /api/trusted-execution/reviews/{request_id}
POST /api/trusted-execution/reviews/{request_id}/confirm
```

能源局示例请求：

```json
{
  "question": "分析上月由于电煤库存变化引起的火电出力与电网负荷平衡趋势",
  "consumer_role": "ENERGY_BUREAU",
  "purpose": "CROSS_ENERGY_TREND",
  "group_by": ["region", "period"],
  "output_mode": "SUMMARY"
}
```

默认情况下，受控解析模块会解析出 `COAL_INVENTORY`、`POWER_THERMAL_OUTPUT` 和 `GRID_LOAD`。能源局的煤炭库存命中 `AGGREGATE`，电力历史统计命中 `AGGREGATE`，最终只交付区域/月度序列、负荷平衡差额和趋势摘要；原始企业级明细不会进入响应。

链上凭证异步写入已有 `blockchain_evidence`，其 `payload_json` 至少包含：

`Request_ID`、`Caller_Identity`、`Target_Data`、`Policy_Hit`、`Execution_Status`、`Result_Hash`，并附带 `Workflow_Steps` 与执行计划哈希。

## 两层可信

1. **安全可信**：DID/VC、角色和用途先认证；策略引擎默认拒绝；节点只返回按区域/月度汇总或 TEE 计算结果；结果审核拒绝原始字段、过小群组和反推风险。
2. **计算可信**：节点返回的安全聚合快照会保存承诺/来源证明；同一期间、区域和数据类型的多份来源先求和，再以四位小数 `HALF_UP` 规则生成结果。系统自动复算负荷平衡公式、核对节点聚合值与交付序列、检查结果哈希；NaN/Infinity 等非有限值直接 fail-closed。自动检查通过后进入 `PENDING`，不会伪装成人工确认。

审计人员（`REGULATOR`/`ADMIN`）在核对页查看结果哈希、节点汇总快照、计算检查项和策略命中，然后点击确认接口：

```json
{
  "opinion": "已核对节点汇总、平衡公式和结果哈希，确认",
  "accept": true
}
```

确认会生成审计人员 DID 签名，并异步追加一条链上 `REVIEW_CONFIRMED` 凭证；如果结果哈希或自动核对失败，确认会被拒绝。

## 策略扩展

修改 `policy/energy_execution_policy.json` 即可增加规则，不需要改控制器。支持的动作是：

- `PROHIBIT`：直接拒绝，且默认拒绝未命中规则的目标。
- `DELAY`：按 `delay_days` 计算最早释放时间。
- `AGGREGATE`：按 `group_by` 返回汇总结果，并执行 `min_group_size` 检查。
- `COMPUTE_ONLY`：节点域内/TEE 中计算，只返回趋势、相关性或图表摘要。
- `ALLOW`：只用于低敏、公开数据。

请求字段中的 `raw_payload`、`raw_records`、客户标识、计量点和精确坐标会被配置规则直接拒绝。

## 验证与部署

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_platform.py -q

cd ..
docker compose config
docker compose -f docker-compose.production.yml config
```

容器镜像现在同时打包 `policy/`，本地 Compose 和 Render 使用同一份策略文件；生产环境可通过 `EXECUTION_POLICY_PATH` 和 `EXECUTION_AUDIT_WORKERS` 调整路径及异步存证线程数。
