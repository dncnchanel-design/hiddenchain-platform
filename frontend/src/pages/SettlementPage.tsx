import { useMemo, useState } from "react";
import { ArrowRight, Plus, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Button, DataTable, DateTimeText, ErrorState, IdText, LoadingState, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { taskNextAction, taskStatusLabel, taskTabFor, type TaskTab } from "../settlement-model";
import type { JsonRecord } from "../types";

const tabs: Array<{ code: TaskTab; label: string }> = [
  { code: "todo", label: "待我处理" },
  { code: "created", label: "我发起的" },
  { code: "running", label: "进行中" },
  { code: "exception", label: "异常" },
  { code: "completed", label: "已完成" },
];

export function SettlementPage() {
  const { session } = useAuth();
  const role = session!.user.role_code;
  const orgId = session!.user.org_id;
  const [activeTab, setActiveTab] = useState<TaskTab>("todo");
  const { data, loading, refreshing, error, reload } = useRemote(
    (signal) => api<JsonRecord[]>("/settlement/tasks", { signal, cache: "no-store" }),
    [role, orgId],
  );

  const taskRows = useMemo<JsonRecord[]>(() => (data || []).map((task) => ({
    ...task,
    business_tab: taskTabFor(task, role, orgId),
    next_action: taskNextAction(task, role, orgId),
  })), [data, orgId, role]);
  const tabCounts = useMemo(() => Object.fromEntries(tabs.map((tab) => [tab.code, taskRows.filter((item) => item.business_tab === tab.code).length])), [taskRows]);
  const visibleRows = taskRows.filter((item) => item.business_tab === activeTab);

  if (loading) return <LoadingState label="正在读取结算任务" variant="page" />;
  if (error) return <ErrorState message={error} retry={reload} />;

  return (
    <>
      <PageHeader
        title="结算任务"
        actions={<>
          <Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>
          {role === "EXCHANGE" && <Link className="button button-primary" to="/settlements/new"><Plus size={16} />发起结算任务</Link>}
        </>}
      />

      <Surface className="task-center-surface">
        <div className="task-tabs" role="tablist" aria-label="结算任务分类">
          {tabs.map((tab) => (
            <button
              key={tab.code}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.code}
              className={activeTab === tab.code ? "active" : ""}
              onClick={() => setActiveTab(tab.code)}
            >
              <span>{tab.label}</span><strong>{tabCounts[tab.code] || 0}</strong>
            </button>
          ))}
        </div>

        <DataTable
          keyField="task_id"
          rows={visibleRows}
          empty={`暂无“${tabs.find((item) => item.code === activeTab)?.label}”任务`}
          label="结算任务列表"
          columns={[
            {
              key: "task_name",
              label: "结算任务",
              minWidth: 250,
              render: (row) => <div className="task-name-cell"><Link to={`/settlements/${row.task_id}`}>{row.task_name}</Link><IdText value={row.capsule_id || row.task_id} length={8} /></div>,
            },
            { key: "trade_batch_no", label: "交易批次", minWidth: 140, render: (row) => <IdText value={row.trade_batch_no} length={8} /> },
            { key: "period", label: "结算周期", minWidth: 190, render: (row) => <span className="tabular-text">{row.period_start} 至 {row.period_end}</span> },
            { key: "status", label: "业务状态", minWidth: 120, render: (row) => <StatusTag value={row.status} label={taskStatusLabel(row.status)} /> },
            { key: "current_stage", label: "当前环节", minWidth: 140 },
            { key: "next_action", label: "下一步", minWidth: 210, render: (row) => <div className="next-action-cell"><strong>{row.next_action.label}</strong><span>{row.next_action.responsible}</span>{row.next_action.blocker && <small>{row.next_action.blocker}</small>}</div> },
            { key: "updated_at", label: "最近更新", minWidth: 170, render: (row) => <DateTimeText value={row.updated_at || row.created_at} /> },
            { key: "action", label: "操作", width: 110, sortable: false, hideable: false, sticky: "right", render: (row) => <Link className="table-action" to={`/settlements/${row.task_id}`}>查看任务 <ArrowRight size={13} /></Link> },
          ]}
        />
      </Surface>
    </>
  );
}
