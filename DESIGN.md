---
name: 隐链明算
description: 面向电力交易可信执行的高密度结算台账界面
colors:
  system-charcoal: "#26363d"
  grid-green-950: "#002f27"
  grid-green-900: "#003d32"
  grid-green-800: "#004c3e"
  grid-green-700: "#005b4a"
  grid-green-600: "#006a56"
  grid-green-500: "#006a56"
  grid-green-400: "#6fa99a"
  grid-green-300: "#b8d4cc"
  grid-green-200: "#ddefea"
  grid-green-100: "#eaf4f1"
  grid-green-50: "#f5faf8"
  brand-primary: "#006a56"
  brand-primary-hover: "#005b4a"
  brand-primary-active: "#004c3e"
  brand-bg-soft: "#eaf4f1"
  brand-bg-subtle: "#f5faf8"
  brand-bg-selected: "#ddefea"
  brand-border: "#b8d4cc"
  brand-focus-ring: "rgba(0, 106, 86, 0.18)"
  brand-text-on-primary: "#ffffff"
  canvas: "#f2f4f5"
  surface: "#ffffff"
  ink: "#202b30"
  text-secondary: "#526067"
  text-muted: "#68747a"
  text-disabled: "#919a9e"
  line: "#cfd6d8"
  line-soft: "#e4e8e9"
  success: "#2e7d32"
  success-soft: "#edf7ee"
  warning: "#a86500"
  warning-soft: "#fff5e5"
  danger: "#c23b3b"
  danger-soft: "#fff0f0"
typography:
  headline:
    fontFamily: '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif'
    fontSize: "20px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "0"
  title:
    fontFamily: '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif'
    fontSize: "14px"
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
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "0"
  mono:
    fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace'
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0"
rounded:
  tight: "2px"
  control: "3px"
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
  system-bar:
    backgroundColor: "{colors.system-charcoal}"
    textColor: "{colors.surface}"
    height: "48px"
    padding: "0 20px"
  primary-navigation:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    height: "42px"
    padding: "0 18px"
  route-context:
    backgroundColor: "#f6f7f7"
    textColor: "{colors.text-muted}"
    height: "34px"
    padding: "0 20px"
  button-primary:
    backgroundColor: "{colors.brand-primary}"
    textColor: "{colors.surface}"
    typography: "{typography.control}"
    rounded: "{rounded.tight}"
    padding: "7px 13px"
    height: "36px"
  button-primary-hover:
    backgroundColor: "{colors.brand-primary-hover}"
    textColor: "{colors.surface}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-secondary}"
    typography: "{typography.control}"
    rounded: "{rounded.tight}"
    padding: "7px 13px"
    height: "36px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.tight}"
    padding: "7px 9px"
    height: "36px"
  status-success:
    backgroundColor: "{colors.success-soft}"
    textColor: "{colors.success}"
    rounded: "{rounded.control}"
    padding: "3px 8px"
    height: "22px"
  surface:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.tight}"
    padding: "14px"
---

# Design System: 隐链明算

## Overview

**Creative North Star: “可信结算台账”**

这是一个严肃、稳定、受监管且高信息密度的 Operate 界面。它把大型电网企业传统生产内网的栏目秩序现代化：先确认机构、角色和运行环境，再进入业务域处理任务，最后沿数据、规则、计算、确认与证据链完成核验和追溯。可信度来自事实密度、精确对齐、清晰权限和可定位记录，而不是技术表演。

整体采用深灰蓝系统栏、白色横向业务栏目、冷灰工作面、电网青绿色品牌识别、1px 结构线和小圆角。系统拒绝通用 SaaS/AI 后台、紫色或蓝紫科技感、玻璃质感、营销 Hero、横幅式欢迎区、超大数据展示，以及对旧式门户的表面仿古。

**Key Characteristics:**

