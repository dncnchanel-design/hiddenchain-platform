# 当前完整功能与分角色验收清单

本清单以当前挂载的 React 路由、实际控件和调用的后端 API 为边界。源码中已经退休、未挂载的旧页面不算当前功能。HTTP 成功、页面加载成功、浏览器交互成功是三种不同证据；任何一项都不代替另外两项。

## 业务助手自然问法追加验收

用户原话“我想查询一下我现在有哪些数据”现在通过受控本方目录动作处理；12业务账号均以真实HTTP与当前组织目录比对，管理员仍403。新增28项后端、11项前端（含原有状态组增量）覆盖范围、空目录、分页、未知重试、校验不一致和复核回执；助手组合67、前端217通过。本地完整HTTP扩为121项/644请求，原有不可达与私有分布说明仍分列，0 FAIL。当前线上执行证据见 `runtime/assistant-catalog-release.json`。

## 本轮收口记录

最终源代码冻结后重新启动平台和七连接器，保留旧证据，完整复跑至 `runtime/deep-workflows-final-release.json`。109 项与 596 次 HTTP 调用中，90 PASS、13 正确阻断、0 FAIL；五个不能由正常当前流程稳定生成的前置状态没有计为成功。PSI 的 HTTP 签名/单位/有限性通过，分布不出域，独立公式 `ln(5)/8` 由 `connector/tests/test_period_comparisons.py` 的已运行测试证明。

浏览器逐项证据在 `runtime/complete-account-ui.json`，覆盖全部13账号。每项保存账号、检查条件及当时 DOM；`HARNESS_*` 保留工具快照/语言文案/遮挡导致的断言修正，不计入成功项；`PRODUCT_*` 保留真实缺陷的修复历史，其后另有复测 PASS。首轮49组与89页面访问属于较早基线，不代替本轮真实操作。

| 功能 | 实际浏览器证据 | 补充或不可达边界 |
| --- | --- | --- |
| 登录/账号 | 13账号登录退出、密码显示/隐藏、记忆勾选与清除、菜单、403/404返回 | 表单值可能被工具脱敏；偏好值另有单元测试。外部钱包未安装，实际点击验证明确提示；有效签名由后端测试验证，不能称真实外部钱包签名已完成。 |
| 全局/手机 | 导航打开/Escape关闭、账号中心、帮助打开刷新关闭；390与1280宽度、无水平溢出 | 输入法 composition、焦点及懒加载失败恢复另由现有自动回归；不将这些测试写成物理输入法操作。 |
| 目录/护照 | 搜索空态/清空、等级筛选、分页；修后第一页可筛煤炭/热能，空搜索仍保留全范围筛选；四标签、复制、DID文档展开与刷新 | 筛选选项仅来自当前账号可见范围；护照不含原始记录或私钥。 |
| 申请/审核 | 五种普通用途、两种处理方式、未勾选/期限/监管依据/应急7日校验、提交、审核意见必填、开始审核、批准、申请方撤回、获批后查询 | 审核拒绝/撤销、并发版本、全角色边界另有真实HTTP和回归；不扩大监管用途或外部授权。 |
| 智能查询 | 七节点所有者均在UI成功计算；四非电交易中心经真实批准成功查询；监管先正确拒绝缺少规则，再批准后成功；中文区间恢复、12条结果、签名证明、任务详情、服务中断重试 | 14固定函数由真实HTTP执行并核验；UI目前提供六种解析函数，小时/阈值/分组不冒称有手工表单。默认自动规则31日，显式授权按批准范围。 |
| 连接器 | 真实文件选择、错误CSV拒绝、修正后3行直传与签名登记；七节点HTTP接入已有证据 | 四非电交易中心均实际检查未就绪和重新检查按钮，不能冒称有本方直传节点。回执崩溃恢复及签名篡改由端到端/边界自动回归。 |
| 合同 | 空状态筛选后仍可选择恢复、ACTIVE协商详情、消息必填、真实回复持久化，禁用反报价/接受/拒绝 | 正常批准直接ACTIVE，没有稳定PENDING/NEGOTIATED入口；后三动作实际409并记录不可达，不造状态。 |
| 结算/TTC | 五步字段/日期/参与方/就绪/规则/回退保留；创建、启动确认取消、刷新、真实执行、日志、结果跳转 | UI任务 `a4e81c4c-4830-4915-ad39-d10208711549` 最终 V13 归档，截图 `.impeccable/review/complete-settlement-ui.png`。短暂运行态中断不可稳定触发，非法状态409另有HTTP证据。 |
| 隐私计算 | 状态筛选、空态/恢复、订阅与停止日志；查询深链；原始记录“不返回”、本方主体去重；完成态禁用重试/取消 | 当前没有真实重排队执行器，无法正常生成可停留的本地QUEUED取消前置；正确拒绝而非虚假重试。 |
| 结果/证据 | 结果列表按任务定位、复制任务号、核验证据、意见必填、选择异议/通过；发电/售电分别签署本方结果，双方后归档 | 真正异议提交与同键重放由独立HTTP任务验证；不替他方签名，摘要不充当原始结算数据。 |
| 审计/报告 | 审计分页、查询审计详情；报告抽屉/证据引用、意见校验、两层确认取消/批准 | 报告驳回和结算返工由真实HTTP验证；补充生成只针对已有AUDITED任务，未伪造该前置。正式证据记录页面只读。 |
| 风险 | 风险/状态筛选、详情、确认与忽略的两层弹窗及持久化；查询事件跳正确审计页面 | 查询失败事件不允许结算REWORK；FAILED结算返工由HTTP验证。 |
| 通知 | 单条已读、全部已读、分页、刷新、Escape、结果关联目标 | 12业务账号均分别产生本轮通知并由HTTP验证单条已读和目标范围。 |
| 业务助手 | 错误对象在计划阶段阻断、没有执行按钮；job状态和资产检查真实成功；取消计划；跨页新会话不携旧job | 全五读、五写草案、重试、旧错类型/跨角色拒绝另由39项组合测试及109真实HTTP验证；写计划保持待人工复核。 |
| 电力聊天 | 两类公式完整计算、无效参数/未确认拒绝、保存/暂不保存后恢复、复用再确认、新对话、继续、完成；真实下载CSV并核对数值 | 本方案例按账号隔离；390/1280截图见 `.impeccable/review/complete-account-{mobile,desktop}.png`。不增加额外示例/免责声明标注。 |
| 管理五模块 | 组织/能力/监控刷新，菜单切换；系统日志关键词/结果空态；表格列设置、三态排序、20/50/100切换 | 当前隔离栈管理日志为空，详情抽屉无合法记录可点击；不为凑通过插库造日志。无账号CRUD/密码重置控件。管理员业务URL403。 |

