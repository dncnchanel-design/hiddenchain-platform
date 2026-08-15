# 第七轮 GitHub 开源项目筛选与落地记录

调研时间：2026-08-16（北京时间）。本轮从测试安全和持续回归缺口入手：上一轮已经把 PyLD 接入运行时，但仓库此前没有独立的后端 GitHub 测试工作流，属性边界也没有持续自动执行。

## 本轮直接落地

| 项目 | GitHub 快照 | 落地内容 | 部署代价 |
| --- | --- | --- | --- |
| [HypothesisWorks/hypothesis](https://github.com/HypothesisWorks/hypothesis) | 未归档；MPL-2.0（仓库许可证文本）；v6.165.9 于 2026-08-15 发布；2026-08-15 有提交；Python | 为负荷曲线长度/数值边界、负值拒绝和 JSON-LD 外部 context 拒绝增加属性测试 | 低；增加 `hypothesis==6.165.9` 与 `sortedcontainers`，只服务测试 |
| [actions/setup-python](https://github.com/actions/setup-python) + [actions/checkout](https://github.com/actions/checkout) | setup-python v7.0.0、checkout v7.0.1；工作流均固定到完整 commit SHA | 新增 `backend-tests.yml`，在 PR、main push 和手工触发时安装锁定后端依赖，执行 pytest 与 `pip check` | 低；只增加 GitHub Actions 测试作业，权限为 `contents: read` |

## 代码落地点

- `backend/tests/test_property_invariants.py`：Hypothesis 生成 24 点负荷曲线，验证非负有限值可接受、负值始终拒绝，并验证任意字符串 JSON-LD context 都不会触发远程加载。
- `.github/workflows/backend-tests.yml`：固定 checkout/setup-python SHA；安装 `backend/requirements.txt`；运行项目根目录 pytest 和依赖一致性检查。
- `backend/requirements.txt`：加入测试依赖 `hypothesis==6.165.9`。

## 安全边界

1. 属性测试只生成内存中的模拟数值和字符串，不接触真实企业数据、Vault 文件或外部网络。
2. 测试工作流不上传业务数据、不写 GitHub Security 面板，权限仅为读取仓库内容；动作依赖固定到 commit，继续接受 zizmor/Scorecard 检查。
3. Hypothesis 发现的是输入不变量和回归样本，不替代 OPA/Rego 语义测试、OSV/Trivy、SBOM 或人工安全审查。
4. 后端测试在 Python 3.12 上运行，与当前 Docker/Render 运行时一致；本地 Python 3.14 仍作为额外兼容性验证环境。

## 本轮结论

当前系统的策略、隐私、目录、能源模型、凭证规范化和供应链扫描已经有对应的自动化检查；新增的后端测试门把这些改动纳入每次 PR 和主分支提交的回归路径，降低后续继续接入 EDC、SecretFlow 或生产身份服务时的回归风险。
