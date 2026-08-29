# 隐链明算生产部署

## 前提

- Linux 主机、Docker Engine 与 Docker Compose Plugin。
- 正式域名与 HTTPS 入口。
- 独立生产数据库或空白持久化卷。
- 两个不同且不少于 32 字符的随机密钥。
- 可用的 OPA 服务；生产不允许本地策略回退。

## 配置

```bash
cp production.env.example .env.production
chmod 600 .env.production
```

下方启动示例使用 `direct-domain` profile，因此至少设置：

```text
JWT_SECRET=<独立随机值>
SIGNING_SECRET=<另一独立随机值>
GIT_COMMIT=<本次部署的完整 Git commit SHA>
CORS_ORIGINS=https://settlement.example.com
PUBLIC_DOMAIN=settlement.example.com
APP_BIND_ADDRESS=127.0.0.1
PLATFORM_SIGNING_PRIVATE_KEY=<平台 Ed25519 私钥的 Base64>
SUBJECT_NODE_ENDPOINTS_JSON=<组织到服务端连接器 HTTPS 地址的 JSON>
SUBJECT_NODE_BROWSER_ENDPOINTS_JSON=<组织到浏览器可达连接器 HTTPS 地址的 JSON>
SUBJECT_NODE_IDS_JSON=<组织到连接器 ID 的 JSON>
SUBJECT_NODE_PUBLIC_KEYS_JSON=<组织到当前 Ed25519 公钥的 JSON>
```

连接器换钥时，把仍需验证历史回执的旧公钥放入 `SUBJECT_NODE_PUBLIC_KEY_RINGS_JSON`；该变量只允许公钥数组，不得放私钥。若启用 DID 钱包登录，还需设置只含公开钱包地址的 `DID_WALLET_BINDINGS_JSON`。

只有启用 `direct-domain` 时才要求 `PUBLIC_DOMAIN`，只有启用 `cloudflare` 时才要求 `CLOUDFLARE_TUNNEL_TOKEN`；未启用 profile 的对应变量可以留空。Windows 安装脚本会仅针对实际选择的 profile 做启动前校验。

白标字段见 [WHITE_LABEL_GUIDE.md](WHITE_LABEL_GUIDE.md)。不要提交 `.env.production`、数据库或访问令牌。

## 生产 Agent 身份初始化（首次 `up` 前必做）

生产启动只登记受控 Tool，不会自动生成 Agent 身份、密钥或授权。初始化清单必须精确定义六个 Agent 引用的全部活动生产组织、一个经外部验证且状态为 `VALID` 的组织 `grant_issuer_did`，以及六个 Agent DID。脚本可直接从空生产卷创建这些缺失记录，不需要预置默认组织或身份。

复制 [PRODUCTION_AGENT_PROVISIONING.example.json](PRODUCTION_AGENT_PROVISIONING.example.json) 到仓库外的受控路径，并逐项替换组织法定信息、组织 issuer DID、外部验证方 DID、所有外部公钥指纹、VC proof 与 verification 元数据。示例哈希仅用于说明格式，不是有效生产证明；清单不得包含私钥、助记词或访问令牌，也不要提交到 Git。

```bash
cp docs/PRODUCTION_AGENT_PROVISIONING.example.json ../production-agent-manifest.json
chmod 600 ../production-agent-manifest.json
docker compose --env-file .env.production -f docker-compose.production.yml build backend
docker compose --env-file .env.production -f docker-compose.production.yml run --rm -T backend \
  python /app/scripts/provision_production_agents.py --manifest /dev/stdin \
  < ../production-agent-manifest.json
```

脚本先执行数据库迁移，再严格核对组织引用全集以及清单是否与仓库内全部 Agent DID 完全一致。它按“组织 → 组织 issuer DID → Agent DID → 受控授权”顺序在一个事务内创建缺失记录；重复运行是幂等的。数据库中已有组织、issuer、Agent 身份、外部公钥指纹或活动授权与清单不一致时会以非零状态退出并回滚本次写入。只有输出中的数据库与 Agent readiness 都为 `READY` 后，才执行下方 `up` 命令。

## 构建与启动

```bash
docker compose --env-file .env.production -f docker-compose.production.yml build
docker compose --env-file .env.production -f docker-compose.production.yml --profile direct-domain up -d
```

构建时会同时运行后端与前端生产门禁。启动时后端再次校验：

- `APP_ENV=production`
- `TEST_FIXTURE_SEED=false`
- `DEMO_CATALOG_SEED=false`
- `DEMO_BUSINESS_SEED=false`
- `TEST_COMPUTE_DELAY_MS=0`
- `OPA_LOCAL_FALLBACK=false`
- 明确的非本地 CORS Origin
- 密钥强度与相互独立
- 主体连接器 endpoint、浏览器 endpoint、connector ID 与当前公钥按同一组织集合显式绑定
- 数据库不含测试主体、默认测试账户、测试任务或不受支持的历史适配器记录

校验失败时服务拒绝启动；不会自动修改或删除现有数据。

## HTTPS

`direct-domain` profile 使用 Caddy 自动申请证书。也可通过受管负载均衡器或命名 Tunnel 把 HTTPS 流量转发到 `frontend:8080`。OPA 只在 Compose 内网暴露 8181，不应直接公开。

## 验收

```bash
docker compose --env-file .env.production -f docker-compose.production.yml ps
docker compose --env-file .env.production -f docker-compose.production.yml logs --tail=100
curl -fsS https://settlement.example.com/api/health
```

随后按 [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) 检查空白生产库、正式账户接入、角色权限、任务闭环、备份恢复、日志与告警。

## 数据持久化

默认 SQLite 位于命名卷 `hiddenchain-runtime`，适合单实例。正式多副本部署应迁移到受管 PostgreSQL、使用共享限流存储，并建立加密备份、恢复演练和迁移流程；这些不由当前 Compose 自动提供。
