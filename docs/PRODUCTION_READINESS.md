# 生产就绪检查

适用版本：`0.2.0`。

当前总体结论：本地实现、验证、实现提交与远端分叉合并 `PASS`，正式生产验收仍为 `BLOCKED`。实现提交为 `71de395bf658fa34c8d271705ace130d9abf0e24`，非快进远端历史已安全合并为 `562f762`，当前待推送；尚无远程 SHA 收敛、生产基础设施或线上冒烟证据。`render.yaml` 仅为 review/test，不是生产环境。

## 自动门禁

```powershell
backend\.venv\Scripts\python.exe backend\scripts\check_production.py

cd frontend
pnpm check:production
pnpm test
pnpm build

cd ..\backend
.\.venv\Scripts\python.exe -m pytest -q
```

镜像构建会重复运行两个生产检查。`backend/tests/test_production_readiness.py` 覆盖配置 fail-closed、白标字段、数据库污染和测试端点隔离。

## 本次验证记录

| 门禁 | 状态 | 证据 |
| --- | --- | --- |
| 后端构建/测试 | `PASS` | `compileall`、`pip check`；117 项 pytest 全量通过 |
| 后端分支覆盖率 | `PASS` | coverage.py 7.15.4 + 固定随机种子全量通过，应用代码分支覆盖率 79%，高于 75% 门槛；GitHub 将在 `agent/**` 推送后以 Python 3.12 同构复跑 |
| 前端 lint/typecheck/test/build | `PASS` | ESLint、TypeScript、46 项 Vitest、生产/品牌守卫及 Vite 构建通过 |
| API 合同/黄金路径 | `PASS` | OpenAPI 0.2.0 可序列化，69 个 path；3 条显式端到端黄金路径通过 |
| 安全/失败/越权检查 | `PASS` | TTC 绕过、Agent 越权、Vault/算法/证据篡改、Outbox 重试/死信及跨组织访问回归通过 |
| commit/push/远程 SHA | `PARTIAL/PENDING` | 本地实现提交与非快进远端合并已完成；合并候选待推送，远程 SHA 尚未核验 |
| Render 部署/健康/在线冒烟 | `PENDING` | 需先推送并核验远端 SHA；当前清单即使可部署也仅允许 review/test |
| 生产外部基础设施 | `BLOCKED` | 需 PostgreSQL、共享限流/队列、持久对象存储、可观测性和高可用部署证据 |

## 发布前人工检查

- [ ] 使用独立生产数据库/卷，未从 development/test 复制。
- [ ] JWT 与签名密钥独立、随机、受密钥管理系统保护。
- [ ] CORS 只含正式 HTTPS Origin。
- [ ] OPA 可用且 `OPA_LOCAL_FALLBACK=false`。
- [ ] 正式身份接入完成；没有固定测试账户。
- [ ] 客户名称、Logo、版权、运营方、支持信息和登录公告已审批。
- [ ] 备份、恢复、保留期、告警、日志访问和事件响应已落地。
- [ ] 1366×768、1440×900、1920×1080 与 125% 缩放完成浏览器回归。
- [ ] 五种角色完成路由/直达/越权/API 数据范围回归。
- [ ] 用正式验收数据完成一条任务，并由双方分别确认。
- [ ] 对 MPC 仅标记 `LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST`，明确无独立节点和跨域生产隐私证明。
- [ ] 对 EDC、TEE、区块链和跨域不出域分别保持 `ADAPTER`、`BLOCKED`、`DEMO` 或 `BLOCKED`。
- [ ] 旧任务 `LEGACY_UNMIGRATED` 已隔离，没有被补造为可信 TTC 历史。
- [ ] 前端视觉冻结约束完成回归，无导航、布局、色彩或视觉层级重设计。

## 本版本验收结论模板

| 验收项 | 结论标准 |
| --- | --- |
| 环境隔离 | 门禁与启动校验通过为 YES |
| 生产无默认账户/夹具 | 空白生产库启动且测试端点 404 为 YES |
| 白标 | 配置变更能更新标题、Logo、客户与登录页为 YES |
| 结算任务闭环 | 创建、预检、执行、双边确认、审计可完成为 YES |
| 角色权限 | 页面、动作、直达路由和 API 数据范围一致为 YES |
| 本地计算与证据 | 回执和摘要核验可复现为 YES |
| 本地实验 MPC | 有限域份额协议验证通过且继续标注单主机边界时为 YES |
| 跨主体 MPC/TEE | 外部节点、传输/密钥与证明未接入时为 NO |
| 区块链存证 | 只有本地 DEMO 哈希回执、无链网络与共识确认时为 NO |
| 跨域不出域证明 | 独立数据面证明未提供时为 NO |

## 已知部署责任

当前 production Compose 默认 SQLite 与单实例内存限流，只适合单实例参考部署。多副本生产需要受管 PostgreSQL、共享限流/队列、持久存储、集中可观测性、备份恢复和基础设施级高可用。外部 EDC、TEE 和链网络也仍需独立建设与验收。任何本地测试或 Render review/test 成功都不能代替这些生产证据。
