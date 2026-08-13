import { useMemo, useState } from "react";
import { Check, Database, FileSignature, Plus, RefreshCw, ShieldCheck, Upload, X } from "lucide-react";
import { api, formatDate, post, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, CodeValue, DataTable, ErrorState, Field, LoadingState, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
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

const sampleCurve = [22, 21, 20, 19, 21, 27, 36, 48, 57, 65, 71, 75, 73, 70, 68, 72, 80, 88, 93, 87, 74, 58, 42, 30];

export function DataPage({ mode }: { mode: DataMode }) {
  const { session } = useAuth();
  const role = session!.user.role_code;
  const displayOptions = mode === "generation"
    ? ([...generationOptions, ...(["EXCHANGE", "REGULATOR", "ADMIN"].includes(role) ? [gridOption] : [])])
    : retailOptions;
  const createOptions = role === "GENERATOR"
    ? generationOptions
    : role === "RETAILER"
      ? retailOptions
      : role === "EXCHANGE"
        ? [gridOption]
        : role === "ADMIN"
          ? displayOptions
          : [];
  const initialType = role === "EXCHANGE" && mode === "generation" ? "GRID_CONSTRAINT" : displayOptions[0].code;
  const [assetType, setAssetType] = useState(initialType);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const title = mode === "generation" ? "发电侧数据" : "售电与用电数据";
  const description = mode === "generation" ? "计量、出力预测和调度边界均以域内引用参与协同，平台不汇聚原始数据。" : "售电履约、用户负荷与虚拟电厂资源按用途授权，只释放必要聚合结果。";
  const canCreate = createOptions.some((item) => item.code === assetType);
  const canSign = ["GENERATOR", "RETAILER", "EXCHANGE", "ADMIN"].includes(role);
  const queryType = assetType;
  const { data, loading, error, reload } = useRemote<JsonRecord[]>(() => api(`/data/uploads?asset_type=${queryType}`), [queryType]);

  async function sign(uploadId: string) {
    setBusy(uploadId);
    setNotice("");
    try {
      await post(`/data/${uploadId}/sign`, {});
      setNotice("数据承诺已由主体 DID 签名，签名值可进入授权证据包。");
      await reload();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "签名失败");
    } finally {
      setBusy("");
    }
  }

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "数据加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader
        eyebrow="业务数据模块"
        title={title}
        description={description}
        actions={<><Button icon={RefreshCw} onClick={reload}>刷新</Button>{canCreate && <Button icon={Plus} variant="primary" onClick={() => setShowForm(true)}>登记数据</Button>}</>}
      />
      <div className="segmented" role="tablist">
        {displayOptions.map((item) => <button key={item.code} className={assetType === item.code ? "active" : ""} onClick={() => setAssetType(item.code)}>{item.label}</button>)}
      </div>
      <div className="boundary-strip">
        <ShieldCheck size={18} />
        <div><strong>本域数据边界生效</strong><span>业务数据库不保存原始明细；交易中心、监管方与 Agent 只能读取摘要和密文引用。</span></div>
        <StatusTag value="ACTIVE" label="策略已启用" />
      </div>
      {notice && <Notice tone={notice.includes("失败") || notice.includes("无权") ? "warning" : "success"}>{notice}</Notice>}
      <Surface title={`${assetNames[assetType]}数据资产`} note={`共 ${data.length} 条可授权数据引用`}>
        <DataTable
          keyField="upload_id"
          rows={data}
          columns={[
            { key: "label", label: "数据资产" },
            { key: "owner_org_name", label: "数据提供方" },
            { key: "trade_batch_no", label: "交易批次" },
            { key: "data_ref", label: "域内引用", render: (row) => <CodeValue title={row.data_ref}>{shortHash(row.data_ref, 14)}</CodeValue> },
            { key: "data_hash", label: "数据哈希", render: (row) => <CodeValue title={row.data_hash}>{shortHash(row.data_hash)}</CodeValue> },
            { key: "summary_json", label: "记录数", render: (row) => row.summary_json?.record_count ?? "-" },
            { key: "validation_status", label: "校验", render: (row) => <StatusTag value={row.validation_status} /> },
            { key: "created_at", label: "登记时间", render: (row) => formatDate(row.created_at) },
            { key: "action", label: "操作", render: (row) => canSign ? <Button icon={FileSignature} busy={busy === row.upload_id} onClick={() => sign(row.upload_id)}>签名</Button> : <span className="muted-text">仅可查看</span> },
          ]}
        />
      </Surface>
      {showForm && <UploadModal options={createOptions} defaultAssetType={assetType} onClose={() => setShowForm(false)} onCreated={async () => { setShowForm(false); setNotice("数据已写入主体本域保险库，平台仅接收 DataRef、哈希与承诺。"); await reload(); }} />}
    </>
  );
}

