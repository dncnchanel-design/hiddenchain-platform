# 开源调研与落地记录（Round 10）

本轮补齐 Python 后端的安全静态检查，把 Bandit 接入 GitHub Actions，并保留完整报告供审计回看。

## 选型与核验

| 项目 | 许可证 / 状态 | 核验结果 | 落地方式 |
|---|---|---|---|
| [PyCQA/bandit](https://github.com/PyCQA/bandit) | Apache-2.0；未归档；GitHub API 显示 2026-08-04 有更新；最新 release 为 [1.9.4](https://github.com/PyCQA/bandit/releases/tag/1.9.4) | 专门检查 Python 常见安全问题，依赖小，适合在现有 Trivy/OSV 之外增加源码级规则扫描 | 新增 `.github/workflows/bandit.yml`，固定 Bandit 1.9.4，保存全量 JSON 报告并以中高危门槛阻断 PR |

## 代码与流程改进

- `.github/workflows/bandit.yml`：对 `backend/app` 运行完整扫描；低危结果进入构建产物，中高危且至少中等置信度的结果失败。
- 工作流中的 checkout、setup-python、upload-artifact 均固定到已核验的 40 位 commit，延续仓库供应链安全约束。
- 当前本地扫描得到 6 条低危 B105 提示，来源是离线演示账号和标准 `bearer` token 类型；它们不是生产密码，生产部署仍应关闭演示种子并使用环境密钥。中高危结果为 0。

## 安全边界

1. Bandit 是源码级规则扫描，不能替代 Trivy 文件系统扫描、OSV 依赖扫描、Scorecard 或运行时测试；多层检查分别保留。
2. 工作流不把 Bandit 加入生产运行时依赖，只在 CI 中固定安装，避免扩大应用镜像。
3. 完整报告只上传到 GitHub Actions artifact，不写入业务数据库、日志指标或用户响应。
4. 演示凭据仅用于离线/MVP 验证；生产环境必须设置强随机 JWT/SIGNING 秘钥，并关闭 `DEMO_SEED`。

## 验证

- 本地：`python -m bandit -r app --severity-level low --confidence-level low --exit-zero` 收集报告。
- 本地门禁：`python -m bandit -r app --severity-level medium --confidence-level medium`，当前 0 条中高危结果。
- GitHub：PR 和 `main` push 同时运行 Bandit，报告保留 14 天。
