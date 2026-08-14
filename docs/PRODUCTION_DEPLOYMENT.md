# 隐链明算长期稳定演示部署

## 推荐架构

```text
评委浏览器
  -> https://demo.<团队域名>
  -> DNS 解析到云服务器，或 Cloudflare 命名 Tunnel
  -> 云服务器 Docker Compose
  -> Caddy/Nginx 前端与 /api 反向代理
  -> FastAPI 后端、OPA 策略服务与持久化数据卷
```

与临时 `trycloudflare.com` 链接不同，此方案使用固定域名和云服务器。服务器重启后 Docker 会自动恢复容器，公网地址不会变化。

## 资源要求

1. 一台可长期运行的 Linux 云服务器。建议 Ubuntu 22.04 及以上、2 vCPU、4 GB RAM、40 GB 磁盘。
2. 一个由团队控制的域名，例如 `demo.example.com`。
3. 服务器上的 Docker Engine 与 Docker Compose Plugin。
4. 可选：Cloudflare 账号和 Tunnel Token。仅方案 B 需要。

请不要把真实密钥、数据库文件或 Cloudflare Token 提交到仓库或发送到群聊。

## 方案 A：直接域名 HTTPS（推荐）

此方案只需要云服务器和域名，不需要 Cloudflare。

1. 在域名 DNS 控制台添加 A 记录：`demo.<团队域名>` 指向云服务器公网 IPv4。
2. 在云服务器安全组中放行 `22/TCP`、`80/TCP` 和 `443/TCP`。
3. 准备生产环境文件：

```bash
cp production.env.example .env.production
chmod 600 .env.production
```

4. 编辑 `.env.production`：

```text
JWT_SECRET=<随机且不少于32字符的值>
SIGNING_SECRET=<随机且不少于32字符的值>
PUBLIC_DOMAIN=demo.<团队域名>
CORS_ORIGINS=https://demo.<团队域名>
```

5. DNS 生效后启动：

```bash
docker compose --env-file .env.production -f docker-compose.production.yml --profile direct-domain up -d --build
```

生产 Compose 会同时启动内部 OPA PDP 和 FastAPI；OPA 不暴露公网端口，后端通过 `OPA_URL=http://opa:8181` 调用 `policy/hiddenchain.rego`。生产配置默认关闭本地策略回退，PDP 不可用时请求会 fail-closed。

`caddy` 会自动申请和续期 HTTPS 证书。最终访问地址为：

```text
https://demo.<团队域名>/login
```

## 方案 B：Cloudflare 命名 Tunnel

适合不希望开放云服务器 80/443 端口的场景。

1. 在 Cloudflare Dashboard 的 `Networking > Tunnels` 新建 Tunnel，例如 `hiddenchain-demo`。
2. 添加 Published application：主机名填写 `demo.<团队域名>`，Service 填写 `http://frontend:80`。
3. 将 Tunnel Token 写入 `.env.production`：

```text
PUBLIC_DOMAIN=demo.<团队域名>
CORS_ORIGINS=https://demo.<团队域名>
CLOUDFLARE_TUNNEL_TOKEN=<Cloudflare控制台复制的token>
```

4. 启动：

```bash
docker compose --env-file .env.production -f docker-compose.production.yml --profile cloudflare up -d --build
```

`frontend` 是 Compose 内部服务名，因此 Tunnel 容器可直接访问它，无需开放服务器入站 80/443 端口。

## 验收与保障

```bash
docker compose --env-file .env.production -f docker-compose.production.yml ps
docker compose --env-file .env.production -f docker-compose.production.yml logs --tail=100
```

- 容器设置为 `restart: unless-stopped`，云服务器重启后会自动恢复。
- SQLite 数据保存在 Docker 命名卷 `hiddenchain-runtime`；答辩前应备份演示数据卷。
- 比赛前使用手机蜂窝网络完成登录、可信数据调用、隐私计算、能源场景验证和审计报告的全流程验收。
- 仍应保留本机局域网演示和录屏作为网络故障预案。

## 关于中国内地服务器

若选择中国内地服务器对外提供网站服务，需要按当地规则完成 ICP 备案。若比赛周期紧张，可选择中国香港或海外节点，并根据团队网络测试访问速度。
