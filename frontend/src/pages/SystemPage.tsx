import { useState } from "react";
import { Building2, Fingerprint, RefreshCw, UserRound, Workflow } from "lucide-react";
import { api, formatDate, shortHash } from "../api";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, PageHeader, StatusTag, Surface } from "../components/ui";
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
  const loader = async () => {
    const [orgs, users, dids] = await Promise.all([api<JsonRecord[]>("/system/organizations"), api<JsonRecord[]>("/system/users"), api<JsonRecord[]>("/system/dids")]);
    return { orgs, users, dids };
  };
  const { data, loading, error, reload } = useRemote(loader, []);

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "身份数据加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader title="身份管理" actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>} />
      <div className="metrics-grid three">
        <div className="metric"><span>注册组织</span><strong>{data.orgs.length}</strong></div>
        <div className="metric"><span>平台用户</span><strong>{data.users.length}</strong></div>
        <div className="metric metric-green"><span>有效身份凭证</span><strong>{data.dids.filter((item) => item.credential_status === "VALID").length}</strong></div>
      </div>
      <div className="segmented" role="tablist"><button className={tab === "ORGS" ? "active" : ""} onClick={() => setTab("ORGS")}>组织</button><button className={tab === "USERS" ? "active" : ""} onClick={() => setTab("USERS")}>用户</button><button className={tab === "DIDS" ? "active" : ""} onClick={() => setTab("DIDS")}>身份凭证</button></div>
      <Surface title={tab === "ORGS" ? "组织列表" : tab === "USERS" ? "用户列表" : "身份凭证列表"}>
        {tab === "ORGS" && <DataTable keyField="org_id" rows={data.orgs} columns={[
          { key: "org_name", label: "组织名称", render: (row) => <span className="identity-name"><Building2 size={16} />{row.org_name}</span> },
          { key: "org_type", label: "主体类型", render: (row) => roleLabel(row.org_type) },
          { key: "credit_code", label: "统一信用代码", render: (row) => <span className="mono-text">{row.credit_code}</span> },
          { key: "org_id", label: "空间标识", render: (row) => <CodeValue>{row.org_id}</CodeValue> },
          { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
          { key: "created_at", label: "注册时间", render: (row) => formatDate(row.created_at) },
        ]} />}
        {tab === "USERS" && <DataTable keyField="user_id" rows={data.users} columns={[
          { key: "display_name", label: "用户", render: (row) => <span className="identity-name"><UserRound size={16} />{row.display_name}</span> },
          { key: "username", label: "账号" },
          { key: "role_code", label: "平台角色", render: (row) => roleLabel(row.role_code) },
          { key: "org_id", label: "所属组织", render: (row) => data.orgs.find((item) => item.org_id === row.org_id)?.org_name || row.org_id },
          { key: "last_login_at", label: "最近登录", render: (row) => formatDate(row.last_login_at) },
          { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
        ]} />}
        {tab === "DIDS" && <DataTable keyField="did_id" rows={data.dids} columns={[
          { key: "owner_id", label: "身份主体", render: (row) => <span className="identity-name">{row.owner_type === "AGENT" ? <Workflow size={16} /> : <Fingerprint size={16} />}{row.owner_id}</span> },
          { key: "owner_type", label: "凭证类型", render: (row) => ownerTypeLabels[row.owner_type] || row.owner_type },
          { key: "did_id", label: "DID", render: (row) => <CodeValue title={row.did_id}>{shortHash(row.did_id, 18)}</CodeValue> },
          { key: "public_key_fingerprint", label: "公钥指纹", render: (row) => <CodeValue title={row.public_key_fingerprint}>{shortHash(row.public_key_fingerprint)}</CodeValue> },
          { key: "chain_address", label: "链地址", render: (row) => <CodeValue title={row.chain_address}>{shortHash(row.chain_address)}</CodeValue> },
          { key: "credential_status", label: "凭证状态", render: (row) => <StatusTag value={row.credential_status} /> },
        ]} />}
      </Surface>
    </>
  );
}