最终本地前端206项与生产构建、节点85项通过；后端591项完整基线与新增定向组合通过，最终693项完整收集交给同提交 GitHub 分支覆盖率门禁（75%不变）。GitHub门禁、八服务SHA和线上复验的实际结果写入 `runtime/account-release-evidence.json`。

以下为完整源码功能盘点与测试定位；其中 `UI_EVIDENCE_MATRIX` 指向上表的实际操作、自动回归和不可达前置说明，绝不默认所有控件都经过人工点击。

## 证据状态与复跑方法

| 状态 | 含义 |
| --- | --- |
| `PASS` | 该 JSON 所列 HTTP 动作已执行，响应与持久化结果满足检查；不代表浏览器点击已通过。 |
| `EXPECTED_BLOCKED` | 已实际请求并验证正确的权限、状态、隐私或参数拒绝；不代表操作执行成功。 |
| `NOT_REACHABLE_FROM_CURRENT_UI` | 正常 UI/HTTP 流程不能生成该操作所需的稳定前置状态，未伪造数据库夹具或修改执行时序。可另附实际拒绝证据。 |
| `NOT_EXERCISED_NO_OWN_RUN_NOTIFICATION` | 该次运行没有自己创建的通知，未改动其他运行的记录。后续补测应替代此状态。 |
| `SEMANTICS_UNVERIFIED` | 传输/执行可以成功，但业务数学口径尚未核验，不能当作数值正确。 |
| `FAIL` | 响应、状态、作用域或数学口径不满足明确要求；需区分验收脚本错误、旧进程和产品缺陷。 |
| `UI_EVIDENCE_MATRIX` | 需要主代理通过真实浏览器操作；本脚本不执行或冒充浏览器验收。 |

使用项目现有 Python 环境复跑：

```powershell
backend/.venv/Scripts/python.exe -B tools/verify-deep-workflows.py --output runtime/deep-workflows-final.json
```

可用 `--areas accounts,authorization,contract,settlement,assistant,electricity,queries,notifications` 选择子集。脚本只连接已授权的 `http://127.0.0.1:8000`，先校验 `APP_ENV=demo`，使用新运行前缀创建自己的申请、会话和任务。它不连接数据库、不读取 Vault、不上传 CSV、不修改全局策略、不修改别人的任务或通知。JSON 不保存口令、令牌、请求签名或原始记录。每次运行使用新前缀；重复运行会消耗正常连接器预算，禁止清零或放宽预算制造通过。

既有证据：

