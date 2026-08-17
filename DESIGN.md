---
name: 隐链明算
description: 面向电力交易可信执行的双工作空间生产界面
colors:
  brand-900: "#0e2a47"
  brand-800: "#102f4f"
  brand-700: "#1d6fa5"
  brand-600: "#267eae"
  brand-100: "#dbeaf4"
  brand-50: "#edf5fa"
  sidebar: "#102f4f"
  sidebar-active: "#1e527d"
  canvas: "#f3f5f7"
  surface: "#ffffff"
  ink: "#1f2d3d"
  text-secondary: "#5f6b78"
  text-muted: "#687583"
  text-disabled: "#9099a3"
  line: "#d7dee6"
  line-soft: "#e7ebef"
  success: "#2e7d32"
  success-soft: "#edf7ee"
  warning: "#a86500"
  warning-soft: "#fff5e5"
  danger: "#c23b3b"
  danger-soft: "#fff0f0"
typography:
  headline:
    fontFamily: '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif'
    fontSize: "22px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "0"
  title:
    fontFamily: '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif'
    fontSize: "15px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "0"
  body:
    fontFamily: '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0"
  control:
    fontFamily: '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif'
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0"
  label:
    fontFamily: '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif'
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "0"
  mono:
    fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace'
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0"
rounded:
  control: "3px"
  surface: "3px"
  overlay: "4px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "7": "32px"
  "8": "40px"
  "9": "48px"
components:
  button-primary:
    backgroundColor: "{colors.brand-700}"
    textColor: "{colors.surface}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "7px 13px"
    height: "36px"
  button-primary-hover:
    backgroundColor: "{colors.brand-800}"
    textColor: "{colors.surface}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-secondary}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "7px 13px"
    height: "36px"
  button-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.surface}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "7px 13px"
    height: "36px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.brand-700}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "7px 13px"
    height: "36px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 9px"
    height: "36px"
  status-success:
    backgroundColor: "{colors.success-soft}"
    textColor: "{colors.success}"
    rounded: "{rounded.control}"
    padding: "3px 8px"
    height: "22px"
  status-warning:
    backgroundColor: "{colors.warning-soft}"
    textColor: "{colors.warning}"
    rounded: "{rounded.control}"
    padding: "3px 8px"
    height: "22px"
  status-danger:
    backgroundColor: "{colors.danger-soft}"
    textColor: "{colors.danger}"
    rounded: "{rounded.control}"
    padding: "3px 8px"
    height: "22px"
---

# Design System: 隐链明算

## Overview

**Creative North Star: “可信执行台账”**

界面属于 Operate 模式：用户进入系统是为了检索、处理、复核和追踪任务。视觉语言接近传统政企内网与电网生产平台——稳重、中性、权威、高信息密度；品牌感来自深蓝壳层、精确对齐和审计细节，而不是装饰。

产品由“业务工作台”和“管理控制台”两个独立工作空间组成。导航、路由、操作和数据范围共同受会话角色与后端菜单约束；工作空间切换只在账号同时拥有两个空间时出现，不能把另一空间的菜单混排或仅用 CSS 隐藏。

视觉层级固定为：侧栏与顶栏建立位置和身份上下文；页面标题说明任务；筛选与状态收窄范围；指标条提供概览；Surface、表格、详情和时间线承载事实。任何辅助解释都低于原始事件、签名、凭证和后端核验结果。

**Key Characteristics:**

- 固定浅色工作区，深蓝用于品牌、导航和高权重操作。
- 4px 节奏、薄边框、小圆角、紧凑行高，允许高密度但不牺牲可扫描性。
- 编号、时间、状态、证据引用和 Trace ID 始终可定位、可复制或可复核。
- 离线可用的系统字体与本地图标，不依赖外部字体、CDN 或装饰素材。

## Colors

颜色体系是“深蓝秩序 + 冷灰工作面 + 克制语义色”。前置 YAML 是规范值；实现以 `frontend/src/styles.css` 的同名 CSS 变量为运行时来源。

### Primary

- **品牌深蓝**（`brand-900` / `brand-800`）：品牌标识、侧栏、标题和高权重文本。
- **操作蓝**（`brand-700`）：主按钮、链接、选中态、焦点和审计标记；悬停进入更深的 `brand-800`。
- **浅蓝层**（`brand-50` / `brand-100`）：信息提示、轻选中态和图标底，不形成大面积彩色卡片。

