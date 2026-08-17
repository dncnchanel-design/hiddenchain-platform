import { useState } from "react";
import { FileSignature, Plus, RefreshCw, Upload } from "lucide-react";
import { api, post } from "../api";
import { useAuth } from "../auth";
import { Button, ConfirmDialog, DataTable, DateTimeText, Field, IdText, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

type DataMode = "generation" | "retail";
type AssetOption = { code: string; label: string };

const generationOptions: AssetOption[] = [
  { code: "GENERATION_DATA", label: "发电计量" },
  { code: "RENEWABLE_FORECAST", label: "新能源预测" },
];
const retailOptions: AssetOption[] = [
  { code: "RETAIL_DATA", label: "售电履约" },
  { code: "USER_LOAD_CURVE", label: "用户负荷曲线" },
  { code: "VPP_RESOURCE", label: "虚拟电厂资源" },
];
const gridOption = { code: "GRID_CONSTRAINT", label: "调度安全边界" };
const assetNames: Record<string, string> = {
  GENERATION_DATA: "发电计量",
  RENEWABLE_FORECAST: "新能源出力预测",
  RETAIL_DATA: "售电履约",
  USER_LOAD_CURVE: "用户负荷",
  VPP_RESOURCE: "虚拟电厂资源池",
  GRID_CONSTRAINT: "调度安全边界",
};

export function DataPage({ mode }: { mode: DataMode }) {
  const { session } = useAuth();
  const role = session!.user.role_code;
  const displayOptions = mode === "generation"
    ? [...generationOptions, ...(["EXCHANGE", "REGULATOR", "ADMIN"].includes(role) ? [gridOption] : [])]
    : retailOptions;
  const createOptions = role === "GENERATOR" ? generationOptions
    : role === "RETAILER" ? retailOptions
      : role === "EXCHANGE" ? [gridOption]
        : role === "ADMIN" ? displayOptions : [];
  const initialType = role === "EXCHANGE" && mode === "generation" ? "GRID_CONSTRAINT" : displayOptions[0].code;
  const [assetType, setAssetType] = useState(initialType);
  const [showForm, setShowForm] = useState(false);
  const [signTarget, setSignTarget] = useState<JsonRecord | null>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const title = mode === "generation" ? "发电侧数据" : "用电侧数据";
  const canCreate = createOptions.some((item) => item.code === assetType);
  const canSign = (row: JsonRecord) => ["GENERATOR", "RETAILER", "EXCHANGE"].includes(role)
    && row.owner_org_id === session!.user.org_id;
  const { data, loading, refreshing, error, reload } = useRemote<JsonRecord[]>(
    (signal) => api(`/data/uploads?asset_type=${assetType}`, { signal, timeoutMs: 12000, cache: "no-store" }),
    [assetType],
  );

  async function sign(uploadId: string) {
    setBusy(uploadId);
    setNotice("");
    try {
      await post(`/data/${uploadId}/sign`, {});
      setNotice("数据承诺已确认并记录。");
      await reload();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "确认失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <PageHeader title={title} description="登记和查看当前权限范围内的数据引用；业务原始值不在列表中展示。" actions={<><Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>{canCreate && <Button icon={Plus} variant="primary" disabled={loading} onClick={() => setShowForm(true)}>登记数据</Button>}</>} />
      <div className="segmented" role="tablist" aria-label="数据类型">
        {displayOptions.map((item) => <button type="button" role="tab" aria-selected={assetType === item.code} key={item.code} className={assetType === item.code ? "active" : ""} onClick={() => setAssetType(item.code)}>{item.label}</button>)}
      </div>
      {notice && <Notice tone={notice.includes("失败") || notice.includes("无权") ? "warning" : "success"}>{notice}</Notice>}
      <Surface title={`${assetNames[assetType]}数据`} meta={data ? `${data.length} 条` : "正在读取"}>
        <DataTable
          keyField="upload_id" rows={data || []} label={`${assetNames[assetType]}数据列表`} loading={loading}
          error={error || (!loading && !data ? "数据加载失败" : "")} onRetry={reload}
          columns={[
            { key: "label", label: "数据资产", minWidth: 180 },
            { key: "owner_org_name", label: "数据提供方", minWidth: 140 },
            { key: "trade_batch_no", label: "批次编号", minWidth: 145, render: (row) => <IdText value={row.trade_batch_no} length={8} /> },
            { key: "data_hash", label: "数据摘要", minWidth: 155, render: (row) => <IdText value={row.data_hash} /> },
            { key: "summary_json", label: "记录数", align: "right", render: (row) => row.summary_json?.record_count ?? "—" },
            { key: "validation_status", label: "校验状态", render: (row) => <StatusTag value={row.validation_status} /> },
            { key: "created_at", label: "登记时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
            { key: "action", label: "操作", sortable: false, hideable: false, sticky: "right", render: (row) => row.signature_value ? <StatusTag value="CONFIRMED" label="已签署" /> : canSign(row) ? <Button icon={FileSignature} busy={busy === row.upload_id} onClick={() => setSignTarget(row)}>确认承诺</Button> : <span className="muted-text">只读</span> },
          ]}
        />
      </Surface>

      {showForm && <UploadModal options={createOptions} defaultAssetType={assetType} onClose={() => setShowForm(false)} onCreated={async () => { setShowForm(false); setNotice("数据引用已登记。"); await reload(); }} />}
      <ConfirmDialog
        open={Boolean(signTarget)} title="确认数据承诺" objectName={signTarget?.label || signTarget?.upload_id || "—"}
        currentState={signTarget?.validation_status} consequence="确认后将使用当前数据提供方身份为摘要签名并写入审计记录。仅数据实际归属组织可以执行此操作。"
        confirmLabel="确认并签署" busy={Boolean(signTarget && busy === signTarget.upload_id)} onCancel={() => setSignTarget(null)}
        onConfirm={async () => { if (!signTarget) return; await sign(signTarget.upload_id); setSignTarget(null); }}
      />
    </>
  );
}

function UploadModal({ options, defaultAssetType, onClose, onCreated }: { options: AssetOption[]; defaultAssetType: string; onClose: () => void; onCreated: () => Promise<void> }) {
  const [assetType, setAssetType] = useState(defaultAssetType);
  const [label, setLabel] = useState("");
  const [batch, setBatch] = useState("");
  const [period, setPeriod] = useState("");
  const [recordCount, setRecordCount] = useState("");
  const [energy, setEnergy] = useState("");
  const [accuracy, setAccuracy] = useState("");
  const [capacity, setCapacity] = useState("");
  const [storage, setStorage] = useState("");
  const [responseMinutes, setResponseMinutes] = useState("");
  const [residualLimit, setResidualLimit] = useState("");
  const [congestionMargin, setCongestionMargin] = useState("");
  const [nMinusOnePassed, setNMinusOnePassed] = useState("");
  const [curveInput, setCurveInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const isCurve = assetType === "USER_LOAD_CURVE";
  const isEnergy = ["GENERATION_DATA", "RETAIL_DATA"].includes(assetType);
  const curveValues = curveInput.trim().split(/[\s,，]+/).filter(Boolean).map(Number);
  const numericReady = (value: string, maximum?: number) => value.trim() !== "" && Number.isFinite(Number(value)) && Number(value) >= 0 && (maximum === undefined || Number(value) <= maximum);
  const countReady = isCurve || (numericReady(recordCount) && Number.isInteger(Number(recordCount)) && Number(recordCount) > 0);
  const curveReady = !isCurve || (curveValues.length === 24 && curveValues.every((value) => Number.isFinite(value) && value >= 0));
  const formReady = label.trim().length >= 2 && batch.trim().length >= 3 && period.trim().length > 0 && countReady && curveReady
    && (!isEnergy || numericReady(energy))
    && (assetType !== "RENEWABLE_FORECAST" || (numericReady(energy) && numericReady(accuracy, 100)))
    && (assetType !== "VPP_RESOURCE" || (numericReady(capacity) && numericReady(storage) && numericReady(responseMinutes)))
    && (assetType !== "GRID_CONSTRAINT" || (numericReady(residualLimit) && numericReady(congestionMargin, 100) && nMinusOnePassed !== ""));

  async function submit() {
    setBusy(true);
    setError("");
    try {
      let localPayload: JsonRecord;
      const common = { period, record_count: isCurve ? curveValues.length : Number(recordCount) };
      if (isCurve) localPayload = { ...common, load_curve: curveValues };
      else if (assetType === "RENEWABLE_FORECAST") localPayload = { ...common, forecast_energy_mwh: Number(energy), forecast_accuracy_pct: Number(accuracy) };
      else if (assetType === "VPP_RESOURCE") localPayload = { ...common, adjustable_capacity_mw: Number(capacity), storage_energy_mwh: Number(storage), response_minutes: Number(responseMinutes) };
      else if (assetType === "GRID_CONSTRAINT") localPayload = { ...common, n_minus_one_passed: nMinusOnePassed === "true", max_residual_imbalance_mwh: Number(residualLimit), congestion_margin_pct: Number(congestionMargin) };
      else localPayload = { ...common, energy_mwh: Number(energy) };
      await post("/data/uploads", { asset_type: assetType, trade_batch_no: batch.trim(), label: label.trim(), schema_version: "v1.0", local_payload: localPayload });
      await onCreated();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登记失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="登记数据引用" onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button icon={Upload} variant="primary" busy={busy} disabled={!formReady} onClick={submit}>登记</Button></>}>
      <div className="form-grid two">
        {options.length > 1 && <Field label="资产类型"><select value={assetType} onChange={(event) => { setAssetType(event.target.value); setLabel(""); }}>{options.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></Field>}
        <Field label="资产名称"><input value={label} placeholder="输入可识别的业务名称" onChange={(event) => setLabel(event.target.value)} /></Field>
        <Field label="验证批次"><input value={batch} placeholder="输入完整批次编号" onChange={(event) => setBatch(event.target.value)} /></Field>
        <Field label="数据期间"><input value={period} placeholder="例如 2026-07" onChange={(event) => setPeriod(event.target.value)} /></Field>
        {!isCurve && <Field label="记录数"><input type="number" min="1" step="1" value={recordCount} onChange={(event) => setRecordCount(event.target.value)} /></Field>}
        {isEnergy && <Field label="电量（MWh）"><input type="number" min="0" value={energy} onChange={(event) => setEnergy(event.target.value)} /></Field>}
        {assetType === "RENEWABLE_FORECAST" && <><Field label="预测电量（MWh）"><input type="number" min="0" value={energy} onChange={(event) => setEnergy(event.target.value)} /></Field><Field label="预测准确率（%）"><input type="number" min="0" max="100" value={accuracy} onChange={(event) => setAccuracy(event.target.value)} /></Field></>}
        {isCurve && <div className="form-span"><Field label="24 时点负荷值" hint={`${curveValues.length} / 24 个值；使用逗号或空格分隔`} error={curveInput && !curveReady ? "必须填写 24 个非负数值" : undefined}><textarea value={curveInput} placeholder="依次输入 24 个时点值" onChange={(event) => setCurveInput(event.target.value)} /></Field></div>}
        {assetType === "VPP_RESOURCE" && <><Field label="可调容量（MW）"><input type="number" min="0" value={capacity} onChange={(event) => setCapacity(event.target.value)} /></Field><Field label="储能电量（MWh）"><input type="number" min="0" value={storage} onChange={(event) => setStorage(event.target.value)} /></Field><Field label="响应时间（分钟）"><input type="number" min="0" value={responseMinutes} onChange={(event) => setResponseMinutes(event.target.value)} /></Field></>}
        {assetType === "GRID_CONSTRAINT" && <><Field label="N-1 校核结果"><select value={nMinusOnePassed} onChange={(event) => setNMinusOnePassed(event.target.value)}><option value="">请选择</option><option value="true">通过</option><option value="false">未通过</option></select></Field><Field label="剩余偏差上限（MWh）"><input type="number" min="0" value={residualLimit} onChange={(event) => setResidualLimit(event.target.value)} /></Field><Field label="拥塞裕度（%）"><input type="number" min="0" max="100" value={congestionMargin} onChange={(event) => setCongestionMargin(event.target.value)} /></Field></>}
      </div>
      {error && <Notice tone="warning">{error}</Notice>}
    </Modal>
  );
}
