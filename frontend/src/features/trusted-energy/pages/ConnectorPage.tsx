import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../../api";
import { useRemote } from "../../../hooks";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { RemoteState } from "../components/ui-primitives";
import {
  issueConnectorUploadTicket,
  loadConnectorCatalog,
  loadConnectorReceipt,
  lookupConnectorReceipt,
  registerConnectorReceipt,
  uploadConnectorCsv,
  type ConnectorCatalogPayload,
  type ConnectorClassification,
  type ConnectorSignedReceipt,
  type ConnectorTicket,
} from "../trusted-space-api";

const PENDING_STORAGE_KEY = "hiddenchain_connector_pending_receipt_v1";
const CSV_TYPES = new Set(["text/csv", "application/csv", "application/vnd.ms-excel"]);

type PendingRegistration = {
  version: 1;
  saved_at: string;
  ticket: ConnectorTicket;
  ticket_id: string;
  upload_url: string;
  receipt_lookup_url: string;
  connector_id: string;
  organization_id: string;
  resource_id: string;
  resource_name: string;
  receipt: ConnectorSignedReceipt | null;
};

function isPendingRegistration(value: unknown): value is PendingRegistration {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const pending = value as Record<string, unknown>;
  const ticket = pending.ticket as Record<string, unknown> | undefined;
  const claims = ticket?.claims as Record<string, unknown> | undefined;
  const receiptIsMetadata = pending.receipt === null
    || (Boolean(pending.receipt) && typeof pending.receipt === "object" && !Array.isArray(pending.receipt));
  return pending.version === 1
    && typeof pending.saved_at === "string"
    && typeof pending.ticket_id === "string"
    && typeof pending.upload_url === "string"
    && typeof pending.receipt_lookup_url === "string"
    && typeof pending.connector_id === "string"
    && typeof pending.organization_id === "string"
    && typeof pending.resource_id === "string"
    && typeof pending.resource_name === "string"
    && receiptIsMetadata
    && typeof claims?.jti === "string"
    && claims.jti === pending.ticket_id;
}

