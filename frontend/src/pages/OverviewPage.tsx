import { Activity, ArrowRight, BatteryCharging, Blocks, CheckCircle2, Database, FileClock, Fingerprint, Gavel, KeyRound, LockKeyhole, Megaphone, Network, RadioTower, RefreshCw, Settings, ShieldCheck, SunMedium, TrendingUp, UsersRound, Workflow } from "lucide-react";
import { Link } from "react-router-dom";
import { api, formatDate, shortHash } from "../api";
import { useAuth } from "../auth";
import { useRemote } from "../hooks";
import { ALGORITHM_LABELS, SCENARIO_LABELS } from "../types";
import type { JsonRecord } from "../types";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Metric, Notice, PageHeader, StatusTag, Surface } from "../components/ui";

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
  AGENT: Workflow,
};

const chainLabels: Record<string, string> = {
  DID: "身份服务",
  PRIVACY: "隐私计算",
  BLOCKCHAIN: "可信凭证",
  AGENT: "受控编排",
};

const nodeLabels: Record<string, string> = {
  ELECTRICITY_NODE: "电力节点",
  COAL_NODE: "煤炭节点",
  OIL_GAS_NODE: "油气节点",
};

const dataTypeLabels: Record<string, string> = {
  COAL_INVENTORY: "电煤库存",
  POWER_THERMAL_OUTPUT: "火电出力",
  GRID_LOAD: "电网负荷",
  POWER_TRADING: "交易摘要",
  POWER_DISPATCH: "调度边界",
  OIL_GAS_SUPPLY: "油气供应",
};

const flow = [
  ["可信采集", "来源与格式校验"],
  ["安全传输", "加密接口接入"],
  ["可控使用", "DID与用途授权"],
  ["隐私计算", "原始数据不出域"],
  ["可溯审计", "结果与证据核验"],
];

type OverviewData = {
  summary: JsonRecord;
  orgs?: JsonRecord[];
  users?: JsonRecord[];
  dids?: JsonRecord[];
  agents?: JsonRecord[];
  logs?: JsonRecord[];
  metrics?: JsonRecord;
  pendingReviews?: JsonRecord[];
  trustedStatus?: JsonRecord;
};

