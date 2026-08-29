# 隐链明算评委部署说明

版本：`0.2.0`
适用：Windows 10/11 64 位、Docker Desktop、WSL 2

本文是本交付包的部署入口。压缩包内的源码、Compose 配置、Dockerfile、OPA 策略、演示数据和说明来自同一份最新工作树；不需要从 GitHub 下载代码，也不需要单独安装 Python、Node.js 或 pnpm。源码目录、调用链、数据边界和测试阅读说明见同目录的 `SOURCE_CODE_GUIDE.md`。

## 1. 评委电脑准备

首次部署需要联网，用于 Docker 下载基础镜像和构建依赖。准备：

- Windows 10/11 64 位；
- Docker Desktop for Windows，并在 Settings 中启用 WSL 2 based engine；
- 建议至少 4 核 CPU、8 GB 可用内存、20 GB 可用磁盘；
- PowerShell 5.1 或 PowerShell 7；
- Docker Desktop 已启动，并可以在 PowerShell 中执行 `docker info`。

建议把压缩包解压到不含中文和空格的目录，例如：

```text
C:\hiddenchain-platform
```

不要把压缩包解压到 OneDrive、临时目录或带很长中文路径的目录。首次构建需要较长时间，具体取决于网络速度。

## 2. 一键部署

打开 PowerShell，进入解压后的目录，依次执行：

```powershell
Set-Location C:\hiddenchain-platform
Set-ExecutionPolicy -Scope Process Bypass
.\install-windows.ps1 -Mode Demo
```

脚本会自动完成：

1. 检查 Docker 引擎和 Docker Compose；
2. 在 `runtime\windows-demo.env` 生成本机演示密钥；
3. 构建 OPA、FastAPI 后端、React/Nginx 前端和 7 个能源主体连接器；
4. 创建持久化 Docker volume；
5. 启动服务并轮询前端 `/api/health`；
6. 输出部署完成提示。

看到“隐链明算 Windows 部署完成”后，打开：

```text
http://127.0.0.1:5173/login
```

演示模式只使用合成数据。系统第一次启动会自动创建组织、DID、数据目录、授权请求和演示账户。
同时会预置一笔“公开演示：2026年8月可信结算闭环”任务，任务状态为“待主体确认”，可直接切换主体账号继续完成结果确认和监管审计。

## 3. 演示账户与建议路线

| 角色 | 账号 | 密码 | 主要用途 |
| --- | --- | --- | --- |
| 电力交易中心 | `exchange` | `exchange123` | 查看数据目录、授权、创建和启动结算任务 |
| 发电企业 | `generator` | `generator123` | 只查看并确认发电方结果 |
| 售电企业 | `retailer` | `retailer123` | 只查看并确认售电方结果 |
| 煤炭企业 | `coal` | `coal123` | 查看煤炭主体数据目录和主体权限 |
| 热能企业 | `heat` | `heat123` | 查看热能主体数据目录和主体权限 |
| 天然气企业 | `gas` | `gas123` | 查看天然气主体数据目录和主体权限 |
| 石油企业 | `oil` | `oil123` | 查看石油主体数据目录和主体权限 |
| 监管方 | `regulator` | `regulator123` | 查看证据、异常和审计报告 |
| 平台运维 | `admin` | `admin123` | 查看平台、组织、身份、策略和日志管理 |

推荐从 `exchange` 开始，依次观察：

1. 可信数据空间中的数据目录、数据资产版本和使用授权；
2. 结算任务创建向导的参与方、数据、规则、计算和提交检查；
3. TTC 可信任务胶囊的状态链和允许动作；
4. 受控计算生成的平台汇总结果和主体结果；
5. 切换到 `generator`、`retailer`，验证主体只能确认本组织结果；
6. 切换到 `regulator`，查看证据链、审计事件和报告；
7. 切换到 `admin`，查看组织、身份、策略和平台日志。

