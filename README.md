# 隐链明算｜可信数据调用与隐私计算平台

隐链明算是一个以“可信数据调用 + 隐私计算”为核心的可信智能执行层 MVP。能源电力交易被作为可运行的验证场景，用来验证多主体之间的数据授权、受控计算、结果回执和审计闭环；智能解释能力只是可选辅助，不承担最终裁决。

本轮开源项目调研、维护状态判断、部署成本比较和界面改造依据见 [docs/OPEN_SOURCE_RESEARCH.md](docs/OPEN_SOURCE_RESEARCH.md)。最新一轮 GitHub 筛选与落地记录见 [docs/OPEN_SOURCE_RESEARCH_ROUND5.md](docs/OPEN_SOURCE_RESEARCH_ROUND5.md)。当前结论是继续基于现有 MVP 改造，不引入大型 IoT 平台重写核心链路。

## 已实现的核心闭环

`可信采集 → 安全传输 → 可控使用 → 隐私计算 → 可溯审计`

平台内部继续用数据目录、DID/VC、DataContract、PEP/PDP、ComputeReceipt 和多方签名支撑这条主链；电力交易的电量与金额只作为能源场景验证输出。

平台覆盖五类账号、数据产品目录、连接器协议、用途控制、隐私计算策略路由、六类受控能力模块、可信回执和用户用电隐私分析。平台强调“数据不搬家、按用途调用、在授权域内计算、只返回必要结果”：业务数据库只保存 DataRef、摘要、承诺、策略哈希、结果哈希和证据索引。能源电力中的新能源消纳、市场交易、虚拟电厂运营与电网调度共用同一验证胶囊，作为跨主体可信协同的示范案例。真实 EDC、SecretFlow、FISCO BCOS、WeIdentity 与大模型均通过适配器边界预留；默认实现明确标注为虚拟仿真验证，不把替换边界包装成生产能力。

## 可选解释服务（DeepSeek 适配器）

平台已为六个能力模块预留 DeepSeek 安全调用网关。`/api/agents/{agent_code}/invoke` 可逐个调用，`/api/agents/invoke-all` 可依次运行全部模块，`/api/agents/llm/status` 提供配置与最近一次真实调用凭证；监管审计 `/api/agent/query` 保留失败时的本地证据模板回退。解释服务只接收任务状态、规则版本与哈希、计算回执摘要、签名状态、能力事件摘要和证据索引，不接收企业原始数据，也不能修改权限、规则、场景结果或风险等级。

进入“能力编排”页面后，可选择可信验证胶囊并点击“运行全部模块”，也可以在各能力卡片中填写执行备注后逐个运行。真实调用成功时页面会显示解释服务凭证、请求 ID、耗时和 Token 用量；没有这些凭证时不得视为外部服务调用成功。

在仓库根目录复制 `.env.example` 为 `.env`，再填写：

```powershell
DEEPSEEK_ENABLED=true
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=20
DEEPSEEK_MAX_TOKENS=800
```

`.env` 已被 Git 忽略，禁止把真实 API Key 提交到代码仓库。Docker Compose 场景也可以通过同名环境变量传入；生产环境应使用密钥管理系统，而不是把 Key 写入镜像或前端代码。

## 产品定位

- 可信数据调用：目录发现、语义标识、DID/VC 互认、DataContract 协商、PEP/PDP 使用控制和调用回执组成主链路。
- 隐私计算：根据场景、敏感等级、参与主体和时延约束路由 PSI/MPC、联邦学习、秘密共享、TEE 或差分隐私，原始数据不进入平台业务库。
- 场景验证：电力交易只承担端到端验证作用，证明上述能力可以进入新能源、负荷、虚拟电厂和调度等真实协作流程。

## 对照赛题的可验收链路

`可信采集 → 安全传输 → 可控使用 → 隐私计算 → 可溯审计`

- 可信采集：数据文件必须通过资产类型和载荷校验，生成 `DataRef`、`DataHash`、数据承诺和来源证明。
- 安全传输：数据资产记录接入层、HTTPS/MQTT/WebSocket 协议和 TLS 元数据，接口边界覆盖终端、边缘、云端和业务应用。
- 可控使用：DID/VC、DataContract、用途策略、有效期、算法、执行环境、输出范围和使用次数都参与 PEP/PDP 判定。
- 隐私计算：只把数据引用交给授权计算沙箱，生成策略哈希、ComputeReceipt 和原始数据不出域证明。
- 可溯审计：按 `PRE_COMPUTE`、`IN_COMPUTE`、`POST_COMPUTE` 三阶段生成证据，并提供哈希核验、结果回执和报告引用。
- 指标验证：系统输出计算耗时、调用完成率、隐私安全记录率、原始数据出域率、授权调用次数和证据核验率；当前值明确标注为虚拟仿真样本。

## 本版业务强化

