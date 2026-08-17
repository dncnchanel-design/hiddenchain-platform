# 非生产：隐链明算比赛演示部署说明

> 该流程只启动 test 环境，不属于 production 发布路径。生产部署见 `PRODUCTION_DEPLOYMENT.md`。

## 三种访问方式

1. 本机开发：`http://127.0.0.1:5173/login`
2. 现场局域网：电脑和评委设备连接同一网络后，访问脚本输出的 `LAN_URL`
3. 临时公网：运行启动脚本后，将 `PUBLIC_URL` 发给老师或评委

## 一键启动

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-competition-demo.ps1
```

当前公网地址、局域网地址和演示账号会同时写入：

```text
runtime/public-url.txt
```

停止演示服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\stop-competition-demo.ps1
```

## 比赛使用边界

- `trycloudflare.com` 是无需账号的临时隧道，适合联调、老师评审和现场答辩。
- 电脑关机、休眠、断网或隧道进程退出后，公网地址失效；重新启动后地址可能变化。
- 公网演示仅使用系统内置假数据和演示账号，不录入真实企业数据、身份证号或生产口令。
- 答辩前应使用手机蜂窝网络测试公网地址，避免只在同一 Wi-Fi 下自测。
- 现场同时保留局域网地址、录屏和关键流程截图，防止比赛场馆网络不稳定。

## 答辩主线

答辩现场建议从“可信调用验证”进入，使用 `demo-data/2026-08-simulation-input.json`，按以下顺序展示：

`可信采集 → 安全传输 → 可控使用 → 隐私计算 → 可溯审计`

电力交易的电量和金额只作为能源场景验证输出；重点讲解数据引用、授权策略、计算沙箱、原始数据不出域和证据核验。

## 正式提交的稳定方案

项目根目录已有 `docker-compose.yml`，前端使用 Nginx 提供静态资源并反向代理 `/api`，后端使用 FastAPI 和持久化运行卷。正式提交或长期评审时，应将该 Compose 部署到云服务器，并配置固定域名、HTTPS、独立密钥、备份和访问日志。

稳定公网域名需要团队提供云服务器或 Cloudflare 账号与自有域名；临时隧道不能替代长期托管。