- `runtime/usability-workflows-online-final.json`：49 项 HTTP 工作流，覆盖批准/撤销、主要查询、结算正向和返工、上传回执、规则 API、无效钱包签名等。
- `runtime/usability-ui-pages.json`：89 次页面访问，字段仅为账号、页面和是否失败，不能证明标签、控件、弹窗或提交操作。
- `runtime/deep-workflows-initial.json`：本轮首批非函数运行。50 `PASS`、1 旧进程撤回映射 `FAIL`、5 不可达状态、1 正确阻断、9 无本轮通知。后续结果见下，不能将首批计数当最终全功能验收。
- `runtime/deep-workflows-notifications-recheck.json`：12 个业务账号均自己触发通知，单条已读和关联目标读取 12 `PASS`，替代上面 9 个通知未测状态。
- 最终新鲜隔离栈整套 JSON：`runtime/deep-workflows-final-release.json`，109项、596请求、0 FAIL；浏览器逐项结果以开头收口表及JSON为准。

## 13 个账号的实际入口和权限

菜单必须同时存在于登录会话和后端当前上下文；只知道 URL 不赋予权限。依据 `frontend/src/App.tsx`、`access.ts`、`features/trusted-energy/layout/TrustedSpaceShell.tsx`、`backend/app/services/trust_space.py`。

| 账号 | 角色/能源 | 当前入口 | 特有前置条件与边界 |
| --- | --- | --- | --- |
| generator | GENERATOR / 电力 | 运行总览、智能数据查询、数据目录、数据连接、数据授权、隐私计算、主体中心 | 可审核自己资产的申请；只能确认本人参与任务的本方结算结果。 |
| retailer | RETAILER / 电力 | 同上 | 与发电方分别确认本方结果，不能替另一方确认。 |
| coal | COAL_ENTERPRISE / 煤炭 | 同上 | 数据连接只绑定本主体；本域目录可能只有自己提供的资产，不能申请使用自己的资产。 |
| heat | HEAT_ENTERPRISE / 热能 | 同上 | 同上；小时数据只限后端声明支持的资源。 |
| gas | GAS_ENTERPRISE / 天然气 | 同上 | 同上。 |
| oil | OIL_ENTERPRISE / 石油 | 同上 | 同上；受明确关闭的跨能源组合限制。 |
| exchange | EXCHANGE / 电力 | 同上 | 可进入创建电力结算；执行、重试仍要任务预检和后端动作许可。 |
| exchange_coal | EXCHANGE / 煤炭 | 同上 | 主要动作是智能计算；不能创建电力结算。没有登记独立节点时连接器能力应真实显示未接入。 |
| exchange_heat | EXCHANGE / 热能 | 同上 | 同上。 |
| exchange_gas | EXCHANGE / 天然气 | 同上 | 同上。 |
| exchange_oil | EXCHANGE / 石油 | 同上 | 同上。 |
| regulator | REGULATOR / 跨能源监管 | 总览、查询、目录、授权、隐私计算、审计追溯、主体中心 | 目录元数据可发现不等于原始数据可读；使用数据仍需合法授权；审批自己的入站申请不可用。审计需 `VIEW_AUDIT` 及任务范围。 |
| admin | ADMIN / 运维 | 管理总览、组织与权限、能力与服务、运行监控、系统日志 | 仅聚合/脱敏运维视图。无业务、结算、监管审计、业务助手入口。当前没有账号增删改、密码重置或组织编辑控件，不能声称这些操作已测试。 |

## 逐页功能、控件与状态前置

下表中的 API 均位于 `/api` 下。角色简称：`业务12` 为除 admin 的 12 个账号；`提供方11` 为六企业与五交易中心；`电力交易方` 仅 exchange。