- 48px 深色系统栏、42px 白色一级导航、34px 面包屑栏构成稳定的 124px 顶部上下文。
- 电网青绿色只承担当前项、主操作、链接、焦点和少量结构提示；大面积内容保持中性。
- 4px 间距节奏、1px 边框、2–4px 圆角和紧凑表格共同服务高频检索与复核。
- 编号、时间、状态、证据引用、Trace ID 和事实边界始终可定位、可复制或可核验。
- 使用离线系统字体与本地图标，不依赖外部字体、CDN 或装饰素材。

## Colors

颜色体系是“深灰蓝系统上下文 + 冷灰生产工作面 + 克制电网青绿 + 明确语义色”。前置 YAML 是默认规范值，实现由 `ProductBrandConfig.brandTheme.primary` 经统一色阶算法注入 `frontend/src/styles.css` 中的语义 Token。默认色仅是电力行业绿色视觉起点，不声明为任何客户的官方品牌色。

### Primary

- **完整原始色阶**（`grid-green-50` 至 `grid-green-950`）：默认品牌基准与主操作统一为 `#006A56`，仅供主题生成器使用。
- **品牌操作层**（`brand-primary` / `brand-primary-hover` / `brand-primary-active`）：主按钮、链接、导航高亮和操作反馈只能读取语义 Token，不直接读取原始色阶。
- **品牌结构层**（`brand-bg-soft` / `brand-bg-subtle` / `brand-bg-selected` / `brand-border`）：分别承担悬停、轻装饰、选中和品牌描边，禁止混用为业务成功状态。
- **焦点与反白层**（`brand-focus-ring` / `brand-text-on-primary`）：焦点环统一为 `rgba(0, 106, 86, 0.18)`，主色表面文字统一为白色。

### Neutral

- **系统深炭灰**（`system-charcoal`）：独立于品牌主题，仅用于顶部系统身份与运行上下文，不覆盖业务内容区。
- **冷灰画布与白色面板**（`canvas` / `surface`）：工作面和承载事实的面板。
- **文字层级**（`ink` / `text-secondary` / `text-muted` / `text-disabled`）：依次表达标题与关键事实、常规数据、元信息和不可用内容。
- **结构线**（`line` / `line-soft`）：面板外框、表头、行分隔和栏目边界；主要层级由明度与线条建立。

### Semantic

- 成功、处理中、提醒、危险分别使用绿、蓝、橙、红的独立语义体系；未知、未核验或普通状态保持中性，不能用品牌色推断业务结论。

**The Restrained Accent Rule.** 电网青绿只标记行动与当前位置，不把整页染成品牌色。

**The Double-Encoding Rule.** 状态颜色必须同时配合文字、图标或形状；颜色不能单独承担含义。

## Typography

**Display / Body Font:** Microsoft YaHei，回退至 PingFang SC、Noto Sans CJK SC、Arial、sans-serif

**Label / Mono Font:** SFMono-Regular，回退至 Consolas、Liberation Mono、monospace

系统字体确保 Windows 办公终端和封闭内网稳定渲染。层级依靠字重、字号、明度和位置，不使用装饰字体、超大标题或营销式字距。

### Hierarchy

- **Page headline**（20px / 650 / 1.3）：每页唯一主标题，紧随面包屑进入任务内容。
- **Section title**（14px / 650 / 1.3）：面板标题，配合左侧 1px 绿色结构提示。
- **Body**（14px / 400 / 1.5）：常规正文；表格、菜单和控件主要使用 13px。
- **Label / Meta**（9–12px）：机构、角色、字段标签、计数和辅助说明；关键事实不得为了挤压布局而缩小。
- **Metrics**（20–22px / 650）：紧凑摘要数字，使用等宽数字特性。
- **Mono**（10–12px）：业务编号、哈希、Trace ID、代码值和技术详情，保持可复制与不换行。

**The Audit Numerals Rule.** 金额固定两位小数，日期统一为 `YYYY-MM-DD HH:mm:ss`，数字列右对齐，缺失值统一显示 `—`。

## Layout

