import { useState } from "react";
import { useRemote } from "../../../hooks";
import { createIdempotencyKey } from "../../../api";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { RemoteState } from "../components/ui-primitives";
import { loadPrototypeAudit, restorePrototypeAudit, tamperPrototypeAudit, verifyPrototypeAudit } from "../trusted-space-api";

function AuditItem({ children, accent = "" }: { children: React.ReactNode; accent?: string }) {
  return <div className={`prototype-audit-item ${accent}`}>{children}</div>;
}

export function AuditCenterPage() {
  const remote = useRemote(() => loadPrototypeAudit(20), []);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("哈希链：未校验");
  const [error, setError] = useState("");
  const data = remote.data;

  async function run(action: "tamper" | "restore" | "verify" | "refresh") {
    if (busy) return;
    setBusy(true); setError("");
    try {
      if (action === "tamper") { const result = await tamperPrototypeAudit({ idempotencyKey: createIdempotencyKey("prototype-chain-tamper") }); setStatus(result.message); }
      if (action === "restore") { const result = await restorePrototypeAudit({ idempotencyKey: createIdempotencyKey("prototype-chain-restore") }); setStatus(result.message); }
      if (action === "verify") { const result = await verifyPrototypeAudit({ idempotencyKey: createIdempotencyKey("prototype-chain-verify") }); setStatus(`哈希链：${result.message}`); }
      await remote.reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "审计操作失败"); } finally { setBusy(false); }
  }

  return <PrototypePageFrame className="prototype-audit-page">
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    <section className="prototype-card prototype-audit-card">
      <div className="prototype-card-heading"><PrototypeCardTitle>审计与存证中心</PrototypeCardTitle><div className="prototype-audit-actions"><button type="button" disabled={busy} onClick={() => void run("tamper")}>⚠ 模拟篡改</button><button type="button" disabled={busy} onClick={() => void run("restore")}>恢复</button><button type="button" disabled={busy} onClick={() => void run("verify")}>验证链</button><button type="button" disabled={busy} onClick={() => void run("refresh")}>刷新</button></div></div>
      {error && <div className="prototype-error" role="alert">{error}</div>}
      {data && <>
        <div className="prototype-audit-stats"><div><b>{data.metrics.total}</b><span>调用总数</span></div><div><b>{data.metrics.denied}</b><span>拒绝次数</span></div><div><b>{data.metrics.controlled}</b><span>受控提供</span></div><div><b>{data.metrics.blocks}</b><span>存证区块</span></div></div>
        <div className={`prototype-chain-status ${data.chain.ok ? "is-ok" : "is-failed"}`}>{status === "哈希链：未校验" ? `哈希链：${data.chain.message}` : status}</div>
        <div className="prototype-audit-columns"><div><h4>审计流水</h4>{data.records.length ? data.records.map((item) => <AuditItem key={item.id}><span className={`prototype-audit-action is-${item.action}`}>{item.action_name}</span> · {item.subject} · {item.resource}<small>{item.ts} · 追踪编号 {item.trace_id}</small></AuditItem>) : <div className="prototype-empty">暂无审计记录</div>}</div><div><h4>存证区块（哈希链）</h4>{data.blocks.length ? data.blocks.map((item) => <AuditItem key={item.id} accent="is-chain">区块 #{item.height} · 存证 {item.id}<small>哈希 {item.hash.slice(0, 16)}… · 交易 {item.tx_hash.slice(0, 16)}…<br />{item.created_at}</small></AuditItem>) : <div className="prototype-empty">暂无存证区块</div>}</div></div>
      </>}
    </section>
  </PrototypePageFrame>;
}