| 页面/路径 | 可见操作与 UI-only 行为 | 前置状态/角色 | 实际 API | 本轮 HTTP / 浏览器剩余 |
| --- | --- | --- | --- | --- |
| `/login` | 账号/密码输入；显示/隐藏密码；记住账号；Caps Lock 提示；提交；账号/DID 双切换入口 | 未登录；浏览器存储受限时不能阻止登录 | `POST /auth/login` | 13 账号登录已执行；偏好保存/清除、显示密码、键盘行为 `UI_EVIDENCE_MATRIX`。 |
| DID 登录 | 连接浏览器钱包、请求账户、一次性挑战、`personal_sign`、签名验证；缺钱包/拒绝连接/拒签提示 | 钱包已登记到既有 DID；无钱包必须清楚报错 | `POST /auth/did/challenge`、`/verify` | 原49仅覆盖无效签名；有效签名后端有测试，真实钱包浏览器流程 `UI_EVIDENCE_MATRIX`，不能假称已通过。 |
| 全局业务壳 | 品牌返回首页、七模块导航、移动抽屉开关、主体账号菜单、主体中心、退出登录、助手模式入口 | 业务12；按菜单交集显示 | `GET /auth/me`、`/trust-space/context`、`POST /auth/logout` | 会话/权限 API 已核验；移动导航、退出后后退、抽屉焦点/Escape `UI_EVIDENCE_MATRIX`。 |
| 页面帮助 | 打开/关闭帮助、阅读版本化条目、刷新/失败重试 | 使用 `PageFrame` 且未关闭帮助的页面；非所有原型页都有帮助按钮 | `GET /trust-space/help?view=...` | 现有帮助 API 测试；每页按钮、关闭、错误恢复 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/workbench` | 当前角色主 CTA；图表 tooltip/图例切换；图表按可见区域加载；加载失败重试 | 业务12；指标授权/节点可用；显示真实最近数据日 | `GET /prototype/dashboard` | 上轮角色指标/新历史窗口已测；实际 CTA 跳转、图表交互/失败重载 `UI_EVIDENCE_MATRIX`。无地图日期滑块，不能虚构此功能。 |
| `/trusted-space/query` | 输入/Enter 发送、中文输入法不误发、六条快捷提问填入、主体下拉、申请授权、重新检查授权、确认并计算、失败重试、任务刷新恢复、结果图表、跳转计算任务、电力计算按钮 | 业务12；解析完整；有效当前版本授权和剩余额度，或获准监管规则路径；监管默认 AUTO_CALL 规则最多31日，手工授权以实际批准范围为准；隐私阈值保留 | `/trust-space/query/parse`、`/confirm`、`/execute`、`/tasks/{id}`、`/result`、目录和授权列表 | 原49多为 average 直接API；本轮14固定函数/参数检查已在新节点完整执行；输入/申请→返回重查、前后台切换、掉线恢复 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/catalog` | 搜索；类型、能源、敏感等级下拉；清空；URL保存过滤；前后分页；查看详情；申请授权 | 业务12；提供方/监管范围不同；`actions.can_request_usage` 控制申请 | `GET /trust-space/catalog` | 89访问没有证明筛选/分页。真实浏览器搜索、空态、返回保留参数 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/assets/{id}` | 复制资产ID；护照、版本历史、使用规则、存证链四标签；查看入站授权；申请使用；查看全部/单条授权；返回 | 资产可见；当前版本来自后台；申请/审核分别由动作标志控制 | `GET /trust-space/assets/{id}` | 版本/护照后端有测试；四标签、剪贴板、授权跳转全部 `UI_EVIDENCE_MATRIX`。无版本切换按钮或证书下载。 |
| `/trusted-space/apply/{id}` | 四步向导前后；五种普通用途；监管专属能源监管/应急用途；MPC聚合/脱敏方式选择；条款勾选；期限输入；监管事项编号；提交；成功返回目录/我的申请 | 申请方不能是资产自己；政策期限先加载；监管只准白名单用途和依据；脱敏为适配器能力 | `GET /trust-space/assets/{id}`、`POST /data/access-requests` | 本轮按真实创建体生成申请；所有向导控件、错期限/未勾选/监管普通用途拒绝、重复提交 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/authorizations` | 待我审核/我的申请切换；选中行/深链；前后分页；刷新；意见输入；开始审核、批准、拒绝、撤回、撤销 | 提供方且有审批权限才可入站；`SUBMITTED→UNDER_REVIEW/APPROVED/REJECTED`；申请方可撤回；批准后按主体撤销；If-Match | `/data/access-requests/{id}`、`/review`、`/approve`、`/reject`、`/withdraw`、`/revoke` | review/reject/withdraw API通过。已发现旧DTO把申请方动作发成revoke而403；主代理修复后需重载复验。行快速切换/空意见/过期版本/按钮文案 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/connector` | 规范资源下拉、L1/L2/L3分级、CSV文件选择、直传登记、待补登记恢复按钮、自动恢复、模板CSV下载、失败重试 | 提供方11；必须登记本组织连接器；CSV类型/大小校验；有待确认上传时禁止重复 | `/trust-space/connectors/catalog`、`/tickets`、`/receipts`、`/receipts/{ticket}`；浏览器直传节点 `/ingest` 和回执查找 | 原49已实传七节点；深HTTP脚本不上传，协调Agent另在隔离浏览器执行错误/正确CSV直传。真实文件选择、模板下载、storage/断网后的恢复、四个无节点交易中心正确阻断 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/contracts` | 合同状态下拉、刷新、分页、查看协商 | 业务12内可见合同；后端限定合同双方 | `GET /trust-space/contracts` | API有分页/范围测试；列表控件和深链 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/contracts/{id}` | 刷新；查看关联资产；回复、反报价、接受、拒绝动作选择；消息/条款摘要；提交；事件轨迹；返回列表 | ACTIVE只能comment；NEGOTIATED/PENDING才有四动作；拒绝/撤销/过期关闭；监管只读；消息与状态版本要求 | `.../events`、`.../counter`、`.../accept`、`.../reject` | COMMENT+同键重放已过；当前正常申请批准直接生成ACTIVE，counter/accept/reject实际409且按钮禁用；不能造待协商库状态冒充通过。后三者记录不可达，待产品决定是否提供生成入口。 |
| `/trusted-space/mpc/new` | 五步创建；任务名、批次、周期、说明；发电/售电主体下拉；数据就绪核对；规则下拉；步骤回退；创建/待准备创建；返回 | 仅电力交易方；选有效规则、不同主体、有效日期；缺数据允许创建待准备任务但不可运行；非电力交易方重定向查询 | `GET /system/organizations`、`/rules`、`/data/catalog`；`POST /settlement/tasks` | 本轮创建自己任务与预检通过；普通/ready模板、错误字段、回退保留、非电力跳转 `UI_EVIDENCE_MATRIX`。计算方式/输出范围是禁用固定控件。 |
| `/trusted-space/ttc` | 状态下拉、刷新、任务选择、前后分页 | 业务12内可见任务，不能自动选第一条 | `GET /trust-space/ttc` | 89访问未覆盖此深链列表；浏览器列表行为 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/ttc/{id}` | 查看结果；监管查看审计；交易方刷新执行条件；启动/重试确认弹窗；实时日志弹窗、关闭/重试；允许状态动作+理由；返回 | 运行仅电力交易方和后端允许动作；手动动作限当前allowed_actions；运行If-Match/幂等；参与方无启动权 | `/settlement/tasks/{id}`、`/run`；`/trust-space/ttc/{id}`、`/events`、`/transitions` | 本轮INIT取消、游标事件、正常运行通过。中断只允许短暂执行阶段，正常同步流程无稳定UI前置；实际INIT中断409，记录不可达。确认/取消弹窗及多次点击 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/mpc` | 状态下拉、刷新、分页、选择任务、发起智能计算 | 有CREATE_COMPUTE_TASK才显示发起；无任务为空态 | `GET /trust-space/computations` | 列表API已有测试；筛选、空态CTA、分页 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/mpc/{id}` | 返回查询/TTC；发起智能计算；订阅/停止本地日志；重试日志；重试计算/取消计算（按后端能力禁用并显示理由） | 任务可见；日志poll_logs许可；当前同步执行器无重排队，retry恒禁用；仅可取消尚未开始且可取消的本地QUEUED/PENDING任务 | `/trust-space/computations/{id}`、`/events`、`/retry`、`/cancel` | 真实完成任务事件/游标通过；retry实际409正确阻断；正常UI不能生成可停留的QUEUED本地作业，取消成功路径不可达，不造夹具。日志订阅开关/错误恢复 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/results` | 刷新；task_id过滤深链；分页；查看结果 | 后端主体/任务/结果范围；非电力企业通常无结算结果应为空，不是故障 | `GET /trust-space/results` | API范围已测；列表/空态/过滤链接 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/results/{id}` | 刷新；复制结果哈希/任务号；逐证据核验；确认通过/提出异议；意见输入；提交；返回列表 | 仅generator/retailer可确认本方当前尝试；先过审计关口；必须意见；相反结论不可覆盖 | `/trust-space/results/{id}`、`/confirm`、`/trust-space/evidence/{id}/verify` | 原49通过APPROVE；本轮REJECT和同键重放通过。复制权限失败、逐证据按钮、意见校验、相反结论/重复点击 `UI_EVIDENCE_MATRIX`。 |
| `/trusted-space/audit`、`/audit/tasks/{id}` | 记录/报告审核/风险处置子视图切换；记录刷新、分页；打开关联任务；详情返回；证据/回执/状态链阅读 | 仅监管且有审计权限与任务范围；query task与settlement task区分 | `GET /trust-space/audit`、`/audit/tasks/{id}` | 原49已验证范围、证据；89只进首页。子视图/任务详情/旧响应不串页 `UI_EVIDENCE_MATRIX`。正式记录页没有篡改/恢复写按钮。 |
| 审计报告子视图 `?view=reports` | 报告/任务链接；详情抽屉；证据引用展开；批准/驳回意见Modal→二次确认；取消/关闭；刷新；AUDITED任务补充生成报告及确认弹窗 | 仅监管；GENERATED才审核；意见至少2字；补充生成仅无任务深链列表，且选择AUDITED任务 | `GET/POST /audit/reports`、`GET /settlement/tasks`、`POST /audit/reports/{id}/decision` | 原49批准/驳回返工已通过；本轮为自有异议任务再批准。补充生成、抽屉、两层确认/取消/错意见、通知定位单报告 `UI_EVIDENCE_MATRIX`。 |
| 风险处置子视图 `?view=anomalies` | 状态/风险等级下拉；详情抽屉；关联证据展开；处置方式ACK/IGNORE/REWORK；意见Modal→确认；刷新/返回 | 仅监管；OPEN可处置；意见至少2字；If-Match；REWORK需任务允许 | `GET /anomalies`、`POST /anomalies/{id}/resolve` | 原49只对REWORK有真实证据；ACK、IGNORE和所有浏览器弹窗/筛选 `UI_EVIDENCE_MATRIX`。未用其他人的风险事件凑通过。 |
| 全局通知中心 | 打开/关闭；刷新；前后分页；单条已读；全部已读；可识别实体跳转；不可识别实体只摘要 | 业务12，各账号自己的通知；目标类型/菜单决定可跳转 | `/trust-space/notifications`、`/{id}/read`、`/read-all`；目标自身API | 本轮12角色自己触发通知→单条已读→真实目标可读已过；原49全部已读API已过。跨页未读数、报告/合同/结果跳转、未知类型摘要、失败状态 `UI_EVIDENCE_MATRIX`。 |
| 全局业务助手 | 开关、业务/电力模式切换、输入/Enter、五快捷命令、五底部入口；展示计划；执行/提交审批草案、取消、重试；加载重试；上下文/历史 | 业务12；资产/授权/任务的目标ID必须可见；证据/审计命令有角色限制；写意图只能审批草案，不得执行审批 | `/trust-space/assistant/sessions`、`/messages`、`/plans`、`/tools`、`/execute`、`/cancel`、`/retry` | 本轮12账号资产计划、五读指令、五写草案不改目标、retry/cancel都实际通过。浏览器上下文切换、失败重试、连续消息/模式切换 `UI_EVIDENCE_MATRIX`。无目标/角色不符应BLOCKED。 |
| 电力交易计算助手 | 两场景快捷启动；自然语言发送/换行；政策链接；公式/过程/校验折叠；字段补齐/修改；范围与小数限制；勾选确认；计算；CSV下载；继续/完成；保存/暂不保存/稍后保存；案例库开关/复用；新对话；重开历史；错误关闭/重载 | 业务12个人会话；数值合法且已确认；结果后才下载/保存；复用必须重新确认，案例不能跨账号 | `/trust-space/assistant/electricity/catalog`、`/prepare`、`/{id}/calculate`、`/{id}/save`、`/cases`、`/sessions/{id}` | 原49两公式+保存全部12角色；本轮两场景新会话复用、确认、等价结果、历史、跨账号拒绝通过。CSV文件、政策新窗、确认checkbox重置、继续/完成和保存分支 `UI_EVIDENCE_MATRIX`。 |