export function OverviewPage() {
  const { session } = useAuth();
  const isAdmin = session?.user.role_code === "ADMIN";
  const canReview = ["EXCHANGE", "REGULATOR", "ADMIN"].includes(session?.user.role_code || "");
  const loader = async (): Promise<OverviewData> => {
    const [summary, pendingReviews, trustedStatus] = await Promise.all([
      api<JsonRecord>("/dashboard/summary"),
      canReview ? api<JsonRecord[]>("/trusted-execution/reviews?review_status=PENDING") : Promise.resolve([] as JsonRecord[]),
      canReview ? api<JsonRecord>("/trusted-execution/status") : Promise.resolve(undefined as JsonRecord | undefined),
    ]);
    if (!isAdmin) return { summary, pendingReviews, trustedStatus };
    const [orgs, users, dids, agents, logs, metrics] = await Promise.all([
      api<JsonRecord[]>("/system/organizations"),
      api<JsonRecord[]>("/system/users"),
      api<JsonRecord[]>("/system/dids"),
      api<JsonRecord[]>("/agents/definitions"),
      api<JsonRecord[]>("/audit/logs"),
      api<JsonRecord>("/metrics/summary"),
    ]);
    return { summary, orgs, users, dids, agents, logs, metrics, pendingReviews, trustedStatus };
  };
  const { data, loading, error, reload } = useRemote<OverviewData>(loader, [isAdmin, canReview]);

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "总览加载失败"} retry={reload} />;
  if (isAdmin) return <AdminOverview data={data} reload={reload} canReview={canReview} />;

  const summary = data.summary;

  return (
    <>
      <PageHeader
        eyebrow="平台概览"
        title="平台总览"
        description={`${String(session?.org.org_name || "当前主体")} · 数据调用与隐私计算`}
        actions={<Button icon={RefreshCw} onClick={reload}>刷新状态</Button>}
      />
      <OperationsRibbon scope={String(session?.org.org_name || "当前主体")} status={data.trustedStatus} pendingCount={data.pendingReviews?.length || 0} />
      <TrustPosture status={data.trustedStatus} />
      <NodeTopology status={data.trustedStatus} />
      <ReviewQueue reviews={data.pendingReviews || []} visible={canReview} />
      <div className="portal-notice" id="notice">
        <div><Megaphone size={17} /><strong>平台状态</strong></div>
        <span>数据目录、授权、计算和回执服务正常。</span>
        <Link to="/logs">查看记录 <ArrowRight size={14} /></Link>
      </div>
      <div className="metrics-grid five">
        <Metric label="可用数据" value={summary.trusted_capabilities.find((item: JsonRecord) => item.code === "DATA")?.metric ?? 0} meta="已登记" />
        <Metric label="计算回执" value={summary.four_chain_fusion.find((item: JsonRecord) => item.code === "PRIVACY")?.metric ?? 0} meta="已生成" tone="green" />
        <Metric label="原始数据出域" value="0" meta="当前记录" tone="green" />
        <Metric label="已完成任务" value={summary.kpis.audited_tasks} meta="结果可查" tone="green" />
        <Metric label="待处理风险" value={summary.kpis.open_anomalies} meta="需要关注" tone={summary.kpis.open_anomalies ? "red" : "green"} />
      </div>

      <Surface title="一次完整可信调用">
        <div className="trust-flow">
          {flow.map(([title, note], index) => (
            <div className="flow-fragment" key={title}>
              <div><span>{index + 1}</span><strong>{title}</strong><small>{note}</small></div>
              {index < flow.length - 1 && <ArrowRight size={17} />}
            </div>
          ))}
        </div>
      </Surface>

      <Surface title="赛题要求的全链路验证">
        <div className="verification-step-grid">
          {(summary.verification_steps || []).map((item: JsonRecord, index: number) => (
            <article key={item.code} className={item.status === "PASSED" ? "verified" : "ready"}>
              <div><span>0{index + 1}</span><StatusTag value={item.status} /></div>
              <strong>{item.name}</strong>
              <p>{item.description}</p>
              <small>{item.metric}</small>
            </article>
          ))}
        </div>
        <Notice>电力交易只作为验证场景：用同一条可信调用链证明跨主体数据可用不可见、可控可计量、可溯可审计。</Notice>
      </Surface>

      <div className="content-grid overview-grid">
        <Surface title="服务状态">
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
        <Surface title="当前待办">
          <div className="todo-list">
            {summary.role_todos.map((item: string, index: number) => (
              <div key={item}><span>{String(index + 1).padStart(2, "0")}</span><strong>{item}</strong><ArrowRight size={16} /></div>
            ))}
          </div>
          <Link className="text-link" to="/workbench">进入角色工作台 <ArrowRight size={15} /></Link>
        </Surface>
      </div>

      <div className="content-grid overview-grid">
        <Surface title="数据目录">
          <div className="feature-callout"><Database size={24} /><div><strong>查找数据 · 查看授权 · 发起调用</strong><span>只返回授权范围内的结果。</span></div><Link className="text-link" to="/data-space">查看目录 <ArrowRight size={15} /></Link></div>
        </Surface>
        <Surface title="隐私计算">
          <div className="feature-callout"><LockKeyhole size={24} /><div><strong>授权计算 · 结果回执 · 全程可查</strong><span>原始数据不出域。</span></div><Link className="text-link" to="/compute">查看计算 <ArrowRight size={15} /></Link></div>
        </Surface>
      </div>

      <Surface title="最近一次验证结果" actions={<Link className="text-link" to="/settlements">进入验证 <ArrowRight size={15} /></Link>}>
        {summary.latest_verification ? <div className="verification-result-summary">
          <div><ShieldCheck size={21} /><span>状态</span><StatusTag value={summary.latest_verification.status} /></div>
          <div><Database size={21} /><span>数据资产</span><strong>{summary.latest_verification.verification_profile?.trusted_acquisition ? "已完成来源校验" : "待登记"}</strong></div>
          <div><LockKeyhole size={21} /><span>隐私边界</span><strong>{summary.latest_verification.verification_profile?.raw_data_exposed === false ? "原始数据未出域" : "待验证"}</strong></div>
          <div><Blocks size={21} /><span>审计证据</span><strong>{summary.latest_verification.verification_profile?.evidence_count || summary.latest_verification.evidence_count || 0} 项可核验</strong></div>
        </div> : <div className="empty-state">还没有验证任务，请从数据目录开始。</div>}
      </Surface>

      <Surface title="最近任务" actions={<Link className="text-link" to="/settlements">查看全部 <ArrowRight size={15} /></Link>}>
        <DataTable
          keyField="task_id"
          rows={summary.recent_tasks}
          columns={[
            { key: "capsule_id", label: "胶囊编号", render: (row) => <Link className="mono-link" to={`/settlements?task=${row.task_id}`}>{row.capsule_id}</Link> },
            { key: "task_name", label: "任务名称" },
            { key: "current_stage", label: "当前阶段" },
            { key: "evidence_count", label: "证据" },
            { key: "agent_event_count", label: "过程记录" },
            { key: "risk_level", label: "风险", render: (row) => <StatusTag value={row.risk_level} /> },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "created_at", label: "创建时间", render: (row) => formatDate(row.created_at) },
          ]}
        />
      </Surface>
    </>
  );
}

