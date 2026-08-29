import { RefreshCw } from "lucide-react";
import { api } from "../api";
import { Button, DataTable, ErrorState, LoadingState, Metric, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";

type AdminSystemData = {
  organization_counts: { total: number; active: number };
  user_counts: { total: number; active: number };
  identity_counts: { total: number; valid: number; organizations: number; users: number; agents: number };
  node_counts: { total: number; active: number; health_confirmed: number };
  technical_status: { identity_registry: string; node_registry: string; raw_payload_access: string };
  security_boundary: string;
};

function loadAdminSystem(signal?: AbortSignal) {
  return api<AdminSystemData>("/admin/system", { signal, timeoutMs: 12000, cache: "no-store" });
}

export function SystemPage() {
  const { data, loading, refreshing, error, reload } = useRemote(loadAdminSystem, []);

  if (loading) return <LoadingState label="正在加载系统摘要" variant="page" />;
  if (error || !data) return <ErrorState message={error || "系统摘要加载失败"} retry={reload} />;

  const registryRows = [
    { key: "organizations", name: "组织注册", total: data.organization_counts.total, active: data.organization_counts.active },
    { key: "users", name: "用户注册", total: data.user_counts.total, active: data.user_counts.active },
    { key: "identities", name: "身份凭证", total: data.identity_counts.total, active: data.identity_counts.valid },
    { key: "nodes", name: "主体节点", total: data.node_counts.total, active: data.node_counts.active },
  ];
  const technicalRows = [
    { key: "identity", name: "身份注册服务", status: data.technical_status.identity_registry },
    { key: "node", name: "节点注册服务", status: data.technical_status.node_registry },
    { key: "raw", name: "原始载荷访问", status: data.technical_status.raw_payload_access },
  ];

  return (
    <>
      <PageHeader title="组织、用户与权限" description="仅查看组织、账号、身份和主体节点的聚合技术状态。" actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>} />
      <div className="metrics-grid four">
        <Metric label="注册组织" value={data.organization_counts.total} meta={`${data.organization_counts.active} 个正常`} />
        <Metric label="平台用户" value={data.user_counts.total} meta={`${data.user_counts.active} 个正常`} />
        <Metric label="有效身份" value={data.identity_counts.valid} meta={`组织 ${data.identity_counts.organizations} · 用户 ${data.identity_counts.users} · 能力 ${data.identity_counts.agents}`} />
        <Metric label="启用节点" value={data.node_counts.active} meta={`${data.node_counts.health_confirmed} 个已确认健康`} />
      </div>

      <div className="content-grid overview-grid">
        <Surface title="注册聚合">
          <DataTable
            keyField="key"
            rows={registryRows}
            label="注册聚合"
            columns={[
              { key: "name", label: "注册类别" },
              { key: "total", label: "总数", align: "right" },
              { key: "active", label: "有效 / 启用", align: "right" },
            ]}
          />
        </Surface>
        <Surface title="技术边界状态">
          <DataTable
            keyField="key"
            rows={technicalRows}
            label="技术边界状态"
            columns={[
              { key: "name", label: "检查项" },
              { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            ]}
          />
        </Surface>
      </div>

      <Surface title="管理视图边界">
        <p>{data.security_boundary}</p>
      </Surface>
    </>
  );
}