### 管理台五页和通用控件

| 页面 | 实际功能/API | 需要浏览器验证 |
| --- | --- | --- |
| `/overview` | 管理总览；刷新；四个管理入口；`GET /admin/overview` | 入口导航、刷新、技术表格控件。 |
| `/system` | 组织/用户/身份/节点聚合与技术边界；刷新；`GET /admin/system` | 两张表的排序、列设置、空态/失败重试；无账号CRUD。 |
| `/agents` | 能力身份、工具、权限、解释服务配置的聚合摘要；刷新；`GET /admin/agents` | 表格控件与未配置状态；无能力写管理。 |
| `/metrics` | 刷新、按单位三图、tooltip、无测量时显示空值；`GET /metrics/summary` | tooltip、空值文案和重试；无业务数值明细。 |
| `/logs` | 关键词、动作、结果筛选；刷新；详情抽屉；脱敏详情展开；复制ID；`GET /audit/logs` | 筛选组合、抽屉、脱敏显示、表格控件、复制失败。 |
| 以上及报告/风险通用 `DataTable` | 表头三态排序（升/降/无）、列设置checkbox（固定操作列不能隐藏）、20/50/100每页、前后分页、局部横向滚动；`IdText`复制完整ID | 全部是本地UI状态，不能以API列表请求代替。表格没有通用导出按钮。 |
| 错误/会话/路由 | 403/404返回工作入口；会话失效→重新登录；服务不可用→重新加载；懒加载失败可重试；Modal/Drawer关闭/取消/Escape/焦点恢复 | 业务越权URL、admin进入业务URL、畸形编码URL、断网、后台标签暂停/恢复均 `UI_EVIDENCE_MATRIX`。 |