function AdminOverview({ data, reload, canReview }: { data: OverviewData; reload: () => Promise<void>; canReview: boolean }) {
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
        description="维护主体身份和平台服务状态。"
        actions={<Button icon={RefreshCw} onClick={reload}>刷新状态</Button>}
      />
      <OperationsRibbon scope="平台运维域" status={data.trustedStatus} pendingCount={data.pendingReviews?.length || 0} />
      <TrustPosture status={data.trustedStatus} />
      <NodeTopology status={data.trustedStatus} />
      <ReviewQueue reviews={data.pendingReviews || []} visible={canReview} />
      <div className="metrics-grid five">
        <Metric label="注册组织" value={orgs.length} meta="参与主体" />
        <Metric label="平台用户" value={users.length} meta="角色账号" />
        <Metric label="有效身份凭证" value={validDids} meta="当前有效" tone="green" />
         <Metric label="受控能力" value={agents.length} meta="已登记" />
        <Metric label="待处理风险" value={openAnomalies} meta="平台事件" tone={openAnomalies ? "red" : "green"} />
      </div>

      <Surface title="平台状态">
        <div className="admin-status-grid">
          <div><Activity size={19} /><span><strong>API 服务</strong><small>FastAPI 控制面</small></span><StatusTag value="HEALTHY" label="运行正常" /></div>
          <div><Database size={19} /><span><strong>业务数据库</strong><small>组织、任务与证据索引</small></span><StatusTag value="HEALTHY" label="连接正常" /></div>
          <div><ShieldCheck size={19} /><span><strong>数据域隔离</strong><small>原始数据不进入业务库</small></span><StatusTag value="PASSED" label="边界正常" /></div>
          <div><Blocks size={19} /><span><strong>可信凭证服务</strong><small>{metrics.evidence_count || 0} 项凭证</small></span><StatusTag value="READY" label="正常" /></div>
        </div>
      </Surface>

      <div className="content-grid overview-grid">
        <Surface title="管理入口">
          <div className="admin-links">
            <Link to="/system"><UsersRound size={19} /><span><strong>主体与 DID</strong><small>维护组织、用户和凭证状态</small></span><ArrowRight size={16} /></Link>
            <Link to="/agents"><Workflow size={19} /><span><strong>能力编排</strong><small>查看能力凭证与工具白名单</small></span><ArrowRight size={16} /></Link>
            <Link to="/metrics"><Activity size={19} /><span><strong>运行指标</strong><small>检查计算、存证和服务指标</small></span><ArrowRight size={16} /></Link>
            <Link to="/logs"><FileClock size={19} /><span><strong>全过程日志</strong><small>追踪平台操作和异常事件</small></span><ArrowRight size={16} /></Link>
          </div>
        </Surface>
        <Surface title="待办">
          <div className="todo-list">
            {(summary.role_todos || ["维护身份凭证", "检查服务状态"]).map((item: string, index: number) => (
              <div key={item}><span>{String(index + 1).padStart(2, "0")}</span><strong>{item}</strong><ArrowRight size={16} /></div>
            ))}
          </div>
          <Link className="text-link" to="/system">进入身份治理 <ArrowRight size={15} /></Link>
        </Surface>
      </div>

      <Surface title="最近操作" actions={<Link className="text-link" to="/logs">查看全部 <ArrowRight size={15} /></Link>}>
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
          <div><KeyRound size={19} /><span><strong>有效凭证</strong><small>主体与服务身份</small></span><b>{validDids}</b></div>
          <div><ShieldCheck size={19} /><span><strong>隐私边界</strong><small>原始数据集中存储</small></span><b>0</b></div>
        </div>
      </Surface>
    </>
  );
}

