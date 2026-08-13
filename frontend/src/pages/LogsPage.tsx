import { useMemo, useState } from "react";
import { Download, Eye, FileClock, Filter, RefreshCw, Search } from "lucide-react";
import { api, formatDate, shortHash } from "../api";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Modal, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

export function LogsPage() {
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const { data, loading, error, reload } = useRemote<JsonRecord[]>(() => api("/audit/logs"), []);
  const actions = useMemo(() => Array.from(new Set((data || []).map((item) => item.action_code))).sort(), [data]);
  const rows = useMemo(() => (data || []).filter((item) => (!action || item.action_code === action) && (!search || JSON.stringify(item).toLowerCase().includes(search.toLowerCase()))), [data, action, search]);

  function exportLogs() {
    const blob = new Blob([JSON.stringify(rows, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "hiddenchain-audit-logs.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "日志加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader eyebrow="全过程留痕" title="全过程日志" description="登录、授权、Agent 调用、计算、存证、核验与处置动作统一记录 traceId 和业务对象。" actions={<><Button icon={RefreshCw} onClick={reload}>刷新</Button><Button icon={Download} onClick={exportLogs}>导出审计日志</Button></>} />
      <Surface>
        <div className="log-filters">
          <label><Search size={16} /><input placeholder="搜索主体、对象或 traceId" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          <label><Filter size={16} /><select value={action} onChange={(event) => setAction(event.target.value)}><option value="">全部动作</option>{actions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <span>显示 {rows.length} / {data.length} 条</span>
        </div>
      </Surface>
      <Surface title="审计日志记录">
        <DataTable
          keyField="log_id"
          rows={rows}
          columns={[
            { key: "occurred_at", label: "时间", render: (row) => formatDate(row.occurred_at) },
            { key: "actor_name", label: "操作主体" },
            { key: "action_code", label: "动作" },
            { key: "target_type", label: "对象类型" },
            { key: "target_id", label: "对象编号", render: (row) => <CodeValue title={row.target_id}>{shortHash(row.target_id, 10)}</CodeValue> },
            { key: "trace_id", label: "Trace ID", render: (row) => <span className="mono-text">{shortHash(row.trace_id, 10)}</span> },
            { key: "result", label: "结果", render: (row) => <StatusTag value={row.result} /> },
            { key: "details", label: "详情", render: (row) => <button className="icon-button" title="查看详情" onClick={() => setSelected(row)}><Eye size={17} /></button> },
          ]}
        />
      </Surface>
      {selected && <Modal title="日志详情" onClose={() => setSelected(null)} footer={<Button onClick={() => setSelected(null)}>关闭</Button>}>
        <div className="detail-grid"><div><span>Trace ID</span><CodeValue>{selected.trace_id}</CodeValue></div><div><span>动作结果</span><StatusTag value={selected.result} /></div><div><span>操作主体</span><strong>{selected.actor_name}</strong></div><div><span>发生时间</span><strong>{formatDate(selected.occurred_at)}</strong></div></div>
        <pre className="json-view">{JSON.stringify(selected.details_json, null, 2)}</pre>
      </Modal>}
    </>
  );
}
