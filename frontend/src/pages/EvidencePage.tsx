import { useMemo, useState } from "react";
import { CheckCircle2, Eye, Fingerprint, RefreshCw, SearchCheck, XCircle } from "lucide-react";
import { api, formatDate, shortHash } from "../api";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { EVIDENCE_TYPE_LABELS, STAGE_LABELS } from "../types";
import type { JsonRecord } from "../types";

const stageLabels = STAGE_LABELS;

export function EvidencePage() {
  const [taskId, setTaskId] = useState("");
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [verifying, setVerifying] = useState("");
  const [verifyingAll, setVerifyingAll] = useState(false);
  const [message, setMessage] = useState("");
  const [checks, setChecks] = useState<Record<string, JsonRecord>>({});
  const loader = async () => {
    const [tasks, evidence] = await Promise.all([api<JsonRecord[]>("/settlement/tasks"), api<JsonRecord[]>("/chain/evidence")]);
    return { tasks, evidence };
  };
  const { data, loading, error, reload } = useRemote(loader, []);
  const filtered = useMemo(() => taskId ? data?.evidence.filter((item) => item.task_id === taskId) || [] : data?.evidence || [], [data, taskId]);

  async function verify(item: JsonRecord) {
    setVerifying(item.evidence_id);
    setMessage("");
    try {
      const result = await api<JsonRecord>(`/chain/evidence/${item.evidence_id}/verify`);
      setChecks((current) => ({ ...current, [item.evidence_id]: result }));
      return result.matched === true;
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "证据核验失败");
      return null;
    } finally {
      setVerifying("");
    }
  }

  async function verifyAll() {
    setVerifyingAll(true);
    setMessage("");
    try {
      let mismatched = 0;
      let failed = 0;
      for (const item of filtered) {
        const result = await verify(item);
        if (result === null) failed += 1;
        else if (!result) mismatched += 1;
      }
      setMessage(failed ? `已完成 ${filtered.length - failed} 项核验，${failed} 项核验失败，请重试。` : mismatched ? `已完成 ${filtered.length} 项证据核验，其中 ${mismatched} 项哈希不一致，请立即复核。` : `已完成 ${filtered.length} 项证据核验，哈希结果一致。`);
    } finally {
      setVerifyingAll(false);
    }
  }

  if (loading) return <LoadingState label="正在加载审计凭证" />;
  if (error || !data) return <ErrorState message={error || "证据加载失败"} retry={reload} />;

  const stageCounts = Object.fromEntries(Object.keys(stageLabels).map((stage) => [stage, filtered.filter((item) => item.stage === stage).length]));

  return (
    <>
      <PageHeader title="审计凭证" actions={<><Button icon={RefreshCw} onClick={reload}>刷新</Button><Button icon={SearchCheck} variant="primary" busy={verifyingAll} disabled={!filtered.length || verifyingAll} onClick={verifyAll}>核验全部</Button></>} />
      <div className="filter-bar">
        <label><span>任务</span><select value={taskId} onChange={(event) => setTaskId(event.target.value)}><option value="">全部任务</option>{data.tasks.map((item) => <option key={item.task_id} value={item.task_id}>{item.task_name}</option>)}</select></label>
      </div>
      <div className="evidence-stages">
        {Object.entries(stageLabels).map(([stage, label]) => (
          <div key={stage}><span>{label}</span><strong>{stageCounts[stage]} 项</strong></div>
        ))}
      </div>
      {message && <Notice tone={message.includes("失败") || message.includes("无权") ? "warning" : "success"}>{message}</Notice>}
      <Surface title="审计凭证清单">
        <DataTable
          keyField="evidence_id"
          rows={filtered}
          columns={[
            { key: "block_height", label: "凭证序号", render: (row) => <span className="mono-text">#{row.block_height}</span> },
            { key: "stage", label: "阶段", render: (row) => <StatusTag value={row.stage} label={stageLabels[row.stage] || row.stage} /> },
            { key: "biz_type", label: "证据类型", render: (row) => EVIDENCE_TYPE_LABELS[row.biz_type] || row.biz_type },
            { key: "task_id", label: "关联任务", render: (row) => <span className="mono-text">{row.task_id}</span> },
            { key: "evidence_hash", label: "证据哈希", render: (row) => <CodeValue title={row.evidence_hash}>{shortHash(row.evidence_hash)}</CodeValue> },
            { key: "tx_hash", label: "凭证编号", render: (row) => <CodeValue title={row.tx_hash}>{shortHash(row.tx_hash)}</CodeValue> },
            { key: "created_at", label: "生成时间", render: (row) => formatDate(row.created_at) },
            { key: "verify", label: "核验", render: (row) => checks[row.evidence_id] ? checks[row.evidence_id].matched ? <span className="verify-ok"><CheckCircle2 size={16} />一致</span> : <span className="verify-bad"><XCircle size={16} />不一致</span> : <Button icon={Fingerprint} busy={verifying === row.evidence_id} disabled={verifyingAll} onClick={() => verify(row)}>核验</Button> },
            { key: "view", label: "详情", render: (row) => <button className="icon-button" title="查看证据" onClick={() => setSelected(row)}><Eye size={17} /></button> },
          ]}
        />
      </Surface>
      {selected && <Modal title="证据载荷摘要" onClose={() => setSelected(null)} footer={<Button onClick={() => setSelected(null)}>关闭</Button>}>
        <div className="detail-grid">
          <div><span>凭证编号</span><CodeValue>{selected.evidence_id}</CodeValue></div>
          <div><span>凭证序号</span><strong>#{selected.block_height}</strong></div>
          <div><span>状态</span><StatusTag value={selected.status} /></div>
        </div>
        <pre className="json-view">{JSON.stringify(selected.payload_json, null, 2)}</pre>
      </Modal>}
    </>
  );
}
