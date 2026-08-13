# 2026 年 8 月模拟数据

这组数据来自系统线上版本的一次完整虚拟仿真运行，所有数值、名称和身份均为演示数据，不对应真实业务主体。它按赛题的“可信采集—安全传输—可控使用—隐私计算—可溯审计”链路组织，电力交易仅作为验证场景。

## 文件

- `2026-08-simulation-input.json`：6 类输入数据（含来源证明、接入层、协议和 TLS 元数据），以及隐私分析和可信调用验证的请求参数。
- `2026-08-simulation-result.json`：任务结果、隐私计算回执、数据使用回执和凭证核验结果。

## 本次运行标识

- 数据批次：`TB-2026-08-SIM-20260813124544`
- 任务编号：`27516e82-d261-407f-8fac-6fe32b3b2c14`
- 可信胶囊：`HC-CAPSULE-202608-62C8BB67`
- 隐私分析编号：`09d6085e-e41b-42e6-8322-001ebfdc7666`
- 隐私计算编号：`2b2ce2ae-15ce-4fa7-8ebb-9aa079289a36`

## 验证结果

- 6 类数据均通过校验并完成签名。
- 隐私分析状态为 `SUCCESS`，未返回原始记录。
- 可信调用验证任务状态为 `AUDITED`，风险等级为 `LOW`。
- 隐私计算状态为 `SUCCESS`，原始数据未暴露。
- 生成 3 项结果回执和 4 项可信凭证。
- 4 项可信凭证核验均匹配。

线上检验账号：`exchange / exchange123`。

## 页面导入

登录线上系统后进入“可信调用验证”，点击“导入并自动验证”，选择
`2026-08-simulation-input.json`，确认文件预览后点击“开始验证”。

系统会自动完成：来源与格式校验 → 数据登记 → 数据签名 → 安全传输元数据核验 →
用途授权 → 隐私分析 → 创建可信调用任务 → 隐私计算 → 结果回执 → 三阶段可信凭证。

上传文件需要保留 `batch`、`data_assets` 和 `business_validation_request` 三个字段。
每个 `data_assets` 项需要包含 `asset_type`、`owner_org_id`、`label` 和
`local_payload`；建议同时填写 `ingress`，用于展示来源、接入层和安全传输验证。可以删除旧的 `upload_id`、`signature_id` 等运行结果字段，系统会重新生成。

## 赛题要求对应

| 赛题要求 | 文件/页面中的验证点 |
| --- | --- |
| 真实能源场景或虚拟仿真 | `is_simulated: true` 与六类能源数据资产 |
| 可信采集 | `ingress.source_type`、来源证明、格式校验、DataHash/Commitment |
| 安全传输与互联互通 | `ingress.protocol`、`stage`、`encryption`；系统保留 HTTPS、MQTT、WebSocket 接口边界 |
| 数据可用不可见 | 数据原文写入主体域 Vault，业务库仅保存 DataRef、摘要和哈希 |
| 可控使用 | DID/VC、DataContract、用途策略、使用次数和 DataPermit |
| 隐私保护 | PSI/MPC、授权计算沙箱、仅聚合输出、ComputeReceipt |
| 可溯可审计 | `PRE_COMPUTE`、`IN_COMPUTE`、`POST_COMPUTE` 三阶段证据、结果哈希和审计报告 |
| 可量化验证 | 计算耗时、原始数据出域数量、授权协议数、证据核验率 |
