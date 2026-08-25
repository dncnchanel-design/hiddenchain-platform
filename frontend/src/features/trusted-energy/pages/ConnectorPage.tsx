import { useRef, useState } from "react";
import { useRemote } from "../../../hooks";
import { createIdempotencyKey } from "../../../api";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { RemoteState } from "../components/ui-primitives";
import { downloadPrototypeSample, loadPrototypeConnector, uploadPrototypeResource } from "../trusted-space-api";

export function ConnectorPage() {
  const remote = useRemote(loadPrototypeConnector, []);
  const fileRef = useRef<HTMLInputElement>(null);
  const [connector, setConnector] = useState("coal");
  const [level, setLevel] = useState("L3-敏感");
  const [resourceId, setResourceId] = useState("coal_inventory");
  const [resourceName, setResourceName] = useState("电煤库存日报");
  const [timeColumn, setTimeColumn] = useState("day");
  const [numericFields, setNumericFields] = useState("inventory_kt, supply_kt, consumption_kt");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function register() {
    const file = fileRef.current?.files?.[0];
    if (!file) { setError("请选择 CSV 文件"); return; }
    setBusy(true);
    setError("");
    setMessage("");
    const form = new FormData();
    form.append("connector_name", connector === "coal" ? "煤炭连接器" : "电力连接器");
    form.append("resource_id", resourceId.trim());
    form.append("name", resourceName.trim());
    form.append("level", level);
    form.append("time_column", timeColumn.trim());
    form.append("numeric_fields", numericFields);
    form.append("file", file);
    try {
      const result = await uploadPrototypeResource(connector, form, { idempotencyKey: createIdempotencyKey("prototype-resource-upload") });
      setMessage(`${result.status} · ${result.resource.name} · ${result.resource.rows} 行`);
      await remote.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "资源注册失败");
    } finally {
      setBusy(false);
    }
  }

  async function downloadSample() {
    setError("");
    try {
      const result = await downloadPrototypeSample();
      const url = URL.createObjectURL(result.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = result.filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "示例文件下载失败");
    }
  }

  return <PrototypePageFrame className="prototype-connector-page">
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    <section className="prototype-card prototype-connector-form-card">
      <PrototypeCardTitle>数据接入（数据提供方上传自有数据）</PrototypeCardTitle>
      <p className="prototype-connector-intro">上传 CSV → 连接器域入库 → 目录出现（默认拒绝）→ 策略中心配置规则 → 受控访问。<b>仅电力企业 / 煤炭企业身份可上传至对应连接器。</b></p>
      <div className="prototype-flow-steps"><span>① 上传 CSV</span><i>→</i><span>② 默认拒绝</span><i>→</i><span>③ 配置策略</span><i>→</i><span>④ 使用方查询</span><i>→</i><span>⑤ 自动裁决</span></div>
      <div className="prototype-connector-layout">
        <div>
          <div className="prototype-form-grid">
            <label><span>目标连接器</span><select value={connector} onChange={(event) => setConnector(event.target.value)}>{(remote.data?.connectors || [{ id: "coal", name: "煤炭连接器", available: true }, { id: "power", name: "电力连接器", available: true }]).map((item) => <option key={item.id} value={item.id} disabled={!item.available}>{item.name}</option>)}</select></label>
            <label><span>数据分级</span><select value={level} onChange={(event) => setLevel(event.target.value)}><option value="L3-敏感">L3-敏感</option><option value="L2-内部">L2-内部</option><option value="L1-公开">L1-公开</option></select></label>
            <label><span>资源 ID（小写字母/下划线，如 coal_inventory）</span><input value={resourceId} onChange={(event) => setResourceId(event.target.value)} placeholder="coal_inventory" /></label>
            <label><span>资源名称</span><input value={resourceName} onChange={(event) => setResourceName(event.target.value)} placeholder="电煤库存日报" /></label>
            <label><span>时间列名（CSV 表头中的一列）</span><input value={timeColumn} onChange={(event) => setTimeColumn(event.target.value)} placeholder="day 或 ts" /></label>
            <label><span>数值列名（逗号分隔）</span><input value={numericFields} onChange={(event) => setNumericFields(event.target.value)} placeholder="inventory_kt, supply_kt" /></label>
            <label className="prototype-file-field"><span>CSV 文件（UTF-8）</span><input ref={fileRef} type="file" accept=".csv,text/csv" /></label>
          </div>
          <div className="prototype-form-actions"><button type="button" className="prototype-primary-button" disabled={busy} onClick={() => void register()}>{busy ? "注册中…" : "上传并注册（默认拒绝）"}</button>{message && <span className="prototype-success-message">{message}</span>}{error && <span className="prototype-error-inline">{error}</span>}</div>
        </div>
        <div className="prototype-connector-sample">
          <div className="prototype-sample-heading"><b>CSV 样例（可直接下载填写）</b><button type="button" className="prototype-secondary-button" onClick={() => void downloadSample()}>↓ 下载示例 CSV</button></div>
          <pre>day,inventory_kt,supply_kt,consumption_kt{"\n"}2026-06-01,6100.0,108.5,110.2{"\n"}2026-06-02,6098.3,107.9,109.8{"\n"}2026-06-03,6096.4,109.1,111.0</pre>
        </div>
      </div>
    </section>
    <section className="prototype-card prototype-resource-list"><PrototypeCardTitle>我的资源（已上传）</PrototypeCardTitle><p className="prototype-resource-intro">下方为您上传的资源及当前访问状态。如需开放给他人使用，请到策略中心添加规则。</p>{remote.data?.resources.length ? <div className="prototype-resource-table">{remote.data.resources.map((item) => <div key={`${item.id}-${item.version}`}><span><strong>{item.name}</strong><code>{item.id}</code></span><span>{item.level} · {item.rows} 行</span><b className="prototype-resource-status">默认拒绝</b></div>)}</div> : <div className="prototype-empty">暂无已上传资源</div>}</section>
  </PrototypePageFrame>;
}
