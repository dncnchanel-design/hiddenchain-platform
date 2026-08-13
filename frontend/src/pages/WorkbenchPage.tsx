import type { ElementType } from "react";
import { ArrowRight, Blocks, Bot, Calculator, CheckCircle2, ClipboardCheck, Database, FileCheck2, FileClock, Gavel, LockKeyhole, Network, RefreshCw, ShieldCheck, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
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

const roleConfig: Record<RoleCode, RoleConfig> = {
  GENERATOR: {
    title: "发电企业工作台",
    description: "管理发电数据，确认已完成的结果回执。",
    nextStep: "登记发电数据",
    nextPath: "/data/generation",
    actions: [
      { title: "登记发电数据", description: "提交计量或新能源预测数据，供授权任务调用。", cta: "登记数据", path: "/data/generation", icon: Database },
      { title: "确认结果", description: "查看本方结果并完成确认。", cta: "查看结果", path: "/results", icon: FileCheck2 },
      { title: "查看凭证", description: "核对本次调用留下的可信凭证。", cta: "进入凭证", path: "/evidence", icon: Blocks },
    ],
  },
  RETAILER: {
    title: "售电企业工作台",
    description: "管理售电与用电数据，参与不交换原始明细的联合计算。",
    nextStep: "登记用电数据",
    nextPath: "/data/retail",
    actions: [
      { title: "登记用电数据", description: "提交履约、负荷或资源数据，供授权任务使用。", cta: "登记数据", path: "/data/retail", icon: Database },
      { title: "发起隐私分析", description: "获得峰谷特征和响应潜力等聚合结果。", cta: "开始分析", path: "/compute", icon: LockKeyhole },
      { title: "确认聚合结果", description: "查看结果回执和确认状态。", cta: "查看结果", path: "/results", icon: FileCheck2 },
    ],
  },
  EXCHANGE: {
    title: "可信调用工作台",
    description: "组织跨主体数据调用，确认隐私计算和可核验证据。",
    nextStep: "导入验证文件",
    nextPath: "/settlements",
    actions: [
      { title: "导入验证文件", description: "校验数据来源、授权范围并自动运行一笔仿真任务。", cta: "开始导入", path: "/settlements", icon: Calculator },
      { title: "检查使用规则", description: "确认数据用途、输出范围和访问次数。", cta: "查看规则", path: "/rules", icon: Gavel },
      { title: "查看隐私回执", description: "核对计算策略、结果哈希和原始数据边界。", cta: "进入回执", path: "/compute", icon: Network },
    ],
  },
  REGULATOR: {
    title: "可信调用审计台",
    description: "从任务、凭证和风险记录判断一次跨主体数据调用是否可信。",
    nextStep: "查看最近可信调用",
    nextPath: "/audit",
    actions: [
      { title: "查看可信调用", description: "按任务查看采集、授权、计算和审计记录。", cta: "开始审计", path: "/audit", icon: ClipboardCheck },
      { title: "处理风险事件", description: "查看待处置风险并记录处理意见。", cta: "查看风险", path: "/anomalies", icon: ShieldCheck },
      { title: "查看审计报告", description: "查看已生成的审计报告和凭证。", cta: "查看报告", path: "/reports", icon: FileCheck2 },
    ],
  },
  ADMIN: {
    title: "平台运维工作台",
    description: "维护主体身份、平台服务和运行记录。",
    nextStep: "检查身份和服务状态",
    nextPath: "/system",
    actions: [
      { title: "维护主体与凭证", description: "查看组织、用户和身份凭证状态。", cta: "进入身份管理", path: "/system", icon: Users },
      { title: "检查服务运行", description: "查看计算、存证和平台服务状态。", cta: "查看状态", path: "/metrics", icon: Network },
      { title: "查看操作记录", description: "追踪平台操作和风险处置。", cta: "查看记录", path: "/logs", icon: FileClock },
    ],
  },
};

export function WorkbenchPage() {
  const { session } = useAuth();
  const role = session!.user.role_code;
  const config = roleConfig[role];
  const { data, loading, error, reload } = useRemote<JsonRecord[]>(() => api("/settlement/tasks"), []);

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "工作台加载失败"} retry={reload} />;

  const pendingTasks = data.filter((item) => item.status !== "AUDITED").length;
  const auditedTasks = data.filter((item) => item.status === "AUDITED").length;
  const evidenceCount = data.reduce((total, item) => total + Number(item.evidence_count || 0), 0);
  const organizationName = String(session?.org?.org_name || "当前主体");

  return (
    <>
      <PageHeader
        eyebrow="我的工作台"
        title={config.title}
        description={config.description}
        actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>}
      />

      <div className="workbench-hero">
        <div className="workbench-hero-intro">
          <div className="workbench-hero-heading"><div className="workbench-hero-icon"><ShieldCheck size={23} /></div><div><span>当前主体</span><h2>{organizationName}</h2></div></div>
          <p>数据按授权调用，计算只返回必要结果。</p>
          <div className="workbench-hero-status"><StatusTag value="HEALTHY" label="工作空间正常" /><span>{ROLE_LABELS[role]}</span><span>原始数据不出域</span></div>
        </div>
        <div className="workbench-next-step">
          <span>下一步</span>
          <strong>{config.nextStep}</strong>
          <Link to={config.nextPath}>立即处理 <ArrowRight size={15} /></Link>
        </div>
      </div>

      <div className="workbench-kpis">
        <Metric label="待验证任务" value={pendingTasks} meta="需要继续操作" tone={pendingTasks ? "amber" : "green"} />
        <Metric label="已完成调用" value={auditedTasks} meta="已形成完整回执" tone="green" />
        <Metric label="可核验证据" value={evidenceCount} meta="授权、计算与审计记录" />
      </div>

      <Surface title="快捷入口">
        <div className="workbench-actions">
          {config.actions.map((action) => {
            const Icon = action.icon;
            return <Link className="workbench-action-card" to={action.path} key={action.path}>
              <div className="workbench-action-icon"><Icon size={21} /></div>
              <div><strong>{action.title}</strong><p>{action.description}</p><span>{action.cta}<ArrowRight size={14} /></span></div>
            </Link>;
          })}
        </div>
      </Surface>

      <div className="content-grid overview-grid">
        <Surface title="最近可信调用" actions={<Link className="text-link" to="/settlements">查看全部 <ArrowRight size={14} /></Link>}>
          <DataTable
            keyField="task_id"
            rows={data.slice(0, 6)}
            empty="暂时没有与你相关的任务"
            columns={[
              { key: "task_name", label: "任务" },
              { key: "current_stage", label: "当前进度" },
              { key: "result_count", label: "结果", render: (row) => `${row.result_count || 0} 份` },
              { key: "evidence_count", label: "证据", render: (row) => `${row.evidence_count || 0} 项` },
              { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
              { key: "action", label: "操作", render: (row) => <Link className="table-link" to={`/settlements?task=${row.task_id}`}>查看任务</Link> },
            ]}
          />
        </Surface>
        <Surface title="平台安全边界">
          <div className="workbench-guardrails">
            <div><Database size={18} /><span><strong>数据原文</strong><small>留在主体域内，不在平台汇聚</small></span><CheckCircle2 size={16} /></div>
            <div><LockKeyhole size={18} /><span><strong>调用结果</strong><small>按授权范围最小披露</small></span><CheckCircle2 size={16} /></div>
            <div><ShieldCheck size={18} /><span><strong>计算过程</strong><small>只保留回执、签名与哈希</small></span><CheckCircle2 size={16} /></div>
            <div><Blocks size={18} /><span><strong>问题追溯</strong><small>每笔任务都能回到证据时间线</small></span><CheckCircle2 size={16} /></div>
          </div>
        </Surface>
      </div>
    </>
  );
}