### Neutral

- **工作画布与面板**（`canvas` / `surface`）：浅灰页面承接白色生产面板。
- **文字层级**（`ink` / `text-secondary` / `text-muted` / `text-disabled`）：依次用于标题、正文数据、说明元信息和禁用内容。
- **结构线**（`line` / `line-soft`）：外框与行分隔；层级主要由线和明度差建立。

### Semantic

- **成功、警告、危险**分别使用 `success`、`warning`、`danger` 及其 soft 背景；同一业务状态在指标、列表、详情和反馈中保持同一映射。
- 中性或未知状态使用灰色描边与文字，不把“有结果”“已登记”推断为“核验通过”或“服务健康”。

**The Double-Encoding Rule.** 状态颜色必须同时配合文字、图标或形状；颜色不能单独承担含义。

## Typography

**Display / Body Font:** Microsoft YaHei，回退至 PingFang SC、Noto Sans CJK SC、Arial、sans-serif
**Label / Mono Font:** SFMono-Regular，回退至 Consolas、Liberation Mono、monospace

系统字体确保 Windows 办公终端与封闭内网稳定渲染。层级依靠字重、字号、明度和位置，不依靠装饰字体或字距技巧。

### Hierarchy

- **Page headline**（22px / 650 / 1.3）：每页唯一主标题；登录表单标题为 21px。
- **Section title**（15–16px / 650）：Surface、抽屉和弹窗标题。
- **Body**（14px / 400 / 1.5）：页面正文；表格与常规控件主要为 13px。
- **Label / Meta**（10–12px / 600 或 400）：字段标签、计数、组织身份和辅助说明；不得缩小关键事实来挤压布局。
- **Metrics**（20–22px / 650）：指标数字使用等宽数字特性。
- **Mono**（10–12px）：业务编号、哈希、Trace ID、代码值和技术详情；保持可复制与不换行。

**The Audit Numerals Rule.** 金额固定两位小数，日期统一为 `YYYY-MM-DD HH:mm:ss`，数字列右对齐，缺失值统一显示 `—`。

## Layout

桌面壳层由固定侧栏、粘性顶栏和独立内容区组成：侧栏展开 216px、折叠 60px；顶栏 50px；内容区最大宽度 1680px，内边距为 16px 20px 28px。侧栏内先显示当前工作空间，再按业务域分组路由；顶栏依次承载折叠控制、面包屑、工作空间切换、环境、组织身份、风险入口和用户菜单。

业务空间按“工作入口 / 数据与授权 / 计算与验证 / 审计与风控”分组；管理空间只承载“管理功能”。管理员默认进入管理总览，其他角色默认进入业务工作台。页面内容遵循 `PageHeader → FilterBar / MetricStrip → Surface / DataTable → Drawer / Dialog` 的稳定顺序。

间距以 4px 为基准，常用 8、12、16、20、24、32px。Surface 间隔 12px，正文内边距 14px；避免卡片套卡片。宽表只在自身容器滚动，页面布局不得依靠全页横向滚动兜底。

### Dense table model

- 表头粘在表格容器顶部（36px），数据行高 40px；容器高度在 320–680px 间随视口调整。
- 默认首个可见列左冻结；业务页的“操作”列显式右冻结、不可隐藏且不参与排序。冻结列在悬停时与所在行使用同一背景。
- 支持排序、列显示配置、20 / 50 / 100 条分页和表格内部双向滚动；至少保留一列。
- 长名称通过列宽和省略处理；编号使用前后片段、完整值提示和复制入口，不能缩小字体强行塞入。

### Responsive behavior

- **≤1120px：**隐藏顶栏组织摘要；四/五列指标降为两列，监控图表与审计双栏改为单列。
- **≤980px：**工作台、主从详情和审计主区域继续收为单列或更窄分栏。
- **≤760px：**侧栏变为 216px 遮罩抽屉；顶栏保留 50px，隐藏桌面工作空间切换器与环境标签；页面内边距降为 12–16px。筛选、操作、指标和分页纵向堆叠，表格保持内部横向滚动与冻结列。
- **≤480px：**Surface 标题、元信息和操作纵向排列；复杂摘要与复核网格降为单列。

## Elevation & Depth

系统默认扁平。页面、Surface、筛选栏、表格和卡片以白色/浅灰色差及 1px 边框分层，不使用常驻大阴影。只有覆盖上下文的菜单、列设置、弹窗和抽屉获得阴影。

