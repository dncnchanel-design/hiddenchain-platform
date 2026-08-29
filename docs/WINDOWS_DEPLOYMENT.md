# Windows 部署手册

适用对象：Windows 10/11 64 位、Docker Desktop、PowerShell。本文部署的是“隐链明算”系统主体，不包含项目书、答辩视频和历史研究材料。

## 1. 运行条件

最低建议：4 核 CPU、8 GB 可用内存、20 GB 可用磁盘。首次构建需要联网下载 Docker 基础镜像和依赖；镜像构建完成后，系统主体可在无外网条件下运行。

需要安装并启动：

- Docker Desktop for Windows；
- Docker Desktop 的 WSL 2 based engine；
- PowerShell 5.1 或 PowerShell 7；
- Windows 防火墙允许本机访问 5173 端口（演示）或 8080 端口（生产本机入口）。

如果 Docker Desktop 没有启动，安装脚本会直接停止，不会修改系统配置。

## 2. 解压与安装

建议把压缩包解压到不含空格和中文的目录，例如 `C:\hiddenchain-platform`。打开 PowerShell：

```powershell
Set-Location C:\hiddenchain-platform
Set-ExecutionPolicy -Scope Process Bypass
.\install-windows.ps1 -Mode Demo
```

脚本会：

1. 检查 Docker 引擎和 Compose Plugin；
2. 在 `runtime\windows-demo.env` 生成本地演示密钥；
3. 构建 OPA、后端、前端和能源主体连接器镜像；
4. 启动 Docker Compose 服务并检查 `/api/health`；
5. 输出本地登录地址。

打开：<http://127.0.0.1:5173/login>

演示账户：`exchange` / `exchange123`。其他演示角色和密码以登录页运行时提示为准。演示账户、合成数据和本地密钥只能用于评审/演示，不得复用于生产。

## 3. 日常操作

```powershell
# 查看服务状态
docker compose --project-name hiddenchain-windows `
  --env-file runtime\windows-demo.env `
  -f docker-compose.yml ps

# 查看最近日志
docker compose --project-name hiddenchain-windows `
  --env-file runtime\windows-demo.env `
  -f docker-compose.yml logs --tail=100

# 停止服务，但保留数据库卷
docker compose --project-name hiddenchain-windows `
  --env-file runtime\windows-demo.env `
  -f docker-compose.yml down

# 重新启动，不重新构建镜像
docker compose --project-name hiddenchain-windows `
  --env-file runtime\windows-demo.env `
  -f docker-compose.yml up -d
```

重新运行 `install-windows.ps1 -Mode Demo` 会复用已有演示密钥和命名卷，不会覆盖数据库。只有明确需要清空演示数据时才执行下面的破坏性命令：

```powershell
docker compose --project-name hiddenchain-windows `
  --env-file runtime\windows-demo.env `
  -f docker-compose.yml down -v
```

## 4. Windows 上的生产参考部署

生产模式不会自动生成或覆盖密钥。先复制配置模板：

```powershell
Copy-Item production.env.example .env.production
notepad .env.production
```

至少修改：

- `JWT_SECRET` 和 `SIGNING_SECRET`：两个不同的随机值，每个至少 32 个字符；
- `GIT_COMMIT`：实际部署源码对应的完整 Git commit SHA；
- `CORS_ORIGINS`：正式 HTTPS Origin；
- `PUBLIC_DOMAIN`：仅 `DirectDomain` profile 需要，填写通过 Caddy 直接提供 HTTPS 的真实域名；
- `ENVIRONMENT_NAME`、白标字段和支持信息；
- `PLATFORM_SIGNING_PRIVATE_KEY`：平台 Ed25519 请求签名私钥；
- `SUBJECT_NODE_ENDPOINTS_JSON` 与 `SUBJECT_NODE_BROWSER_ENDPOINTS_JSON`：组织到服务端/浏览器可达 HTTPS 连接器地址；
- `SUBJECT_NODE_IDS_JSON` 与 `SUBJECT_NODE_PUBLIC_KEYS_JSON`：组织到连接器 ID 与当前 Ed25519 公钥；
- 连接器换钥且需保留历史回执验证时，在 `SUBJECT_NODE_PUBLIC_KEY_RINGS_JSON` 中仅加入退役公钥。

首次生产启动必须先预配 Organization、组织 issuer DID、Agent DID 与受控授权。把示例复制到仓库外；逐项替换组织法定信息、外部公钥指纹、VC proof 和 verification 元数据。示例值不是生产证明，清单不得包含私钥、助记词或访问令牌，也不得提交 Git。

