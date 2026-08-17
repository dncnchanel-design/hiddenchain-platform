# 双工作空间与角色路由矩阵

## 权限来源与原则

前端权限由会话中的 `user.role_code`、后端返回的 `menus` 和本文件定义的工作空间策略共同推导。后端仍是数据权限和操作权限的最终边界；前端不修改接口契约，也不把隐藏菜单当作安全控制。

当前后端实际角色只有 `GENERATOR`、`RETAILER`、`EXCHANGE`、`REGULATOR`、`ADMIN`。未提供独立的结算复核或运维角色代码，因此不能在前端伪造这些角色。对应职责通过现有角色可访问操作表达。

## 工作空间

### 业务工作台

适用角色：`GENERATOR`、`RETAILER`、`EXCHANGE`、`REGULATOR`、`ADMIN`。

导航分组：

1. 工作入口：工作台 `/workbench`
2. 数据与授权：数据目录 `/data-space`、发电侧数据 `/data/generation`、用电侧数据 `/data/retail`、授权规则 `/rules`
3. 计算与验证：隐私计算 `/compute`、调用验证 `/settlements`、结果确认 `/results`
4. 审计与风控：审计凭证 `/evidence`、审计复核 `/audit`、审计报告 `/reports`、风险处置 `/anomalies`

### 管理控制台

当前仅 `ADMIN` 具有完整管理权限并可进入。

导航：管理总览 `/overview`、组织与权限 `/system`、能力与服务 `/agents`、运行监控 `/metrics`、系统日志 `/logs`。

`ADMIN` 同时拥有业务和管理菜单，因此显示工作空间切换入口。其他角色不显示该入口，也不能直接访问管理路由。

## 路由矩阵

| 角色 | 工作空间 | 可访问路由 | 主要允许操作 |
| --- | --- | --- | --- |
| `GENERATOR` 发电企业 | 业务 | `/workbench` `/data-space` `/data/generation` `/settlements` `/compute` `/results` `/evidence` | 登记和确认本角色允许的发电数据；查看参与任务、计算回执和证据；确认本组织结果 |
| `RETAILER` 售电企业 | 业务 | `/workbench` `/data-space` `/data/retail` `/settlements` `/compute` `/results` `/evidence` | 登记和确认本角色允许的用电数据；发起现有接口支持的用电隐私分析；确认本组织结果 |
| `EXCHANGE` 交易中心 | 业务 | `/workbench` `/data-space` `/data/generation` `/data/retail` `/rules` `/compute` `/settlements` `/results` `/evidence` `/audit` `/reports` `/anomalies` | 登记调度边界；创建和启用规则；创建、导入和运行调用验证；确认结果；查看审计与风险 |
| `REGULATOR` 监管方 | 业务 | `/workbench` `/data-space` `/data/generation` `/data/retail` `/rules` `/compute` `/settlements` `/results` `/evidence` `/audit` `/reports` `/anomalies` | 只读查看业务数据与规则；复核结果；生成审计报告；处置风险事件 |
| `ADMIN` 系统管理员 | 业务 + 管理 | 全部业务路由；`/overview` `/system` `/agents` `/metrics` `/logs` | 在业务空间按现有接口权限操作；在管理空间查看组织、身份、能力服务、指标和日志 |

## 按钮权限

- 规则新建、启用：仅 `EXCHANGE`。
- 验证任务新建：仅 `EXCHANGE`；导入并运行：`EXCHANGE`、`ADMIN`。
- 结果确认：`GENERATOR`、`RETAILER`、`EXCHANGE`。
- 计算复核确认：`REGULATOR`、`ADMIN`。
- 报告生成：`REGULATOR`、`ADMIN`。
- 风险处置：`REGULATOR`、`ADMIN`。
- 管理控制台页面与操作：仅 `ADMIN`。
- 当前后端未提供结果、报告或日志的授权审计导出端点，因此这些页面不显示浏览器侧导出；后续开放时必须同时具备显式导出权限与服务端审计记录。

## 拒绝与会话规则

- 未登录访问受保护路由：进入 `/login`。
- 会话过期或接口返回 401：清理内存与会话级令牌，进入 `/session-expired`，不无限重试。
- 超时、离线或 5xx：保留有效会话级令牌，进入可重试不可用状态；服务恢复后无需重新登录。
- 已登录但无权访问路由：进入 `/403`，显示被拒绝路径和返回当前工作空间入口。
- 未知路由：进入正式 404 页面，不重定向到总览或空白页。
- 工作空间切换后，若当前路径不属于目标空间，进入该空间默认页；业务默认 `/workbench`，管理默认 `/overview`。
- 菜单与路由使用同一权限定义生成，不能出现“菜单隐藏但 URL 可访问”的分叉逻辑。
