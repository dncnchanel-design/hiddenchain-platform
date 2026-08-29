# 源代码导读

本文档只说明系统主体，不包含项目书、答辩材料、历史研究记录或运行时数据库。

## 1. 系统边界

```text
浏览器
  │
  ▼
frontend/              React + Vite + Nginx 静态前端
  │ /api
  ▼
backend/app/           FastAPI API、权限、工作流和确定性执行服务
  │                     │
  │                     ├─ SQLite 持久化运行账本
  │                     ├─ OPA 策略服务
  │                     └─ connector/app/ 各能源主体本地节点
  ▼
policy/                OPA/Rego 与能源执行策略
```

系统的权威业务主线是可信任务胶囊（TTC）：

```text
INIT → IDENTITY_VERIFIED → DATA_AUTHORIZED → RULE_FROZEN → COMPUTE_EXEC
     → RESULT_CONFIRM → AUDIT_GATE → EVIDENCE_STAGE → EVIDENCE_ANCHOR → ARCHIVED
```

## 2. 后端阅读顺序

| 路径 | 责任 | 阅读重点 |
| --- | --- | --- |
| `backend/app/main.py` | FastAPI 入口、启动校验、路由注册、健康检查 | 启动时迁移、环境门禁和种子数据边界 |
| `backend/app/config.py` | 环境变量和运行时设置 | production fail-closed、白标、连接器和可信执行开关 |
| `backend/app/database.py`、`migrations.py`、`models.py` | 数据库连接、版本化迁移、领域模型 | 迁移账本与运行状态一致性 |
| `backend/app/security.py`、`production.py` | 会话、签名、生产库清洁检查 | 密钥、默认账户和历史模拟记录隔离 |
| `backend/app/routers/` | API 边界 | `auth` 登录，`data` 数据，`trade` 结算，`execution` 计算，`evidence` 存证，`trust*` 可信数据空间 |
| `backend/app/services/workflow.py` | 结算/任务状态机 | TTC 允许动作、前置条件、重试和状态转换 |
| `backend/app/services/trust_execution.py` | 可信执行策略编排 | 规则冻结、工具白名单和确定性执行入口 |
| `backend/app/services/mpc.py`、`privacy.py`、`paillier.py` | 隐私计算适配器 | 实现标签和单主机实验边界 |
| `backend/app/services/vault.py`、`local_data_boundary.py` | 主体数据引用与本地数据边界 | 中央账本保存引用/摘要，不返回 Vault 原始记录 |
| `backend/app/services/formal_evidence.py`、`evidence_outbox.py` | 证据摘要、Merkle 批次和 Outbox | 事务写入与锚定适配器边界 |
| `backend/app/services/*connector*.py` | 数据空间/连接器协议适配 | 外部 EDC、ODCS、Arrow、DuckDB 等均须标注实际运行状态 |

## 3. 连接器与策略

- `connector/app/main.py` 是主体侧本地节点的最小 HTTP 服务，按 `ENERGY_DOMAIN` 启动为电力、煤炭、热能、天然气或石油连接器。
- `connector/requirements.txt` 和 `connector/Dockerfile` 只服务于连接器镜像，不与中心后端共享数据库。
- `policy/hiddenchain.rego` 是通用策略包；`policy/hiddenchain_test.rego` 是策略测试；`policy/energy_execution_policy.json` 是能源执行约束配置。

## 4. 前端阅读顺序

| 路径 | 责任 |
| --- | --- |
| `frontend/src/main.tsx`、`App.tsx`、`routes.tsx` | 应用启动、品牌配置和路由 |
| `frontend/src/api.ts`、`auth.tsx`、`types.ts` | API 客户端、会话和共享类型 |
| `frontend/src/pages/` | 结算、数据、审计、管理等页面 |
| `frontend/src/features/trusted-energy/` | 可信数据空间、目录、授权、查询、Agent 和结果证据页面 |
| `frontend/src/components/` | 共享布局、面板和 UI 原语 |
| `frontend/scripts/check-production.mjs` | 生产前端源码边界检查 |

## 5. 注释与实现边界

注释优先解释安全边界、状态转换、数据来源和“为什么不能绕过”，不重复明显的变量名。新增业务逻辑应同时补：

1. 输入/权限边界说明；
2. 官方数值的确定性来源；
3. 失败、重试和审计行为；
4. 能力标签：`REAL`、`LOCAL_REAL`、`ADAPTER`、`DEMO` 或 `BLOCKED`。

当前版本必须如实保留以下边界：单服务进程确定性结算；MPC/Paillier 为单主机实验；EDC 为适配器；TEE 为 `BLOCKED`；区块链锚定默认为本地哈希演示，不代表外部链共识或终局性。

## 6. 验证入口

```powershell
# 后端
cd backend
.\.venv\Scripts\python.exe -m pytest -q

# 前端
cd ..\frontend
pnpm test
pnpm build
```

Windows Docker Compose 的构建、启动、停止和故障排查见 [Windows 部署手册](WINDOWS_DEPLOYMENT.md)。

Windows 源码包同时保留 `.github/workflows/` 下的工作流 YAML，使后端的 CI Action 固定版本检查可以在解压包内复现；GitHub 凭据、运行产物和缓存不在交付范围内。
