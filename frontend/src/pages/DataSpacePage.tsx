import { useMemo, useState } from "react";
import { CheckCircle2, Database, Fingerprint, Network, RefreshCw, ScrollText, ShieldCheck, XCircle } from "lucide-react";
import { api, shortHash } from "../api";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Metric, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { ALGORITHM_LABELS, UNIFIED_REQUIREMENT_LABELS } from "../types";
import type { JsonRecord } from "../types";

const assetNames: Record<string, string> = {
  GENERATION_DATA: "发电计量",
  RETAIL_DATA: "售电履约",
  RENEWABLE_FORECAST: "新能源预测",
  VPP_RESOURCE: "虚拟电厂资源",
  GRID_CONSTRAINT: "调度安全边界",
};

const capabilityLabels: Record<string, string> = {
  CATALOG_DISCOVERY: "目录发现",
  IDENTITY_VERIFICATION: "身份互认",
  CONTRACT_NEGOTIATION: "合同协商",
  USAGE_CONTROL: "使用控制",
  AGGREGATE_ONLY_OUTPUT: "聚合输出",
  RECEIPT_RECORDING: "回执存证",
};

export function DataSpacePage() {
  const [batch, setBatch] = useState("TB-2026-07-DEMO");
  const loader = () => Promise.all([
    api<JsonRecord>(`/data/catalog?trade_batch_no=${encodeURIComponent(batch)}`),
    api<JsonRecord>("/data-space/protocol"),
    api<JsonRecord[]>(`/data/agreements?task_id=task-ready-demo`),
  ]).then(([catalog, protocol, agreements]) => ({ catalog, protocol, agreements }));
  const { data, loading, error, reload } = useRemote(loader, [batch]);
  const entries = data?.catalog.entries || [];
  const agreements = data?.agreements || [];
  const assetCount = useMemo(() => new Set(entries.map((item: JsonRecord) => item.asset_type)).size, [entries]);

  if (loading) return <LoadingState label="正在发现数据产品与连接器协议" />;
  if (error || !data) return <ErrorState message={error || "数据空间加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader
        eyebrow="可信数据空间"
        title="可信数据调用"
        description="按照目录发现、身份互认、合同协商、使用控制和回执存证的顺序，让跨主体数据可调用但不搬运原始数据。"
        actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>}
      />
      <div className="boundary-strip">
        <Network size={18} />
        <div><strong>HCDS-1.0 可信调用协议已启用</strong><span>原始数据留在主体域内，调用方只获得数据产品元数据、策略决定和可验证回执。</span></div>
        <StatusTag value="ACTIVE" label="协议在线" />
      </div>
      <div className="inline-actions" style={{ marginBottom: 16 }}>
        <label className="field"><span>数据空间批次</span><input value={batch} onChange={(event) => setBatch(event.target.value)} /></label>
        <Button icon={Database} onClick={reload}>发现目录</Button>
      </div>
      <div className="metrics-grid five">
        <Metric label="可调用数据产品" value={entries.length} meta={`${assetCount} 类能源资产`} />
        <Metric label="协议版本" value={data.protocol.protocol_version} meta="轻量连接器" />
        <Metric label="协议能力" value={data.protocol.capabilities.length} meta="目录至回执" />
        <Metric label="已协商协议" value={data.protocol.negotiated_agreements} meta="跨主体合同" tone="green" />
        <Metric label="原始数据传输" value="0" meta="调用边界目标" tone="green" />
      </div>
      <div className="content-grid two-equal">
        <Surface title="可信调用能力" note="从发现到回执形成一条可验证的数据调用链">
          <div className="acceptance-list">
            {data.protocol.capabilities.map((code: string) => <div key={code}><CheckCircle2 size={18} /><span>{capabilityLabels[code] || code}</span><StatusTag value="PASSED" label="已接入" /></div>)}
          </div>
        </Surface>
        <Surface title="三统一映射" note="目录标识、身份登记、接口要求统一后才能被调用">
          <div className="acceptance-list">
            {data.protocol.three_unified.map((code: string) => <div key={code}><ShieldCheck size={18} /><span>{UNIFIED_REQUIREMENT_LABELS[code] || code}</span><StatusTag value="READY" label="已统一" /></div>)}
          </div>
          <Notice>当前为标准对齐参考实现；SecretFlow、FISCO BCOS 和真实 DID/VC 仍通过适配器替换。</Notice>
        </Surface>
      </div>
      <Surface title="可调用能源数据产品目录" note={`${data.catalog.catalog_id} · 语义版本 ${data.catalog.semantic_version}`}>
        <DataTable
          keyField="data_product_id"
          rows={entries}
          columns={[
            { key: "data_product_id", label: "数据产品 ID", render: (row) => <CodeValue title={row.data_product_id}>{shortHash(row.data_product_id, 12)}</CodeValue> },
            { key: "asset_type", label: "资产类型", render: (row) => assetNames[row.asset_type] || row.asset_type },
            { key: "owner_org_name", label: "提供方" },
            { key: "semantic_ref", label: "语义标识", render: (row) => <CodeValue>{row.semantic_ref}</CodeValue> },
            { key: "schema_version", label: "Schema" },
            { key: "unit", label: "单位" },
            { key: "sensitivity_level", label: "敏感等级", render: (row) => <StatusTag value={row.sensitivity_level} /> },
            { key: "usage", label: "输出约束", render: (row) => row.usage?.raw_data_export === false ? "仅聚合输出" : "需复核" },
          ]}
        />
      </Surface>
      <Surface title="数据调用协议记录" note="每条记录对应一组提供方—使用方—用途—算法的可验证协议">
        <DataTable
          keyField="agreement_id"
          rows={agreements}
          empty="尚未产生调用协议，请运行一笔场景验证任务"
          columns={[
            { key: "agreement_id", label: "协议 ID", render: (row) => <CodeValue title={row.agreement_id}>{shortHash(row.agreement_id, 10)}</CodeValue> },
            { key: "provider_org_id", label: "提供方", render: (row) => shortHash(row.provider_org_id, 12) },
            { key: "consumer_org_id", label: "使用方", render: (row) => shortHash(row.consumer_org_id, 12) },
            { key: "requested_purpose", label: "用途" },
            { key: "algorithm_code", label: "计算方案", render: (row) => ALGORITHM_LABELS[row.algorithm_code] || row.algorithm_code },
            { key: "state", label: "状态", render: (row) => <StatusTag value={row.state} /> },
            { key: "use_count", label: "使用次数", render: (row) => `${row.use_count}/${row.max_uses}` },
            { key: "last_receipt_json", label: "回执", render: (row) => row.last_receipt_json?.receipt_hash ? <><CheckCircle2 size={15} /> 已记录</> : <><XCircle size={15} /> 待生成</> },
          ]}
        />
      </Surface>
      <div className="content-grid two-equal">
        <Surface title="身份与语义边界" note="连接器仅暴露可发现的元数据">
          <div className="detail-grid">
            <div><span>目录地址</span><strong>catalog://hiddenchain/energy-v1</strong></div>
            <div><span>身份方式</span><strong><Fingerprint size={15} /> DID/VC 模拟互认</strong></div>
            <div><span>原始数据</span><strong><ShieldCheck size={15} /> 不进入业务库</strong></div>
          </div>
        </Surface>
        <Surface title="可审计回执" note="ComputeReceipt 绑定策略、输入承诺与输出哈希">
          <div className="detail-grid">
            <div><span>策略执行</span><strong>PEP/PDP 已启用</strong></div>
            <div><span>输出形式</span><strong>仅聚合结果</strong></div>
            <div><span>回执索引</span><strong><ScrollText size={15} /> 进入三阶段证据链</strong></div>
          </div>
        </Surface>
      </div>
    </>
  );
}
