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
    description: "管理发电侧可调用数据，确认经过隐私计算的结果回执。",
    nextStep: "登记或更新发电侧数据",
    nextPath: "/data/generation",
    actions: [
      { title: "登记可调用数据", description: "登记计量和新能源预测摘要，原始记录留在本域。", cta: "登记数据", path: "/data/generation", icon: Database },
      { title: "确认结果回执", description: "查看按主体最小披露的计算结果，并完成签名确认。", cta: "查看结果", path: "/results", icon: FileCheck2 },
      { title: "核验数据回执", description: "检查授权、计算和结果哈希是否与平台记录一致。", cta: "进入核验", path: "/evidence", icon: Blocks },
    ],
  },
  RETAILER: {
    title: "售电企业工作台",
    description: "管理售电与用电数据，在不暴露单户明细的前提下参与联合计算。",
    nextStep: "检查用电数据是否已授权调用",
    nextPath: "/data/retail",
    actions: [
      { title: "登记用电数据", description: "登记履约、负荷和虚拟电厂资源的可调用引用。", cta: "登记数据", path: "/data/retail", icon: Database },
      { title: "发起隐私分析", description: "只返回聚合分析结果，不导出用户负荷曲线。", cta: "开始分析", path: "/compute", icon: LockKeyhole },
      { title: "确认聚合结果", description: "查看结果回执和签名状态，确认本方可见内容。", cta: "查看结果", path: "/results", icon: FileCheck2 },
    ],
  },
  EXCHANGE: {
    title: "业务协同工作台",
    description: "组织数据调用和隐私计算，把电力交易作为一个可运行的验证场景。",
    nextStep: "发起一笔场景验证任务",
    nextPath: "/settlements",
    actions: [
      { title: "发起场景验证", description: "选择参与主体和规则，生成一笔可追踪的验证任务。", cta: "创建任务", path: "/settlements", icon: Calculator },
      { title: "检查使用规则", description: "确认数据用途、输出范围和人工审批边界。", cta: "查看规则", path: "/rules", icon: Gavel },
      { title: "查看计算进度", description: "查看隐私计算回执、策略路由和执行结果。", cta: "进入计算", path: "/compute", icon: Network },
    ],
  },
  REGULATOR: {
    title: "监管方工作台",
    description: "从任务状态、证据回执和异常事件快速判断一笔调用是否可信。",
    nextStep: "查看最近任务的证据时间线",
    nextPath: "/audit",
    actions: [
      { title: "审计验证任务", description: "按任务查看数据调用、隐私计算和结果证据。", cta: "开始审计", path: "/audit", icon: ClipboardCheck },
      { title: "处理风险事件", description: "查看待处置异常，记录复核结论和处理意见。", cta: "查看风险", path: "/anomalies", icon: ShieldCheck },
      { title: "生成可信报告", description: "基于结构化证据生成可引用、可追溯的审计报告。", cta: "查看报告", path: "/reports", icon: FileCheck2 },
    ],
  },
  ADMIN: {
    title: "平台运维工作台",
    description: "维护主体身份、平台服务和运行记录，不参与业务结果裁决。",
    nextStep: "检查主体凭证和服务状态",
    nextPath: "/system",
    actions: [
      { title: "维护主体与凭证", description: "查看组织、用户和 DID/VC 的有效状态。", cta: "进入身份治理", path: "/system", icon: Users },
      { title: "检查服务运行", description: "查看计算、存证和接口适配器是否正常。", cta: "查看指标", path: "/metrics", icon: Network },
      { title: "查看操作记录", description: "追踪登录、授权、计算和异常处置等平台动作。", cta: "查看日志", path: "/logs", icon: FileClock },
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
          <p>平台只交换可验证的数据引用和计算结果，原始业务数据不会离开主体域。</p>
          <div className="workbench-hero-status"><StatusTag value="HEALTHY" label="工作空间正常" /><span>当前角色：{ROLE_LABELS[role]}</span><span>原始数据：不出域</span></div>
        </div>
        <div className="workbench-next-step">
          <span>建议下一步</span>
          <strong>{config.nextStep}</strong>
          <Link to={config.nextPath}>立即处理 <ArrowRight size={15} /></Link>
        </div>
      </div>

      <div className="workbench-kpis">
        <Metric label="待处理任务" value={pendingTasks} meta="需要继续操作" tone={pendingTasks ? "amber" : "green"} />
        <Metric label="已完成任务" value={auditedTasks} meta="已形成完整回执" tone="green" />
        <Metric label="可核验证据" value={evidenceCount} meta="授权、计算与结果记录" />
      </div>

      <Surface title="现在可以做什么" note="从下面进入与你的角色相关的业务操作">
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
        <Surface title="最近任务" note={`${data.length} 个与你相关的验证任务`} actions={<Link className="text-link" to="/settlements">查看全部 <ArrowRight size={14} /></Link>}>
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
        <Surface title="平台会替你守住什么" note="你只需要关注业务动作，平台负责执行边界">
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