### Shadow Vocabulary

- **Overlay**（`0 10px 26px rgba(14, 42, 71, 0.14)`）：弹窗、下拉菜单和列设置面板。
- **Drawer**（`-8px 0 24px rgba(14, 42, 71, 0.14)`）：右侧详情抽屉与主页面分离。
- **Selected segment**（`0 1px 3px rgba(16, 42, 70, 0.12)`）：仅表示分段控件当前项。

状态过渡使用 140ms，抽屉和遮罩使用 180ms；页面进入只做轻微透明度变化。`prefers-reduced-motion: reduce` 下动画和过渡缩至近零。

层级令牌固定为顶栏 20、侧栏 30、抽屉 40、模态框 80、Toast 100，禁止页面自行抬高覆盖关系。

**The Flat-by-Default Rule.** 阴影表达覆盖关系，不表达普通内容的重要性。

## Shapes

控件与 Surface 使用 3px 小圆角，弹窗、抽屉菜单等覆盖层使用 4px。状态点、时间线标记等真正的点状信息可使用圆形；按钮、标签、卡片和输入框不使用胶囊或巨型圆角。

边框是主要结构语言：Surface 和表格外框使用标准结构线，表格行、弹层分区和列表项使用更浅分隔线。深色侧栏用低透明白色线维持同一秩序。

## Components

### Application shell and navigation

- `AppShell` 统一双工作空间壳层；`BusinessLayout` 与 `AdminLayout` 保留内容边界，`WorkspaceSwitcher` 只显示账号可访问的空间。
- 菜单激活态使用实色深蓝底和左侧 3px 指示线；折叠态保留图标、`title` 和可访问名称。移动端导航使用遮罩抽屉。
- 入口、直达路由和操作分别校验角色与后端菜单；无权、未知路由和会话失效进入正式 403、404、SESSION 页面。

### Buttons

- 主、次、危险、幽灵四种变体共用 36px 最小高度、3px 圆角和紧凑内边距。
- 主按钮只用于当前区域的主要提交或执行；危险按钮只用于有明确后果的操作。
- 异步按钮显示旋转状态、设置 `aria-busy` 并锁定重复提交；禁用态使用灰色文字、边框与背景。

### Forms and filters

- `Field` 用真实 `<label>` 包裹标签与控件；输入、选择和文本域最小高度 36px。辅助说明在控件后，错误替换提示并以 `role="alert"` 暴露。
- 聚焦时边框切换为操作蓝并出现 3px 低透明焦点环；字段错误使用危险色边框。文本域只允许纵向缩放。
- `FilterBar` 将字段与操作分区并贴近结果；筛选结果、当前状态和风险等级直接放在筛选上下文，不再复制页面标题。

### Tables, metrics, and status

- `DataTable` 是列表唯一基线，统一固定表头、首列与右侧操作列、排序、列设置、分页、空/错/加载状态及可聚焦滚动区域。
- `MetricStrip` 用薄边框与等宽数字呈现摘要；语义色只改变边框，不把指标做成彩色营销卡。
- `StatusTag` 集中映射成功、警告、危险和中性状态。`IdText`、`AmountText`、`DateTimeText` 统一长编号、金额、时间和缺失值。

### Modals, drawers, and confirmation

- `Modal` 最大宽度 720px、上下分区清楚；`DetailDrawer` 从右侧进入，最大宽度 560px，正文独立滚动。两者均使用 `role="dialog"`、`aria-modal`、标题关联、首个控件聚焦、Tab 焦点圈定、Escape 关闭和触发点焦点恢复。
- `ConfirmDialog` 最大宽度 520px，必须列出操作对象、当前状态和后果。请求进行中禁用取消、关闭、Escape 与背景关闭，避免状态歧义。
- 详情优先显示业务摘要；JSON、代码、证据引用和复核原始数据放入可展开的次级技术区。

### Loading, error, empty, and session states

- 首次页面加载使用标题与面板骨架；表格加载使用工具栏加六行结构骨架；局部加载使用 `role="status"` 与 `aria-live="polite"`。
- 错误状态使用 `role="alert"`，展示安全化错误、可选 Trace ID 和重试。刷新失败应保留旧数据并就地反馈，不清空上下文。
- 空状态提供图标、明确标题和可选说明；“无数据”与“无权限”“加载失败”“未核验”不可混用。
- 只有 401 清除会话凭证并进入 SESSION；超时、网络错误和 5xx 保留 `sessionStorage` 中的有效凭证，进入可重试 UNAVAILABLE。启动验证、403、404 与服务不可用各自使用独立状态页。

