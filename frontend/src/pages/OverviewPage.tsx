import { ArrowRight, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Button, DataTable, ErrorState, LoadingState, Metric, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";

type AdminOverviewData = {
  service_health: {
    api: string;
    database: string;
    environment: string;
  };
  counts: {
    organizations_total: number;
    organizations_active: number;
    users_total: number;
    users_active: number;
    identities_total: number;
    identities_valid: number;
    nodes_total: number;
    nodes_active: number;
  };
  security_boundary: string;
};

function loadAdminOverview(signal?: AbortSignal) {
  return api<AdminOverviewData>("/admin/overview", { signal, timeoutMs: 12000, cache: "no-store" });
}

export function OverviewPage() {
  const { data, loading, refreshing, error, reload } = useRemote(loadAdminOverview, []);

  if (loading) return <LoadingState label="正在读取管理总览" variant="page" />;
  if (error || !data) return <ErrorState message={error || "管理总览加载失败"} retry={reload} />;

  const serviceRows = [
    { key: "api", name: "API 服务", status: data.service_health.api },
    { key: "database", name: "数据库连接", status: data.service_health.database },
    { key: "environment", name: "运行环境", status: data.service_health.environment },
  ];

  return (
    <>
      <PageHeader
        title="管理总览"
        description="查看平台服务健康与主体、身份、节点的聚合运行状态。"
        actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>}
      />

      <div className="metrics-grid five">
        <Metric label="注册组织" value={data.counts.organizations_total} meta={`${data.counts.organizations_active} 个正常`} />
        <Metric label="平台用户" value={data.counts.users_total} meta={`${data.counts.users_active} 个正常`} />
        <Metric label="身份凭证" value={data.counts.identities_total} meta={`${data.counts.identities_valid} 个有效`} />
        <Metric label="主体节点" value={data.counts.nodes_total} meta={`${data.counts.nodes_active} 个启用`} />
        <Metric label="API 状态" value={<StatusTag value={data.service_health.api} />} />
      </div>

      <div className="content-grid overview-grid">
        <Surface title="技术运行状态">
          <DataTable
            keyField="key"
            rows={serviceRows}
            label="技术运行状态"
            columns={[
              { key: "name", label: "检查项" },
              { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            ]}
          />
        </Surface>

        <Surface title="管理入口">
          <div className="management-link-list">
            <Link to="/system"><div><strong>组织与权限</strong><span>查看聚合注册与身份状态</span></div><ArrowRight size={15} /></Link>
            <Link to="/agents"><div><strong>能力与服务</strong><span>查看能力注册与配置状态</span></div><ArrowRight size={15} /></Link>
            <Link to="/metrics"><div><strong>运行监控</strong><span>查看平台技术指标</span></div><ArrowRight size={15} /></Link>
            <Link to="/logs"><div><strong>系统日志</strong><span>查看脱敏运维记录</span></div><ArrowRight size={15} /></Link>
          </div>
        </Surface>
      </div>

      <Surface title="管理视图边界">
        <p>{data.security_boundary}</p>
      </Surface>
    </>
  );
}