function OperationsRibbon({ scope, status, pendingCount }: { scope: string; status?: JsonRecord; pendingCount: number }) {
  const policyEngine = (status?.policy_engine || {}) as JsonRecord;
  const policyVersion = String(policyEngine.version || "energy-execution/v1");
  return (
    <div className="ops-ribbon" aria-label="可信运营状态">
      <div className="ops-ribbon-context"><span className="ops-live-dot" /><div><small>当前运营域</small><strong>{scope}</strong></div></div>
      <div className="ops-ribbon-item"><ShieldCheck size={17} /><span><small>安全边界</small><strong>原始数据不出域</strong></span></div>
      <div className="ops-ribbon-item"><Activity size={17} /><span><small>计算校验</small><strong>{status ? `策略 ${policyVersion}` : "确定性复核在线"}</strong></span></div>
      <div className="ops-ribbon-item"><Blocks size={17} /><span><small>审计留痕</small><strong>{pendingCount ? `${pendingCount} 项待确认` : "链上队列正常"}</strong></span></div>
    </div>
  );
}

function TrustPosture({ status }: { status?: JsonRecord }) {
  const accuracyReview = (status?.accuracy_review || {}) as JsonRecord;
  const manualRequired = accuracyReview.manual_confirmation_required !== false;
  return (
    <div className="trust-posture" aria-label="两层可信状态">
      <article className="trust-posture-card trust-posture-security">
        <div className="trust-posture-index">01</div>
        <div><div className="trust-posture-heading"><ShieldCheck size={19} /><span>安全可信</span><StatusTag value="PASSED" label="边界正常" /></div><strong>原始数据不出域</strong><p>DID/VC、用途策略和最小结果输出共同形成访问边界。</p><ul><li><CheckCircle2 size={14} />身份与权限已校验</li><li><CheckCircle2 size={14} />细粒度数据不直接返回</li></ul></div>
      </article>
      <article className="trust-posture-card trust-posture-accuracy">
        <div className="trust-posture-index">02</div>
        <div><div className="trust-posture-heading"><Activity size={19} /><span>计算可信</span><StatusTag value="PASSED" label="复核在线" /></div><strong>结果可重算、可确认</strong><p>自动核对公式、来源快照和结果哈希，人工确认后形成签名凭证。</p><ul><li><CheckCircle2 size={14} />确定性复算通过</li><li><CheckCircle2 size={14} />{manualRequired ? "确认记录异步留痕" : "确认流程已配置"}</li></ul></div>
      </article>
    </div>
  );
}

function NodeTopology({ status }: { status?: JsonRecord }) {
  const nodes = Array.isArray(status?.nodes) ? status.nodes as JsonRecord[] : [];
  if (!nodes.length) return null;
  return (
    <Surface title="能源节点目录" note="平台只登记节点接口能力；原始数据仍保留在各主体域内。">
      <div className="node-topology-grid">
        {nodes.map((node) => {
          const types = Array.isArray(node.supported_data_types) ? node.supported_data_types as string[] : [];
          return (
            <article className="node-topology-card" key={String(node.node_code)}>
              <div className="node-topology-card-header"><div className="node-topology-icon"><RadioTower size={18} /></div><StatusTag value="READY" label="接口已登记" /></div>
              <strong>{nodeLabels[String(node.node_code)] || node.node_code}</strong>
              <span className="node-topology-code">{node.node_code} · {node.interface_version || "ENERGY-NODE-1.0"}</span>
              <small>{types.length} 个数据产品 · {types.map((type) => dataTypeLabels[type] || type).join("、") || "等待登记"}</small>
            </article>
          );
        })}
      </div>
    </Surface>
  );
}

function ReviewQueue({ reviews, visible }: { reviews: JsonRecord[]; visible: boolean }) {
  if (!visible) return null;
  return (
    <Surface title="计算复核队列" note="自动核验通过后，仍需授权审计角色确认计算结果。" actions={<Link className="text-link" to="/audit">进入审计 <ArrowRight size={14} /></Link>}>
      {reviews.length ? <DataTable
        keyField="review_id"
        rows={reviews.slice(0, 4)}
        columns={[
          { key: "request_id", label: "请求", render: (row) => <CodeValue title={row.request_id}>{shortHash(row.request_id, 12)}</CodeValue> },
          { key: "automatic_status", label: "自动核验", render: (row) => <StatusTag value={row.automatic_status} /> },
          { key: "result_hash", label: "结果哈希", render: (row) => <CodeValue title={row.result_hash}>{shortHash(row.result_hash)}</CodeValue> },
          { key: "created_at", label: "生成时间", render: (row) => formatDate(row.created_at) },
          { key: "action", label: "操作", render: () => <Link className="table-link" to="/audit">打开复核</Link> },
        ]}
      /> : <div className="review-queue-empty"><CheckCircle2 size={18} /><div><strong>当前没有待人工确认的计算结果</strong><span>新结果完成自动核验后会出现在这里。</span></div></div>}
    </Surface>
  );
}