应用壳层没有常驻左侧栏，也没有工作空间切换器。顶部依次是 48px 深色系统栏、42px 白色一级导航和 34px 冷灰面包屑栏；其下直接进入页面标题、操作与高密度业务内容。系统栏承载品牌、机构、角色、环境、风险入口和用户菜单；一级导航表达业务域，面包屑保持 1–3 层任务位置。

导航由当前会话的角色策略和后端 `menus` 共同生成。首页是直达入口；结算管理、可信数据空间、隐私计算、审计与风控、管理控制台按实际权限出现，管理栏目不会与无权角色的业务导航混排。桌面端在 1366px 及以上保持单行横向一级导航。

内容区最大宽度 1840px，常规内边距为 14px 20px 28px；面板间隔 12px，面板正文 14px。页面遵循 `PageHeader → FilterBar / MetricStrip → Surface / DataTable → Drawer / Dialog`，避免卡片套卡片。表格表头固定 36px，数据行 40px；宽表在自身容器双向滚动，首列与操作列按业务需要冻结。

### Responsive behavior

- **≤1400px：**壳层水平内边距收至 16px，品牌和导航间距压缩。
- **≤1120px：**隐藏机构摘要，复杂指标、图表和审计布局减列。
- **≤980px / ≤1080px：**工作台、主从详情和五步任务布局转为单列或横向步骤条。
- **<820px：**42px 横向导航从布局中移除，使用临时左侧抽屉与遮罩；抽屉关闭后不占空间，也不恢复常驻侧栏。系统栏仍为 48px，面包屑仍为 34px。
- **≤760px / ≤480px：**筛选、操作、指标、分页和复杂摘要继续纵向堆叠；表格仍在自身容器滚动。

## Elevation & Depth

系统默认扁平，页面、面板、筛选栏、表格和摘要条依靠白色/冷灰色差与 1px 边框分层。阴影只表示覆盖关系或临时浮层，不表示普通内容的重要性。

### Shadow Vocabulary

- **Overlay:** 用户菜单、列设置和通用覆盖层使用低对比环境阴影。
- **Navigation menu:** 桌面纵向下拉菜单使用更短、更贴近栏目栏的阴影。
- **Side overlay:** 临时移动导航和右侧详情抽屉只向内容侧投影。
- **Selected segment:** 分段控件当前项使用极轻阴影；普通按钮、面板和指标无常驻阴影。

状态过渡使用 140ms 或 180ms；桌面下拉菜单以 120ms 轻微淡入和上移进入。`prefers-reduced-motion: reduce` 下动画与过渡缩至近零。

**The Flat-by-Default Rule.** 阴影只证明一个表面正在覆盖另一个表面。

## Shapes

主要面板、按钮和输入采用紧致直角感（2px）；基础控件与状态标签使用 3px；菜单和覆盖层最多 4px。圆形只用于状态点、可信链节点、时间线标记和步骤序号；任务计数可使用胶囊，但按钮、输入、面板和普通标签不能变成胶囊。

边框是主要结构语言：系统栏与栏目栏使用清晰横线，面板与表格使用标准结构线，表格行和次级区域使用柔和分隔线。避免大圆角、厚描边和漂浮轮廓。

## Components

### Application shell and navigation

- 系统栏固定 48px，白色栏目栏固定 42px，面包屑栏固定 34px；三层作为一个粘性应用头部滚动。
- 一级栏目默认深灰文字，悬停进入浅灰绿底；当前栏目使用绿色文字、650 字重和底部 2px 绿线。
- 含子项的栏目打开 224px 宽纵向下拉菜单。鼠标约 120ms 打开、离开约 220ms 关闭；点击外部或完成跳转后关闭。
- 键盘支持 `Tab`、`Enter`、`Space`、`Escape`、方向键、`Home` 和 `End`；触发器与菜单使用 `aria-haspopup`、`aria-expanded`、`aria-controls`、`role="menu"`、`role="menuitem"` 和 `aria-current`。
- 820px 以下临时导航宽度为 `min(292px, 86vw)`；遮罩点击和明确关闭按钮都能退出，路由变化后自动关闭。