function UploadModal({ options, defaultAssetType, onClose, onCreated }: { options: AssetOption[]; defaultAssetType: string; onClose: () => void; onCreated: () => Promise<void> }) {
  const [assetType, setAssetType] = useState(defaultAssetType);
  const [label, setLabel] = useState(`2026年7月${assetNames[defaultAssetType]}`);
  const [batch, setBatch] = useState("TB-2026-07-DEMO");
  const [period, setPeriod] = useState("2026-07");
  const [energy, setEnergy] = useState("12680");
  const [accuracy, setAccuracy] = useState("92.6");
  const [capacity, setCapacity] = useState("18.6");
  const [storage, setStorage] = useState("42");
  const [responseMinutes, setResponseMinutes] = useState("5");
  const [residualLimit, setResidualLimit] = useState("90");
  const [congestionMargin, setCongestionMargin] = useState("14.2");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const isCurve = assetType === "USER_LOAD_CURVE";
  const isEnergy = ["GENERATION_DATA", "RETAIL_DATA"].includes(assetType);
  const numericReady = (value: string, maximum?: number) => value.trim() !== "" && Number.isFinite(Number(value)) && Number(value) >= 0 && (maximum === undefined || Number(value) <= maximum);
  const formReady = label.trim().length >= 2 && batch.trim().length >= 3 && period.trim().length > 0
    && (!isEnergy || numericReady(energy))
    && (assetType !== "RENEWABLE_FORECAST" || (numericReady(energy) && numericReady(accuracy, 100)))
    && (assetType !== "VPP_RESOURCE" || (numericReady(capacity) && numericReady(storage) && numericReady(responseMinutes)))
    && (assetType !== "GRID_CONSTRAINT" || (numericReady(residualLimit) && numericReady(congestionMargin, 100)));

  async function submit() {
    setBusy(true);
    setError("");
    try {
      let localPayload: JsonRecord;
      if (isCurve) localPayload = { period, record_count: 240, load_curve: sampleCurve, source: "MASKED_DEMO_METER_GROUP" };
      else if (assetType === "RENEWABLE_FORECAST") localPayload = { period, record_count: 31, forecast_energy_mwh: Number(energy), forecast_accuracy_pct: Number(accuracy), source: "DEMO_FORECAST_SERVICE" };
      else if (assetType === "VPP_RESOURCE") localPayload = { period, record_count: 1860, adjustable_capacity_mw: Number(capacity), storage_energy_mwh: Number(storage), response_minutes: Number(responseMinutes), source: "DEMO_VPP_GATEWAY" };
      else if (assetType === "GRID_CONSTRAINT") localPayload = { period, record_count: 24, n_minus_one_passed: true, max_residual_imbalance_mwh: Number(residualLimit), congestion_margin_pct: Number(congestionMargin), source: "DEMO_DISPATCH_GATEWAY" };
      else localPayload = { period, record_count: 31, energy_mwh: Number(energy), source: "DEMO_METER_GATEWAY" };
      await post("/data/uploads", {
        asset_type: assetType,
        trade_batch_no: batch,
        label,
        schema_version: "v1.0",
        local_payload: localPayload,
      });
      await onCreated();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登记失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="登记域内数据资产" onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button icon={Upload} variant="primary" busy={busy} disabled={!formReady} onClick={submit}>写入本域并登记引用</Button></>}>
      <div className="form-grid two">
        {options.length > 1 && <Field label="资产类型"><select value={assetType} onChange={(event) => { setAssetType(event.target.value); setLabel(`2026年7月${assetNames[event.target.value]}`); }}>{options.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></Field>}
        <Field label="资产名称"><input value={label} onChange={(event) => setLabel(event.target.value)} /></Field>
        <Field label="交易批次"><input value={batch} onChange={(event) => setBatch(event.target.value)} /></Field>
        <Field label="数据期间"><input value={period} onChange={(event) => setPeriod(event.target.value)} /></Field>
        {isEnergy && <Field label="电量（MWh）"><input type="number" value={energy} onChange={(event) => setEnergy(event.target.value)} /></Field>}
        {assetType === "RENEWABLE_FORECAST" && <><Field label="预测电量（MWh）"><input type="number" value={energy} onChange={(event) => setEnergy(event.target.value)} /></Field><Field label="预测准确率（%）"><input type="number" value={accuracy} onChange={(event) => setAccuracy(event.target.value)} /></Field></>}
        {assetType === "VPP_RESOURCE" && <><Field label="可调容量（MW）"><input type="number" value={capacity} onChange={(event) => setCapacity(event.target.value)} /></Field><Field label="储能电量（MWh）"><input type="number" value={storage} onChange={(event) => setStorage(event.target.value)} /></Field><Field label="响应时间（分钟）"><input type="number" value={responseMinutes} onChange={(event) => setResponseMinutes(event.target.value)} /></Field></>}
        {assetType === "GRID_CONSTRAINT" && <><Field label="剩余偏差上限（MWh）"><input type="number" value={residualLimit} onChange={(event) => setResidualLimit(event.target.value)} /></Field><Field label="拥塞裕度（%）"><input type="number" value={congestionMargin} onChange={(event) => setCongestionMargin(event.target.value)} /></Field></>}
      </div>
      <Notice>{isCurve ? "24点负荷曲线将写入主体本域，后续仅通过隐私计算返回聚合特征。" : `${assetNames[assetType]}原文不会进入平台业务数据库，登记后自动生成 DataRef、DataHash 和数据承诺。`}</Notice>
      {error && <Notice tone="warning">{error}</Notice>}
    </Modal>
  );
}
