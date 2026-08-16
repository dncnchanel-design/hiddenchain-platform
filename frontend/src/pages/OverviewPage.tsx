import { ArrowRight, CheckCircle2, Database, Fingerprint, Gavel, Network, RadioTower, RefreshCw, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { api, formatDate, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Metric, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

const capabilityIcons: Record<string, React.ElementType> = {
  IDENTITY: Fingerprint,
  DATA: Database,
  RULE: Gavel,
  COMPUTE: Network,
  AUDIT: ShieldCheck,
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

type OverviewData = {
  summary: JsonRecord;
  orgs?: JsonRecord[];
  users?: JsonRecord[];
  dids?: JsonRecord[];
  agents?: JsonRecord[];
  logs?: JsonRecord[];
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
    const [orgs, users, dids, agents, logs] = await Promise.all([
      api<JsonRecord[]>("/system/organizations"),
      api<JsonRecord[]>("/system/users"),
      api<JsonRecord[]>("/system/dids"),
      api<JsonRecord[]>("/agents/definitions"),
      api<JsonRecord[]>("/audit/logs"),
    ]);
    return { summary, orgs, users, dids, agents, logs, pendingReviews, trustedStatus };
  };
  const { data, loading, error, reload } = useRemote<OverviewData>(loader, [isAdmin, canReview]);

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "总览加载失败"} retry={reload} />;
  if (isAdmin) return <AdminOverview data={data} reload={reload} />;

  const summary = data.summary;
  const capabilities = summary.trusted_capabilities || [];
  const computeReceipts = (summary.four_chain_fusion || []).find((item: JsonRecord) => item.code === "PRIVACY")?.metric ?? 0;

  return (
    <>
      <PageHeader title="平台总览" actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>} />
      <div className="metrics-grid four">
        <Metric label="可用数据" value={capabilities.find((item: JsonRecord) => item.code === "DATA")?.metric ?? 0} />
        <Metric label="计算回执" value={computeReceipts} tone="green" />
        <Metric label="已完成任务" value={summary.kpis.audited_tasks} tone="green" />
        <Metric label="待处理风险" value={summary.kpis.open_anomalies} tone={summary.kpis.open_anomalies ? "red" : "green"} />
      </div>

      <NodeTopology status={data.trustedStatus} />
      <ReviewQueue reviews={data.pendingReviews || []} visible={canReview} />

      <div className="content-grid overview-grid">
        <Surface title="服务状态">
          <div className="capability-list">
            {capabilities.map((item: JsonRecord) => {
              const Icon = capabilityIcons[item.code] || CheckCircle2;
              return (
                <div className="capability-row" key={item.code}>
                  <div className="capability-icon"><Icon size={19} /></div>
                  <div><strong>{item.name}</strong><span>{item.unit}</span></div>
                  <b>{item.metric}</b>
                  <StatusTag value={item.status} />
                </div>
              );
            })}
          </div>
        </Surface>
        <Surface title="当前待办">
          <div className="todo-list">
            {(summary.role_todos || []).map((item: string, index: number) => (
              <div key={item}><span>{String(index + 1).padStart(2, "0")}</span><strong>{item}</strong><ArrowRight size={16} /></div>
            ))}
          </div>
          <Link className="text-link" to="/workbench">进入工作台 <ArrowRight size={15} /></Link>
        </Surface>
      </div>

      <Surface title="最近一次验证结果" actions={<Link className="text-link" to="/settlements">进入验证 <ArrowRight size={15} /></Link>}>
        {summary.latest_verification ? <div className="verification-result-summary">
          <div><ShieldCheck size={21} /><span>状态</span><StatusTag value={summary.latest_verification.status} /></div>
          <div><Database size={21} /><span>数据资产</span><strong>{summary.latest_verification.verification_profile?.trusted_acquisition ? "已完成来源校验" : "待登记"}</strong></div>
          <div><Network size={21} /><span>数据出域</span><strong>{summary.latest_verification.verification_profile?.raw_data_exposed === false ? "否" : "待验证"}</strong></div>
          <div><Fingerprint size={21} /><span>审计凭证</span><strong>{summary.latest_verification.verification_profile?.evidence_count || summary.latest_verification.evidence_count || 0} 项</strong></div>
        </div> : <div className="empty-state">暂无验证任务</div>}
      </Surface>

      <Surface title="最近任务" actions={<Link className="text-link" to="/settlements">查看全部 <ArrowRight size={15} /></Link>}>
        <DataTable
          keyField="task_id"
          rows={summary.recent_tasks}
          columns={[
            { key: "capsule_id", label: "胶囊编号", render: (row) => <Link className="mono-link" to={`/settlements?task=${row.task_id}`}>{row.capsule_id}</Link> },
            { key: "task_name", label: "任务名称" },
            { key: "current_stage", label: "当前阶段" },
            { key: "evidence_count", label: "凭证" },
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

function AdminOverview({ data, reload }: { data: OverviewData; reload: () => Promise<void> }) {
  const summary = data.summary;
  const orgs = data.orgs || [];
  const users = data.users || [];
  const dids = data.dids || [];
  const agents = data.agents || [];
  const logs = data.logs || [];
  const validDids = dids.filter((item) => item.credential_status === "VALID").length;
  const openAnomalies = Number(summary.kpis?.open_anomalies || 0);

  return (
    <>
      <PageHeader title="系统管理员总览" actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>} />
      <div className="metrics-grid five">
        <Metric label="注册组织" value={orgs.length} />
        <Metric label="平台用户" value={users.length} />
        <Metric label="有效身份凭证" value={validDids} tone="green" />
        <Metric label="受控能力" value={agents.length} />
        <Metric label="待处理风险" value={openAnomalies} tone={openAnomalies ? "red" : "green"} />
      </div>

      <NodeTopology status={data.trustedStatus} />
      <ReviewQueue reviews={data.pendingReviews || []} visible />

      <Surface title="当前待办">
        <div className="todo-list">
          {(summary.role_todos || []).map((item: string, index: number) => (
            <div key={item}><span>{String(index + 1).padStart(2, "0")}</span><strong>{item}</strong><ArrowRight size={16} /></div>
          ))}
        </div>
      </Surface>

      <Surface title="最近操作" actions={<Link className="text-link" to="/logs">查看全部 <ArrowRight size={15} /></Link>}>
        <DataTable
          keyField="log_id"
          rows={logs.slice(0, 6)}
          empty="暂无操作记录"
          columns={[
            { key: "action_code", label: "操作" },
            { key: "actor_name", label: "操作主体" },
            { key: "target_type", label: "对象类型" },
            { key: "result", label: "结果", render: (row) => <StatusTag value={row.result} /> },
            { key: "trace_id", label: "追踪编号", render: (row) => <CodeValue title={row.trace_id}>{shortHash(row.trace_id, 8)}</CodeValue> },
            { key: "occurred_at", label: "时间", render: (row) => formatDate(row.occurred_at) },
          ]}
        />
      </Surface>
    </>
  );
}

function NodeTopology({ status }: { status?: JsonRecord }) {
  const nodes = Array.isArray(status?.nodes) ? status.nodes as JsonRecord[] : [];
  if (!nodes.length) return null;
  return (
    <Surface title="能源节点目录" meta={`${nodes.length} 个`}>
      <div className="node-topology-grid">
        {nodes.map((node) => {
          const types = Array.isArray(node.supported_data_types) ? node.supported_data_types as string[] : [];
          return (
            <article className="node-topology-card" key={String(node.node_code)}>
              <div className="node-topology-card-header"><div className="node-topology-icon"><RadioTower size={18} /></div><StatusTag value="READY" label="已登记" /></div>
              <strong>{nodeLabels[String(node.node_code)] || node.node_code}</strong>
              <span className="node-topology-code">{node.node_code} · {node.interface_version || "ENERGY-NODE-1.0"}</span>
              <small>{types.length} 项 · {types.map((type) => dataTypeLabels[type] || type).join("、") || "暂无数据产品"}</small>
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
    <Surface title="计算复核队列" meta={`${reviews.length} 项`} actions={<Link className="text-link" to="/audit">进入审计 <ArrowRight size={14} /></Link>}>
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
      /> : <div className="review-queue-empty"><CheckCircle2 size={18} /><strong>暂无待确认结果</strong></div>}
    </Surface>
  );
}
