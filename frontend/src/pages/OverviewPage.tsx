import { Activity, ArrowRight, BatteryCharging, Blocks, Bot, CheckCircle2, Database, FileClock, Fingerprint, Gavel, KeyRound, Megaphone, Network, RadioTower, RefreshCw, Settings, ShieldCheck, SunMedium, TrendingUp, UsersRound } from "lucide-react";
import { Link } from "react-router-dom";
import { api, formatDate, shortHash } from "../api";
import { useAuth } from "../auth";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";
import { Button, DataTable, ErrorState, LoadingState, Metric, PageHeader, StatusTag, Surface } from "../components/ui";

const capabilityIcons: Record<string, React.ElementType> = {
  IDENTITY: Fingerprint,
  DATA: Database,
  RULE: Gavel,
  COMPUTE: Network,
  AUDIT: ShieldCheck,
};

const scenarioIcons: Record<string, React.ElementType> = {
  RENEWABLE_CONSUMPTION: SunMedium,
  MARKET_TRADING: TrendingUp,
  VPP_OPERATION: BatteryCharging,
  GRID_DISPATCH: RadioTower,
};

const chainIcons: Record<string, React.ElementType> = {
  DID: Fingerprint,
  PRIVACY: Network,
  BLOCKCHAIN: Blocks,
  AGENT: Bot,
};

const flow = [
  ["用户请求", "业务意图"],
  ["Agent 编排", "任务 DAG"],
  ["DID 与授权", "VC + ODRL"],
  ["策略路由", "MPC / FL / TEE"],
  ["安全校核", "调度边界闸门"],
  ["链上存证", "三阶段证据"],
  ["监管审计", "可追溯报告"],
];

type OverviewData = {
  summary: JsonRecord;
  orgs?: JsonRecord[];
  users?: JsonRecord[];
  dids?: JsonRecord[];
  agents?: JsonRecord[];
  logs?: JsonRecord[];
  metrics?: JsonRecord;
};