## 14 个固定函数与参数验收

当前自然语言解析仅开放 `sum/average/max/min/count/trend` 六种；小时、分组、阈值没有手工表单。其余接口可调用，不等于当前浏览器已提供八个函数的交互入口。

| 函数 | 应核对的事实 | 本脚本覆盖 |
| --- | --- | --- |
| sum | 同一授权期间的和 | 与average×count在舍入容差内一致。 |
| average | 同一范围平均 | 位于min/max之间；同比/环比用同范围均值作独立对照。 |
| max / min | 极值 | min≤average、median≤max。 |
| count | 记录条数，单位条 | v2三天×四地区=12，不沿用MW单位。 |
| median | 中位数 | 位于min/max之间；不能假称已从原始明细独立重算。 |
| growth_rate | 首末日期相同地区集合聚合的增长率，单位% | 独立请求第一/最后日受控均值计算期望；不能拿首末不同地区两行相除。 |
| yoy | 去年同期同范围增长率，单位% | 当前2026-06-01..03与2025同期均值；原授权必须同时覆盖基期。 |
| mom | 上月同期间同范围增长率，单位% | 当前2026-06-01..03与2026-05-01..03均值；基期边界同上。 |
| group_by | region / record_date / organization；每组保留隐私阈值 | 三字段各有结果/组数检查；非法字段应拒绝。 |
| threshold | 必填阈值；满足+不满足=记录数，单位条 | 正常阈值与全满足阈值；缺值拒绝。 |
| trend | 多日期受控趋势、方向/变化率；图表单位保留原指标 | 至少两日期；结果结构和曲线值来自连接器。 |
| psi | 基期/观察期分布的标准PSI，非负无量纲 | 需按修正后的分箱+平滑算法补独立对照；不得将相对均值差视为PSI正确。 |
| mpc_aggregation | 当前本地受控求和份额，真实能力标签 | 与同授权sum一致；不声称部署了外部多方协议。 |

