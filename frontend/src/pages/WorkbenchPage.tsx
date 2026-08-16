import type { ElementType } from "react";
import { ArrowRight, BarChart3, Building2, CheckCircle2, Clock3, Database, FileCheck2, FileClock, Gavel, KeyRound, LockKeyhole, Network, RefreshCw, ShieldCheck, Upload, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { api, formatDate, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, DataTable, ErrorState, LoadingState, Metric, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { ROLE_LABELS } from "../types";
import type { JsonRecord, RoleCode } from "../types";

type WorkbenchAction = {
  title: string;
  description: string;
  cta: string;
  path: string;
  icon: ElementType;
};

type RoleConfig = {
  title: string;
  description: string;
  nextStep: string;
  nextPath: string;
  actions: WorkbenchAction[];
};

type WorkbenchData = {
  tasks: JsonRecord[];
  organizations: JsonRecord[];
  summary: JsonRecord;
  rules: JsonRecord[];
};

const roleConfig: Record<RoleCode, RoleConfig> = {
  GENERATOR: {
    title: "发电企业工作台",
    description: "处理发电数据登记、结果确认和相关审计凭证。",
    nextStep: "登记发电数据",
    nextPath: "/data/generation",
    actions: [
      { title: "登记发电数据", description: "提交计量或新能源预测数据。", cta: "进入数据登记", path: "/data/generation", icon: Database },
      { title: "确认结果", description: "查看本方结果并完成确认。", cta: "查看结果", path: "/results", icon: FileCheck2 },
      { title: "审计凭证", description: "核对本次调用的凭证记录。", cta: "查看凭证", path: "/evidence", icon: FileClock },
    ],
  },
  RETAILER: {
    title: "售电企业工作台",
    description: "处理用电数据登记、隐私分析和结果确认。",
    nextStep: "登记用电数据",
    nextPath: "/data/retail",
    actions: [
      { title: "登记用电数据", description: "提交履约、负荷或资源数据。", cta: "进入数据登记", path: "/data/retail", icon: Database },
      { title: "发起隐私分析", description: "获取峰谷特征和响应潜力等聚合结果。", cta: "开始分析", path: "/compute", icon: LockKeyhole },
      { title: "确认聚合结果", description: "查看结果回执和确认状态。", cta: "查看结果", path: "/results", icon: FileCheck2 },
    ],
  },
  EXCHANGE: {
    title: "交易中心工作台",
    description: "处理待验证文件、授权调用、结果确认和审计事项。",
    nextStep: "上传验证文件",
    nextPath: "/settlements",
    actions: [
      { title: "上传验证文件", description: "校验数据来源、授权范围并启动验证。", cta: "导入文件", path: "/settlements", icon: Upload },
      { title: "查看授权规则", description: "确认用途、输出范围和访问次数。", cta: "查看规则", path: "/rules", icon: Gavel },
      { title: "查看计算回执", description: "核对策略、结果哈希和数据边界。", cta: "进入回执", path: "/compute", icon: Network },
    ],
  },
  REGULATOR: {
    title: "监管审计工作台",
    description: "从任务、凭证和风险记录核验跨主体数据调用。",
    nextStep: "查看最近审计事项",
    nextPath: "/audit",
    actions: [
      { title: "查看调用审计", description: "按任务查看采集、授权、计算和审计记录。", cta: "开始审计", path: "/audit", icon: ShieldCheck },
      { title: "处理风险事件", description: "查看待处置风险并记录处理意见。", cta: "查看风险", path: "/anomalies", icon: BarChart3 },
      { title: "查看审计报告", description: "查看已生成的报告和凭证。", cta: "查看报告", path: "/reports", icon: FileCheck2 },
    ],
  },
  ADMIN: {
    title: "平台运维工作台",
    description: "处理主体身份、平台服务和运行记录。",
    nextStep: "检查身份和服务状态",
    nextPath: "/system",
    actions: [
      { title: "组织与身份", description: "查看组织、用户和身份凭证状态。", cta: "进入身份管理", path: "/system", icon: Users },
      { title: "系统服务状态", description: "查看计算、存证和平台服务状态。", cta: "查看状态", path: "/metrics", icon: Network },
      { title: "操作记录", description: "追踪平台操作和风险处置。", cta: "查看记录", path: "/logs", icon: FileClock },
    ],
  },
};

const statusServices = [
  ["IDENTITY", "身份认证服务"],
  ["RULE", "策略服务"],
  ["COMPUTE", "计算节点"],
  ["DATA", "数据目录服务"],
  ["AUDIT", "审计与回执服务"],
] as const;

function organizationName(organizations: JsonRecord[], orgId: unknown) {
  const name = organizations.find((item) => item.org_id === orgId)?.org_name;
  return name || (orgId ? shortHash(String(orgId), 10) : "未提供");
}

function formatDeadline(value: unknown) {
  if (!value) return "-";
  return String(value).slice(0, 10).replace(/-/g, "/");
}

export function WorkbenchPage() {
  const { session } = useAuth();
  if (!session) return null;
  const role = session.user.role_code;
  const config = roleConfig[role];
  const canReadRules = ["EXCHANGE", "REGULATOR", "ADMIN"].includes(role);
  const loader = async (): Promise<WorkbenchData> => {
    const [tasks, organizations, summary, rules] = await Promise.all([
      api<JsonRecord[]>("/settlement/tasks"),
      api<JsonRecord[]>("/system/organizations"),
      api<JsonRecord>("/dashboard/summary"),
      canReadRules ? api<JsonRecord[]>("/rules") : Promise.resolve([] as JsonRecord[]),
    ]);
    return { tasks, organizations, summary, rules };
  };
  const { data, loading, error, reload } = useRemote(loader, [role, canReadRules]);

  if (loading) return <LoadingState label="正在读取工作空间任务" />;
  if (error || !data) return <ErrorState message={error || "工作台加载失败"} retry={reload} />;

  const tasks = data.tasks;
  const pendingTasks = tasks.filter((item) => item.status !== "AUDITED");
  const runningTasks = tasks.filter((item) => ["AUTHORIZED", "COMPUTING", "RUNNING", "EVIDENCED"].includes(String(item.status))).length;
  const exceptionTasks = tasks.filter((item) => ["FAILED", "INVALID", "REJECTED"].includes(String(item.status)) || item.risk_level === "HIGH").length;
  const completedTasks = tasks.filter((item) => item.status === "AUDITED").length;
  const openAnomalies = Number(data.summary.kpis?.open_anomalies || 0);
  const activeRule = data.rules.find((item) => item.status === "ACTIVE");
  const organization = String(session.org.org_name || "当前组织");
  const capabilityByCode = new Map<string, JsonRecord>((data.summary.trusted_capabilities || []).map((item: JsonRecord) => [String(item.code), item]));
  const latestSync = tasks[0]?.updated_at || tasks[0]?.created_at;

  return (
    <>
      <PageHeader
        eyebrow="工作入口"
        title={config.title}
        description={config.description}
        actions={<Button icon={RefreshCw} onClick={reload}>刷新任务</Button>}
      />

      <section className="workspace-bar" aria-label="当前工作空间信息">
        <div className="workspace-context-primary"><div className="workspace-icon"><Building2 size={19} /></div><div><span>当前组织</span><strong>{organization}</strong></div></div>
        <div className="workspace-context-item"><span>当前工作空间</span><strong>默认业务空间</strong></div>
        <div className="workspace-context-item"><span>环境</span><strong>演示环境</strong></div>
        <div className="workspace-context-item"><span>规则版本</span><strong>{activeRule?.rule_version || "按任务绑定"}</strong></div>
        <div className="workspace-context-item"><span>最近同步</span><strong>{latestSync ? formatDate(latestSync) : "本次载入"}</strong></div>
        <Link className="button button-primary workspace-action" to={config.nextPath}><Upload size={15} />{config.nextStep}</Link>
      </section>

      <div className="policy-summary" aria-label="当前空间策略">
        <div className="policy-summary-label"><ShieldCheck size={16} /><strong>当前空间策略</strong></div>
        <div><span>数据出域</span><strong>禁止</strong></div>
        <div><span>结果生效</span><strong>确认后生效</strong></div>
        <div><span>审计留痕</span><strong>回执可查</strong></div>
        <div><span>授权规则</span><strong>{activeRule?.rule_version || "按任务绑定"}</strong></div>
      </div>

      <div className="metrics-grid four workbench-kpis">
        <Metric label="待处理任务" value={pendingTasks.length} meta="当前工作空间" tone={pendingTasks.length ? "amber" : "green"} />
        <Metric label="待确认结果" value={tasks.filter((item) => item.result_count && item.status !== "AUDITED").length} meta="需完成签名或确认" tone="amber" />
        <Metric label="执行中任务" value={runningTasks} meta="授权 / 计算 / 生成凭证" />
        <Metric label="异常任务" value={exceptionTasks + openAnomalies} meta="任务与风险事件" tone={exceptionTasks + openAnomalies ? "red" : "green"} />
      </div>

      <div className="workbench-toolbar">
        <div><strong>常用操作</strong><span>按当前身份显示可用入口</span></div>
        <div className="workbench-quick-actions">
          {config.actions.map((action) => {
            const Icon = action.icon;
            return <Link key={action.path} className="quick-action" to={action.path}><Icon size={15} /><span>{action.title}</span><ArrowRight size={13} /></Link>;
          })}
        </div>
      </div>

      <div className="workbench-grid">
        <div className="workbench-main">
          <Surface title="待处理任务" note={`${pendingTasks.length} 项需要继续处理`} actions={<Link className="text-link" to="/settlements">查看全部 <ArrowRight size={14} /></Link>}>
            <DataTable
              keyField="task_id"
              rows={pendingTasks}
              empty="当前没有待处理任务；新建或导入验证任务后会显示在这里。"
              columns={[
                { key: "task_id", label: "任务编号", render: (row) => <span className="mono-text">{shortHash(row.task_id, 8)}</span> },
                { key: "task_name", label: "业务对象" },
                { key: "creator_org_id", label: "申请机构", render: (row) => organizationName(data.organizations, row.creator_org_id) },
                { key: "trade_batch_no", label: "数据批次", render: (row) => <span className="mono-text">{row.trade_batch_no || "-"}</span> },
                { key: "created_at", label: "创建时间", render: (row) => formatDate(row.created_at) },
                { key: "period_end", label: "截止日期", render: (row) => formatDeadline(row.period_end) },
                { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
                { key: "action", label: "操作", render: (row) => <Link className="table-link" to={`/settlements?task=${row.task_id}`}>{row.status === "AUDITED" ? "查看" : "继续处理"} <ArrowRight size={13} /></Link> },
              ]}
            />
          </Surface>

          <Surface title="最近调用记录" note="按最近创建时间展示当前身份可见任务" actions={<Link className="text-link" to="/audit">查看审计链路 <ArrowRight size={14} /></Link>}>
            <DataTable
              keyField="task_id"
              rows={tasks.slice(0, 6)}
              empty="尚未产生调用记录。"
              columns={[
                { key: "capsule_id", label: "调用编号", render: (row) => <span className="mono-text">{shortHash(row.capsule_id, 9)}</span> },
                { key: "creator_org_id", label: "调用方", render: (row) => organizationName(data.organizations, row.creator_org_id) },
                { key: "task_name", label: "计算任务" },
                { key: "rule_id", label: "规则", render: (row) => <span className="mono-text">{shortHash(row.rule_id, 8)}</span> },
                { key: "created_at", label: "执行时间", render: (row) => formatDate(row.created_at) },
                { key: "status", label: "结果状态", render: (row) => <StatusTag value={row.status} /> },
                { key: "evidence_count", label: "审计回执", render: (row) => `${row.evidence_count || 0} 项` },
              ]}
            />
          </Surface>
        </div>

        <aside className="workbench-side">
          <Surface title="系统服务状态" note="来自当前工作空间可见服务数据">
            <div className="service-status-list">
              {statusServices.map(([code, label]) => {
                const capability = capabilityByCode.get(code);
                return <div key={code}><span className="service-status-name"><i className={`service-dot ${capability?.status === "HEALTHY" ? "is-healthy" : ""}`} />{label}</span><StatusTag value={capability?.status || "UNKNOWN"} /></div>;
              })}
            </div>
            <Link className="panel-link" to="/metrics"><BarChart3 size={14} />查看完整服务指标 <ArrowRight size={13} /></Link>
          </Surface>

          <Surface title="近期告警" note="风险事件与任务异常">
            {openAnomalies || exceptionTasks ? (
              <div className="alert-list">
                {openAnomalies > 0 && <Link to="/anomalies"><span><i className="alert-dot danger" />待处置风险事件</span><strong>{openAnomalies} 项</strong><ArrowRight size={14} /></Link>}
                {exceptionTasks > 0 && <Link to="/settlements"><span><i className="alert-dot warning" />任务需要复核</span><strong>{exceptionTasks} 项</strong><ArrowRight size={14} /></Link>}
              </div>
            ) : <div className="alert-empty"><CheckCircle2 size={17} /><span>当前没有需要处理的系统告警。</span></div>}
          </Surface>

          <Surface title="当前身份" note="权限由服务端认证结果决定">
            <div className="identity-summary"><div className="identity-summary-icon"><KeyRound size={17} /></div><div><strong>{session.user.display_name}</strong><span>{ROLE_LABELS[role]} · {session.user.username}</span></div></div>
            <div className="identity-summary-meta"><span>账号状态</span><StatusTag value={session.user.status} /><span>身份凭证</span><StatusTag value="VALID" /></div>
          </Surface>
        </aside>
      </div>

      <div className="workbench-footer-note"><Clock3 size={14} /><span>页面数据由当前组织权限范围内的任务与服务接口返回；没有业务数据时不展示虚构结果。</span></div>
    </>
  );
}