export function OverviewPage() {
  const { session } = useAuth();
  const isAdmin = session?.user.role_code === "ADMIN";
  const loader = async (): Promise<OverviewData> => {
    const summary = await api<JsonRecord>("/dashboard/summary");
    if (!isAdmin) return { summary };
    const [orgs, users, dids, agents, logs, metrics] = await Promise.all([
      api<JsonRecord[]>("/system/organizations"),
      api<JsonRecord[]>("/system/users"),
      api<JsonRecord[]>("/system/dids"),
      api<JsonRecord[]>("/agents/definitions"),
      api<JsonRecord[]>("/audit/logs"),
      api<JsonRecord>("/metrics/summary"),
    ]);
    return { summary, orgs, users, dids, agents, logs, metrics };
  };
  const { data, loading, error, reload } = useRemote<OverviewData>(loader, [isAdmin]);

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "总览加载失败"} retry={reload} />;
  if (isAdmin) return <AdminOverview data={data} reload={reload} />;

  const summary = data.summary;

  return (
    <>
      <PageHeader
        eyebrow="可信交易空间运行态"
        title="平台总览"
        description={`${String(session?.org.org_name || "当前主体")} · 新能源消纳、市场交易、虚拟电厂与电网调度协同运行`}
        actions={<Button icon={RefreshCw} onClick={reload}>刷新状态</Button>}
      />
      <div className="portal-notice" id="notice">
        <div><Megaphone size={17} /><strong>通知公告</strong></div>
        <span>可信交易空间运行正常，近期结算任务、隐私计算和链上存证均已完成可信校验。</span>
        <Link to="/logs">查看运行记录 <ArrowRight size={14} /></Link>
      </div>
      <div className="metrics-grid five">
        <Metric label="结算任务" value={summary.kpis.task_total} meta="全部可信胶囊" />
        <Metric label="已审计闭环" value={summary.kpis.audited_tasks} meta="证据链完整" tone="green" />
        <Metric label="开放异常" value={summary.kpis.open_anomalies} meta="待监管处置" tone={summary.kpis.open_anomalies ? "red" : "green"} />
        <Metric label="Agent 事件" value={summary.kpis.agent_events} meta="签名工具调用" />
        <Metric label="可信报告" value={summary.kpis.audit_reports} meta="引用证据生成" />
      </div>

      <Surface title="可信交易闭环" note="可信交易胶囊作为统一标识贯穿控制面与确定性执行面">
        <div className="trust-flow">
          {flow.map(([title, note], index) => (
            <div className="flow-fragment" key={title}>
              <div><span>{index + 1}</span><strong>{title}</strong><small>{note}</small></div>
              {index < flow.length - 1 && <ArrowRight size={17} />}
            </div>
          ))}
        </div>
      </Surface>

      <Surface title="四场景一体化协同运行" note={`${summary.data_mode === "MVP_DEMO_DATA" ? "MVP 演示数据" : "业务数据"} · 每一步输出直接成为下一场景的受控输入`}>
        <div className="scenario-coupling">
          {summary.scenario_coordination.map((item: JsonRecord, index: number) => {
            const Icon = scenarioIcons[item.code] || CheckCircle2;
            return (
              <div className="scenario-fragment" key={item.code}>
                <article>
                  <header><span><Icon size={19} /></span><small>0{index + 1}</small><StatusTag value={item.status} /></header>
                  <strong>{item.name}</strong>
                  <b>{item.metric}</b>
                  <dl><dt>输入</dt><dd>{item.input}</dd><dt>输出</dt><dd>{item.output}</dd></dl>
                </article>
                {index < summary.scenario_coordination.length - 1 && <ArrowRight size={18} />}
              </div>
            );
          })}
        </div>
      </Surface>

      <div className="content-grid overview-grid">
        <Surface title="五大可信能力" note="每项能力均形成可验证输出">
          <div className="capability-list">
            {summary.trusted_capabilities.map((item: JsonRecord) => {
              const Icon = capabilityIcons[item.code] || CheckCircle2;
              return (
                <div className="capability-row" key={item.code}>
                  <div className="capability-icon"><Icon size={19} /></div>
                  <div><strong>{item.name}</strong><span>{item.unit}</span></div>
                  <b>{item.metric}</b>
                  <StatusTag value={item.status} label="正常" />
                </div>
              );
            })}
          </div>
        </Surface>
        <Surface title="当前主体待办" note="由角色、权限与流程状态联合生成">
          <div className="todo-list">
            {summary.role_todos.map((item: string, index: number) => (
              <div key={item}><span>{String(index + 1).padStart(2, "0")}</span><strong>{item}</strong><ArrowRight size={16} /></div>
            ))}
          </div>
          <Link className="text-link" to="/workbench">进入角色工作台 <ArrowRight size={15} /></Link>
        </Surface>
      </div>

      <Surface title="四链融合可信治理" note="四条治理链通过可信交易胶囊相互引用，不把技术能力并排堆放">
        <div className="four-chain-grid">
          {summary.four_chain_fusion.map((item: JsonRecord) => {
            const Icon = chainIcons[item.code] || ShieldCheck;
            return (
              <div key={item.code}>
                <span><Icon size={19} /></span>
                <div><strong>{item.name}</strong><small>{item.artifact}</small></div>
                <b>{item.metric}</b>
                <em>{item.unit}</em>
              </div>
            );
          })}
        </div>
      </Surface>

      <Surface title="近期可信交易胶囊" actions={<Link className="text-link" to="/settlements">查看全部 <ArrowRight size={15} /></Link>}>
        <DataTable
          keyField="task_id"
          rows={summary.recent_tasks}
          columns={[
            { key: "capsule_id", label: "胶囊编号", render: (row) => <Link className="mono-link" to={`/settlements?task=${row.task_id}`}>{row.capsule_id}</Link> },
            { key: "task_name", label: "任务名称" },
            { key: "current_stage", label: "当前阶段" },
            { key: "evidence_count", label: "证据" },
            { key: "agent_event_count", label: "Agent 事件" },
            { key: "risk_level", label: "风险", render: (row) => <StatusTag value={row.risk_level} /> },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "created_at", label: "创建时间", render: (row) => formatDate(row.created_at) },
          ]}
        />
      </Surface>
    </>
  );
}