- 四场景耦合：能源电力场景用于验证数据产品跨主体调用、隐私聚合、调度安全边界和可审计结果，不改变平台以可信数据调用和隐私计算为核心的定位。
- 四链融合：DID 身份链、隐私计算链、区块链存证链、智能体协作链通过 `capsule_id` 相互引用。
- 自适应隐私路由：按业务场景、敏感等级、参与主体和时延约束选择联邦学习、PSI/MPC、秘密共享/同态加密、TEE 与差分隐私组合。
- 六类能力模块双闭环：四类能源专业模块加编排模块、报告模块；所有调用绑定模块 DID、工具白名单、输入输出哈希与签名值。

## 技术栈

- 前端：React、TypeScript、Vite、React Router、Lucide、Recharts
- 后端：FastAPI、SQLAlchemy、Pydantic、SQLite（兼容 PostgreSQL）
- 安全：PBKDF2 密码哈希、JWT、DID/VC 模拟、能力令牌、HMAC 签名、SHA-256 承诺、OpenDP 差分隐私、OSV-Scanner 依赖扫描
- 可信能力：数据合同与 ODRL 风格策略、OPA REST/同构本地策略判定、Frictionless Data Package 目录、MPC 适配器、模拟链、证据图谱
- 运行观测：可选 OpenTelemetry FastAPI tracing、OpenLineage 标准 RunEvent 脱敏血缘
- 场景适配：新能源预测资产、pvlib 太阳资源校核、虚拟电厂资源池、pandapower 三母线电网安全校核、偏差响应和电力交易场景验证

## 快速启动

### 1. 后端

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2. 前端

```powershell
cd frontend
pnpm install
pnpm dev
```

浏览器访问 `http://localhost:5173`。前端开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。

也可以在仓库根目录执行：

```powershell
docker compose up --build
```

容器启动后仍访问 `http://localhost:5173`，OpenAPI 文档位于 `http://localhost:5173/api/docs`。Compose 会同时启动 OPA 策略服务；离线启动脚本未配置 `OPA_URL` 时使用同构本地策略引擎。

## 按角色开放的功能页面

登录认证、平台总览、角色工作台、发电侧数据、售电与用电数据、可信数据调用、用途与规则控制、能源场景验证、隐私计算、结果与回执、区块链存证、监管审计、能力编排、异常处置、全过程日志、主体与 DID、可信报告、运行指标。

## 演示账号

| 主体 | 用户名 | 密码 |
| --- | --- | --- |
| 发电企业 | `generator` | `generator123` |
| 售电企业 | `retailer` | `retailer123` |
| 交易中心 | `exchange` | `exchange123` |
| 监管方 | `regulator` | `regulator123` |
| 系统管理员 | `admin` | `admin123` |

## 目录结构

```text
hiddenchain-platform/
├─ backend/
│  ├─ app/
│  │  ├─ routers/        # REST API 与 RBAC
│  │  └─ services/       # DID、数据空间、MPC、链、Agent 工作流
│  ├─ tests/             # 核心闭环与权限测试
│  └─ runtime/           # SQLite 与模拟数据域（运行时生成）
├─ frontend/
│  └─ src/               # 按角色开放的功能页面
├─ policy/                # OPA Rego 策略包
├─ docs/                  # 架构映射与开发任务分工
└─ docker-compose.yml
```

## 可信数据调用主链路

当前版本新增并前置一条可运行的轻量数据空间主链：

`数据产品目录 → DID/VC 身份互认 → DataContract → HCDS-1.0 连接器协商 → PEP/PDP 使用控制 → 隐私计算 → DataSpace Receipt → 三阶段证据`

- `/api/data/catalog` 提供电力数据产品目录、语义标识、Schema、质量和用途限制，原始数据仍留在组织 Vault。
- `/api/data/agreements` 查看提供方与使用方之间的协商协议；`/api/data-space/protocol` 查看连接器能力和“三统一”映射。
- `/api/data-space/usage-control/check` 可通过 OPA REST 或同构本地 Rego 兼容引擎验证用途、算法、执行环境、输出模式、原始数据导出和使用次数等策略，并返回策略输入哈希与决策哈希。
- “可信数据调用”前端页面展示目录、协议能力、协商状态、使用次数和回执记录；“隐私计算”页面展示策略路由、计算任务和 ComputeReceipt。
- 结算安全闸门使用 `pandapower` 对 110kV 三母线模型执行潮流、线路负载、电压和剩余偏差校核；结果只返回约束摘要，不返回原始数据。

该实现是 IDS-RAM/ODS-RAM 与国内可信数据空间标准方向的 MVP 对齐实现，隐私计算、联盟链和 DID 仍通过适配器保留真实组件替换边界。

## 生产化替换点

本次可信智能执行层的模块边界、API 示例和能源局跨能源调用验证见 [`docs/TRUSTED_EXECUTION.md`](docs/TRUSTED_EXECUTION.md)。

