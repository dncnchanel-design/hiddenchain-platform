# 生产就绪检查

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

## 本次代码验收证据

- 后端：58 项通过，1 项按条件跳过。
- 前端：4 个测试文件、12 项通过；ESLint、TypeScript、生产源码门禁和 Vite 正式构建通过；Impeccable 检测 0 项。
- 浏览器：1366×768、1440×900、1920×1080 共 63 张页面截图，9 个越权直链检查，0 个失败。
- Compose：production 配置使用显式密钥、HTTPS CORS 与 production 构建目标时可解析。
- 镜像边界：production stage 物理删除 `seed.py`、`test_support.py` 与 `test_schemas.py`。

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
- [ ] 对 MPC、TEE、区块链和跨域不出域的对外材料仍标记未配置/未提供。

## 本版本验收结论模板

| 验收项 | 结论标准 |
| --- | --- |
| 环境隔离 | 门禁与启动校验通过为 YES |
| 生产无默认账户/夹具 | 空白生产库启动且测试端点 404 为 YES |
| 白标 | 配置变更能更新标题、Logo、客户与登录页为 YES |
| 结算任务闭环 | 创建、预检、执行、双边确认、审计可完成为 YES |
| 角色权限 | 页面、动作、直达路由和 API 数据范围一致为 YES |
| 本地计算与证据 | 回执和摘要核验可复现为 YES |
| 真实 MPC/TEE | 外部运行时与证明未接入时为 NO |
| 区块链存证 | 链网络与交易确认未接入时为 NO |
| 跨域不出域证明 | 独立数据面证明未提供时为 NO |

## 已知部署责任

当前 Compose 默认 SQLite 与单实例内存限流，只适合单实例。多副本生产需要外部 PostgreSQL、共享限流存储、集中可观测性、迁移工具和基础设施级高可用；这些属于部署责任，不能由应用测试结果替代。

本次本机 Docker Desktop 引擎未启动，因此已完成 Compose 配置解析、构建目标和源码门禁验证，但未实际生成 production 镜像。正式发布前必须在可用 Docker/CI 引擎中执行 production 镜像构建、文件清单核验和部署冒烟测试。