function readPendingRegistration(): PendingRegistration | null {
  try {
    const value = sessionStorage.getItem(PENDING_STORAGE_KEY);
    if (!value) return null;
    const parsed: unknown = JSON.parse(value);
    return isPendingRegistration(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function persistPendingRegistration(value: PendingRegistration): boolean {
  try {
    sessionStorage.setItem(PENDING_STORAGE_KEY, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

function clearPendingRegistration() {
  try {
    sessionStorage.removeItem(PENDING_STORAGE_KEY);
  } catch {
    // The in-memory state is still cleared; session storage is best-effort recovery metadata.
  }
}

function matchesIssuedEndpoint(endpoint: string, candidate: string, suffix: string): boolean {
  try {
    const expected = new URL(`${endpoint.replace(/\/+$/, "")}${suffix}`);
    return expected.toString() === new URL(candidate).toString();
  } catch {
    return false;
  }
}

function pendingMatchesCatalog(pending: PendingRegistration, catalog: ConnectorCatalogPayload): boolean {
  return pending.connector_id === catalog.connector.connector_id
    && pending.organization_id === catalog.connector.organization_id
    && pending.ticket.claims.connector_id === catalog.connector.connector_id
    && pending.ticket.claims.organization_id === catalog.connector.organization_id
    && pending.ticket.claims.resource_id === pending.resource_id
    && catalog.resources.some((resource) => resource.resource_id === pending.resource_id)
    && (pending.receipt === null || receiptMatchesPending(pending.receipt, pending))
    && (pending.receipt !== null || matchesIssuedEndpoint(catalog.connector.endpoint, pending.receipt_lookup_url, "/ingest/receipts/lookup"));
}

function receiptMatchesPending(receipt: ConnectorSignedReceipt, pending: PendingRegistration): boolean {
  return receipt.ticket_id === pending.ticket_id
    && receipt.connector_id === pending.connector_id
    && receipt.organization_id === pending.organization_id
    && receipt.resource_id === pending.resource_id;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.ceil(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function csvCell(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function statusLabel(status: string): string {
  if (status === "REGISTERED") return "已登记";
  if (status === "NOT_REGISTERED") return "待接入";
  return "状态待确认";
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.message : fallback;
}

function isAmbiguousUploadFailure(reason: unknown): boolean {
  return reason instanceof ApiError && [
    "CONNECTOR_NETWORK_OR_CORS",
    "CONNECTOR_TIMEOUT",
    "CONNECTOR_TICKET_USED",
    "CONNECTOR_UNAVAILABLE",
    "CONNECTOR_INVALID_RESPONSE",
    "CONNECTOR_INVALID_RECEIPT",
    "CONNECTOR_RECEIPT_MISMATCH",
  ].includes(reason.code || "");
}

export function ConnectorPage() {
  const remote = useRemote(loadConnectorCatalog, []);
  const reloadCatalog = remote.reload;
  const fileRef = useRef<HTMLInputElement>(null);
  const [initialRecovery] = useState(() => {
    const value = readPendingRegistration();
    return { value, shouldAutoRecover: Boolean(value) };
  });
  const shouldAutoRecoverRef = useRef(initialRecovery.shouldAutoRecover);
  const autoRecoveryStartedRef = useRef(false);
  const [selectedResourceId, setSelectedResourceId] = useState("");
  const [classification, setClassification] = useState<ConnectorClassification>("L3");
  const [busy, setBusy] = useState<"upload" | "recover" | null>(null);
  const [pending, setPending] = useState<PendingRegistration | null>(initialRecovery.value);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const selectedResource = remote.data?.resources.find((item) => item.resource_id === selectedResourceId)
    || remote.data?.resources[0]
    || null;

  const completeRegistration = useCallback(async (candidate: PendingRegistration) => {
    let receipt = candidate.receipt;
    if (!receipt) {
      try {
        const central = await loadConnectorReceipt(candidate.ticket_id);
        if (central.receipt_id) {
          clearPendingRegistration();
          setPending(null);
          setError("");
          setMessage("签名回执已完成中央登记");
          await reloadCatalog();
          return;
        }
      } catch {
        // Continue with connector receipt recovery; central read outages are handled by registration below.
      }
      receipt = await lookupConnectorReceipt(candidate.receipt_lookup_url, candidate.ticket);
      if (!receiptMatchesPending(receipt, candidate)) {
        throw new ApiError("连接器返回的签名回执与当前票据不一致，已停止补登记", 422, undefined, { code: "CONNECTOR_RECEIPT_MISMATCH" });
      }
      const recovered = { ...candidate, receipt, saved_at: new Date().toISOString() };
      persistPendingRegistration(recovered);
      setPending(recovered);
    }
    try {
      await registerConnectorReceipt(receipt);
    } catch {
      setError("");
      setMessage("本地上传成功，待补登记");
      return;
    }
    clearPendingRegistration();
    setPending(null);
    setError("");
    setMessage("本地上传与签名回执登记均已完成");
    await reloadCatalog();
  }, [reloadCatalog]);

  const recover = useCallback(async () => {
    if (!pending || !remote.data || busy) return;
    if (!pendingMatchesCatalog(pending, remote.data)) {
      clearPendingRegistration();
      setPending(null);
      setMessage("");
      setError("待补登记记录不属于当前主体或连接器地址已变更，已停止自动恢复");
      return;
    }
    setBusy("recover");
    setError("");
    setMessage(pending.receipt ? "正在补登记签名回执…" : "正在恢复签名回执并补登记…");
    try {
      await completeRegistration(pending);
    } catch (reason) {
      setMessage(pending.receipt ? "本地上传成功，待补登记" : "上传结果仍待确认，请勿重复上传");
      setError(errorMessage(reason, "签名回执恢复失败，请稍后重试"));
    } finally {
      setBusy(null);
    }
  }, [busy, completeRegistration, pending, remote.data]);

  useEffect(() => {
    if (!shouldAutoRecoverRef.current || autoRecoveryStartedRef.current || !remote.data || !pending) return;
    autoRecoveryStartedRef.current = true;
    void recover();
  }, [pending, recover, remote.data]);

  async function upload() {
    const catalog = remote.data;
    const resource = selectedResource;
    const file = fileRef.current?.files?.[0];
    if (!catalog || !resource) { setError("当前主体没有可接入的规范资源，请刷新目录"); return; }
    if (pending) { setError("存在待确认的上传记录，请先恢复回执或完成补登记"); return; }
    if (!file) { setError("请选择 CSV 文件"); return; }
    const lowerName = file.name.toLowerCase();
    if (!lowerName.endsWith(".csv") || (file.type && !CSV_TYPES.has(file.type.toLowerCase()))) {
      setError("请选择扩展名和文件类型均为 CSV 的文件");
      return;
    }
    if (file.size > catalog.upload_contract.max_bytes) {
      setError(`CSV 文件不能超过 ${formatBytes(catalog.upload_contract.max_bytes)}`);
      return;
    }
    if (catalog.connector.status !== "ACTIVE") {
      setError("企业连接器当前离线，请联系本主体管理员");
      return;
    }

    setBusy("upload");
    setError("");
    setMessage("正在获取一次性上传凭证…");
    let candidate: PendingRegistration | null = null;
    try {
      let ticketPayload;
      try {
        ticketPayload = await issueConnectorUploadTicket(resource.resource_id, classification);
      } catch {
        throw new ApiError("一次性上传凭证获取失败，请刷新目录后重试", 503, undefined, { code: "CONNECTOR_TICKET_ISSUE_FAILED" });
      }
      if (ticketPayload.ticket.claims.jti.length < 8
        || ticketPayload.ticket.claims.resource_id !== resource.resource_id
        || ticketPayload.ticket.claims.resource_name !== resource.resource_name
        || ticketPayload.ticket.claims.connector_id !== catalog.connector.connector_id
        || ticketPayload.ticket.claims.organization_id !== catalog.connector.organization_id
        || ticketPayload.ticket.claims.energy_domain !== catalog.connector.energy_domain
        || ticketPayload.connector.connector_id !== catalog.connector.connector_id
        || ticketPayload.connector.organization_id !== catalog.connector.organization_id
        || ticketPayload.connector.energy_domain !== catalog.connector.energy_domain
        || !matchesIssuedEndpoint(catalog.connector.endpoint, ticketPayload.upload_url, "/ingest")
        || !matchesIssuedEndpoint(catalog.connector.endpoint, ticketPayload.receipt_lookup_url, "/ingest/receipts/lookup")) {
        throw new ApiError("一次性上传凭证与当前目录不一致，请刷新后重试", 502, undefined, { code: "CONNECTOR_TICKET_MISMATCH" });
      }
      candidate = {
        version: 1,
        saved_at: new Date().toISOString(),
        ticket: ticketPayload.ticket,
        ticket_id: ticketPayload.ticket.claims.jti,
        upload_url: ticketPayload.upload_url,
        receipt_lookup_url: ticketPayload.receipt_lookup_url,
        connector_id: ticketPayload.connector.connector_id,
        organization_id: ticketPayload.connector.organization_id,
        resource_id: resource.resource_id,
        resource_name: resource.resource_name,
        receipt: null,
      };
      if (!persistPendingRegistration(candidate)) {
        throw new ApiError("浏览器无法保存回执恢复信息，本次未上传；请检查会话存储设置", 507, undefined, { code: "CONNECTOR_RECOVERY_STORAGE_FAILED" });
      }
      setPending(candidate);
      setMessage("正在将原始 CSV 直传企业连接器…");
      const receipt = await uploadConnectorCsv(candidate.upload_url, candidate.ticket, file);
      if (!receiptMatchesPending(receipt, candidate)) {
        throw new ApiError("连接器返回的签名回执与当前票据不一致，已停止中央登记", 422, undefined, { code: "CONNECTOR_RECEIPT_MISMATCH" });
      }
      candidate = { ...candidate, receipt, saved_at: new Date().toISOString() };
      persistPendingRegistration(candidate);
      setPending(candidate);
      setMessage("本地上传成功，正在登记签名回执…");
      await completeRegistration(candidate);
      if (fileRef.current) fileRef.current.value = "";
    } catch (reason) {
      if (candidate?.receipt) {
        setError("");
        setMessage("本地上传成功，待补登记");
      } else if (candidate && isAmbiguousUploadFailure(reason)) {
        setMessage("上传结果待确认，请使用“恢复回执并补登记”；请勿重复上传");
        setError(errorMessage(reason, "企业连接器暂时无法访问"));
      } else {
        clearPendingRegistration();
        setPending(null);
        setMessage("");
        setError(errorMessage(reason, "上传失败，请稍后重试"));
      }
    } finally {
      setBusy(null);
    }
  }

  function downloadSample() {
    if (!remote.data || !selectedResource) { setError("请先从目录选择资源"); return; }
    setError("");
    const today = new Date().toISOString().slice(0, 10);
    const csv = [
      "record_date,value,region,organization,unit",
      [today, "100", "示例区域", remote.data.connector.organization_name, selectedResource.unit].map(csvCell).join(","),
    ].join("\r\n");
    const url = URL.createObjectURL(new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${selectedResource.resource_id}-template.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const isBusy = busy !== null;

  return <PrototypePageFrame className="prototype-connector-page">
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    <RemoteState loading={false} error={remote.refreshError} onRetry={() => void remote.reload()} />
    {remote.data && <section className="prototype-card prototype-connector-form-card" aria-busy={isBusy}>
      <PrototypeCardTitle>企业连接器数据接入</PrototypeCardTitle>
      <p className="prototype-connector-intro"><b>原始 CSV 直达本企业连接器，中央只登记签名回执。</b> 当前主体为 {remote.data.connector.organization_name}，能源域为 {remote.data.connector.energy_domain}；平台不会代收文件内容。</p>
      <div className="prototype-connector-layout">
        <div>
          <div className="prototype-form-grid">
            <label><span>规范资源</span><select value={selectedResource?.resource_id || ""} disabled={isBusy || !remote.data.resources.length} onChange={(event) => setSelectedResourceId(event.target.value)}>{remote.data.resources.map((item) => <option key={item.resource_id} value={item.resource_id}>{item.resource_name}（{item.unit}）</option>)}</select></label>
            <label><span>数据分级</span><select value={classification} disabled={isBusy} onChange={(event) => setClassification(event.target.value as ConnectorClassification)}><option value="L3">L3 · 敏感</option><option value="L2">L2 · 内部</option><option value="L1">L1 · 公开</option></select></label>
            <label className="prototype-file-field"><span>CSV 文件（最大 {formatBytes(remote.data.upload_contract.max_bytes)}）</span><input ref={fileRef} type="file" accept=".csv,text/csv,application/csv" disabled={isBusy || Boolean(pending)} /></label>
          </div>
          {selectedResource && <p className="prototype-resource-intro">必需列：{selectedResource.required_columns.join("、")}；可选列：{selectedResource.optional_columns.join("、") || "无"}。最终格式与数据校验由企业连接器完成。</p>}
          <div className="prototype-form-actions">
            <button type="button" className="prototype-primary-button" disabled={isBusy || Boolean(pending) || !selectedResource} aria-label="将 CSV 直传企业连接器并登记签名回执" onClick={() => void upload()}>{busy === "upload" ? "上传处理中…" : "直传连接器并登记回执"}</button>
            {pending && <button type="button" className="prototype-secondary-button" disabled={isBusy} aria-label={pending.receipt ? "补登记签名回执" : "恢复签名回执并补登记"} onClick={() => void recover()}>{busy === "recover" ? "恢复处理中…" : pending.receipt ? "补登记" : "恢复回执并补登记"}</button>}
            {message && <span className="prototype-success-message" role="status" aria-live="polite">{message}</span>}
            {error && <span className="prototype-error-inline" role="alert">{error}</span>}
          </div>
        </div>
        <div className="prototype-connector-sample">
          <div className="prototype-sample-heading"><b>规范 CSV 示例</b><button type="button" className="prototype-secondary-button" disabled={isBusy || !selectedResource} aria-label="在浏览器本地生成并下载规范 CSV 示例" onClick={downloadSample}>↓ 下载示例 CSV</button></div>
          <pre>record_date,value,region,organization,unit{"\n"}2026-08-29,100,示例区域,{remote.data.connector.organization_name},{selectedResource?.unit || "单位"}</pre>
        </div>
      </div>
    </section>}
    {remote.data && <section className="prototype-card prototype-resource-list">
      <PrototypeCardTitle>本主体规范资源目录</PrototypeCardTitle>
      <p className="prototype-resource-intro">资源名称、计量单位和列要求均由当前主体连接器目录提供。</p>
      {remote.data.resources.length ? <div className="prototype-resource-table">{remote.data.resources.map((item) => <div key={item.resource_id}><span><strong>{item.resource_name}</strong><code>{item.resource_id}</code></span><span>{item.current_version ? `v${item.current_version}` : "暂无版本"} · {item.record_count ?? 0} 行 · {item.schema_version}</span><b className="prototype-resource-status">{statusLabel(item.status)}</b></div>)}</div> : <div className="prototype-empty">当前能源域暂无可接入资源</div>}
    </section>}
  </PrototypePageFrame>;
}
