import type { ElementType } from "react";
import { ArrowRight, BarChart3, Building2, Database, FileCheck2, FileClock, Gavel, LockKeyhole, Network, RefreshCw, ShieldCheck, Upload } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Button, DataTable, DateTimeText, ErrorState, IdText, LoadingState, Metric, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord, RoleCode } from "../types";

type WorkbenchAction = { title: string; path: string; icon: ElementType };
type RoleConfig = { title: string; nextStep: string; nextPath: string; actions: WorkbenchAction[] };
type WorkbenchData = { tasks: JsonRecord[]; organizations: JsonRecord[]; summary: JsonRecord; rules: JsonRecord[] };

const roleConfig: Record<RoleCode, RoleConfig> = {
  GENERATOR: {
    title: "发电企业工作台", nextStep: "登记发电数据", nextPath: "/data/generation",
    actions: [
      { title: "登记发电数据", path: "/data/generation", icon: Database },
      { title: "确认结果", path: "/results", icon: FileCheck2 },
      { title: "查看审计凭证", path: "/evidence", icon: FileClock },
    ],
  },
  RETAILER: {
    title: "售电企业工作台", nextStep: "登记用电数据", nextPath: "/data/retail",
    actions: [
      { title: "登记用电数据", path: "/data/retail", icon: Database },
      { title: "发起隐私分析", path: "/compute", icon: LockKeyhole },
      { title: "确认聚合结果", path: "/results", icon: FileCheck2 },
    ],
  },
  EXCHANGE: {
    title: "交易中心工作台", nextStep: "进入调用验证", nextPath: "/settlements",
    actions: [
      { title: "进入调用验证", path: "/settlements", icon: Upload },
      { title: "维护授权规则", path: "/rules", icon: Gavel },
      { title: "查看计算任务", path: "/compute", icon: Network },
    ],
  },
  REGULATOR: {
    title: "监管审计工作台", nextStep: "查看审计事项", nextPath: "/audit",
    actions: [
      { title: "查看调用审计", path: "/audit", icon: ShieldCheck },
      { title: "处置风险事件", path: "/anomalies", icon: BarChart3 },
      { title: "查看审计报告", path: "/reports", icon: FileCheck2 },
    ],
  },
  ADMIN: {
    title: "可信执行业务工作台", nextStep: "查看验证任务", nextPath: "/settlements",
    actions: [
      { title: "查看验证任务", path: "/settlements", icon: Network },
      { title: "查看授权规则", path: "/rules", icon: Gavel },
      { title: "查看风险事件", path: "/anomalies", icon: ShieldCheck },
    ],
  },
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
    const [tasks, organizations, summary, rules] = await Promise.all([
      api<JsonRecord[]>("/settlement/tasks", request),
      api<JsonRecord[]>("/system/organizations", request),
      api<JsonRecord>("/dashboard/summary", request),
      canReadRules ? api<JsonRecord[]>("/rules", request) : Promise.resolve([] as JsonRecord[]),
    ]);
    return { tasks, organizations, summary, rules };
  };
  const { data, loading, refreshing, error, reload } = useRemote(loader, [role, canReadRules]);

  if (loading) return <LoadingState label="正在读取工作台" variant="page" />;
  if (error || !data) return <ErrorState message={error || "工作台加载失败"} retry={reload} />;

  const tasks = data.tasks;
  const pendingTasks = tasks.filter((item) => item.status !== "AUDITED");
  const runningTasks = tasks.filter((item) => ["AUTHORIZED", "COMPUTING", "RUNNING", "EVIDENCED"].includes(String(item.status))).length;
  const exceptionTasks = tasks.filter((item) => ["FAILED", "INVALID", "REJECTED"].includes(String(item.status)) || item.risk_level === "HIGH").length;
  const resultTasks = tasks.filter((item) => Number(item.result_count || 0) > 0).length;
  const openAnomalies = Number(data.summary.kpis?.open_anomalies || 0);
  const activeRule = data.rules.find((item) => item.status === "ACTIVE");
  const latestUpdatedAt = tasks.map((item) => item.updated_at || item.created_at).filter(Boolean).sort().at(-1);

  return (
    <>
      <PageHeader title={config.title} description="聚合当前身份可处理的任务、风险和最近业务活动。" actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>} />

      <section className="workspace-bar" aria-label="当前业务上下文">
        <div className="workspace-context-primary"><div className="workspace-icon"><Building2 size={19} /></div><div><span>当前组织</span><strong>{String(authenticatedSession.org.org_name || "—")}</strong></div></div>
        <div className="workspace-context-item"><span>生效规则</span><strong>{activeRule?.rule_version || "—"}</strong></div>
        <div className="workspace-context-item"><span>最近更新</span><strong>{latestUpdatedAt ? <DateTimeText value={String(latestUpdatedAt)} /> : "—"}</strong></div>
        <Link className="button button-primary workspace-action" to={config.nextPath}>{config.nextStep}<ArrowRight size={15} /></Link>
      </section>

      <div className="metrics-grid four workbench-kpis">
        <Metric label="待处理任务" value={pendingTasks.length} tone={pendingTasks.length ? "amber" : "green"} />
        <Metric label="执行中任务" value={runningTasks} />
        <Metric label="已生成结果任务" value={resultTasks} />
        <Metric label="待处置风险事件" value={openAnomalies} tone={openAnomalies ? "red" : "green"} />
      </div>

      <div className="workbench-toolbar">
        <strong>常用操作</strong>
        <div className="workbench-quick-actions">
          {config.actions.map((action) => {
            const Icon = action.icon;
            return <Link key={action.path} className="quick-action" to={action.path}><Icon size={15} /><span>{action.title}</span><ArrowRight size={13} /></Link>;
          })}
        </div>
      </div>

      <div className="workbench-grid">
        <div className="workbench-main">
          <Surface title="待处理任务" meta={`${pendingTasks.length} 项`} actions={<Link className="text-link" to="/settlements">查看全部 <ArrowRight size={14} /></Link>}>
            <DataTable
              keyField="task_id" rows={pendingTasks} empty="暂无待处理任务" label="待处理任务列表"
              columns={[
                { key: "task_id", label: "任务编号", minWidth: 150, render: (row) => <IdText value={row.task_id} /> },
                { key: "task_name", label: "业务对象", minWidth: 180 },
                { key: "creator_org_id", label: "申请机构", minWidth: 150, render: (row) => organizationName(data.organizations, row.creator_org_id) },
                { key: "trade_batch_no", label: "数据批次", minWidth: 130, render: (row) => <IdText value={row.trade_batch_no} length={8} /> },
                { key: "created_at", label: "创建时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
                { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
                { key: "action", label: "操作", sortable: false, hideable: false, sticky: "right", render: (row) => <Link className="table-link" to={`/settlements?task=${row.task_id}`}>查看 <ArrowRight size={13} /></Link> },
              ]}
            />
          </Surface>
        </div>

        <aside className="workbench-side" aria-label="风险与最近活动">
          <Surface title="风险与异常">
            {openAnomalies || exceptionTasks ? (
              <div className="alert-list">
                {openAnomalies > 0 && <Link to="/anomalies"><span><i className="alert-dot danger" />待处置风险事件</span><strong>{openAnomalies} 项</strong><ArrowRight size={14} /></Link>}
                {exceptionTasks > 0 && <Link to="/settlements"><span><i className="alert-dot warning" />异常验证任务</span><strong>{exceptionTasks} 项</strong><ArrowRight size={14} /></Link>}
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
