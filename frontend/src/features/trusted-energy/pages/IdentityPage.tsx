import { CheckCircle2, Copy, FileKey2, Fingerprint, Link2, LockKeyhole, RefreshCw, ShieldCheck, UserRound } from "lucide-react";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, Divider, IconButton, RemoteState, StatusBadge, SurfaceHeader } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { loadIdentity } from "../trusted-space-api";

function valueOrDash(value?: string | null) {
  return value || "—";
}

function formatTime(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN", { hour12: false });
}

function capabilityLabel(key: string) {
  return ({ identity: "身份凭证", asset_registry: "资产注册表", connector_control_plane: "Connector 控制面", tee: "TEE 远程证明", blockchain: "区块链存证" } as Record<string, string>)[key] || key;
}

async function copyValue(value?: string | null) {
  if (value && navigator.clipboard) await navigator.clipboard.writeText(value);
}

export function IdentityPage() {
  const remote = useRemote(loadIdentity, []);
  const identity = remote.data;
  return <PageFrame title="身份中心" description="管理当前主体的 DID、数字证书与 Connector 适配边界。" action={<Button variant="secondary" onClick={() => void remote.reload()} busy={remote.refreshing}><RefreshCw size={14} />刷新身份状态</Button>}>
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    {identity && <>
      <div className="trusted-detail-grid trusted-identity-grid">
        <div className="trusted-detail-main"><Card><CardHeader><SurfaceHeader title="主体信息" description={`来源：${identity.source_of_truth || "organizations/users"}`} action={<StatusBadge value={identity.subject.status} />} /></CardHeader><CardContent><div className="trusted-profile-block"><span className="trusted-profile-avatar"><UserRound size={24} /></span><div><h3>{identity.subject.org_name || "未配置组织"}</h3><p>{identity.actor.display_name} · {identity.actor.role_code}</p><Badge tone="brand">{identity.subject.org_id}</Badge></div></div><Divider /><dl className="trusted-definition-grid"><div><dt>主体名称</dt><dd>{valueOrDash(identity.subject.org_name)}</dd></div><div><dt>主体类型</dt><dd>{valueOrDash(identity.subject.org_type)}</dd></div><div><dt>组织标识</dt><dd><code>{identity.subject.org_id}</code><IconButton label="复制组织标识" onClick={() => void copyValue(identity.subject.org_id)}><Copy size={13} /></IconButton></dd></div><div><dt>当前用户</dt><dd>{identity.actor.display_name}</dd></div><div><dt>凭证状态</dt><dd><StatusBadge value={identity.did.credential_status} /></dd></div><div><dt>信用代码</dt><dd>{valueOrDash(identity.subject.credit_code)}</dd></div></dl></CardContent></Card><Card><CardHeader><SurfaceHeader title="数字证书" description="后端只返回凭证元数据与验证结果，不返回私钥或下载文件" action={<FileKey2 size={17} />} /></CardHeader><CardContent><dl className="trusted-definition-grid"><div><dt>证书颁发方</dt><dd>{valueOrDash(identity.did.issuer)}</dd></div><div><dt>凭证类型</dt><dd>{identity.did.credential_type?.join(" / ") || "—"}</dd></div><div><dt>生效时间</dt><dd className="trusted-mono">{formatTime(identity.did.issued_at)}</dd></div><div><dt>有效期至</dt><dd className="trusted-mono">{formatTime(identity.did.expires_at)}</dd></div></dl><Button variant="secondary" disabled title="BLOCKED：当前后端未提供证书文件下载动作"><FileKey2 size={14} />查看证书摘要</Button></CardContent></Card></div>
        <div className="trusted-detail-side"><Card><CardHeader><SurfaceHeader title="DID 信息" description={`来源：${identity.did.source_of_truth || "did_identities"}`} action={<Fingerprint size={17} />} /></CardHeader><CardContent><div className="trusted-did-value"><code>{valueOrDash(identity.did.did_id)}</code><IconButton label="复制 DID" onClick={() => void copyValue(identity.did.did_id)}><Copy size={13} /></IconButton></div><dl className="trusted-definition-list"><div><dt>公钥指纹</dt><dd><code>{valueOrDash(identity.did.public_key_fingerprint)}</code></dd></div><div><dt>链上地址</dt><dd><code>{valueOrDash(identity.did.chain_address)}</code></dd></div><div><dt>密钥托管</dt><dd><Badge tone="warning">本地受控环境</Badge></dd></div></dl><div className="trusted-note"><LockKeyhole size={14} /><span>私钥不离开当前受控环境；DID 与凭证展示来自后端身份记录。</span></div></CardContent></Card><Card><CardHeader><SurfaceHeader title="EDC / Connector" description={`来源：${identity.connector.source_of_truth || "data_sources"}`} action={<Link2 size={17} />} /></CardHeader><CardContent><dl className="trusted-definition-list"><div><dt>Connector 类型</dt><dd><code>{identity.connector.code}</code></dd></div><div><dt>协议版本</dt><dd>{identity.connector.protocol_version}</dd></div><div><dt>已登记源</dt><dd>{identity.connector.source_count}</dd></div><div><dt>当前能力</dt><dd><Badge tone="warning" dot>{identity.connector.capability_state || "ADAPTER"}</Badge></dd></div><div><dt>连接状态</dt><dd><StatusBadge value={identity.connector.readiness} /></dd></div></dl><Button variant="secondary" disabled title="BLOCKED：当前后端未提供 Connector 管理动作"><Link2 size={14} />管理 Connector</Button></CardContent></Card></div>
      </div>
      <Card className="trusted-capability-card"><CardHeader><SurfaceHeader title="可信能力矩阵" description="能力标签由后端返回；适配器、阻断和演示状态不会被包装成生产连接。" /></CardHeader><CardContent><div className="trusted-capability-table">{Object.entries(identity.capability_matrix).map(([key, item]) => <div className="trusted-capability-row" key={key}><span className="trusted-capability-name"><ShieldCheck size={15} />{capabilityLabel(key)}</span><Badge tone={item.capability_state === "BLOCKED" ? "danger" : item.capability_state === "DEMO" || item.capability_state === "ADAPTER" ? "warning" : "success"}>{item.capability_state || "NOT_CONFIGURED"}</Badge><span className="trusted-muted">{item.readiness ? String(item.readiness) : item.source_of_truth || "—"}</span><CheckCircle2 size={15} className={item.capability_state === "BLOCKED" ? "trusted-icon-muted" : "trusted-icon-success"} /></div>)}</div></CardContent></Card>
    </>}
  </PageFrame>;
}
