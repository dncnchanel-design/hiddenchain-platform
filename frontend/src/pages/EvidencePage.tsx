import { useMemo, useState } from "react";
import { CheckCircle2, Eye, Fingerprint, RefreshCw, SearchCheck, XCircle } from "lucide-react";
import { api } from "../api";
import { Button, DataTable, DateTimeText, DetailDrawer, ErrorState, FilterBar, IdText, LoadingState, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { EVIDENCE_TYPE_LABELS, STAGE_LABELS, type JsonRecord } from "../types";

export function EvidencePage() {
  const [taskId, setTaskId] = useState("");
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [verifying, setVerifying] = useState("");
  const [verifyingAll, setVerifyingAll] = useState(false);
  const [message, setMessage] = useState("");
  const [checks, setChecks] = useState<Record<string, JsonRecord>>({});
  const loader = async (signal?: AbortSignal) => {
    const request = { signal, timeoutMs: 12000, cache: "no-store" as RequestCache };
    const [tasks, evidence] = await Promise.all([api<JsonRecord[]>("/settlement/tasks", request), api<JsonRecord[]>("/chain/evidence", request)]);
    return { tasks, evidence };
  };
  const { data, loading, refreshing, error, reload } = useRemote(loader, []);
  const filtered = useMemo(() => taskId ? data?.evidence.filter((item) => item.task_id === taskId) || [] : data?.evidence || [], [data, taskId]);

  async function verifyRecord(item: JsonRecord, showRowBusy = true) {
    if (showRowBusy) setVerifying(item.evidence_id);
    try {
      const result = await api<JsonRecord>(`/chain/evidence/${item.evidence_id}/verify`, { timeoutMs: 12000, cache: "no-store" });
      setChecks((current) => ({ ...current, [item.evidence_id]: result }));
      return result.matched === true;
    } catch {
      return null;
    } finally {
      if (showRowBusy) setVerifying("");
    }
  }

  async function verifyOne(item: JsonRecord) {
    setMessage("");
    const result = await verifyRecord(item);
    setMessage(result === null ? "证据核验失败，请重试。" : result ? "证据摘要核验一致。" : "证据摘要不一致，请立即复核。");
  }

  async function verifyAll() {
    setVerifyingAll(true);
    setMessage("");
    try {
      const results: Array<boolean | null> = [];
      for (let index = 0; index < filtered.length; index += 4) {
        results.push(...await Promise.all(filtered.slice(index, index + 4).map((item) => verifyRecord(item, false))));
      }
      const failed = results.filter((result) => result === null).length;
      const mismatched = results.filter((result) => result === false).length;
      setMessage(failed ? `已完成 ${filtered.length - failed} 项核验，${failed} 项请求失败。` : mismatched ? `已完成 ${filtered.length} 项核验，其中 ${mismatched} 项摘要不一致。` : `已完成 ${filtered.length} 项核验，摘要均一致。`);
    } finally {
      setVerifyingAll(false);
    }
  }

  if (loading) return <LoadingState label="正在加载审计凭证" variant="page" />;
  if (error || !data) return <ErrorState message={error || "证据加载失败"} retry={reload} />;

  const stageCounts = Object.fromEntries(Object.keys(STAGE_LABELS).map((stage) => [stage, filtered.filter((item) => item.stage === stage).length]));
  const warningMessage = message.includes("失败") || message.includes("不一致");

  return (
    <>
      <PageHeader title="审计凭证" description="按验证任务查看各阶段凭证，并核验证据摘要与链上记录是否一致。" actions={<><Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button><Button icon={SearchCheck} variant="primary" busy={verifyingAll} disabled={!filtered.length} onClick={verifyAll}>批量核验</Button></>} />
      <FilterBar>
        <label><span>验证任务</span><select value={taskId} onChange={(event) => setTaskId(event.target.value)}><option value="">全部任务</option>{data.tasks.map((item) => <option key={item.task_id} value={item.task_id}>{item.task_name || item.task_id}</option>)}</select></label>
      </FilterBar>
      <div className="evidence-stages">
        {Object.entries(STAGE_LABELS).map(([stage, label]) => <div key={stage}><span>{label}</span><strong>{stageCounts[stage]} 项</strong></div>)}
      </div>
      {message && <Notice tone={warningMessage ? "warning" : "success"}>{message}</Notice>}
      <Surface title="审计凭证清单" meta={`${filtered.length} 项`}>
        <DataTable
          keyField="evidence_id" rows={filtered} label="审计凭证清单"
          columns={[
            { key: "block_height", label: "凭证序号", render: (row) => row.block_height === undefined ? "—" : `#${row.block_height}` },
            { key: "stage", label: "阶段", minWidth: 110, render: (row) => <StatusTag value={row.stage} label={STAGE_LABELS[row.stage] || row.stage} /> },
            { key: "biz_type", label: "证据类型", minWidth: 130, render: (row) => EVIDENCE_TYPE_LABELS[row.biz_type] || row.biz_type || "—" },
            { key: "task_id", label: "关联任务", minWidth: 150, render: (row) => <IdText value={row.task_id} /> },
            { key: "evidence_hash", label: "证据摘要", minWidth: 150, render: (row) => <IdText value={row.evidence_hash} /> },
            { key: "tx_hash", label: "交易摘要", minWidth: 150, render: (row) => <IdText value={row.tx_hash} /> },
            { key: "created_at", label: "生成时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
            { key: "verify", label: "核验结果", sortable: false, render: (row) => checks[row.evidence_id] ? checks[row.evidence_id].matched ? <span className="verify-ok"><CheckCircle2 size={16} />一致</span> : <span className="verify-bad"><XCircle size={16} />不一致</span> : <Button icon={Fingerprint} busy={verifying === row.evidence_id} disabled={verifyingAll} onClick={() => verifyOne(row)}>核验</Button> },
            { key: "view", label: "操作", sortable: false, hideable: false, sticky: "right", render: (row) => <Button icon={Eye} onClick={() => setSelected(row)}>详情</Button> },
          ]}
        />
      </Surface>

      {selected && <DetailDrawer title="审计凭证详情" onClose={() => setSelected(null)} footer={<Button onClick={() => setSelected(null)}>关闭</Button>}>
        <div className="detail-grid">
          <div><span>凭证编号</span><IdText value={selected.evidence_id} /></div>
          <div><span>关联任务</span><IdText value={selected.task_id} /></div>
          <div><span>凭证序号</span><strong>{selected.block_height === undefined ? "—" : `#${selected.block_height}`}</strong></div>
          <div><span>证据阶段</span><StatusTag value={selected.stage} label={STAGE_LABELS[selected.stage] || selected.stage} /></div>
          <div><span>证据类型</span><strong>{EVIDENCE_TYPE_LABELS[selected.biz_type] || selected.biz_type || "—"}</strong></div>
          <div><span>状态</span><StatusTag value={selected.status} /></div>
          <div><span>证据摘要</span><IdText value={selected.evidence_hash} /></div>
          <div><span>交易摘要</span><IdText value={selected.tx_hash} /></div>
          <div><span>生成时间</span><DateTimeText value={selected.created_at} /></div>
        </div>
        {selected.payload_json && <details className="secondary-details"><summary>查看技术载荷</summary><pre className="json-view">{JSON.stringify(selected.payload_json, null, 2)}</pre></details>}
      </DetailDrawer>}
    </>
  );
}
