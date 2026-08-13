# 隐链明算｜可信数据调用与隐私计算平台

隐链明算是一个以“可信数据调用 + 隐私计算”为核心的 Agent 原生可信数据空间 MVP。能源电力交易被作为可运行的验证场景，用来验证多主体之间的数据授权、受控计算、结果回执和审计闭环，而不是平台本身的唯一业务边界。

## 已实现的核心闭环

`发现数据产品 → DID/VC身份互认 → DataContract/用途授权 → PEP/PDP使用控制 → PSI/MPC等隐私计算 → 聚合结果与ComputeReceipt → 多方签名 → 证据核验 → 场景验证报告`

平台覆盖五类账号、数据产品目录、连接器协议、用途控制、隐私计算策略路由、六类专业 Agent、可信回执、用户用电隐私分析和 18 个界面模块。平台强调“数据不搬家、按用途调用、在授权域内计算、只返回必要结果”：业务数据库只保存 DataRef、摘要、承诺、策略哈希、结果哈希和证据索引。能源电力中的新能源消纳、市场交易、虚拟电厂运营与电网调度共用同一验证胶囊，作为跨主体可信协同的示范案例。真实 EDC、SecretFlow、FISCO BCOS、WeIdentity 与大模型均通过适配器边界预留；默认实现不会伪装成生产能力，而是用模拟节点和假数据稳定演示完整流程。

## DeepSeek 审计解释 Agent

平台已为六个专业 Agent 接入 DeepSeek 安全调用网关。`/api/agents/{agent_code}/invoke` 可逐个调用，`/api/agents/invoke-all` 可依次调用六个 Agent，`/api/agents/llm/status` 提供配置与最近一次真实调用凭证；监管审计 `/api/agent/query` 保留失败时的本地证据模板回退。模型只接收任务状态、规则版本与哈希、计算回执摘要、签名状态、Agent 事件摘要和证据索引，不接收企业原始数据，也不能修改权限、规则、结算结果或风险等级。

进入“Agent 协同”页面后，可选择可信验证胶囊并点击“依次真实调用六个 Agent”，也可以在各 Agent 卡片中修改指令后逐个调用。真实调用成功时页面会显示 DeepSeek 模型、请求 ID、耗时和 Token 用量；没有这些凭证时不得视为真实 AI 调用成功。

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

## 本版业务强化

- 四场景耦合：能源电力场景用于验证数据产品跨主体调用、隐私聚合、调度安全边界和可审计结果，不改变平台以可信数据调用和隐私计算为核心的定位。
- 四链融合：DID 身份链、隐私计算链、区块链存证链、智能体协作链通过 `capsule_id` 相互引用。
- 自适应隐私路由：按业务场景、敏感等级、参与主体和时延约束选择联邦学习、PSI/MPC、秘密共享/同态加密、TEE 与差分隐私组合。
- 六 Agent 双闭环：四类能源专业 Agent 加编排 Agent、报告 Agent；所有调用绑定 Agent DID、工具白名单、输入输出哈希与签名值。

## 技术栈

- 前端：React、TypeScript、Vite、React Router、Lucide、Recharts
- 后端：FastAPI、SQLAlchemy、Pydantic、SQLite（兼容 PostgreSQL）
- 安全：PBKDF2 密码哈希、JWT、DID/VC 模拟、能力令牌、HMAC 签名、SHA-256 承诺
- 可信能力：数据合同与 ODRL 风格策略、OPA 风格策略判定、MPC 适配器、模拟链、证据图谱
- 场景适配：新能源预测资产、虚拟电厂资源池、调度安全边界、偏差响应和电力交易场景验证

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

容器启动后仍访问 `http://localhost:5173`，OpenAPI 文档位于 `http://localhost:5173/api/docs`。

## 18 个界面模块

登录认证、平台总览、角色工作台、发电侧数据、售电与用电数据、可信数据调用、用途与规则控制、能源场景验证、隐私计算、结果与回执、区块链存证、监管审计、Agent 协同、异常处置、全过程日志、主体与 DID、可信报告、运行指标。

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
│  └─ src/               # 18 模块界面
├─ docs/                  # 架构映射与开发任务分工
└─ docker-compose.yml
```

## 可信数据调用主链路

当前版本新增并前置一条可运行的轻量数据空间主链：

`数据产品目录 → DID/VC 身份互认 → DataContract → HCDS-1.0 连接器协商 → PEP/PDP 使用控制 → 隐私计算 → DataSpace Receipt → 三阶段证据`

- `/api/data/catalog` 提供电力数据产品目录、语义标识、Schema、质量和用途限制，原始数据仍留在组织 Vault。
- `/api/data/agreements` 查看提供方与使用方之间的协商协议；`/api/data-space/protocol` 查看连接器能力和“三统一”映射。
- `/api/data-space/usage-control/check` 可验证用途、算法、执行环境、输出模式、原始数据导出和使用次数等策略。
- “可信数据调用”前端页面展示目录、协议能力、协商状态、使用次数和回执记录；“隐私计算”页面展示策略路由、计算任务和 ComputeReceipt。

该实现是 IDS-RAM/ODS-RAM 与国内可信数据空间标准方向的 MVP 对齐实现，隐私计算、联盟链和 DID 仍通过适配器保留真实组件替换边界。

## 生产化替换点

1. `MockDataSpaceAdapter` 替换为 EDC Connector，并将数据合同映射到 ODRL Profile。
2. `MockPrivacyComputeAdapter` 替换为 SecretFlow 多节点任务，保持 `DataPermit → ComputeReceipt` 接口不变。
   - 新能源联合预测接入联邦学习与差分隐私。
   - 能源场景验证接入 PSI + MPC。
   - 虚拟电厂聚合接入秘密共享/HEU。
   - 实时调度校核接入 TEE 与经过验证的潮流/安全约束服务。
3. `MockBlockchainAdapter` 替换为 FISCO BCOS SDK 与证据合约。
4. `MockDidAdapter` 替换为 WeIdentity 或企业统一身份体系。
5. 市场交易 Agent 的本地知识条款替换为正式规则库与可审计 RAG；LLM 仍不能越过 DSL、OPA、调度安全闸门和人工签署闸门。

## 测试

```powershell
cd backend
pytest -q

cd ..\frontend
pnpm build
```

## 当前联调验收

本地离线演示脚本会自动启动 FastAPI 和 Vite：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-offline-demo.ps1 -OpenBrowser
```

启动后使用 `exchange / exchange123` 登录，并按“可信数据调用 → 隐私计算 → 能源场景验证 → 结果与回执 → 区块链存证 → 监管审计 → 可信报告”检查主链路。电力交易页面是验证入口，不是产品叙事的起点。

后端当前已增加请求数据结构校验、任务参与方校验、跨组织隐私分析隔离，以及数据签名和结算结果确认的重复请求幂等处理。生产 Compose 默认关闭演示数据灌入；正式部署前仍需设置随机 JWT 和签名密钥。