### Buttons, fields, and status

- 主、次、危险和幽灵按钮最小高度 36px，使用 2px 圆角和紧凑内边距；主按钮只用于当前区域的主要提交或执行。
- 输入、选择与文本域最小高度 36px，白底、1px 边框；聚焦同时改变边框并保留清晰焦点环。错误、禁用和提交中状态不可仅靠颜色。
- 状态标签最小高度 22px，采用语义色文字、soft 背景和描边；未知与未核验使用中性样式。

### Surfaces, metrics, and tables

- Surface 使用白底、1px 边框和 2px 圆角；标题栏为紧凑浅灰底，正文通常为 14px 内边距。
- 指标条优先拼成单个有分隔线的摘要带，不做独立营销卡片；数字使用等宽数字特性，语义色最多改变边框。
- DataTable 统一固定表头、冻结列、排序、列显示、20 / 50 / 100 条分页、空/错/加载状态和可聚焦滚动区域。长名称省略，长编号保留完整值提示与复制入口。

### Audit and settlement patterns

- 任务详情通过事实条、主操作、八步可信链和“业务信息 / 技术信息”分层建立可追踪状态；八步状态来自数据库事实，不使用静态百分比。
- 审计页面沿对象筛选、事件时间线、凭证引用、规则命中、复算口径和确认主体组织证据。只有后端明确返回布尔结论时才显示“已通过/需复核”，否则显示“未核验”。
- 弹窗、详情抽屉和确认对话框维持标题关联、焦点圈定、Escape 关闭和触发点焦点恢复；请求进行中禁用会造成歧义的关闭动作。

### Loading, error, empty, and session states

- 页面、表格和局部加载各自使用对应骨架或 `role="status"`；错误使用 `role="alert"`，保留安全化错误、可选 Trace ID 和重试入口。
- “无数据”“无权限”“加载失败”“未核验”“会话失效”和“服务不可用”是不同状态。只有 401 清除会话；超时、网络错误和 5xx 保留有效凭证并提供恢复路径。

## Do's and Don'ts

### Do:

- **Do** 复用三层顶部壳层、PageHeader、FilterBar、MetricStrip、Surface、DataTable 和共享状态组件。
- **Do** 让菜单入口、路由、操作和数据范围同时服从角色策略与后端菜单；无权状态进入正式 403 页面。
- **Do** 让表头、冻结列、分页、长编号、金额、时间和缺失值遵守统一紧凑表格规则。
- **Do** 保留清晰的 `:focus-visible`、图标按钮可访问名称、语义表单和状态双重编码。
- **Do** 只陈述接口提供的事实，并就近展示来源、编号、时间、引用、Trace ID、测量范围和未核验边界。
- **Do** 在 1366×768、1440×900、1920×1080、Windows 125% 缩放与 820px 以下窄屏验证导航、长机构名、表格和弹层。

### Don't:

- **Don't** 恢复常驻左侧导航、工作空间切换器或蓝色主导视觉；管理入口应由同一权限驱动顶部导航生成。
- **Don't** 使用紫色/蓝紫渐变、AI 科技光晕、玻璃质感、营销 Hero、欢迎横幅、旧门户拼贴或超大仪表盘展示。
- **Don't** 使用大阴影、漂浮卡片、卡片套卡片、Bento Grid、巨型标题、巨型圆角、全站胶囊标签或彩色图标底座。
- **Don't** 创造后端没有的字段、状态、审批、证书、合规结论、实时健康结论或行情，也不要把生成式解释冒充生产事实。
- **Don't** 用 CSS 隐藏代替权限控制，用全页横向滚动或裁切掩盖布局问题，或用缩小字体塞入长内容。
- **Don't** 使用欢迎语、宣传口号、“赋能业务”“智能洞察”“一站式体验”等无法核验的营销文案。