参数另测：明确授权2021-01-01..2026-09-30；起末历史日期；三日全地区12条；北部三日3条；小时8点12条；分组日期3组/机构4组；阈值0；缺阈值/非法分组；单日单区1条低于隐私阈值应阻断；默认31日 AUTO_CALL 规则的32日查询应拒绝（手工宽期授权不作全局31日限制）。无原始数据被查询或写入平台。

## 与原49工作流、89页面访问的差集

1. **真实新缺陷**：申请方DTO以前返回`revoke`，UI显示“撤回申请”却调用provider-only端点而403。首批HTTP已复现；已修成applicant `withdraw`，最终新进程的同一检查与浏览器撤回均通过。
2. **合同路径**：原49不含协商四动作，89只覆盖顶层菜单。COMMENT现已实测；其它三动作缺少正常生成的待协商前置，禁止把固定测试数据库造态当产品可用证据。
3. **结算/结果/日志**：原49有APPROVE和返工，没有本轮新增的结果REJECT、INIT手动取消、MPC游标/完成态控制拒绝。中断/队列取消的成功态仍明确不可达。
4. **助手/案例**：原49每账号只执行资产读和两个公式保存，没有其它快捷读、全部写草案、取消/重试、复用到新会话/历史。现已补HTTP；实际聊天控件和CSV下载已由浏览器验证，见收口表。
5. **通知**：原49只有read-all。现12业务角色各触发自己的通知并单条已读，目标读API验证通过；不能据此推断菜单关闭、导航和未读角标浏览器行为。
6. **计算函数**：原49主要average；六UI函数及八API-only函数的正确数值、比较期间授权、小时/分组/阈值均须单列，不能只断言200。
7. **报告/风险**：原49批准/驳回/REWORK通过；浏览器两层Modal/Confirm取消、补充生成、ACK/IGNORE、表格筛选/详情抽屉的已执行范围与补充生成前置边界见收口表。
8. **全局/管理UI**：登录偏好、密码显示、钱包交互、移动抽屉、帮助、列设置、排序、每页数、复制、图表图例、懒加载恢复、会话失效均未被89个“页面可打开”关闭。

### 真实存在但没有当前UI入口的旧API/源码

- `/rules`、`/data-space`、`/trusted-execution`、`/compute`、`/results`、`/reports` 等旧业务地址现在由 `legacy-routes.ts` 迁往当前模块。旧 `RulesPage`、`TrustedExecutionPage`、`DataSpacePage`、`ExcelUploadPage`、旧结算详情等没有挂载；其写控件不能算当前可见功能。
- `StrategyCenterPage` 未挂载，当前授权页没有访问规则创建/撤销表单；原49的access-rule成功是API证据。
- `downloadAudit`客户端函数和`/trust-space/audit/export` API存在，但当前`AuditCenterPage`未调用导出函数，没有JSON/CSV导出按钮。原49导出证明服务器API，不证明浏览器下载入口。
- 数字证书页只读凭证元数据；没有证书文件下载、私钥读取、远程连接器配置入口。忘记密码是联系说明，没有找回密码按钮。不得为满足“全部功能”假设这些功能已存在。

