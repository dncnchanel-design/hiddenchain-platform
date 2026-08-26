import { useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronRight, RefreshCw, RotateCcw, Search, ShieldCheck, X } from "lucide-react";
import { useRemote } from "../../../hooks";
import { createIdempotencyKey } from "../../../api";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { RemoteState, Sheet } from "../components/ui-primitives";
import { loadPrototypeAudit, restorePrototypeAudit, tamperPrototypeAudit, verifyPrototypeAudit, type PrototypeTamperEvent } from "../trusted-space-api";

function AuditItem({ children, accent = "", onClick, ariaLabel }: { children: React.ReactNode; accent?: string; onClick?: () => void; ariaLabel?: string }) {
  const className = ["prototype-audit-item", accent, onClick ? "is-interactive" : ""].filter(Boolean).join(" ");
  if (onClick) {
    return <button type="button" className={className} onClick={onClick} aria-label={ariaLabel}>{children}</button>;
  }
  return <div className={className}>{children}</div>;
}

function valueOrFallback(value: string | number | null | undefined) {
  return value === null || value === undefined || value === "" ? "未登记" : String(value);
}

export function AuditCenterPage() {
  const remote = useRemote(() => loadPrototypeAudit(20), []);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("哈希链：未校验");
  const [error, setError] = useState("");
  const [selectedTamper, setSelectedTamper] = useState<PrototypeTamperEvent | null>(null);
  const data = remote.data;
  const tamperEvent = data?.tamper ?? null;
  const activeTamper = Boolean(tamperEvent?.active);

  async function run(action: "tamper" | "restore" | "verify" | "refresh") {
    if (busy) return;
    setBusy(true);
    setError("");
    setSelectedTamper(null);
    try {
      if (action === "tamper") {
        const result = await tamperPrototypeAudit({ idempotencyKey: createIdempotencyKey("prototype-chain-tamper") });
        setStatus(result.message);
      } else if (action === "restore") {
        const result = await restorePrototypeAudit({ idempotencyKey: createIdempotencyKey("prototype-chain-restore") });
        setStatus(result.message);
      } else if (action === "verify") {
        const result = await verifyPrototypeAudit({ idempotencyKey: createIdempotencyKey("prototype-chain-verify") });
        setStatus("哈希链：" + result.message);
      }
      await remote.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审计操作失败");
    } finally {
      setBusy(false);
    }
  }

  const statusText = data && status === "哈希链：未校验" ? "哈希链：" + data.chain.message : status;
  const statusTitle = data?.chain.ok ? "哈希链校验通过" : activeTamper ? "检测到模拟篡改" : "哈希链校验未通过";
  const affectedBlockId = tamperEvent?.block?.id;

  return <PrototypePageFrame className="prototype-audit-page">
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    <section className="prototype-card prototype-audit-card">
      <div className="prototype-card-heading">
        <PrototypeCardTitle>审计与存证中心</PrototypeCardTitle>
        <div className="prototype-audit-actions">
          <button type="button" disabled={busy} onClick={() => void run("tamper")}><AlertTriangle size={13} />模拟篡改</button>
          <button type="button" disabled={busy} onClick={() => void run("restore")}><RotateCcw size={13} />恢复</button>
          <button type="button" disabled={busy} onClick={() => void run("verify")}><ShieldCheck size={13} />验证链</button>
          <button type="button" disabled={busy} onClick={() => void run("refresh")}><RefreshCw size={13} />刷新</button>
        </div>
      </div>
      {error && <div className="prototype-error" role="alert">{error}</div>}
      {data && <>
        <div className="prototype-audit-stats">
          <div className="prototype-audit-stat"><b>{data.metrics.total}</b><span>调用总数</span></div>
          <div className="prototype-audit-stat"><b>{data.metrics.denied}</b><span>拒绝次数</span></div>
          <div className="prototype-audit-stat"><b>{data.metrics.controlled}</b><span>受控提供</span></div>
          <div className={"prototype-audit-stat " + (activeTamper ? "is-tampered" : "")}><b>{data.metrics.blocks}</b><span>存证区块</span>{activeTamper && <small>发现异常标记</small>}</div>
        </div>
        <div className={"prototype-chain-status " + (data.chain.ok ? "is-ok" : "is-failed")} role={data.chain.ok ? "status" : "alert"} aria-live="polite">
          <span className="prototype-chain-status-icon" aria-hidden="true">{data.chain.ok ? <CheckCircle2 size={19} /> : <AlertTriangle size={19} />}</span>
          <div className="prototype-chain-status-copy">
            <strong>{statusTitle}</strong>
            <span>{statusText}</span>
            {activeTamper && <small>已定位受影响存证区块，可查询操作主体与追踪信息。</small>}
          </div>
          {tamperEvent && <button type="button" className="prototype-chain-status-action" onClick={() => setSelectedTamper(tamperEvent)}><Search size={14} />{activeTamper ? "查看篡改区块信息" : "查看最近篡改记录"}<ChevronRight size={14} /></button>}
        </div>
        <div className="prototype-audit-columns">
          <div>
            <h4>审计流水</h4>
            {data.records.length ? data.records.map((item) => <AuditItem key={item.id}>
              <span className={"prototype-audit-action is-" + item.action}>{item.action_name}</span> · {item.subject} · {item.resource}
              <small>{item.ts} · 追踪编号 {item.trace_id}</small>
            </AuditItem>) : <div className="prototype-empty">暂无审计记录</div>}
          </div>
          <div>
            <h4>存证区块（哈希链）</h4>
            {data.blocks.length ? data.blocks.map((item) => {
              const isTamperBlock = item.id === affectedBlockId;
              const blockAccent = ["is-chain", isTamperBlock && activeTamper ? "is-tampered" : "", isTamperBlock && !activeTamper ? "is-tamper-history" : ""].filter(Boolean).join(" ");
              return <AuditItem
                key={item.id}
                accent={blockAccent}
                onClick={isTamperBlock && tamperEvent ? () => setSelectedTamper(tamperEvent) : undefined}
                ariaLabel={isTamperBlock ? "查看篡改区块信息" : undefined}
              >
                <span className="prototype-audit-item-heading">
                  <span>区块 #{item.height} · 存证 {item.id}</span>
                  {isTamperBlock && <span className={"prototype-audit-item-badge " + (activeTamper ? "is-danger" : "is-restored")}>{activeTamper ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}{activeTamper ? "已标记篡改" : "曾发生篡改"}</span>}
                </span>
                <small>哈希 {item.hash.slice(0, 16)}… · 交易 {item.tx_hash.slice(0, 16)}…<br />{item.created_at}</small>
                {isTamperBlock && <span className="prototype-audit-item-link"><Search size={13} />查看篡改区块信息<ChevronRight size={13} /></span>}
              </AuditItem>;
            }) : <div className="prototype-empty">暂无存证区块</div>}
          </div>
        </div>
      </>}
    </section>
    {selectedTamper && <Sheet
      open={Boolean(selectedTamper)}
      onOpenChange={(open) => { if (!open) setSelectedTamper(null); }}
      title="篡改区块信息"
      className="trusted-utility-sheet prototype-tamper-sheet"
    >
      <div className="prototype-tamper-sheet-toolbar">
        <button type="button" onClick={() => setSelectedTamper(null)}><X size={14} />关闭详情</button>
      </div>
      <div className={"prototype-tamper-detail " + (selectedTamper.active ? "is-active" : "is-restored")}>
        <div className="prototype-tamper-detail-state">
          <span aria-hidden="true">{selectedTamper.active ? <AlertTriangle size={20} /> : <CheckCircle2 size={20} />}</span>
          <div>
            <strong>{selectedTamper.active ? "发现模拟篡改标记" : "最近一次模拟篡改已恢复"}</strong>
            <small>{selectedTamper.active ? "当前验证状态未通过，建议核查该审计事件。" : "链状态已恢复，该事件仍保留在审计流水中。"}</small>
          </div>
        </div>
        <dl className="prototype-tamper-detail-grid">
          <div><dt>操作主体</dt><dd>{valueOrFallback(selectedTamper.actor_name)}</dd></div>
          <div><dt>主体账号</dt><dd><code>{valueOrFallback(selectedTamper.actor_user_id)}</code></dd></div>
          <div><dt>主体组织</dt><dd><code>{valueOrFallback(selectedTamper.actor_org_id)}</code></dd></div>
          <div><dt>操作时间</dt><dd>{selectedTamper.occurred_at}</dd></div>
          <div><dt>关联区块</dt><dd>{selectedTamper.block ? "#" + selectedTamper.block.height + " · " + selectedTamper.block.id : "未关联存证区块"}</dd></div>
          <div><dt>区块状态</dt><dd>{selectedTamper.block ? valueOrFallback(selectedTamper.block.status) : "未登记"}</dd></div>
          <div><dt>追踪编号</dt><dd><code>{valueOrFallback(selectedTamper.trace_id)}</code></dd></div>
          <div><dt>事件编号</dt><dd><code>{valueOrFallback(selectedTamper.event_id)}</code></dd></div>
        </dl>
        {selectedTamper.block && <div className="prototype-tamper-hashes">
          <div><span>存证哈希</span><code>{selectedTamper.block.hash}</code></div>
          <div><span>交易哈希</span><code>{selectedTamper.block.tx_hash}</code></div>
        </div>}
        <div className="prototype-tamper-boundary"><ShieldCheck size={15} /><span>{selectedTamper.note}</span></div>
      </div>
    </Sheet>}
  </PrototypePageFrame>;
}