压缩包中的 `demo-data\` 仅保存可复核的合成输入和期望结果，不是真实企业数据；评委第一次体验不需要额外导入文件，直接操作启动时预置的任务即可。

## 4. 系统做了什么

```text
浏览器
  │
  ▼
frontend/ React + Vite + Nginx
  │  同源 /api 反向代理
  ▼
backend/app/ FastAPI + JWT/RBAC + SQLite 运行账本
  │             │                 │
  │             │                 ├─ OPA 用途与执行策略
  │             │                 └─ connector/app/ 主体侧本地节点
  │             └─ 数据引用、承诺、规则、结果、证据和审计
  ▼
policy/ OPA/Rego 与能源执行约束
```

本系统围绕可信任务胶囊（TTC）组织一次受控数据使用和结算：

```text
INIT → IDENTITY_VERIFIED → DATA_AUTHORIZED → RULE_FROZEN → COMPUTE_EXEC
     → RESULT_CONFIRM → AUDIT_GATE → EVIDENCE_STAGE → EVIDENCE_ANCHOR → ARCHIVED
```

核心工作包括：

- 数据授权：数据目录、版本、用途、算法、输出模式、期限和调用次数进入授权约束；
- 可信执行：每次执行冻结规则、策略、合同、数据引用、算法、参数和单位，形成执行快照；
- 受控结算：生成确定性的聚合结果，不向中心业务 API 返回主体 Vault 原始记录；
- 多方隔离：后端按角色和组织校验权限，主体只能处理本组织结果；
- 隐私计算：提供差分隐私、加法秘密分享和 Paillier 适配器，并在结果中保留能力标签；
- 证据审计：记录数据、规则、计算、结果确认和审计事件，按域分离摘要形成 Merkle 批次，并通过事务 Outbox 留痕；
- 多能源扩展：电力、煤炭、热能、天然气、石油均有主体连接器和数据目录模型；
- 可解释管理：前端提供任务中心、可信数据空间、授权、隐私计算、结果证据、审计和平台运维页面。

## 5. 源代码阅读入口

交付包中的前后端代码均为可运行源代码，关键模块如下：

| 路径 | 内容 |
| --- | --- |
| `backend/app/main.py` | FastAPI 入口、路由、启动迁移、健康检查 |
| `backend/app/config.py` | 环境变量、演示/生产边界、白标和连接器配置 |
| `backend/app/database.py`、`migrations.py`、`models.py` | SQLite 连接、版本化迁移和领域模型 |
| `backend/app/security.py`、`production.py` | 密码、令牌、签名和生产门禁 |
| `backend/app/routers/` | 登录、数据、交易、执行、证据、审计、可信数据空间 API |
| `backend/app/services/workflow.py` | TTC 状态机、前置条件、动作和结算流程 |
| `backend/app/services/trust_execution.py` | 规则冻结、受控 Tool 和执行编排 |
| `backend/app/services/formal_evidence.py`、`evidence_outbox.py` | 证据摘要、Merkle 批次和事务 Outbox |
| `backend/app/services/mpc.py`、`privacy.py`、`paillier.py` | 隐私计算适配器和能力标签 |
| `backend/app/services/vault.py`、`local_data_boundary.py` | 主体数据引用、本地 Vault 和原始数据边界 |
| `SOURCE_CODE_GUIDE.md` | 源码目录、前后端调用链、数据边界、测试入口和扩展说明 |
| `connector/app/main.py` | 电力、煤炭、热能、天然气、石油主体侧本地连接器 |
| `frontend/src/App.tsx`、`auth.tsx`、`api.ts` | 前端入口、会话、API 客户端 |
| `frontend/src/features/trusted-energy/` | 可信数据空间目录、授权、查询、Agent、结果和审计页面 |
| `frontend/src/pages/` | 结算、数据、身份、策略、审计和管理页面 |
| `policy/hiddenchain.rego` | OPA 通用访问与用途策略 |
| `policy/energy_execution_policy.json` | 能源受控执行约束 |
| `docker-compose.yml` | 评委本地演示闭环 |
| `install-windows.ps1` | Windows 检查、构建、启动和健康检查 |

代码注释重点解释安全边界、状态转换、数据来源、失败行为和不能绕过的校验，不重复显而易见的变量含义。`backend/tests/`、`connector/tests/` 和 `frontend/src/*.test.*` 保留了后端、连接器和前端测试。

## 6. 验收命令

部署脚本成功后，可在 PowerShell 验证：

```powershell
Invoke-RestMethod http://127.0.0.1:5173/api/health
Invoke-RestMethod http://127.0.0.1:5173/api/health/ready

docker compose --project-name hiddenchain-windows `
  --env-file runtime\windows-demo.env `
  -f docker-compose.yml ps
```

前端能打开登录页、`/api/health` 返回 `status: ok`、`/api/health/ready` 返回 `status: READY`，即表示系统主体已启动。

## 7. 日常停止、启动与重置

停止服务但保留数据：

```powershell
docker compose --project-name hiddenchain-windows `
  --env-file runtime\windows-demo.env `
  -f docker-compose.yml down
```

再次启动：

```powershell
docker compose --project-name hiddenchain-windows `
  --env-file runtime\windows-demo.env `
  -f docker-compose.yml up -d
```

查看日志：

```powershell
docker compose --project-name hiddenchain-windows `
  --env-file runtime\windows-demo.env `
  -f docker-compose.yml logs --tail=100
```

只有需要清空本机演示数据时才执行下面的命令；它会删除演示 Docker volume：

```powershell
docker compose --project-name hiddenchain-windows `
  --env-file runtime\windows-demo.env `
  -f docker-compose.yml down -v
```

清空后重新执行 `install-windows.ps1 -Mode Demo` 即可重新初始化。

## 8. 故障排查

| 现象 | 处理 |
| --- | --- |
| `docker info` 失败 | 启动 Docker Desktop，确认使用 WSL 2 engine。 |
| Compose 构建下载失败 | 检查网络、代理和 Docker Desktop 镜像源，重新执行同一命令。 |
| 端口 5173 被占用 | 停止占用该端口的程序，或先执行 `docker compose ... down`。 |
| 页面打不开 | 执行 `docker compose ... ps` 和 `logs --tail=100`，等待 backend 健康后 frontend 才会启动。 |
| 登录失败 | 确认使用 Demo 模式、演示账号和本机 `5173` 地址；不要使用 production 配置登录。 |
| 启动后数据异常 | 备份需要保留的数据后执行 `down -v`，再重新运行安装脚本。 |
| 中文路径构建异常 | 把包移动到 `C:\hiddenchain-platform` 等 ASCII 路径后重试。 |

## 9. 能力边界

本交付包可运行的是本地评审闭环，不把演示环境包装成已经完成的跨主体生产基础设施：

- 确定性结算：`LOCAL_REAL`，单服务进程内执行；
- 差分隐私：`LOCAL_REAL`，本地 OpenDP 适配器；
- MPC/秘密分享和 Paillier：本地实验，份额/密钥编排仍在同一主机；
- EDC：`ADAPTER`，提供协议映射，不包含独立 EDC 控制面和数据面；
- TEE：`BLOCKED`，未接入硬件远程证明和密钥释放服务；
- 区块链锚定：默认 `DEMO`，使用本地确定性哈希回执，不代表外部链共识或终局性；
- 演示数据：全部为合成数据，不能用于生产结算。

这些边界在源码的能力标签、健康接口和注释中保持一致，评委可以从 `backend/app/version.py`、`backend/app/services/` 和本文复核。

## 10. 交付边界

压缩包不包含 `.env`、`.env.production`、数据库、Docker volume、日志、Python 虚拟环境、`node_modules`、前端构建缓存、截图、项目书和历史研究资料。Demo 密钥只在评委电脑首次运行时生成，生产密钥不得放入压缩包。
