# 历史非生产验收样例

本目录只用于 development/test 的兼容回归，不进入生产镜像，也不能作为实际客户、业务结果或安全能力证明。

- `2026-08-simulation-input.json`：固定虚拟输入。当前导入请求已改为 `LOCAL_CONTROLLED / CONTROLLED_SETTLEMENT_V1`。
- `2026-08-simulation-result.json`：2026-08-13 旧版本生成的历史快照，包含当时的模拟适配器名称和未经外部证明的验收字段。它只用于比较旧数据结构，不代表当前实现。
- `2026-08-full-settlement-simulation.json`：一笔可从导入、隐私分析、受控结算、双方确认到审计归档的完整模拟输入。
- `2026-08-full-settlement-expected-result.json`：上述输入的人工核对答案；最终应结金额为 412300.00 元。
- Excel 单表版样例位于 `frontend/public/sample-data/hiddenchain-single-table-*.xlsx`：发电方、售电方、交易中心各一个工作表，兼容 Excel 批量上传。

完整操作顺序见 [`docs/FULL_SETTLEMENT_SIMULATION_RUNBOOK.md`](../docs/FULL_SETTLEMENT_SIMULATION_RUNBOOK.md)。

production 中：

- 根 `.dockerignore` 排除此目录；
- `/api/settlement/import-and-run` 返回 404；
- 启动守卫拒绝包含该类测试主体、任务、账户或历史适配器记录的数据库。

当前权威能力边界见 `docs/TRUSTED_EXECUTION_MODEL.md`。真实结算仅执行本地受控确定性计算；MPC、TEE、区块链和跨域不出域证明均未配置或未提供。
