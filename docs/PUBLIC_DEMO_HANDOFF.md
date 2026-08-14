# 公网演示交接说明

当前公网演示地址：<https://hiddenchain-platform.onrender.com>

## 快速验收

- 健康检查：`GET /api/health`
- 可信执行控制面：登录后 `GET /api/trusted-execution/status`
- 前端入口：`/login`
- 演示账号：见项目根目录运行时生成的交接文件，不在文档中记录真实生产口令。

推荐按以下顺序演示：

1. 进入“平台概览”，查看能源节点目录、原始数据不出域和计算复核状态。
2. 进入“安全审计”，查看“安全可信 / 计算可信 / 可追溯”三层入口。
3. 在“计算复核队列”打开跨能源结果，核对策略命中、可复算口径、聚合趋势和结果哈希。
4. 使用监管账号点击“确认并留痕”，再切换到“已确认”筛选回看确认记录。

## 演示环境边界

Render 演示服务当前使用 `render.yaml` 中的 SQLite 运行时路径，适合展示和接口联调；服务重启或重新部署时，演示数据库中的运行时记录可能被重新初始化。因此：

- 不要上传真实企业数据、生产口令或个人敏感信息。
- 公网演示只验证控制器、策略边界、聚合计算、结果复核和模拟链凭证，不作为生产审计存储。
- 长期部署应将 `DATABASE_URL` 指向受管 PostgreSQL，或使用带备份的持久化卷，并配置独立密钥、HTTPS、访问日志和备份策略。
- 当前演示中的 FISCO BCOS、TEE、DID/VC 和隐私计算均保留替换边界；详情见 [`docs/TRUSTED_EXECUTION.md`](TRUSTED_EXECUTION.md) 和 [`docs/PRODUCTION_DEPLOYMENT.md`](PRODUCTION_DEPLOYMENT.md)。

## 长时巡检

公网巡检脚本会检查页面、健康接口、登录、任务、隐私计算、凭证、目录、协议和可信执行安全边界：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\performance-soak.ps1 `
  -BaseUrl https://hiddenchain-platform.onrender.com `
  -DurationHours 4 `
  -IntervalSeconds 30
```

日志写入 `runtime/performance/`，结束后查看 `*-summary.json`，确认 `failed_checks` 为 `0`。
