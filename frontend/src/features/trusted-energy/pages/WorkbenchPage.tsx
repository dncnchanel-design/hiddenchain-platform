import { ArrowUpRight, BadgeCheck, ClipboardList, Database, FileCheck2, FilePlus2, Fingerprint, Network, Plus, ScanSearch, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, MetricBand, Progress, RemoteState, StatusBadge, SurfaceHeader, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { useTrustedSpaceContext } from "../trusted-space-context";
import { loadWorkbench, type WorkbenchPayload } from "../trusted-space-api";
import { ACTION_LABELS, ASSET_TYPE_LABELS, labelForCode } from "../../../types";
import { routeForView } from "../types";
import { quickActionPath } from "../trusted-space-ui";
import { purposeLabel, usageModeLabel } from "../trusted-space-labels";

function statusLabel(value: string) {
  return labelForCode(value, "未知");
}
function quickActionIcon(code: string) {
  switch (code) {
    case "REVIEW_INBOUND_AUTHORIZATIONS":
    case "VIEW_AUTHORIZATIONS":
      return ClipboardList;
    case "VIEW_PENDING_AUDIT":
    case "REVIEW_AUDIT_EVIDENCE":
      return ScanSearch;
    case "CREATE_SETTLEMENT":
    case "VIEW_RUNTIME_STATUS":
      return Network;
    case "REQUEST_USAGE":
      return FilePlus2;
    case "CONFIRM_OWN_RESULT":
      return BadgeCheck;
    case "VIEW_SYSTEM_CAPABILITIES":
      return Fingerprint;
    case "VIEW_OWN_ASSETS":
    case "VIEW_ALL_ASSETS":
    default:
      return Database;
  }
}

function renderWorkbenchMetric(data: WorkbenchPayload) {
  const { kpis } = data;
  return [
    { label: "可见数据资产", value: String(kpis.visible_assets), detail: "当前组织范围", tone: "brand" as const },
    { label: "使用申请", value: String(kpis.usage_requests), detail: `${kpis.active_usage_requests} 条活跃`, tone: "info" as const },
    { label: "计算任务", value: String(kpis.compute_jobs), detail: `${kpis.visible_tasks} 条可信任务`, tone: "warning" as const },
    { label: "审计报告", value: String(kpis.audit_reports), detail: "真实数据库计数", tone: "success" as const },
  ];
}

export function WorkbenchPage() {
  const navigate = useNavigate();
  const { context } = useTrustedSpaceContext();
  const remote = useRemote(loadWorkbench, []);
  const data = remote.data;
  const quickActions = data?.quick_action_items ?? [];
  const canRequest = context?.role_capabilities.can_request_usage === true;
  return <PageFrame title="工作台" description="按主体、数据授权、受控计算和证据留痕组织当前工作。" action={<Button variant="primary" disabled={!canRequest} title={canRequest ? undefined : "当前角色不能发起数据使用申请"} onClick={() => navigate(routeForView("catalog"))}><Plus size={15} />申请数据使用</Button>}>
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    {data && <>
      <section className="trusted-subject-strip"><div className="trusted-subject-identity"><span className="trusted-subject-avatar"><ShieldCheck size={18} /></span><div><strong>您好，{context?.current_subject.org_name || context?.actor.display_name}</strong><span>{context?.actor.role_label} · 当前工作主体</span></div></div><div className="trusted-subject-facts"><span><small>主体身份标识</small><code>{context?.identity_ref.did || "未配置"}</code></span><span><small>权限范围</small><b>{context?.role_capabilities.can_view_all_assets ? "全域资产 · 受控计算" : "本方资产 · 受控计算"}</b></span><span><small>运行边界</small><Badge tone="warning" dot>{labelForCode(data.capability_state || "LOCAL_REAL")}</Badge></span></div></section>
      <MetricBand items={renderWorkbenchMetric(data)} />
      <div className="trusted-workbench-grid">
        <Card className="trusted-table-surface"><CardHeader><SurfaceHeader title="最近数据资产" description="按最近更新时间排序 · 仅展示当前主体可见范围" action={<Button variant="link" size="sm" onClick={() => navigate(routeForView("catalog"))}>查看全部 <ArrowUpRight size={14} /></Button>} /></CardHeader><CardContent className="trusted-table-wrap"><RemoteState empty={!data.recent_assets.length} emptyLabel="暂无可见数据资产" />{Boolean(data.recent_assets.length) && <Table><TableHeader><TableRow><TableHead>资产名称</TableHead><TableHead>资产类型</TableHead><TableHead>提供方</TableHead><TableHead>能力标签</TableHead></TableRow></TableHeader><TableBody>{data.recent_assets.map((asset) => <TableRow key={asset.asset_id} onClick={() => navigate(routeForView("asset", asset.asset_id))}><TableCell><div className="trusted-table-primary"><strong>{asset.asset_name}</strong><small>{asset.asset_code}</small></div></TableCell><TableCell>{ASSET_TYPE_LABELS[asset.asset_type] || labelForCode(asset.asset_type)}</TableCell><TableCell>{asset.owner_org_name || asset.owner_org_id}</TableCell><TableCell className="trusted-muted">{labelForCode(asset.source_capability)}</TableCell></TableRow>)}</TableBody></Table>}</CardContent></Card>
        <Card className="trusted-task-surface"><CardHeader><SurfaceHeader title="近期任务动态" description="来自真实可信任务记录；进度为状态机阶段估算，不是实时执行进度" action={<Button variant="link" size="sm" onClick={() => navigate(routeForView("ttc"))}>查看全部 <ArrowUpRight size={14} /></Button>} /></CardHeader><CardContent><RemoteState empty={!data.recent_tasks.length} emptyLabel="暂无可见任务" />{Boolean(data.recent_tasks.length) && <div className="trusted-task-list">{data.recent_tasks.map((task) => { const estimate = task.phase_progress_estimate; return <button className="trusted-task-row" key={task.task_id} type="button" onClick={() => navigate(routeForView("ttc", task.task_id))}><span className="trusted-task-icon"><Network size={15} /></span><span className="trusted-task-copy"><strong>{task.task_name}</strong><small><code>{task.task_id}</code> · {statusLabel(task.status)}</small></span><span className="trusted-task-state"><StatusBadge value={statusLabel(task.status)} /><Progress value={estimate?.value ?? 0} label={estimate?.label || "阶段估算（非实时执行进度）"} /></span></button>; })}</div>}</CardContent></Card>
      </div>
      <div className="trusted-lower-grid"><Card><CardHeader><SurfaceHeader title="快捷入口" description="入口由后端角色上下文返回" /></CardHeader><CardContent><RemoteState empty={!quickActions.length} emptyLabel="当前角色暂无快捷动作" />{Boolean(quickActions.length) && <div className="trusted-quick-grid">{quickActions.map((action) => { const Icon = quickActionIcon(action.code); const actionPath = quickActionPath(action); const canOpen = actionPath !== null; const actionLabel = ACTION_LABELS[action.code] || labelForCode(action.label, "快捷动作"); return <button type="button" className={`trusted-quick-action${canOpen ? "" : " is-disabled"}`} key={action.code} disabled={!canOpen} title={!canOpen ? action.disabled_reason || "后端当前未允许此动作" : actionPath} onClick={() => { if (actionPath) navigate(actionPath); }}><span><Icon size={16} /></span><b>{actionLabel}</b><small>{canOpen ? `系统动作 · ${ACTION_LABELS[action.code] || labelForCode(action.label, "已登记")}` : action.disabled_reason || "后端当前未允许此动作"}</small><ArrowUpRight size={13} /></button>; })}</div>}</CardContent></Card><Card><CardHeader><SurfaceHeader title="可信执行边界" description="当前环境能力清单" /></CardHeader><CardContent><div className="trusted-boundary-list"><div><span><ShieldCheck size={14} />身份凭证</span><Badge tone={context?.identity_ref.credential_status === "VALID" ? "success" : "warning"} dot>{labelForCode(context?.identity_ref.credential_status || "NOT_CONFIGURED")}</Badge></div><div><span><Fingerprint size={14} />数据空间连接器</span><Badge tone="warning" dot>{labelForCode(context?.capabilities.data_space_connector?.capability_state || "ADAPTER")}</Badge></div><div><span><FileCheck2 size={14} />链上存证</span><Badge tone="warning" dot>{labelForCode(context?.capabilities.blockchain_anchor?.capability_state || "DEMO")}</Badge></div></div></CardContent></Card></div>
      {data.recent_usage_requests.length > 0 && <Card><CardHeader><SurfaceHeader title="授权动态" description="提供方查看入站，申请方查看本人记录" action={<Button variant="link" size="sm" onClick={() => navigate(routeForView("authorizations"))}>查看授权记录 <ArrowUpRight size={14} /></Button>} /></CardHeader><CardContent><div className="trusted-task-list">{data.recent_usage_requests.slice(0, 4).map((request) => <button type="button" className="trusted-task-row" key={request.request_id} onClick={() => navigate(`${routeForView("authorizations")}?request=${encodeURIComponent(request.request_id)}`)}><span className="trusted-task-icon"><ClipboardList size={15} /></span><span className="trusted-task-copy"><strong>{request.request_id}</strong><small>{purposeLabel(request.purpose)} · {usageModeLabel(request.usage_mode)}</small></span><StatusBadge value={statusLabel(request.status)} /></button>)}</div></CardContent></Card>}
    </>}
  </PageFrame>;
}