function AdminOverview({ data, reload }: { data: OverviewData; reload: () => Promise<void> }) {
  const summary = data.summary;
  const orgs = data.orgs || [];
  const users = data.users || [];
  const dids = data.dids || [];
  const agents = data.agents || [];
  const logs = data.logs || [];
  const metrics = data.metrics || {};
  const validDids = dids.filter((item) => item.credential_status === "VALID").length;
  const openAnomalies = Number(summary.kpis?.open_anomalies || 0);

  return (
    <>
      <PageHeader
        eyebrow="系统运维工作台"
        title="系统管理员总览"
        description="维护平台主体、DID/VC、Agent 能力凭证与服务运行状态，不参与交易规则审批或结算业务裁决。"
        actions={<Button icon={RefreshCw} onClick={reload}>刷新状态</Button>}
      />
      <div className="metrics-grid five">
        <Metric label="注册组织" value={orgs.length} meta="数据空间参与主体" />
        <Metric label="平台用户" value={users.length} meta="角色授权账号" />
        <Metric label="有效 DID/VC" value={validDids} meta="主体与 Agent 凭证" tone="green" />
        <Metric label="Agent 凭证" value={agents.length} meta="工具白名单已登记" />
        <Metric label="开放异常" value={openAnomalies} meta="平台风险事件" tone={openAnomalies ? "red" : "green"} />
      </div>

      <Surface title="平台基础设施运行状态" note="管理员只维护平台可信基础设施，不直接处理企业原始业务数据">
        <div className="admin-status-grid">
          <div><Activity size={19} /><span><strong>API 服务</strong><small>FastAPI 控制面</small></span><StatusTag value="HEALTHY" label="运行正常" /></div>
          <div><Database size={19} /><span><strong>业务数据库</strong><small>组织、任务与证据索引</small></span><StatusTag value="HEALTHY" label="连接正常" /></div>
          <div><ShieldCheck size={19} /><span><strong>数据域隔离</strong><small>原始数据不进入业务库</small></span><StatusTag value="PASSED" label="边界正常" /></div>
          <div><Blocks size={19} /><span><strong>存证适配器</strong><small>{metrics.evidence_count || 0} 项证据索引</small></span><StatusTag value="READY" label="接口就绪" /></div>
        </div>
      </Surface>

      <div className="content-grid overview-grid">
        <Surface title="管理员职责入口" note="按运维职责快速进入对应管理模块">
          <div className="admin-links">
            <Link to="/system"><UsersRound size={19} /><span><strong>主体与 DID</strong><small>维护组织、用户和凭证状态</small></span><ArrowRight size={16} /></Link>
            <Link to="/agents"><Bot size={19} /><span><strong>Agent 协同</strong><small>查看能力凭证与工具白名单</small></span><ArrowRight size={16} /></Link>
            <Link to="/metrics"><Activity size={19} /><span><strong>运行指标</strong><small>检查计算、存证和服务指标</small></span><ArrowRight size={16} /></Link>
            <Link to="/logs"><FileClock size={19} /><span><strong>全过程日志</strong><small>追踪平台操作和异常事件</small></span><ArrowRight size={16} /></Link>
          </div>
        </Surface>
        <Surface title="当前运维待办" note="系统管理员只处理平台运行与身份治理事项">
          <div className="todo-list">
            {(summary.role_todos || ["维护 DID/VC 状态", "检查服务与节点健康"]).map((item: string, index: number) => (
              <div key={item}><span>{String(index + 1).padStart(2, "0")}</span><strong>{item}</strong><ArrowRight size={16} /></div>
            ))}
          </div>
          <Link className="text-link" to="/system">进入身份治理 <ArrowRight size={15} /></Link>
        </Surface>
      </div>

      <Surface title="最近平台操作" note="仅展示操作摘要、结果和追踪编号，不展示企业原始明细" actions={<Link className="text-link" to="/logs">查看全部 <ArrowRight size={15} /></Link>}>
        <DataTable
          keyField="log_id"
          rows={logs.slice(0, 6)}
          empty="暂无平台操作记录"
          columns={[
            { key: "action_code", label: "操作" },
            { key: "actor_name", label: "操作主体" },
            { key: "target_type", label: "对象类型" },
            { key: "result", label: "结果", render: (row) => <StatusTag value={row.result} /> },
            { key: "trace_id", label: "追踪编号", render: (row) => <code className="mono-text" title={row.trace_id}>{shortHash(row.trace_id, 8)}</code> },
            { key: "occurred_at", label: "时间", render: (row) => formatDate(row.occurred_at) },
          ]}
        />
      </Surface>

      <Surface title="身份治理摘要" note="平台主体与能力凭证的当前状态">
        <div className="admin-governance-grid">
          <div><Settings size={19} /><span><strong>组织主体</strong><small>发电、售电、交易、监管及管理组织</small></span><b>{orgs.length}</b></div>
          <div><UsersRound size={19} /><span><strong>业务用户</strong><small>按角色进行菜单和字段授权</small></span><b>{users.length}</b></div>
          <div><KeyRound size={19} /><span><strong>有效凭证</strong><small>DID/VC 与 Agent 能力凭证</small></span><b>{validDids}</b></div>
          <div><ShieldCheck size={19} /><span><strong>隐私边界</strong><small>原始数据集中存储</small></span><b>0</b></div>
        </div>
      </Surface>
    </>
  );
}
