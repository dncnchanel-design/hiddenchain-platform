# 白标配置指南

白标配置由后端运行时读取，通过公开只读接口 `/api/public/config` 提供给登录页与通用应用壳层。前端不把客户名称或 Logo 编译进产物。

| 环境变量 | 用途 | 默认值 |
| --- | --- | --- |
| `PRODUCT_NAME` | 浏览器标题与完整产品名 | 隐链明算 |
| `PRODUCT_SHORT_NAME` | 侧栏紧凑名称 | 隐链明算 |
| `PRODUCT_SUBTITLE` | 产品定位 | 多能源可信数据空间 |
| `PRODUCT_LOGO` | 完整 Logo URL/站内路径 | 空，使用文字标识 |
| `PRODUCT_LOGO_COMPACT` | 折叠侧栏 Logo | 空 |
| `PRODUCT_FAVICON` | favicon URL/站内路径 | 空 |
| `BRAND_THEME_ID` | 部署主题技术标识，不在普通用户界面展示 | power-grid-green |
| `BRAND_PRIMARY` | 品牌视觉基准色，由前端统一生成完整色阶与语义 Token | #0A806C |
| `CUSTOMER_NAME` | 客户单位 | 空 |
| `OPERATOR_NAME` | 运营单位 | 空 |
| `BUILDER_NAME` | 建设单位 | 空 |
| `COPYRIGHT_OWNER` | 版权主体 | 空 |
| `COPYRIGHT_YEAR` | 版权年份 | 空 |
| `SUPPORT_NAME` | 支持团队 | 空 |
| `SUPPORT_CONTACT` | 支持联系方式 | 空 |
| `ENVIRONMENT_NAME` | 非生产环境标签 | production 默认空 |
| `LOGIN_NOTICE` | 登录公告 | 空 |

## 资源要求

- 推荐使用同源站内路径，如 `/branding/customer-logo.svg`，避免 CSP、跨域和第三方可用性问题。
- 完整 Logo 建议横向、透明背景；紧凑 Logo 建议正方形。界面限制高度，不会拉伸原比例。
- 未配置资源时保持文字标识，不显示破图。
- 客户 Logo、名称和公告应经过授权；不要在配置中放密钥或内部工单信息。

## 示例

```text
PRODUCT_NAME=华北电力结算协同平台
PRODUCT_SHORT_NAME=结算协同
PRODUCT_SUBTITLE=多能源可信数据空间
PRODUCT_LOGO=/branding/full-logo.svg
PRODUCT_LOGO_COMPACT=/branding/mark.svg
PRODUCT_FAVICON=/branding/favicon.svg
BRAND_THEME_ID=customer-blue
BRAND_PRIMARY="#1769AA"
CUSTOMER_NAME=某电力交易机构
OPERATOR_NAME=某运营单位
BUILDER_NAME=某建设单位
COPYRIGHT_OWNER=某电力交易机构
COPYRIGHT_YEAR=2026
SUPPORT_NAME=平台服务台
SUPPORT_CONTACT=service@example.com
LOGIN_NOTICE=仅限授权用户访问
```

修改后重启后端即可；前端配置缓存为 60 秒，刷新页面后更新浏览器标题、favicon、品牌主题、登录页和应用壳层。主题属于部署配置能力，生产界面不提供换肤入口。

可信数据空间业务壳层的深蓝信息头、白色八模块导航、青蓝当前项和状态语义属于本产品固定视觉规则，不由 `BRAND_PRIMARY` 改写；白标变量仍负责浏览器标识、登录页品牌内容和通用壳层主题。
