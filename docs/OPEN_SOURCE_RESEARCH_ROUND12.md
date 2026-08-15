# 开源调研与落地记录（Round 12）

本轮把后端测试从“测试通过”推进到“测试覆盖面有最低保障”，在现有 Backend Tests 工作流中接入 coverage.py 分支覆盖率门禁。

## 选型与核验

| 项目 | 许可证 / 状态 | 核验结果 | 落地方式 |
|---|---|---|---|
| [coveragepy/coveragepy](https://github.com/coveragepy/coveragepy) | Apache-2.0；未归档；GitHub API 显示 2026-08-09 有更新；最新 release 为 [7.15.4](https://github.com/coveragepy/coveragepy/releases/tag/7.15.4) | Python 官方生态中成熟的行/分支覆盖率工具，支持 Python 3.12，运行时依赖轻 | 在 `.github/workflows/backend-tests.yml` 中固定 7.15.4，运行全量后端 pytest，并以 `--fail-under=75` 阻断覆盖率回退 |

## 代码与流程改进

- 后端测试使用 `coverage run --branch --source=backend/app -m pytest -q`，只统计应用代码，不把测试代码和第三方库混入门槛。
- `coverage report --fail-under=75` 当前本地得到 76% 分支覆盖率，留出 1 个百分点的维护缓冲，避免把偶然的小数波动当成质量倒退。
- coverage.py 仅作为 CI 工具安装，不加入 `backend/requirements.txt`，不扩大生产镜像和业务依赖图。

## 安全边界

1. 覆盖率是测试质量指标，不代表隐私、授权或业务正确性；仍需保留 pytest/Hypothesis、Schemathesis、OPA、OSV、Trivy、Bandit 和人工审计。
2. 测试只使用现有演示数据库和内存输入，不上传覆盖率源代码或业务数据到第三方服务。
3. 分支门槛只作用于 GitHub PR、`main` push 和手工触发的 Backend Tests，不改变线上 API 行为。

## 验证

- 本地：42 项 pytest 通过，应用分支覆盖率 76%，75% 门禁通过。
- GitHub：Backend Tests 在 PR 和 `main` push 上同时执行覆盖率报告与 `pip check`。