### Audit-oriented patterns

- 审计页面以对象筛选、事件时间线、凭证引用、状态标签、来源快照、规则命中、复算口径和确认主体组成可追踪链路。
- 核验只有后端返回明确布尔结论时才显示“已通过/需复核”，否则显示“未核验”。结果摘要存在不能替代核验结论。
- “证据辅助解释”必须同时展示置信度、证据关联、生成方式和能力边界，并持续声明它不构成确定性核验、审批或合规结论；最终依据仍是事件链、签名和凭证核验。
- 未开放服务端授权和审计通道时，不显示浏览器侧结果、报告或日志导出；运行指标同时标明测量范围与基线说明。

### Settlement task patterns

- 任务中心固定使用“待我处理 / 我发起 / 进行中 / 异常 / 已完成”五个业务视图。每行首先回答任务、当前状态、下一步、责任主体与阻塞原因，再提供详情入口。
- 发起任务是独立五步页面，不在列表弹窗中压缩完成。步骤只负责组织输入；后端启动预检始终是最终判断。
- 任务详情以事实条、主操作和八步可信链建立全局状态，再分“业务信息 / 技术信息”。数据、规则、计算、结果、证据、审计、报告和异常都提供带 `task_id` 的关联入口与返回路径。
- 八步链由数据库事实推导，状态必须是已完成、当前、受阻或待处理；不使用静态百分比，不把任务创建时间冒充各阶段完成时间。
- 发电与售电的结果确认是双方独立的业务动作。交易中心、监管与管理员不显示代确认按钮。

### Capability truth and white-label

- “实际执行方式”只显示本次作业回执中的适配器；MPC、TEE、联邦学习等未接入能力只放在明确标注“候选方案 / 未配置 / 不可执行”的区域。
- 本地证据统一称“证据台账”或“证据记录”；兼容字段中的区块高度、交易摘要不得转译为“已上链”。
- `false`、`NOT_PROVIDED`、`NOT_CONFIGURED` 和 `UNVERIFIED` 是可见状态，不以空白、成功色或模糊说明替代。
- Logo、产品名、客户、运营方、建设方、版权、支持信息、环境标签和登录公告来自运行时配置。缺失 Logo 时使用文字标识；生产环境默认不显示环境徽标。

## Do's and Don'ts

### Do:

- **Do** 复用 `PageHeader`、`FilterBar`、`MetricStrip`、`Surface`、`DataTable` 和共享状态组件，保持各路由相同阅读顺序。
- **Do** 让首列、操作列、表头、分页、长编号和缺失值遵守统一表格规则；金额与数量右对齐。
- **Do** 为加载、刷新、空、超时、错误、403、404、会话失效、提交中、成功和危险确认提供不同且可恢复的状态。
- **Do** 保留清晰的 `:focus-visible`，为图标按钮提供可访问名称，为表格滚动区、表单和弹层使用正确语义；正文、控件和状态文字维持 WCAG AA 对比度，状态不只依赖颜色。
- **Do** 只陈述接口提供的事实；来源、编号、时间、引用、Trace ID、测量范围和未核验边界应就近展示。
- **Do** 在 1366×768、1440×900、1920×1080、Windows 125% 缩放与窄屏下验证长机构名、编号、表格和弹层。

### Don't:

- **Don't** 使用紫蓝渐变、霓虹、光晕、星空、科技网格、毛玻璃、大面积深色数据大屏或无意义动效。
- **Don't** 使用大阴影、漂浮卡片、卡片套卡片、Bento Grid、巨型标题、巨型圆角、全站胶囊标签或彩色图标底座。
- **Don't** 创造后端没有的字段、状态、审批、证书、合规结论、实时健康结论或行情，也不要把演示/生成式解释冒充生产事实。
- **Don't** 用 CSS 隐藏代替权限控制，用 `overflow: hidden` 掩盖裁切，用缩小字体塞入长内容，或把整段 JSON 放在主任务路径。
- **Don't** 在没有服务端授权与审计能力时伪造导出；不要因超时或 5xx 清除有效会话。
- **Don't** 使用欢迎语、宣传口号、“赋能业务”“智能洞察”“一站式体验”等无法核验的营销文案。
