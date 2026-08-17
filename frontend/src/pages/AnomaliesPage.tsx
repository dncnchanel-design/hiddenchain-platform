import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Eye, RefreshCw } from "lucide-react";
import { api, post } from "../api";
import { useAuth } from "../auth";
import { Button, ConfirmDialog, DataTable, DateTimeText, DetailDrawer, ErrorState, Field, FilterBar, IdText, LoadingState, Metric, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

const eventLabels: Record<string, string> = {
  HASH_MISMATCH: "证据摘要不一致",
  UNAUTHORIZED_ACCESS: "越权访问拦截",
  MISSING_SIGNATURE: "多方签名缺失",
  POLICY_DENIED: "用途策略拒绝",
};

export function AnomaliesPage() {
  const { session } = useAuth();
  const [statusFilter, setStatusFilter] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [resolveTarget, setResolveTarget] = useState<JsonRecord | null>(null);
  const [resolution, setResolution] = useState("");
  const [confirmResolve, setConfirmResolve] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const { data, loading, refreshing, error, reload } = useRemote<JsonRecord[]>(
    (signal) => api("/anomalies", { signal, timeoutMs: 12000, cache: "no-store" }), [],
  );
  const canResolve = ["REGULATOR", "ADMIN"].includes(session!.user.role_code);
  const rows = useMemo(() => (data || []).filter((item) => (!statusFilter || item.status === statusFilter) && (!riskFilter || item.risk_level === riskFilter)), [data, riskFilter, statusFilter]);

  async function resolve() {
    if (!resolveTarget || resolution.trim().length < 2) return;
    setBusy(resolveTarget.event_id);
    setMessage("");
    try {
      await post(`/anomalies/${resolveTarget.event_id}/resolve`, { resolution: resolution.trim() });
      setMessage("风险事件已处置并记录处置意见。");
      setResolveTarget(null);
      setResolution("");
      await reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "处置失败");
    } finally {
      setBusy("");
    }
  }

  if (loading) return <LoadingState label="正在加载风险事件" variant="page" />;
  if (error || !data) return <ErrorState message={error || "风险事件加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader title="风险处置" description="查看检测到的风险事件、关联证据及处置状态。" actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>} />
      <div className="metrics-grid three">
        <Metric label="待处置事件" value={data.filter((item) => item.status === "OPEN").length} tone="red" />
        <Metric label="待处置高风险" value={data.filter((item) => item.risk_level === "HIGH" && item.status === "OPEN").length} tone="amber" />
        <Metric label="已闭环" value={data.filter((item) => item.status === "RESOLVED").length} tone="green" />
      </div>
      <FilterBar>
        <label><span>处置状态</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="">全部状态</option><option value="OPEN">待处置</option><option value="RESOLVED">已处理</option></select></label>
        <label><span>风险等级</span><select value={riskFilter} onChange={(event) => setRiskFilter(event.target.value)}><option value="">全部等级</option><option value="HIGH">高风险</option><option value="MEDIUM">中风险</option><option value="LOW">低风险</option></select></label>
      </FilterBar>
      {message && <Notice tone={message.includes("失败") ? "warning" : "success"}>{message}</Notice>}
      <Surface title="风险事件清单" meta={`${rows.length} 项`}>
        <DataTable
          keyField="event_id" rows={rows} label="风险事件清单"
          columns={[
            { key: "title", label: "事件", minWidth: 220, render: (row) => <button className="table-link risk-title" type="button" onClick={() => setSelected(row)}><AlertTriangle size={16} />{row.title || "—"}</button> },
            { key: "task_id", label: "关联任务", minWidth: 150, render: (row) => <IdText value={row.task_id} /> },
            { key: "event_type", label: "检测规则", minWidth: 150, render: (row) => eventLabels[row.event_type] || row.event_type || "—" },
            { key: "risk_level", label: "风险等级", render: (row) => <StatusTag value={row.risk_level} /> },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "created_at", label: "发现时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
            { key: "action", label: "操作", sortable: false, hideable: false, sticky: "right", render: (row) => <div className="inline-actions"><Button icon={Eye} onClick={() => setSelected(row)}>详情</Button>{row.status === "OPEN" && canResolve && <Button icon={CheckCircle2} busy={busy === row.event_id} onClick={() => { setResolveTarget(row); setResolution(""); }}>处置</Button>}</div> },
          ]}
        />
      </Surface>

      {selected && <DetailDrawer title="风险事件详情" onClose={() => setSelected(null)} footer={<Button onClick={() => setSelected(null)}>关闭</Button>}>
        <div className="detail-grid"><div><span>事件编号</span><IdText value={selected.event_id} /></div><div><span>关联任务</span><IdText value={selected.task_id} /></div><div><span>检测规则</span><strong>{eventLabels[selected.event_type] || selected.event_type || "—"}</strong></div><div><span>风险等级</span><StatusTag value={selected.risk_level} /></div><div><span>处置状态</span><StatusTag value={selected.status} /></div><div><span>发现时间</span><DateTimeText value={selected.created_at} /></div></div>
        <div className="detail-section"><h3>事件说明</h3><p>{selected.description || "—"}</p></div>
        {selected.resolution && <div className="detail-section"><h3>处置意见</h3><p>{selected.resolution}</p></div>}
        {selected.evidence_json && <details className="secondary-details"><summary>查看关联证据</summary><pre className="json-view">{JSON.stringify(selected.evidence_json, null, 2)}</pre></details>}
      </DetailDrawer>}

      {resolveTarget && <Modal title="填写处置意见" onClose={() => setResolveTarget(null)} footer={<><Button onClick={() => setResolveTarget(null)}>取消</Button><Button variant="primary" disabled={resolution.trim().length < 2} onClick={() => setConfirmResolve(true)}>下一步</Button></>}>
        <div className="detail-grid"><div><span>事件</span><strong>{resolveTarget.title || "—"}</strong></div><div><span>当前状态</span><StatusTag value={resolveTarget.status} /></div></div>
        <Field label="处置意见" hint="说明核对结果、责任主体或后续措施"><textarea maxLength={500} value={resolution} onChange={(event) => setResolution(event.target.value)} /></Field>
      </Modal>}
      <ConfirmDialog
        open={confirmResolve} title="确认完成风险处置" objectName={resolveTarget?.title || resolveTarget?.event_id || "—"} currentState={resolveTarget?.status}
        consequence="确认后，该事件将标记为已处理，处置意见会写入事件记录并用于后续审计。"
        confirmLabel="确认处置" busy={Boolean(resolveTarget && busy === resolveTarget.event_id)} onCancel={() => setConfirmResolve(false)}
        onConfirm={async () => { await resolve(); setConfirmResolve(false); }}
      />
    </>
  );
}
