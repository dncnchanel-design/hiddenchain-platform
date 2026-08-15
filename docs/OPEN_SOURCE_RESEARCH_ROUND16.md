# 开源调研与落地记录（Round 16）

本轮将 pytest-randomly 接入后端 CI，并修复测试夹具对共享 SQLite 数据库和执行顺序的隐式依赖，让后续数据空间、隐私计算和策略改动在不同测试顺序下都能被稳定复核。

## 选型与核验

| 项目 | 许可证 / 状态 | 核验结果 | 落地方式 |
|---|---|---|---|
| [pytest-dev/pytest-randomly](https://github.com/pytest-dev/pytest-randomly) | MIT；未归档；GitHub API 显示 2026-08-13 仍有更新；PyPI 固定 4.1.0 | pytest 插件，可重排测试并固定随机种子；不改变生产运行时 | Backend Tests CI 安装 4.1.0，并以 `20260816` 固定种子运行 44 项后端测试 |

## 代码与流程改进

- `backend/tests/conftest.py`：增加 autouse 测试夹具，每个测试重新创建表结构并重新 seed 演示数据，防止结算、审计、上传和策略测试互相污染。
- `backend/tests/test_platform.py`：审计问答测试显式先完成一笔结算，再验证引用证据，不再依赖其他测试先运行。
- `.github/workflows/backend-tests.yml`：将 coverage.py 和 pytest-randomly 固定版本安装，并以固定随机种子执行覆盖率测试。

## 安全边界

1. pytest-randomly 只存在于 CI/测试环境，不进入 `backend/requirements.txt` 或生产镜像。
2. 测试重置的 SQLite 仅位于 `backend/tests/hiddenchain_test.db`，不触碰运行时 Vault、线上数据库或 Render 数据。
3. 固定种子使失败可复现；每个测试重新 seed 后，策略使用次数、审计证据和数据合同不会从其他测试泄漏。
4. 该插件只发现测试顺序问题，不改变 OPA 授权、隐私输出或真实数据流。

## 验证

- 本地串行随机种子 `20260816`、`17`、`314159` 均通过 44 项测试。
- 覆盖率命令继续使用应用代码分支覆盖率门槛 75%；随后由 GitHub Backend Tests、Schemathesis、Bandit、OSV、Trivy、SBOM、OPA、SHACL 和 Actions 安全流程共同保护。
