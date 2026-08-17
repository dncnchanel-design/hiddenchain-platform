import { useState } from "react";
import { Building2, Fingerprint, RefreshCw, UserRound, Workflow } from "lucide-react";
import { api } from "../api";
import { Button, DataTable, DateTimeText, ErrorState, IdText, LoadingState, Metric, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { ROLE_LABELS } from "../types";
import type { JsonRecord } from "../types";

type SystemTab = "ORGS" | "USERS" | "DIDS";

const ownerTypeLabels: Record<string, string> = {
  USER: "用户",
  AGENT: "能力模块",
  ORG: "组织",
};

function roleLabel(value: unknown) {
  const key = String(value ?? "") as keyof typeof ROLE_LABELS;
  return ROLE_LABELS[key] || String(value ?? "");
}

export function SystemPage() {
  const [tab, setTab] = useState<SystemTab>("ORGS");
  const loader = async (signal?: AbortSignal) => {
    const request = { signal, timeoutMs: 12000, cache: "no-store" as RequestCache };
    const [orgs, users, dids] = await Promise.all([api<JsonRecord[]>("/system/organizations", request), api<JsonRecord[]>("/system/users", request), api<JsonRecord[]>("/system/dids", request)]);
    return { orgs, users, dids };
  };
  const { data, loading, refreshing, error, reload } = useRemote(loader, []);

  if (loading) return <LoadingState label="正在加载组织与用户" variant="page" />;
  if (error || !data) return <ErrorState message={error || "身份数据加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader title="组织、用户与权限" description="查看平台注册组织、用户角色范围与身份凭证状态。" actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>} />
      <div className="metrics-grid three">
        <Metric label="注册组织" value={data.orgs.length} />
        <Metric label="平台用户" value={data.users.length} />
        <Metric label="有效身份凭证" value={data.dids.filter((item) => item.credential_status === "VALID").length} tone="green" />
      </div>
      <div className="segmented" role="tablist" aria-label="身份管理分类"><button type="button" role="tab" aria-selected={tab === "ORGS"} className={tab === "ORGS" ? "active" : ""} onClick={() => setTab("ORGS")}>组织</button><button type="button" role="tab" aria-selected={tab === "USERS"} className={tab === "USERS" ? "active" : ""} onClick={() => setTab("USERS")}>用户与权限</button><button type="button" role="tab" aria-selected={tab === "DIDS"} className={tab === "DIDS" ? "active" : ""} onClick={() => setTab("DIDS")}>身份凭证</button></div>
      <Surface title={tab === "ORGS" ? "组织列表" : tab === "USERS" ? "用户列表" : "身份凭证列表"}>
        {tab === "ORGS" && <DataTable keyField="org_id" rows={data.orgs} columns={[
          { key: "org_name", label: "组织名称", render: (row) => <span className="identity-name"><Building2 size={16} />{row.org_name}</span> },
          { key: "org_type", label: "主体类型", render: (row) => roleLabel(row.org_type) },
          { key: "credit_code", label: "统一信用代码", minWidth: 160, render: (row) => <IdText value={row.credit_code} length={10} /> },
          { key: "org_id", label: "组织编号", minWidth: 150, render: (row) => <IdText value={row.org_id} /> },
          { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
          { key: "created_at", label: "注册时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
        ]} />}
        {tab === "USERS" && <DataTable keyField="user_id" rows={data.users} columns={[
          { key: "display_name", label: "用户", render: (row) => <span className="identity-name"><UserRound size={16} />{row.display_name}</span> },
          { key: "username", label: "账号" },
          { key: "role_code", label: "平台角色", render: (row) => roleLabel(row.role_code) },
          { key: "org_id", label: "所属组织", render: (row) => data.orgs.find((item) => item.org_id === row.org_id)?.org_name || row.org_id },
          { key: "last_login_at", label: "最近登录", minWidth: 165, render: (row) => <DateTimeText value={row.last_login_at} /> },
          { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
        ]} />}
        {tab === "DIDS" && <DataTable keyField="did_id" rows={data.dids} columns={[
          { key: "owner_id", label: "身份主体", minWidth: 160, render: (row) => <span className="identity-name">{row.owner_type === "AGENT" ? <Workflow size={16} /> : <Fingerprint size={16} />}<IdText value={row.owner_id} /></span> },
          { key: "owner_type", label: "凭证类型", render: (row) => ownerTypeLabels[row.owner_type] || row.owner_type },
          { key: "did_id", label: "DID", minWidth: 180, render: (row) => <IdText value={row.did_id} length={12} /> },
          { key: "public_key_fingerprint", label: "公钥指纹", minWidth: 150, render: (row) => <IdText value={row.public_key_fingerprint} /> },
          { key: "chain_address", label: "链地址", minWidth: 150, render: (row) => <IdText value={row.chain_address} /> },
          { key: "credential_status", label: "凭证状态", render: (row) => <StatusTag value={row.credential_status} /> },
        ]} />}
      </Surface>
    </>
  );
}
