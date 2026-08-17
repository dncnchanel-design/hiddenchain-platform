import { ArrowRight, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Button, DataTable, DateTimeText, ErrorState, IdText, LoadingState, Metric, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { ACTION_LABELS, TARGET_TYPE_LABELS, type JsonRecord } from "../types";

type AdminOverviewData = {
  summary: JsonRecord;
  orgs: JsonRecord[];
  users: JsonRecord[];
  dids: JsonRecord[];
  services: JsonRecord[];
  logs: JsonRecord[];
};

export function OverviewPage() {
  const loader = async (signal?: AbortSignal): Promise<AdminOverviewData> => {
    const request = { signal, timeoutMs: 12000, cache: "no-store" as RequestCache };
    const [summary, orgs, users, dids, services, logs] = await Promise.all([
      api<JsonRecord>("/dashboard/summary", request),
      api<JsonRecord[]>("/system/organizations", request),
      api<JsonRecord[]>("/system/users", request),
      api<JsonRecord[]>("/system/dids", request),
      api<JsonRecord[]>("/agents/definitions", request),
      api<JsonRecord[]>("/audit/logs", request),
    ]);
    return { summary, orgs, users, dids, services, logs };
  };
  const { data, loading, refreshing, error, reload } = useRemote(loader, []);

  if (loading) return <LoadingState label="正在读取管理总览" variant="page" />;
  if (error || !data) return <ErrorState message={error || "管理总览加载失败"} retry={reload} />;

  const activeOrganizations = data.orgs.filter((item) => item.status === "ACTIVE").length;
  const activeUsers = data.users.filter((item) => item.status === "ACTIVE").length;
  const openRisks = Number(data.summary.kpis?.open_anomalies || 0);
  const capabilityRows = (data.summary.trusted_capabilities || []).map((item: JsonRecord) => ({ ...item, capability_key: item.code || item.name }));

  return (
    <>
      <PageHeader
        title="管理总览"
        description="查看组织、用户、能力服务、风险与最近操作概况。"
        actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>}
      />

      <div className="metrics-grid five">
        <Metric label="组织" value={data.orgs.length} meta={`${activeOrganizations} 个启用`} />
        <Metric label="用户" value={data.users.length} meta={`${activeUsers} 个启用`} />
        <Metric label="身份凭证" value={data.dids.length} meta={`${data.dids.filter((item) => item.credential_status === "VALID").length} 个有效`} />
        <Metric label="能力定义" value={data.services.length} meta="已登记" />
        <Metric label="待处置风险" value={openRisks} tone={openRisks ? "red" : "green"} />
      </div>

      <div className="content-grid overview-grid">
        <Surface title="可信能力登记概况" actions={<Link className="text-link" to="/metrics">查看能力指标 <ArrowRight size={14} /></Link>}>
          <DataTable
            keyField="capability_key"
            rows={capabilityRows}
            empty="暂无能力登记数据"
            label="可信能力登记概况"
            columns={[
              { key: "name", label: "能力", minWidth: 160 },
              { key: "metric", label: "登记值", align: "right" },
              { key: "unit", label: "单位" },
            ]}
          />
        </Surface>

        <Surface title="管理入口">
          <div className="management-link-list">
            <Link to="/system"><div><strong>组织、用户与权限</strong><span>查看组织、账号与身份凭证状态</span></div><ArrowRight size={15} /></Link>
            <Link to="/agents"><div><strong>能力与服务</strong><span>查看受控能力定义及调用状态</span></div><ArrowRight size={15} /></Link>
            <Link to="/logs"><div><strong>系统日志</strong><span>按操作主体、对象和追踪编号检索</span></div><ArrowRight size={15} /></Link>
            <Link to="/anomalies"><div><strong>风险事件</strong><span>查看当前待处置事件及结果</span></div><ArrowRight size={15} /></Link>
          </div>
        </Surface>
      </div>

      <Surface title="最近操作" meta={`最近 ${Math.min(20, data.logs.length)} 条 / 共 ${data.logs.length} 条`} actions={<Link className="text-link" to="/logs">查看全部 <ArrowRight size={14} /></Link>}>
        <DataTable
          keyField="log_id"
          rows={data.logs.slice(0, 20)}
          empty="暂无操作记录"
          label="最近操作记录"
          columns={[
            { key: "action_code", label: "操作", minWidth: 180, render: (row) => ACTION_LABELS[row.action_code] || row.action_code || "—" },
            { key: "actor_name", label: "操作主体", minWidth: 130 },
            { key: "target_type", label: "对象类型", render: (row) => TARGET_TYPE_LABELS[row.target_type] || row.target_type || "—" },
            { key: "result", label: "结果", render: (row) => <StatusTag value={row.result} /> },
            { key: "trace_id", label: "追踪编号", minWidth: 150, render: (row) => <IdText value={row.trace_id} /> },
            { key: "occurred_at", label: "时间", minWidth: 165, render: (row) => <DateTimeText value={row.occurred_at} /> },
          ]}
        />
      </Surface>
    </>
  );
}
