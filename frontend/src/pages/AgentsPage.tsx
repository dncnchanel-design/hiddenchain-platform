import { RefreshCw } from "lucide-react";
import { api } from "../api";
import { Button, DataTable, ErrorState, LoadingState, Metric, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";

type AdminAgentsData = {
  service_health: {
    api: string;
    explanation_service: string;
    provider: string | null;
    model: string | null;
    credential_configured: boolean;
  };
  identity_counts: { total: number; valid: number };
  tool_counts: { total: number; enabled: number };
  permission_counts: { total: number; active: number };
  security_boundary: string;
};

function loadAdminAgents(signal?: AbortSignal) {
  return api<AdminAgentsData>("/admin/agents", { signal, timeoutMs: 12000, cache: "no-store" });
}

export function AgentsPage() {
  const { data, loading, refreshing, error, reload } = useRemote(loadAdminAgents, []);

  if (loading) return <LoadingState label="正在加载能力服务摘要" variant="page" />;
  if (error || !data) return <ErrorState message={error || "能力服务摘要加载失败"} retry={reload} />;

  const serviceRows = [
    { key: "api", name: "能力管理 API", value: data.service_health.api, status: data.service_health.api },
    { key: "explanation", name: "解释服务", value: data.service_health.explanation_service, status: data.service_health.explanation_service },
    { key: "provider", name: "服务提供方", value: data.service_health.provider || "未启用" },
    { key: "model", name: "模型配置", value: data.service_health.model || "未启用" },
    { key: "credential", name: "凭据配置", value: data.service_health.credential_configured ? "已配置" : "未配置", status: data.service_health.credential_configured ? "READY" : "DISABLED" },
  ];

  return (
    <>
      <PageHeader title="能力与服务" description="查看能力身份、受控工具、权限和解释服务的聚合技术状态。" actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>} />
      <div className="metrics-grid four">
        <Metric label="能力身份" value={data.identity_counts.total} meta={`${data.identity_counts.valid} 个有效`} />
        <Metric label="受控工具" value={data.tool_counts.total} meta={`${data.tool_counts.enabled} 个启用`} />
        <Metric label="权限授予" value={data.permission_counts.total} meta={`${data.permission_counts.active} 个有效`} />
        <Metric label="解释服务" value={<StatusTag value={data.service_health.explanation_service} />} />
      </div>

      <Surface title="能力服务技术状态">
        <DataTable
          keyField="key"
          rows={serviceRows}
          label="能力服务技术状态"
          columns={[
            { key: "name", label: "检查项" },
            { key: "value", label: "配置" },
            { key: "status", label: "状态", render: (row) => row.status ? <StatusTag value={row.status} /> : "—" },
          ]}
        />
      </Surface>

      <Notice tone="info">{data.security_boundary}</Notice>
    </>
  );
}
