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

至少设置：

```text
JWT_SECRET=<独立随机值>
SIGNING_SECRET=<另一独立随机值>
CORS_ORIGINS=https://settlement.example.com
PUBLIC_DOMAIN=settlement.example.com
APP_BIND_ADDRESS=127.0.0.1
```

白标字段见 [WHITE_LABEL_GUIDE.md](WHITE_LABEL_GUIDE.md)。不要提交 `.env.production`、数据库或访问令牌。

## 构建与启动

```bash
docker compose --env-file .env.production -f docker-compose.production.yml build
docker compose --env-file .env.production -f docker-compose.production.yml --profile direct-domain up -d
```

构建时会同时运行后端与前端生产门禁。启动时后端再次校验：

- `APP_ENV=production`
- `TEST_FIXTURE_SEED=false`
- `TEST_COMPUTE_DELAY_MS=0`
- `OPA_LOCAL_FALLBACK=false`
- 明确的非本地 CORS Origin
- 密钥强度与相互独立
- 数据库不含测试主体、默认测试账户、测试任务或不受支持的历史适配器记录

校验失败时服务拒绝启动；不会自动修改或删除现有数据。

## HTTPS

`direct-domain` profile 使用 Caddy 自动申请证书。也可通过受管负载均衡器或命名 Tunnel 把 HTTPS 流量转发到 `frontend:80`。OPA 只在 Compose 内网暴露 8181，不应直接公开。

## 验收

```bash
docker compose --env-file .env.production -f docker-compose.production.yml ps
docker compose --env-file .env.production -f docker-compose.production.yml logs --tail=100
curl -fsS https://settlement.example.com/api/health
```

随后按 [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) 检查空白生产库、正式账户接入、角色权限、任务闭环、备份恢复、日志与告警。

## 数据持久化

默认 SQLite 位于命名卷 `hiddenchain-runtime`，适合单实例。正式多副本部署应迁移到受管 PostgreSQL、使用共享限流存储，并建立加密备份、恢复演练和迁移流程；这些不由当前 Compose 自动提供。
