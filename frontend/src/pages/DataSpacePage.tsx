import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Eye, RefreshCw, Search } from "lucide-react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Button, DataTable, DateTimeText, DetailDrawer, FilterBar, IdText, Metric, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { ALGORITHM_LABELS, SCENARIO_LABELS, labelForCode, type JsonRecord } from "../types";

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
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get("task_id") || "";
  const [batch, setBatch] = useState("");
  const [batchInput, setBatchInput] = useState("");
  const [assetFilter, setAssetFilter] = useState("");
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const loader = async (signal?: AbortSignal) => {
    const request = { signal, timeoutMs: 12000, cache: "no-store" as RequestCache };
    const task = taskId ? await api<JsonRecord>(`/settlement/tasks/${taskId}`, request) : null;
    const effectiveBatch = batch || task?.trade_batch_no || "";
    const query = effectiveBatch ? `?trade_batch_no=${encodeURIComponent(effectiveBatch)}` : "";
    const [catalog, agreements] = await Promise.all([
      api<JsonRecord>(`/data/catalog${query}`, request),
      api<JsonRecord[]>(taskId ? `/data/agreements?task_id=${encodeURIComponent(taskId)}` : "/data/agreements", request),
    ]);
    return { catalog, agreements, task, effectiveBatch };
  };
  const { data, loading, refreshing, error, reload } = useRemote(loader, [batch, taskId]);
  const entries = useMemo(() => {
    const rows = data?.catalog.entries || [];
    return assetFilter ? rows.filter((item: JsonRecord) => item.asset_type === assetFilter) : rows;
  }, [assetFilter, data]);
  const agreements = data?.agreements || [];
  const assetCount = useMemo(() => new Set(entries.map((item: JsonRecord) => item.asset_type)).size, [entries]);
  const receiptCount = agreements.filter((item) => item.last_receipt_json?.receipt_hash).length;

  useEffect(() => {
    if (loading || location.hash !== "#data-authorizations") return;
    const frame = window.requestAnimationFrame(() => document.getElementById("data-authorizations")?.scrollIntoView());
    return () => window.cancelAnimationFrame(frame);
  }, [loading, location.hash]);

  async function applyBatch() {
    const next = batchInput.trim();
    if (next === batch) await reload();
    else setBatch(next);
  }

  return (
    <>
      <PageHeader title="可信数据目录" actions={<>{taskId && <Link className="button button-secondary" to={`/settlements/${taskId}`}><ArrowLeft size={16} />返回结算任务</Link>}<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button></>} />
      {data?.task && <div className="association-context"><span>关联任务</span><Link to={`/settlements/${taskId}`}>{data.task.task_name}</Link><IdText value={data.task.capsule_id || taskId} /></div>}
      <FilterBar actions={<><Button icon={Search} variant="primary" onClick={applyBatch}>查询</Button>{(batch || assetFilter) && <Button onClick={() => { setBatch(""); setBatchInput(""); setAssetFilter(""); }}>重置</Button>}</>}>
        <label><span>批次编号</span><input value={batchInput} placeholder="输入完整批次编号" onChange={(event) => setBatchInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void applyBatch(); } }} /></label>
        <label><span>资产类型</span><select value={assetFilter} onChange={(event) => setAssetFilter(event.target.value)}><option value="">全部类型</option>{Object.entries(assetNames).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>
      </FilterBar>

      <div className="metrics-grid three">
        <Metric label="数据产品" value={entries.length} meta={`${assetCount} 类资产`} />
        <Metric label="调用协议" value={agreements.length} />
        <Metric label="已生成回执" value={receiptCount} tone={receiptCount ? "green" : "default"} />
      </div>

      <Surface title="可用数据产品" meta={loading ? "正在读取" : `${entries.length} 项`}>
        <DataTable
          keyField="data_product_id" rows={entries} loading={loading} error={error} onRetry={reload} label="可用数据产品"
          columns={[
            { key: "data_product_id", label: "数据产品编号", minWidth: 160, render: (row) => <IdText value={row.data_product_id} /> },
            { key: "label", label: "数据产品", minWidth: 170 },
            { key: "asset_type", label: "资产类型", render: (row) => assetNames[row.asset_type] || labelForCode(row.asset_type, "已登记资产类型") },
            { key: "owner_org_name", label: "提供方", minWidth: 140 },
            { key: "trade_batch_no", label: "批次编号", minWidth: 135, render: (row) => <IdText value={row.trade_batch_no} length={8} /> },
            { key: "unit", label: "单位" },
            { key: "sensitivity_level", label: "敏感等级", render: (row) => <StatusTag value={row.sensitivity_level} /> },
            { key: "usage", label: "输出约束", render: (row) => row.usage?.output_mode === "AGGREGATE_ONLY" ? "仅聚合输出" : "—" },
          ]}
        />
      </Surface>

      <Surface id="data-authorizations" title="数据授权记录" meta={`${agreements.length} 项`}>
        <DataTable
          keyField="agreement_id" rows={agreements} empty="暂无调用协议" label="调用协议列表"
          columns={[
            { key: "agreement_id", label: "协议编号", minWidth: 160, render: (row) => <button className="table-link" type="button" onClick={() => setSelected(row)}><IdText value={row.agreement_id} copyable={false} /></button> },
            { key: "provider_org_id", label: "提供方", minWidth: 170, render: (row) => row.provider_org_name || <IdText value={row.provider_org_id} /> },
            { key: "consumer_org_id", label: "使用方", minWidth: 170, render: (row) => row.consumer_org_name || <IdText value={row.consumer_org_id} /> },
            { key: "requested_purpose", label: "用途", minWidth: 140, render: (row) => purposeNames[row.requested_purpose] || SCENARIO_LABELS[row.requested_purpose] || labelForCode(row.requested_purpose, "任务约定用途") },
            { key: "algorithm_code", label: "计算方式", minWidth: 160, render: (row) => ALGORITHM_LABELS[row.algorithm_code] || labelForCode(row.algorithm_code, "已登记计算方式") },
            { key: "state", label: "状态", render: (row) => <StatusTag value={row.state} /> },
            { key: "use_count", label: "调用次数", align: "right", render: (row) => `${row.use_count ?? 0} / ${row.max_uses ?? "—"}` },
            { key: "action", label: "操作", sortable: false, hideable: false, sticky: "right", render: (row) => <Button icon={Eye} onClick={() => setSelected(row)}>详情</Button> },
          ]}
        />
      </Surface>

      {selected && <DetailDrawer title="调用协议详情" onClose={() => setSelected(null)}>
        <div className="detail-grid">
          <div><span>协议编号</span><IdText value={selected.agreement_id} /></div>
          <div><span>关联任务</span>{selected.task_id ? <Link className="text-link" to={`/settlements/${selected.task_id}`}><IdText value={selected.task_id} /></Link> : "—"}</div>
          <div><span>协议状态</span><StatusTag value={selected.state} /></div>
          <div><span>数据提供方</span><strong>{selected.provider_org_name || selected.provider_org_id || "—"}</strong></div>
          <div><span>授权使用方</span><strong>{selected.consumer_org_name || selected.consumer_org_id || "—"}</strong></div>
          <div><span>协议版本</span><strong>{selected.protocol_version || "—"}</strong></div>
          <div><span>生效时间</span><DateTimeText value={selected.valid_from} /></div>
          <div><span>失效时间</span><DateTimeText value={selected.expires_at} /></div>
          <div><span>用途</span><strong>{purposeNames[selected.requested_purpose] || SCENARIO_LABELS[selected.requested_purpose] || labelForCode(selected.requested_purpose, "任务约定用途")}</strong></div>
          <div><span>计算方式</span><strong>{ALGORITHM_LABELS[selected.algorithm_code] || labelForCode(selected.algorithm_code, "已登记计算方式")}</strong></div>
          <div><span>数据产品数</span><strong>{selected.data_product_ids_json?.length ?? 0}</strong></div>
          <div><span>追踪编号</span><IdText value={selected.trace_id} /></div>
        </div>
        <details className="secondary-details"><summary>技术校验信息</summary><div className="detail-grid"><div><span>协商策略摘要</span><IdText value={selected.negotiated_policy_hash} /></div><div><span>最近回执摘要</span><IdText value={selected.last_receipt_json?.receipt_hash} /></div></div></details>
      </DetailDrawer>}
    </>
  );
}
