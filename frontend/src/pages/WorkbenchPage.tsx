import type { ElementType } from "react";
import { ArrowRight, BarChart3, Building2, FileCheck2, FileClock, Gavel, LockKeyhole, Network, RefreshCw, RotateCcw, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Button, DataTable, DateTimeText, ErrorState, IdText, LoadingState, Metric, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { taskActionPath, taskNextAction, taskTabFor } from "../settlement-model";
import type { JsonRecord, RoleCode } from "../types";
import { loadWorkbench, type WorkbenchQuickAction } from "../features/trusted-energy/trusted-space-api";

type RoleConfig = { title: string };
type WorkbenchData = { tasks: JsonRecord[]; organizations: JsonRecord[]; summary: JsonRecord; rules: JsonRecord[]; quick_action_items: WorkbenchQuickAction[] | null };

const roleConfig: Record<RoleCode, RoleConfig> = {
  GENERATOR: {
    title: "发电企业工作台",
  },
  RETAILER: {
    title: "售电企业工作台",
  },
  COAL_ENTERPRISE: {
    title: "煤炭企业工作台",
  },
  HEAT_ENTERPRISE: {
    title: "热能企业工作台",
  },
  GAS_ENTERPRISE: {
    title: "天然气企业工作台",
  },
  OIL_ENTERPRISE: {
    title: "石油企业工作台",
  },
  EXCHANGE: {
    title: "交易中心工作台",
  },
  REGULATOR: {
    title: "监管审计工作台",
  },
  ADMIN: {
    title: "可信执行业务工作台",
  },
};

const quickActionIcons: Record<string, ElementType> = {
  VIEW_OWN_ASSETS: FileClock,
  REVIEW_INBOUND_AUTHORIZATIONS: FileCheck2,
  CONFIRM_OWN_RESULT: FileCheck2,
  REQUEST_USAGE: LockKeyhole,
  CREATE_SETTLEMENT: Network,
  VIEW_PENDING_AUDIT: ShieldCheck,
  VIEW_ALL_ASSETS: FileClock,
  VIEW_AUTHORIZATIONS: FileCheck2,
  REVIEW_AUDIT_EVIDENCE: ShieldCheck,
  VIEW_SYSTEM_CAPABILITIES: Gavel,
  VIEW_RUNTIME_STATUS: BarChart3,
};

function organizationName(organizations: JsonRecord[], orgId: unknown) {
  const name = organizations.find((item) => item.org_id === orgId)?.org_name;
  return name || (orgId ? String(orgId) : "—");
}

export function WorkbenchPage() {
  const { session } = useAuth();
  const authenticatedSession = session!;
  const role = authenticatedSession.user.role_code;
  const config = roleConfig[role];
  const canReadRules = ["EXCHANGE", "REGULATOR", "ADMIN"].includes(role);
  const loader = async (signal?: AbortSignal): Promise<WorkbenchData> => {
    const request = { signal, timeoutMs: 12000, cache: "no-store" as RequestCache };
    const [tasks, organizations, summary, rules, trustedWorkbench] = await Promise.all([
      api<JsonRecord[]>("/settlement/tasks", request),
      api<JsonRecord[]>("/system/organizations", request),
      api<JsonRecord>("/dashboard/summary", request),
      canReadRules ? api<JsonRecord[]>("/rules", request) : Promise.resolve([] as JsonRecord[]),
      loadWorkbench(signal).catch(() => null),
    ]);
    return { tasks, organizations, summary, rules, quick_action_items: trustedWorkbench?.quick_action_items ?? null };
  };
  const { data, loading, refreshing, error, reload } = useRemote(loader, [role, canReadRules]);

  if (loading) return <LoadingState label="正在读取工作台" variant="page" />;
  if (error || !data) return <ErrorState message={error || "工作台加载失败"} retry={reload} />;

  const tasks: JsonRecord[] = data.tasks.map((item) => ({
    ...item,
    next_action: taskNextAction(item, role, authenticatedSession.user.org_id),
    business_tab: taskTabFor(item, role, authenticatedSession.user.org_id),
  }));
  const pendingTasks = tasks.filter((item) => item.business_tab === "todo");
  const runningTasks = tasks.filter((item) => ["running", "created"].includes(item.business_tab)).length;
  const exceptionTasks = tasks.filter((item) => ["EXCEPTION", "INVALID", "REJECTED"].includes(String(item.status)) || item.risk_level === "HIGH").length;
  const resultTasks = tasks.filter((item) => Number(item.result_count || 0) > 0).length;
  const openAnomalies = Number(data.summary.kpis?.open_anomalies || 0);
  const activeRule = data.rules.find((item) => item.status === "ACTIVE");
  const latestUpdatedAt = tasks.map((item) => item.updated_at || item.created_at).filter(Boolean).sort().at(-1);
  const primaryAction = data.quick_action_items?.find((item) => item.allowed && item.path?.trim());
  const workflowTask = pendingTasks[0] || tasks.find((item) => item.status !== "AUDITED");
  const workflowTaskId = workflowTask ? String(workflowTask.task_id || "") : "";
  const workflowStartPath = role === "EXCHANGE" ? "/settlements/new?template=ready" : (workflowTaskId ? taskActionPath(workflowTask, role, authenticatedSession.user.org_id) : "/settlements");
  const workflowStartLabel = role === "EXCHANGE"
    ? (primaryAction?.label || "发起一笔新结算")
    : (workflowTask ? (workflowTask.next_action?.label || "处理当前待办") : "查看任务中心");
  const workflowSteps = [
    { label: "发起任务", detail: "交易中心登记批次与参与主体" },
    { label: "数据与授权", detail: "引用数据、确认承诺、锁定用途" },
    { label: "受控计算", detail: "按规则生成聚合结果和计算回执" },
    { label: "审计复核", detail: "核对证据、风险和报告" },
    { label: "多方确认", detail: "发电方与售电方分别签名确认" },
    { label: "闭环归档", detail: "保留任务、结果和证据追溯" },
  ];

  return (
    <>
      <PageHeader title={config.title} actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>} />

      <section className="workspace-bar" aria-label="当前业务上下文">
        <div className="workspace-context-primary"><div className="workspace-icon"><Building2 size={19} /></div><div><span>当前组织</span><strong>{String(authenticatedSession.org.org_name || "—")}</strong></div></div>
        <div className="workspace-context-item"><span>生效规则</span><strong>{activeRule?.rule_version || "—"}</strong></div>
        <div className="workspace-context-item"><span>最近更新</span><strong>{latestUpdatedAt ? <DateTimeText value={String(latestUpdatedAt)} /> : "—"}</strong></div>
        <Link className="button button-primary workspace-action" to={workflowStartPath}>{workflowStartLabel}<ArrowRight size={15} /></Link>
      </section>

      <Surface className="workflow-launch-surface" title="从任务开始跑通全流程" meta={workflowTask ? `当前待办：${workflowTask.task_name}` : "从一笔新任务开始"}>
        <div className="workflow-launch-grid">
          <div className="workflow-launch-copy">
            <strong>{workflowTask ? "系统已为你定位下一步" : "先创建一笔任务，再沿证据链推进"}</strong>
            <p>{workflowTask ? `${workflowTask.next_action?.label || "查看当前任务进度"} · 责任方：${workflowTask.next_action?.responsible || "当前角色"}` : "任务会把数据引用、授权、规则、计算、确认和审计记录在同一条链上。"}</p>
            <div className="workflow-launch-actions">
              <Link className="button button-primary" to={workflowStartPath}>{workflowStartLabel}<ArrowRight size={15} /></Link>
              {role === "EXCHANGE" && <Link className="button button-secondary" to="/settlements?view=todo"><RotateCcw size={15} />查看待处理任务</Link>}
            </div>
          </div>
          <ol className="workflow-route-list" aria-label="结算全流程">
            {workflowSteps.map((step, index) => <li key={step.label} className={index === 0 && role === "EXCHANGE" && !workflowTask ? "current" : undefined}>
              <span>{index + 1}</span><div><strong>{step.label}</strong><small>{step.detail}</small></div>
            </li>)}
          </ol>
        </div>
      </Surface>

      <div className="metrics-grid four workbench-kpis">
        <Metric label="待处理任务" value={pendingTasks.length} tone={pendingTasks.length ? "amber" : "green"} />
        <Metric label="执行中任务" value={runningTasks} />
        <Metric label="已生成结果任务" value={resultTasks} />
        <Metric label="待处置风险事件" value={openAnomalies} tone={openAnomalies ? "red" : "green"} />
      </div>

      <div className="workbench-toolbar">
        <strong>常用操作</strong>
        <div className="workbench-quick-actions">
          {data.quick_action_items === null && <Notice tone="warning">角色快捷动作服务暂不可用，已保留任务主线入口。</Notice>}
          {data.quick_action_items && !data.quick_action_items.length && <span className="muted">当前角色暂无快捷动作</span>}
          {data.quick_action_items?.map((action) => {
            const Icon = quickActionIcons[action.code] || ArrowRight;
            const canOpen = action.allowed && Boolean(action.path?.trim());
            return canOpen
              ? <Link key={action.code} className="quick-action" to={action.path}><Icon size={15} /><span>{action.label}</span><ArrowRight size={13} /></Link>
              : <span key={action.code} className="quick-action is-disabled" title={action.disabled_reason || "后端未允许此动作"}><Icon size={15} /><span>{action.label}</span><small>{action.disabled_reason || "后端未允许此动作"}</small></span>;
          })}
        </div>
      </div>

      <div className="workbench-grid">
        <div className="workbench-main">
          <Surface title="待处理任务" meta={`${pendingTasks.length} 项`} actions={<Link className="text-link" to="/settlements">查看全部 <ArrowRight size={14} /></Link>}>
            <DataTable
              keyField="task_id" rows={pendingTasks} empty="暂无待处理任务" label="待处理任务列表"
              columns={[
                { key: "task_name", label: "结算任务", minWidth: 210, render: (row) => <div className="task-name-cell"><Link to={`/settlements/${row.task_id}`}>{row.task_name}</Link><IdText value={row.capsule_id || row.task_id} length={7} /></div> },
                { key: "creator_org_id", label: "发起机构", minWidth: 150, render: (row) => organizationName(data.organizations, row.creator_org_id) },
                { key: "trade_batch_no", label: "数据批次", minWidth: 130, render: (row) => <IdText value={row.trade_batch_no} length={8} /> },
                { key: "current_stage", label: "当前环节", minWidth: 130 },
                { key: "next_action", label: "下一步", minWidth: 210, render: (row) => <div className="next-action-cell"><strong>{row.next_action.label}</strong><span>{row.next_action.responsible}</span>{row.next_action.blocker && <small>{row.next_action.blocker}</small>}</div> },
                { key: "action", label: "操作", sortable: false, hideable: false, sticky: "right", render: (row) => <Link className="table-link" to={`/settlements/${row.task_id}`}>处理 <ArrowRight size={13} /></Link> },
              ]}
            />
          </Surface>
        </div>

        <aside className="workbench-side" aria-label="风险与最近活动">
          <Surface title="风险与异常">
            {openAnomalies || exceptionTasks ? (
              <div className="alert-list">
                {openAnomalies > 0 && <Link to="/anomalies"><span><i className="alert-dot danger" />待处置风险事件</span><strong>{openAnomalies} 项</strong><ArrowRight size={14} /></Link>}
                {exceptionTasks > 0 && <Link to="/settlements"><span><i className="alert-dot warning" />异常结算任务</span><strong>{exceptionTasks} 项</strong><ArrowRight size={14} /></Link>}
              </div>
            ) : <div className="alert-empty"><ShieldCheck size={17} /><span>暂无待处置风险。</span></div>}
          </Surface>

          <Surface title="最近业务活动">
            <ol className="workbench-activity-list">
              {tasks.slice(0, 6).map((item) => (
                <li key={String(item.task_id)}>
                  <div><strong>{item.task_name || <IdText value={item.task_id} copyable={false} />}</strong><span>{organizationName(data.organizations, item.creator_org_id)}</span></div>
                  <DateTimeText value={item.updated_at || item.created_at} />
                  <StatusTag value={item.status} />
                </li>
              ))}
              {!tasks.length && <li className="activity-empty">暂无业务活动</li>}
            </ol>
          </Surface>
        </aside>
      </div>
    </>
  );
}
