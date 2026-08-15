# 开源调研与落地记录（Round 13）

本轮把 Dataspace Protocol 目录从 JSON Schema 字段校验推进到离线 RDF/SHACL 语义校验，增加独立的 SHACL CI 工作流。

## 选型与核验

| 项目 | 许可证 / 状态 | 核验结果 | 落地方式 |
|---|---|---|---|
| [RDFLib/pySHACL](https://github.com/RDFLib/pySHACL) | Apache-2.0；未归档；GitHub API 显示 2026-07-28 有更新；最新 release 为 [v0.40.1](https://github.com/RDFLib/pySHACL/releases/tag/v0.40.1) | Python SHACL validator，适合验证 RDF 图的类、属性和最小基数约束 | 新增本地 Dataspace Catalog SHACL shape 和独立 CI，固定 pySHACL 0.40.1 |
| [RDFLib/rdflib](https://github.com/RDFLib/rdflib) | BSD-3-Clause；未归档；GitHub API 显示 2026-08-14 有更新；最新 release 为 7.6.0 | 将已脱敏的目录 projection 转成内存 RDF 图，不触碰 Vault payload | CI 固定 RDFLib 7.6.0，仅用于元数据语义测试 |

## 代码与流程改进

- `backend/tests/fixtures/dataspace_catalog.shacl.ttl`：约束 Catalog 必须有 Dataset 和 DataService；Dataset 必须有标题、ODRL Offer 和 Distribution；Offer/Permission/Constraint 必须有用途控制字段；Distribution 必须指向 DataService endpoint。
- `backend/tests/test_dataspace_shacl.py`：把 Dataspace Protocol 元数据 projection 转成内存 RDF 图，验证正常 descriptor 和缺失 policy 的拒绝分支。
- `.github/workflows/shacl.yml`：只安装测试依赖并运行两个 SHACL 回归测试，随后执行 `pip check`；pySHACL/RDFLib 不进入应用运行时依赖。

## 安全边界

1. 所有 RDF 三元组由本地已脱敏的 catalog metadata 构造，测试不读取 `vault://`、数据库原始 payload 或线上接口。
2. SHACL shape 和 RDF graph 均为本地资源；工作流不解析远程 JSON-LD context、远程 schema 或外部 ontology。
3. 该工作流校验协议语义，不替代 OPA 运行时授权；ODRL 仍是互操作描述，OPA 仍是 fail-closed PDP。
4. pySHACL/RDFLib 作为 CI-only 依赖，避免扩大 Render/生产镜像和请求延迟；未来若接入真实数据空间协商，应先单独做依赖和性能评审。

## 验证

- 本地：SHACL 正常 descriptor 通过；删除 `odrl:hasPolicy` 的 descriptor 被拒绝；现有 pytest 仍通过。
- GitHub：PR、`main` push 和每周计划任务运行 Dataspace SHACL Tests，动作依赖固定到 commit SHA。
