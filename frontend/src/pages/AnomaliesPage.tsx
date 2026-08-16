import { useState } from "react";
import { AlertTriangle, CheckCircle2, Plus, RefreshCw, ShieldAlert } from "lucide-react";
import { api, formatDate, post } from "../api";
import { useAuth } from "../auth";
import { Button, DataTable, ErrorState, Field, LoadingState, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

const eventLabels: Record<string, string> = { HASH_MISMATCH: "证据哈希不一致", UNAUTHORIZED_ACCESS: "越权访问拦截", MISSING_SIGNATURE: "多方签名缺失", POLICY_DENIED: "用途策略拒绝" };

export function AnomaliesPage() {
  const { session } = useAuth();
  const [showInject, setShowInject] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const loader = async () => {
    const [events, tasks] = await Promise.all([api<JsonRecord[]>("/anomalies"), api<JsonRecord[]>("/settlement/tasks")]);
    return { events, tasks };
  };
  const { data, loading, error, reload } = useRemote(loader, []);
  const canResolve = ["REGULATOR", "ADMIN"].includes(session!.user.role_code);

  async function resolve(eventId: string) {
    setBusy(eventId);
    try {
      await post(`/anomalies/${eventId}/resolve`, { resolution: "已完成证据复核与责任主体确认，事件关闭。" });
      setMessage("风险事件已处置。");
      await reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "处置失败");
    } finally {
      setBusy("");
    }
  }

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "异常事件加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader title="风险处置" actions={<><Button icon={RefreshCw} onClick={reload}>刷新</Button><Button icon={Plus} variant="primary" onClick={() => setShowInject(true)}>新增风险</Button></>} />
      <div className="metrics-grid three">
        <div className="metric metric-red"><span>开放事件</span><strong>{data.events.filter((item) => item.status === "OPEN").length}</strong></div>
        <div className="metric metric-amber"><span>高风险</span><strong>{data.events.filter((item) => item.risk_level === "HIGH" && item.status === "OPEN").length}</strong></div>
        <div className="metric metric-green"><span>已闭环</span><strong>{data.events.filter((item) => item.status === "RESOLVED").length}</strong></div>
      </div>
      {message && <Notice tone={message.includes("失败") ? "warning" : "success"}>{message}</Notice>}
      <Surface title="风险事件清单">
        <DataTable
          keyField="event_id"
          rows={data.events}
          columns={[
            { key: "title", label: "事件", render: (row) => <span className="risk-title"><AlertTriangle size={16} />{row.title}</span> },
            { key: "task_id", label: "关联任务", render: (row) => <span className="mono-text">{row.task_id}</span> },
            { key: "event_type", label: "检测规则", render: (row) => eventLabels[row.event_type] || row.event_type },
            { key: "risk_level", label: "风险", render: (row) => <StatusTag value={row.risk_level} /> },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "created_at", label: "发现时间", render: (row) => formatDate(row.created_at) },
            { key: "action", label: "操作", render: (row) => row.status === "OPEN" && canResolve ? <Button icon={CheckCircle2} busy={busy === row.event_id} onClick={() => resolve(row.event_id)}>确认处置</Button> : row.resolution || "-" },
          ]}
        />
      </Surface>
      {showInject && <InjectModal tasks={data.tasks} onClose={() => setShowInject(false)} onCreated={async () => { setShowInject(false); await reload(); }} />}
    </>
  );
}

function InjectModal({ tasks, onClose, onCreated }: { tasks: JsonRecord[]; onClose: () => void; onCreated: () => Promise<void> }) {
  const [taskId, setTaskId] = useState(tasks[0]?.task_id || "");
  const [eventType, setEventType] = useState("UNAUTHORIZED_ACCESS");
  const [mutate, setMutate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await post("/anomalies/inject", { task_id: taskId, event_type: eventType, mutate_evidence: mutate && eventType === "HASH_MISMATCH" });
      await onCreated();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "注入失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="新增风险事件" onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button icon={ShieldAlert} variant="danger" busy={busy} disabled={!taskId} onClick={submit}>提交</Button></>}>
      <div className="form-grid two">
        <Field label="关联任务"><select value={taskId} onChange={(event) => setTaskId(event.target.value)}>{tasks.map((item) => <option key={item.task_id} value={item.task_id}>{item.capsule_id} · {item.task_name}</option>)}</select></Field>
        <Field label="事件类型"><select value={eventType} onChange={(event) => { setEventType(event.target.value); setMutate(false); }}>{Object.entries(eventLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
      </div>
      {eventType === "HASH_MISMATCH" && <label className="check-row"><input type="checkbox" checked={mutate} onChange={(event) => setMutate(event.target.checked)} /><span>同时修改一项凭证内容，触发一致性复核</span></label>}
      <Notice tone="warning">提交后将新增风险事件。</Notice>
      {error && <Notice tone="warning">{error}</Notice>}
    </Modal>
  );
}