1. 当前 MVP 已将 `MockDataSpaceAdapter` 保留为兼容外壳，策略判定接入 OPA REST/同构本地 Rego；后续再将数据空间连接器替换为 EDC Connector，并将数据合同映射到 ODRL Profile。
2. `MockPrivacyComputeAdapter` 替换为 SecretFlow 多节点任务，保持 `DataPermit → ComputeReceipt` 接口不变。
   - 新能源联合预测接入联邦学习与差分隐私。
   - 能源场景验证接入 PSI + MPC。
   - 虚拟电厂聚合接入秘密共享/HEU。
   - 实时调度校核在当前 MVP 使用 pandapower 三母线模型；后续再接入 TEE 与经过验证的生产级潮流/安全约束服务。
3. `MockBlockchainAdapter` 替换为 FISCO BCOS SDK 与证据合约。
4. `MockDidAdapter` 替换为 walt.id 或企业统一身份体系。
5. 市场交易 Agent 的本地知识条款替换为正式规则库与可审计 RAG；LLM 仍不能越过 DSL、OPA、调度安全闸门和人工签署闸门。

## MVP 组件配置

`docker-compose.yml` 会启动 `openpolicyagent/opa:1.17.0`，加载 `policy/hiddenchain.rego`，后端通过以下配置访问：

```text
OPA_URL=http://opa:8181
OPA_POLICY_PATH=/v1/data/hiddenchain/decision
OPA_LOCAL_FALLBACK=true
```

生产 Compose 默认关闭策略服务不可用时的本地回退，避免远程 PDP 故障时继续授权。离线演示不依赖 Docker OPA，仍使用相同输入结构和规则语义的本地兼容实现。

## 测试

```powershell
cd backend
pytest -q

cd ..\frontend
pnpm build
```

### 前端流畅度长稳验证

项目内置四小时轻量巡检脚本，验证页面入口、健康检查、登录、任务、隐私计算、可信凭证、数据目录和数据空间策略协议接口。脚本不会创建结算任务或上传数据；登录接口会按正常行为留下登录审计记录。日志写入 `runtime/performance/`，该目录已加入 Git 忽略。

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\performance-soak.ps1
```

可用参数：`-DurationHours 4`、`-IntervalSeconds 30`、`-BaseUrl http://127.0.0.1:5173`。结束后查看生成的 `*-summary.json`，确认 `failed_checks` 为 `0`。

## 当前联调验收

本地离线演示脚本会自动启动 FastAPI 和 Vite：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-offline-demo.ps1 -OpenBrowser
```

启动后使用 `exchange / exchange123` 登录，并按“可信采集 → 安全传输 → 可控使用 → 隐私计算 → 可溯审计”检查主链路。进入“可信调用验证”上传 `demo-data/2026-08-simulation-input.json` 即可自动运行；电力交易只作为其中的能源仿真验证场景。

后端当前已增加请求数据结构校验、任务参与方校验、跨组织隐私分析隔离，以及数据签名和场景结果确认的重复请求幂等处理。生产 Compose 默认关闭演示数据灌入；正式部署前仍需设置随机 JWT 和签名密钥。

### 本轮开源能力配置

- 负荷分析选择“差分隐私”时，后端通过 OpenDP 生成有界求和 + Laplace 保护序列，并在回执中显示预算、边界与组合次数。
- `OPENLINEAGE_ENABLED=true` 时，可信结算和跨能源受控调用会在 `runtime/lineage/events.jsonl` 写入不含原始数据的 OpenLineage RunEvent；可通过 `/api/audit/lineage/{run_id}` 查询。
- Prometheus 指标通过受 `REGULATOR`/`ADMIN` 角色保护的 `/api/metrics/prometheus` 提供，只记录方法、路由模板、状态和耗时，不记录查询参数或请求体。
- `/api/energy/solar/evaluate` 使用 pvlib 计算太阳位置与组件面辐照度，只返回派生指标和输入哈希；地理坐标与辐照度原值不会进入响应或指标标签。
- `/api/data/catalog/package` 按 Frictionless Data Package 标准输出可发现的目录元数据和连接器 URI，不返回 Vault 路径、原始记录或密码字段。
- 设置 `OTEL_ENABLED=true` 并提供 `OTEL_EXPORTER_OTLP_ENDPOINT` 后，FastAPI 请求会发往 OTLP collector，审计 `trace_id` 可与外部链路关联。
- GitHub Actions 已加入 OSV-Scanner；提交或 PR 进入 GitHub 后会执行依赖漏洞扫描。
- GitHub Actions 已加入 Syft SBOM；提交或 PR 会生成 CycloneDX 组件清单 artifact，默认保留 14 天，便于发布前复核。
- GitHub Actions 已加入 Trivy 文件系统安全审计和 zizmor 工作流供应链审计；报告型扫描默认不阻断业务发布，先保留 artifact 和审计输出。
- GitHub Actions 已加入固定 OPA v1.19.0 的 Rego 格式与策略测试，覆盖正常放行、原始数据导出拒绝和使用次数耗尽拒绝。
