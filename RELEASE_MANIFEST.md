# 隐链明算完整技术实现材料与 Windows 部署包交付清单

## 1. 基本信息

- 系统版本：`0.2.0`
- 交付平台：Windows 10/11 64 位 + Docker Desktop + WSL 2 engine
- 交付包类型：源码、注释文档、Windows Docker Compose 部署包和部署手册
- Demo 启动命令：`install-windows.ps1 -Mode Demo`
- 默认访问地址：`http://127.0.0.1:5173/login`
- 默认演示账号：`exchange / exchange123`

本包提供可在 Windows 上构建并启动的部署材料。Docker 镜像本体不预置在压缩包内，首次部署时由 Docker Desktop 根据 Compose 文件和各服务 Dockerfile 自动构建；这样可以避免提交不可移植的大型镜像文件。

## 2. 图片要求与包内对应关系

### 2.1 完整源代码（含注释文档）

- `backend/`：FastAPI 服务、数据库迁移、权限、TTC 工作流、确定性执行、证据和隐私计算适配器；含后端测试和生产门禁。
- `connector/`：电力、煤炭、热能、天然气、石油等能源主体的本地连接器服务。
- `frontend/`：React/Vite/Nginx 前端、锁定依赖、页面源码和生产检查脚本。
- `policy/`：OPA/Rego 策略和能源执行约束。
- `.github/workflows/`：仅包含可复现 CI 门禁所需的工作流 YAML；不包含 GitHub 凭据、运行产物或缓存。
- `SOURCE_CODE_GUIDE.md`：源码目录、关键文件、前后端调用链、数据边界、测试和扩展说明。
- 源码文件内的 Python、TypeScript、TSX 注释：解释安全边界、状态转换、数据来源、失败处理和不能绕过的校验。

### 2.2 可运行程序安装包/部署材料

- `install-windows.ps1`：Windows 一键检查、Demo 密钥生成、构建、启动和健康检查。
- `docker-compose.yml`：本地评审闭环编排。
- `docker-compose.production.yml`：生产参考编排。
- `Dockerfile`、`backend/Dockerfile`、`frontend/Dockerfile`、`connector/Dockerfile`：镜像构建入口。
- `deploy/Caddyfile`：生产反向代理配置。
- `production.env.example`：生产配置模板。
- `docs/PRODUCTION_AGENT_PROVISIONING.example.json`：生产 Agent 身份与授权的离线预配清单示例；仅含结构占位，不含真实身份、私钥或凭据。
- `frontend/public/sample-data/`：可选 Excel 导入样例。

### 2.3 详细部署手册

- `JUDGE_DEPLOYMENT.md`：Windows 环境准备、部署、登录、操作路线、验收、停止、重启、重置和故障排查。
- `JUDGE_DEPLOYMENT.tex`：部署手册的 XeLaTeX 源码。
- 如需 PDF，可在交付机上使用 XeLaTeX 从 `JUDGE_DEPLOYMENT.tex` 生成；源码包不承诺携带预编译 PDF。

## 3. 推荐操作

1. 解压到 `C:\hiddenchain-platform`；
2. 打开 `JUDGE_DEPLOYMENT.md`；如需 PDF，请按上一节说明从 `JUDGE_DEPLOYMENT.tex` 本地生成；
3. 启动 Docker Desktop，并确认 `docker info` 成功；
4. 执行：

   ```powershell
   Set-Location C:\hiddenchain-platform
   Set-ExecutionPolicy -Scope Process Bypass
   .\install-windows.ps1 -Mode Demo
   ```

5. 打开 `http://127.0.0.1:5173/login`；
6. 阅读 `SOURCE_CODE_GUIDE.md`，从 `backend/app/main.py`、`backend/app/services/workflow.py`、`connector/app/main.py`、`frontend/src/App.tsx` 和 `policy/hiddenchain.rego` 开始核对实现。

## 4. 明确排除

不交付 `.env`、`.env.production`、其他 `*.env` 运行配置、真实密钥、数据库、Docker volume、日志、`node_modules`、Python 虚拟环境、构建缓存、截图、项目书、答辩材料和历史研究资料。Demo 密钥由安装脚本首次运行时在评委电脑本机生成。

## 5. 已完成验证

- Windows PowerShell 5.1 脚本语法与 UTF-8 BOM 兼容性：通过；
- Demo/production Compose 配置展开校验：通过；
- Python 后端全量 pytest：通过；
- 前端 lint、Vitest、生产守卫、品牌守卫和 Vite 构建：通过；
- 源码与交付包逐文件哈希比对：通过；
- LaTeX 部署手册源码随包提供；预编译 PDF 不在本次源码交付范围内。

## 6. 目标 Windows 机器验收说明

当前开发机只有 Docker CLI，没有运行中的 Docker Desktop Linux engine，因此没有在本机完成 Docker 镜像实际构建和容器启动。目标机器首次运行 `install-windows.ps1 -Mode Demo` 时应保留构建日志，并按 `JUDGE_DEPLOYMENT.md` 完成 `/api/health` 和 `/api/health/ready` 验收。

这不是缺少源码或配置；它表示镜像构建和容器启动需要在已安装并启动 Docker Desktop 的 Windows 机器上完成。
