import { useMemo, useState } from "react";
import { CheckCircle2, Database, RefreshCw, XCircle } from "lucide-react";
import { api, shortHash } from "../api";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Metric, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { ALGORITHM_LABELS, SCENARIO_LABELS } from "../types";
import type { JsonRecord } from "../types";

const assetNames: Record<string, string> = {
  GENERATION_DATA: "发电计量",
  RETAIL_DATA: "售电履约",
  RENEWABLE_FORECAST: "新能源预测",
  USER_LOAD_CURVE: "用户负荷曲线",
  VPP_RESOURCE: "虚拟电厂资源",
  GRID_CONSTRAINT: "调度安全边界",
};

const purposeNames: Record<string, string> = {
  POWER_SETTLEMENT: "电力结算",
  GRID_SECURITY_CHECK: "电网安全检查",
  PRIVACY_LOAD_ANALYSIS: "用电隐私分析",
};

export function DataSpacePage() {
  const [batch, setBatch] = useState("TB-2026-07-001");
  const [batchInput, setBatchInput] = useState("TB-2026-07-001");
  const loader = () => Promise.all([
    api<JsonRecord>(`/data/catalog?trade_batch_no=${encodeURIComponent(batch)}`),
    api<JsonRecord[]>("/data/agreements"),
  ]).then(([catalog, agreements]) => ({ catalog, agreements }));
  const { data, loading, error, reload } = useRemote(loader, [batch]);
  const entries = data?.catalog.entries || [];
  const agreements = data?.agreements || [];
  const assetCount = useMemo(() => new Set(entries.map((item: JsonRecord) => item.asset_type)).size, [entries]);

  async function applyBatch() {
    if (batchInput === batch) await reload();
    else setBatch(batchInput);
  }

  if (loading) return <LoadingState label="正在加载数据目录" />;
  if (error || !data) return <ErrorState message={error || "数据目录加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader
        title="数据目录"
        actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>}
      />
      <div className="inline-actions" style={{ marginBottom: 16 }}>
        <label className="field"><span>批次编号</span><input value={batchInput} onChange={(event) => setBatchInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void applyBatch(); } }} /></label>
        <Button icon={Database} onClick={applyBatch}>查询</Button>
      </div>
      <div className="metrics-grid three">
        <Metric label="可调用数据产品" value={entries.length} meta={`${assetCount} 类能源资产`} />
        <Metric label="已授权调用" value={agreements.length} tone="green" />
        <Metric label="原始数据传输" value="0" tone="green" />
      </div>
      <Surface title="可用数据产品" meta={`${entries.length} 项`}>
        <DataTable
          keyField="data_product_id"
          rows={entries}
          columns={[
            { key: "data_product_id", label: "数据产品 ID", render: (row) => <CodeValue title={row.data_product_id}>{shortHash(row.data_product_id, 12)}</CodeValue> },
            { key: "label", label: "数据产品" },
            { key: "asset_type", label: "资产类型", render: (row) => assetNames[row.asset_type] || row.asset_type },
            { key: "owner_org_name", label: "提供方" },
            { key: "unit", label: "单位" },
            { key: "sensitivity_level", label: "敏感等级", render: (row) => <StatusTag value={row.sensitivity_level} /> },
            { key: "usage", label: "输出约束", render: (row) => row.usage?.raw_data_export === false ? "仅聚合输出" : "需复核" },
          ]}
        />
      </Surface>
      <Surface title="最近调用">
        <DataTable
          keyField="agreement_id"
          rows={agreements}
          empty="暂无调用协议"
          columns={[
            { key: "agreement_id", label: "协议 ID", render: (row) => <CodeValue title={row.agreement_id}>{shortHash(row.agreement_id, 10)}</CodeValue> },
            { key: "provider_org_id", label: "提供方", render: (row) => shortHash(row.provider_org_id, 12) },
            { key: "consumer_org_id", label: "使用方", render: (row) => shortHash(row.consumer_org_id, 12) },
            { key: "requested_purpose", label: "用途", render: (row) => purposeNames[row.requested_purpose] || SCENARIO_LABELS[row.requested_purpose] || row.requested_purpose },
            { key: "algorithm_code", label: "计算方式", render: (row) => ALGORITHM_LABELS[row.algorithm_code] || row.algorithm_code },
            { key: "state", label: "状态", render: (row) => <StatusTag value={row.state} /> },
            { key: "use_count", label: "使用次数", render: (row) => `${row.use_count}/${row.max_uses}` },
            { key: "last_receipt_json", label: "回执", render: (row) => row.last_receipt_json?.receipt_hash ? <><CheckCircle2 size={15} /> 已记录</> : <><XCircle size={15} /> 待生成</> },
          ]}
        />
      </Surface>
    </>
  );
}