```powershell
$manifestDirectory = Join-Path $env:USERPROFILE "hiddenchain-production-config"
New-Item -ItemType Directory -Force -Path $manifestDirectory | Out-Null
$manifestPath = Join-Path $manifestDirectory "production-agent-manifest.json"
Copy-Item docs\PRODUCTION_AGENT_PROVISIONING.example.json $manifestPath
notepad $manifestPath

$resolvedManifestPath = (Resolve-Path -LiteralPath $manifestPath).Path
$composeArgs = @(
  "--project-name", "hiddenchain-windows",
  "--env-file", ".env.production",
  "-f", "docker-compose.production.yml"
)

docker compose @composeArgs build backend
if ($LASTEXITCODE -ne 0) { throw "Backend production build failed" }
docker compose @composeArgs run --rm `
  --volume "${resolvedManifestPath}:/run/config/production-agent-manifest.json:ro" `
  backend python /app/scripts/provision_production_agents.py `
  --manifest /run/config/production-agent-manifest.json
if ($LASTEXITCODE -ne 0) { throw "Production Agent provisioning failed" }
docker compose @composeArgs up -d
```

CLI 会先迁移空生产卷，再按清单原子创建缺失记录；重复运行是幂等的。已有 Organization、issuer、Agent 身份或活动授权不一致时会退出并回滚本次写入。确认输出中的数据库和 Agent readiness 都为 `READY` 后才允许执行最后一行 `up`；若 CLI 失败，先修正清单或冲突数据，不要跳过预配。

后续仅供内网或本机反向代理使用时，可用安装脚本启动默认 profile：

```powershell
.\install-windows.ps1 -Mode Production
```

使用 Caddy 自动申请正式证书时，先确保域名 DNS 已指向本机，再执行：

```powershell
.\install-windows.ps1 -Mode Production -Profile DirectDomain
```

此模式会开放 80/443；`PUBLIC_DOMAIN` 必须是真实域名，不能使用 localhost。使用 Cloudflare Named Tunnel 时，把 `CLOUDFLARE_TUNNEL_TOKEN` 写入 `.env.production` 后执行：

```powershell
.\install-windows.ps1 -Mode Production -Profile Cloudflare
```

未启用 profile 的对应变量可以留空：默认 profile 不要求 `PUBLIC_DOMAIN` 或 `CLOUDFLARE_TUNNEL_TOKEN`，`DirectDomain` 只校验前者，`Cloudflare` 只校验后者。

生产入口的后端不会启用测试夹具、默认测试账户或 OPA 本地回退。生产数据库必须使用独立持久化卷，且需要自行配置备份、恢复、日志、告警和密钥管理。

## 5. 生产停止与日志

```powershell
docker compose --project-name hiddenchain-windows `
  --env-file .env.production `
  -f docker-compose.production.yml ps

docker compose --project-name hiddenchain-windows `
  --env-file .env.production `
  -f docker-compose.production.yml logs --tail=100

docker compose --project-name hiddenchain-windows `
  --env-file .env.production `
  -f docker-compose.production.yml down
```

不要把 `.env.production`、`runtime\`、数据库文件或 Docker volume 打包、提交 Git 或发送给评委。

## 6. 故障排查

| 现象 | 处理 |
| --- | --- |
| `docker info` 失败 | 启动 Docker Desktop，确认 WSL 2 engine 可用 |
| 构建下载超时 | 检查网络、代理和 Docker Desktop 镜像源；重新执行同一安装命令 |
| `5173` 无法访问 | 执行 `docker compose ... ps` 和 `logs --tail=100`，确认 backend 健康后 frontend 才会启动 |
| 后端健康检查失败 | 查看 backend 日志；常见原因是旧卷中的配置/迁移异常，先备份后再决定是否重建演示卷 |
| 生产启动拒绝 | 保留拒绝信息，检查密钥、CORS、OPA、环境标签和数据库是否混入测试数据 |
| 中文路径导致构建问题 | 把压缩包移到 `C:\hiddenchain-platform` 等 ASCII 路径后重试 |

## 7. 能力边界

本安装包提供可运行的能源可信数据空间演示闭环。确定性结算在单服务进程内执行；MPC/Paillier 标记为单主机实验；EDC 是协议适配器；TEE 尚未接入；默认区块链锚定是本地哈希演示。部署手册不把这些能力表述为已经完成的跨主体生产基础设施。