## 现有测试定位

以下是可直接复核的已有测试，覆盖协议或回归边界；SSR、静态源码检查和mock API单元测试仍不能替代真实浏览器完整操作。

| 范围 | 测试位置 |
| --- | --- |
| 菜单/角色/管理边界 | `backend/tests/test_auth_menu_contract.py`、`test_admin_safe_summaries.py`；`frontend/src/access.test.ts`、`admin-boundaries.test.ts`、`legacy-routes.test.ts` |
| 登录/钱包/退出 | `backend/tests/test_auth_did.py`、`test_auth_logout.py`；`frontend/src/login-preferences.test.ts` |
| 目录/身份/护照 | `backend/tests/test_trust_space.py`、`test_trust_space_pagination_queries.py`；前端`trusted-space-api.test.ts` |
| 使用申请/审批/范围/额度 | `backend/tests/test_data_usage_requests.py`、`test_usage_request_budget.py`、`test_query_review_regressions.py`；前端`authorizations-page-boundaries.test.tsx`、`query-authorization-gate.test.tsx` |
| 合同四动作/TTC/计算控制/结果 | `backend/tests/test_trust_space_workflows.py`各命名用例；前端`workflow-api.test.ts`、`ttc-actions.test.tsx`、`route-detail-boundaries.test.ts` |
| 连接器直传/恢复/不出域 | `backend/tests/test_connector_ingestion.py`、`test_connector_ingestion_e2e.py`；前端`connector-page-boundaries.test.ts`、`trusted-space-api.test.ts`直传/lookup用例 |
| 异步查询/恢复/31天/隐私 | `backend/tests/test_trusted_query_async.py`、`test_trusted_query_translation.py`、`test_trusted_query_connector_errors.py`；前端`query-task-lifecycle.test.ts`、`query-page-boundaries.test.ts` |
| 助手五读/写草案/取消重试 | `backend/tests/test_trust_space_assistant.py`、`test_assistant_energy_roles.py`；前端`assistant-state.test.ts`、`workflow-recovery.test.ts` |
| 电力公式/精度/案例/隔离 | `backend/tests/test_electricity_calculation.py`；前端`electricity-api.test.ts`。没有完整`ElectricityChat`事件级浏览器测试，必须实点。 |
| 通知/帮助/审计 | `backend/tests/test_trust_space_notifications.py`、`test_audit_scope_pagination_hardening.py`；前端`audit-center-boundaries.test.tsx`、`audit-operation-pages.test.tsx`、`trusted-space-api.test.ts` |
| 表格/焦点/输入法/性能恢复 | `frontend/src/layout-accessibility.test.tsx`、`features/trusted-energy/performance-boundaries.test.ts`、`components/RetryableLazy.test.ts`；通用DataTable排序/列设置/每页数仍需真实交互验收。 |

验收关闭条件：最终JSON无未解释FAIL；所有正确阻断/不可达能力明确陈述；浏览器待测项附实际步骤与结果；旧测试、页面访问和HTTP传输成功不混写成“13账号全部功能交互通过”。

## 2026-10-25 助手语义与全账号验收补充

- 新增 tools/assistant-language-cases.json 与 tools/verify-assistant-language.py，区分真实读取成功、需要选择、预期权限拒绝、人工复核、模型不可用、夹具不足与失败；不将 HTTP 200 或计划创建冒充实际执行。
- 语料覆盖本方/可见/可用数据、授权/任务/报告/通知列表、对象详情、序号/名称追问、否定、多个操作、越权、管理员、统计与电力导航。保留问法不得从解析关键词表生成或删除失败项。
- 写复核前后比较真实业务 DTO，审批夹具只允许匹配能源的本轮唯一申请；复核不执行真实审批。
- 继续运行 verify-deep-workflows.py 的既有授权、合同、结算、计算、查询函数、电力案例和通知闭环。已知未配置外部能力、当前 UI 不可达路径与隐私分布参考限制仍独立披露，不计入功能成功数。

本地阶段结果：13账号 common 482项无FAIL；旧功能闭环121项（102真实通过、13正确权限/参数阻断、5当前界面不可达、1隐私PSI参考限制）。前端238 tests、ESLint与production build，连接器85 tests通过。39项解析回归与135项路由/范围集成通过；额外反例和全量随机顺序覆盖继续按最后冻结源码复验。

本机模型启用探针收到HTTP401，已如实记为FALLBACK/MODEL_UNAVAILABLE；不把本地降级结果当作真实模型成功。发布后必须在已配置的Render环境实际验证模型解析及全部保留问法，失败则继续修复，不提前报完工。
