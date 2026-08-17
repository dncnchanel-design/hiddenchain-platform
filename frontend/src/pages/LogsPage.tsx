import { useMemo, useState } from "react";
import { Eye, RefreshCw, Search } from "lucide-react";
import { api } from "../api";
import { Button, DataTable, DateTimeText, DetailDrawer, ErrorState, FilterBar, IdText, LoadingState, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { ACTION_LABELS, TARGET_TYPE_LABELS, type JsonRecord } from "../types";

const sensitiveKey = /(password|passcode|token|secret|authorization|cookie|private.?key|signature.?value|signed.?call)/i;

function redactSensitive(value: unknown, depth = 0): unknown {
  if (depth > 8) return "[已省略]";
  if (Array.isArray(value)) return value.map((item) => redactSensitive(item, depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as JsonRecord).map(([key, item]) => [key, sensitiveKey.test(key) ? "[已脱敏]" : redactSensitive(item, depth + 1)]));
  }
  if (typeof value === "string") return value.replace(/Bearer\s+[A-Za-z0-9._~+/-]+=*/gi, "Bearer [已脱敏]");
  return value;
}

export function LogsPage() {
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
  const [resultFilter, setResultFilter] = useState("");
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const { data, loading, refreshing, error, reload } = useRemote<JsonRecord[]>((signal) => api("/audit/logs", { signal, timeoutMs: 12000, cache: "no-store" }), []);
  const actions = useMemo(() => Array.from(new Set((data || []).map((item) => String(item.action_code)))).sort(), [data]);
  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (data || []).filter((item) => {
      const searchable = [item.actor_name, item.action_code, item.target_type, item.target_id, item.trace_id, item.result].map((value) => String(value || "").toLowerCase());
      return (!action || item.action_code === action) && (!resultFilter || item.result === resultFilter) && (!query || searchable.some((value) => value.includes(query)));
    });
  }, [data, action, resultFilter, search]);

  if (loading) return <LoadingState label="正在加载系统日志" variant="page" />;
  if (error || !data) return <ErrorState message={error || "日志加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader title="系统日志" description="按操作主体、对象、动作、结果或追踪编号检索审计记录；当前环境尚未开放经服务端审计的导出通道。" actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>} />
      <FilterBar actions={<span className="filter-result-count">显示 {rows.length} / {data.length} 条</span>}>
        <label><span>关键词</span><div className="input-with-icon"><Search size={15} /><input placeholder="主体、对象或追踪编号" value={search} onChange={(event) => setSearch(event.target.value)} /></div></label>
        <label><span>操作动作</span><select value={action} onChange={(event) => setAction(event.target.value)}><option value="">全部动作</option>{actions.map((item) => <option key={item} value={item}>{ACTION_LABELS[item] || item}</option>)}</select></label>
        <label><span>执行结果</span><select value={resultFilter} onChange={(event) => setResultFilter(event.target.value)}><option value="">全部结果</option><option value="SUCCESS">成功</option><option value="FAILED">失败</option><option value="DENY">未通过</option></select></label>
      </FilterBar>
      <Surface title="记录列表" meta={`${rows.length} 条`}>
        <DataTable
          keyField="log_id" rows={rows} label="系统日志列表" pageSize={20}
          columns={[
            { key: "occurred_at", label: "时间", minWidth: 165, render: (row) => <DateTimeText value={row.occurred_at} /> },
            { key: "actor_name", label: "操作主体", minWidth: 130 },
            { key: "action_code", label: "动作", minWidth: 190, render: (row) => ACTION_LABELS[row.action_code] || row.action_code || "—" },
            { key: "target_type", label: "对象类型", minWidth: 120, render: (row) => TARGET_TYPE_LABELS[row.target_type] || row.target_type || "—" },
            { key: "target_id", label: "对象编号", minWidth: 150, render: (row) => <IdText value={row.target_id} /> },
            { key: "trace_id", label: "追踪编号", minWidth: 150, render: (row) => <IdText value={row.trace_id} /> },
            { key: "result", label: "结果", render: (row) => <StatusTag value={row.result} /> },
            { key: "details", label: "操作", sortable: false, hideable: false, sticky: "right", render: (row) => <Button icon={Eye} onClick={() => setSelected(row)}>详情</Button> },
          ]}
        />
      </Surface>

      {selected && <DetailDrawer title="日志详情" onClose={() => setSelected(null)} footer={<Button onClick={() => setSelected(null)}>关闭</Button>}>
        <div className="detail-grid"><div><span>日志编号</span><IdText value={selected.log_id} /></div><div><span>追踪编号</span><IdText value={selected.trace_id} /></div><div><span>动作</span><strong>{ACTION_LABELS[selected.action_code] || selected.action_code || "—"}</strong></div><div><span>操作结果</span><StatusTag value={selected.result} /></div><div><span>操作主体</span><strong>{selected.actor_name || "—"}</strong></div><div><span>发生时间</span><DateTimeText value={selected.occurred_at} /></div><div><span>对象类型</span><strong>{TARGET_TYPE_LABELS[selected.target_type] || selected.target_type || "—"}</strong></div><div><span>对象编号</span><IdText value={selected.target_id} /></div></div>
        <details className="secondary-details"><summary>查看脱敏详情</summary><pre className="json-view">{JSON.stringify(redactSensitive(selected.details_json), null, 2)}</pre></details>
      </DetailDrawer>}
    </>
  );
}
