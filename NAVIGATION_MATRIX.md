# 顶部导航与路由矩阵

## 生成原则

- 一级导航表示业务域，二级菜单表示可完成的真实功能，页面内 Tab 只切换同一功能的视图。
- 菜单同时受 `frontend/src/access.ts` 的角色策略与登录响应中的 `menus` 控制。缺少任一条件均不生成入口。
- 前端菜单隐藏不构成授权。直接访问路由仍由 `Allowed`、角色校验和后端数据权限共同拒绝，无权访问进入正式 403 页面。
- `管理控制台` 仅在会话实际拥有管理路由时生成。当前角色模型中仅 `ADMIN` 满足条件。
- 带查询参数或锚点的入口只定位现有页面视图，不增加后端接口，也不虚构独立页面。

## 路由矩阵

| 路由 | Workspace | 一级栏目 | 二级菜单或页面入口 | 页面标题 | 允许角色 |
| --- | --- | --- | --- | --- | --- |
| `/login` | Public | - | 身份认证 | 登录 | 未登录用户 |
| `/workbench` | Business | 首页 | 首页 | 工作台 | `GENERATOR` `RETAILER` `EXCHANGE` `REGULATOR` `ADMIN` |
| `/settlements` | Business | 结算管理 | 结算任务 | 结算任务 | 全部已登录角色 |
| `/settlements?view=todo` | Business | 结算管理 | 待我处理 | 结算任务 | 全部已登录角色 |
| `/settlements?view=completed` | Business | 结算管理 | 结算记录 | 结算任务 / 已完成视图 | 全部已登录角色 |
| `/settlements/new` | Business | 结算管理 | 发起结算任务 | 发起结算任务 | `EXCHANGE` |
| `/settlements/:taskId` | Business | 结算管理 | 结算任务 | 结算任务详情 | 全部已登录角色，数据范围由后端限定 |
| `/results` | Business | 结算管理 | 结果确认 | 结算结果 | 全部已登录角色，确认动作仅业务主体 |
| `/rules` | Business | 结算管理 | 结算规则 | 结算规则 | `EXCHANGE` `REGULATOR` `ADMIN` |
| `/data-space` | Business | 可信数据空间 | 数据目录 | 可信数据目录 | 全部已登录角色 |
| `/data-space#data-authorizations` | Business | 可信数据空间 | 数据授权记录 | 可信数据目录 / 数据授权记录 | 全部已登录角色 |
| `/data/generation` | Business | 可信数据空间 | 发电侧数据 | 发电侧数据 | `GENERATOR` `EXCHANGE` `REGULATOR` `ADMIN` |
| `/data/retail` | Business | 可信数据空间 | 用电侧数据 | 用电侧数据 | `RETAILER` `EXCHANGE` `REGULATOR` `ADMIN` |
| `/compute` | Business | 隐私计算 | 计算任务 | 隐私计算 | 全部已登录角色 |
| `/compute?tab=tasks` | Business | 隐私计算 | 计算任务 | 隐私计算 / 调用计算 | 全部已登录角色 |
| `/compute#compute-strategies` | Business | 隐私计算 | 计算方案 | 隐私计算 / 计算方案 | 全部已登录角色 |
| `/compute?tab=analysis` | Business | 隐私计算 | 用电分析 | 隐私计算 / 用电分析 | `RETAILER` `EXCHANGE` `REGULATOR` `ADMIN` |
| `/evidence` | Business | 审计与风控 | 审计凭证 | 证据台账 | 全部已登录角色 |
| `/audit` | Business | 审计与风控 | 审计复核 | 审计复核 | `EXCHANGE` `REGULATOR` `ADMIN` |
| `/reports` | Business | 审计与风控 | 审计报告 | 审计报告 | `EXCHANGE` `REGULATOR` `ADMIN` |
| `/anomalies` | Business | 审计与风控 | 风险处置 | 风险处置 | `EXCHANGE` `REGULATOR` `ADMIN` |
| `/overview` | Admin | 管理控制台 | 管理总览 | 管理总览 | `ADMIN` |
| `/system` | Admin | 管理控制台 | 组织与权限 | 组织与权限 | `ADMIN` |
| `/agents` | Admin | 管理控制台 | 能力与服务 | 能力与服务 | `ADMIN` |
| `/metrics` | Admin | 管理控制台 | 运行监控 | 运行监控 | `ADMIN` |
| `/logs` | Admin | 管理控制台 | 系统日志 | 系统日志 | `ADMIN` |
| `/403` | Protected state | 页面状态 | - | 无权访问 | 已登录但无对应权限 |
| `*` | Protected state | 页面状态 | - | 页面不存在 | 已登录用户 |

## 当前选中规则

- 任务详情、发起任务、结算规则与结果页面均保持 `结算管理` 一级栏目激活。
- 数据目录、数据授权记录和两侧数据页面均保持 `可信数据空间` 激活。
- 查询参数与锚点匹配时优先选中对应二级入口；普通路径不与视图入口重复高亮。
- 管理路由只激活 `管理控制台`，普通业务角色不会收到该栏目数据。
- 面包屑限制在 1-3 层。任务详情显示 `结算管理 / 结算任务 / 任务编号`。

## 交互与可访问性

- 鼠标悬停约 120ms 打开，离开约 220ms 关闭；触发器和菜单位于同一悬停区域，跨越边界不会立即消失。
- 点击一级栏目可切换菜单，点击页面其他区域或完成路由跳转后关闭。
- 支持 `Tab`、`Enter`、`Space`、`Escape`、`ArrowDown`、`ArrowUp`、`Home`、`End`。
- 触发器使用 `aria-haspopup="menu"`、`aria-expanded`、`aria-controls`；当前栏目和当前功能使用 `aria-current="page"`。
- 1366px 及以上保持单行横向导航；窄屏改为临时导航抽屉，不恢复常驻左侧主导航。
