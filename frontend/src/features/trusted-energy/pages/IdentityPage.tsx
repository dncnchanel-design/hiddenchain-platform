import { CheckCircle2, Copy, FileKey2, Fingerprint, Link2, LockKeyhole, RefreshCw, ShieldCheck, UserRound } from "lucide-react";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, Divider, IconButton, RemoteState, StatusBadge, SurfaceHeader } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { loadIdentity } from "../trusted-space-api";
import { ROLE_LABELS, labelForCode } from "../../../types";
import { useTrustedSpaceContext } from "../trusted-space-context";

function valueOrDash(value?: string | null) {
  return value || "暂无";
}

function formatTime(value?: string | null) {
  if (!value) return "暂无";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN", { hour12: false });
}

function capabilityLabel(key: string) {
  return ({ identity: "身份凭证", asset_registry: "数据目录登记", connector_control_plane: "可信数据空间连接器", tee: "TEE 远程证明", hash_chain: "审计哈希链", blockchain: "外部区块链存证" } as Record<string, string>)[key] || labelForCode(key, "已登记能力");
}

const permissionLabels: Record<string, string> = {
  MANAGE_CATALOG: "管理数据目录",
  MANAGE_CONNECTOR: "管理数据连接",
  MANAGE_PUBLICATION_POLICY: "配置数据公布规则",
  APPROVE_AUTHORIZATION: "审批数据授权",
  CREATE_COMPUTE_TASK: "创建计算任务",
  VIEW_COMPUTE_RESULT: "查看计算结果",
  VIEW_AUDIT: "查看审计记录",
  MANAGE_MEMBERS: "管理成员与权限",
  CREATE_CROSS_ENERGY_QUERY: "发起跨能源查询",
  MANAGE_PLATFORM_OPERATIONS: "维护平台运行",
};

async function copyValue(value?: string | null) {
  if (value && navigator.clipboard) await navigator.clipboard.writeText(value);
}

export function IdentityPage() {
  const remote = useRemote(loadIdentity, []);
  const { context } = useTrustedSpaceContext();
  const identity = remote.data;
  return <PageFrame title="参与主体" description="企业是平台参与主体，个人账号归属于一家企业，并以企业名义使用获授权限。" action={<Button variant="secondary" onClick={() => void remote.reload()} busy={remote.refreshing}><RefreshCw size={14} />刷新主体状态</Button>}>
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    {identity && <>
      <div className="trusted-identity-layout">
        <nav className="trusted-identity-nav" aria-label="参与主体分区">
          <a className="is-active" href="#trusted-identity-subject"><UserRound size={14} />主体概览</a>
          <a href="#trusted-identity-did"><Fingerprint size={14} />DID 身份</a>
          <a href="#trusted-identity-certificate"><FileKey2 size={14} />数字证书</a>
          <a href="#trusted-identity-subject"><ShieldCheck size={14} />身份凭证</a>
          <a href="#trusted-identity-subject"><Link2 size={14} />关联主体</a>
          <a href="#trusted-identity-capabilities"><RefreshCw size={14} />操作记录</a>
          <a href="#trusted-identity-connector"><Link2 size={14} />连接器绑定</a>
        </nav>
        <div className="trusted-identity-content">
          <div className="trusted-detail-grid trusted-identity-grid">
            <div className="trusted-detail-main"><Card id="trusted-identity-subject"><CardHeader><SurfaceHeader title="主体信息" description={`来源：${labelForCode(identity.source_of_truth, "组织与用户记录")}`} action={<StatusBadge value={identity.subject.status} />} /></CardHeader><CardContent><div className="trusted-profile-block"><span className="trusted-profile-avatar"><UserRound size={24} /></span><div><h3>{identity.subject.org_name || "未配置组织"}</h3><p>{identity.actor.display_name} · {ROLE_LABELS[identity.actor.role_code as keyof typeof ROLE_LABELS] || labelForCode(identity.actor.role_code, "未登记角色")}</p><Badge tone="brand">{identity.subject.org_id}</Badge></div></div><Divider /><dl className="trusted-definition-grid"><div><dt>主体名称</dt><dd>{valueOrDash(identity.subject.org_name)}</dd></div><div><dt>主体类型</dt><dd>{ROLE_LABELS[identity.subject.org_type as keyof typeof ROLE_LABELS] || labelForCode(identity.subject.org_type, "未登记主体类型")}</dd></div><div><dt>组织标识</dt><dd><code>{identity.subject.org_id}</code><IconButton label="复制组织标识" onClick={() => void copyValue(identity.subject.org_id)}><Copy size={13} /></IconButton></dd></div><div><dt>当前用户</dt><dd>{identity.actor.display_name}</dd></div><div><dt>凭证状态</dt><dd><StatusBadge value={identity.did.credential_status} /></dd></div><div><dt>信用代码</dt><dd>{valueOrDash(identity.subject.credit_code)}</dd></div></dl></CardContent></Card><Card id="trusted-identity-certificate"><CardHeader><SurfaceHeader title="数字证书" description="后端只返回凭证元数据与验证结果，不返回私钥或下载文件" action={<FileKey2 size={17} />} /></CardHeader><CardContent><dl className="trusted-definition-grid"><div><dt>证书颁发方</dt><dd>{valueOrDash(identity.did.issuer)}</dd></div><div><dt>凭证类型</dt><dd>{identity.did.credential_type?.map((item) => labelForCode(item, "已登记凭证类型")).join(" / ") || "—"}</dd></div><div><dt>生效时间</dt><dd className="trusted-mono">{formatTime(identity.did.issued_at)}</dd></div><div><dt>有效期至</dt><dd className="trusted-mono">{formatTime(identity.did.expires_at)}</dd></div></dl><Button variant="secondary" disabled title="已阻断：当前后端未提供证书文件下载动作"><FileKey2 size={14} />查看证书摘要</Button></CardContent></Card></div>
            <div className="trusted-detail-side"><Card id="trusted-identity-did"><CardHeader><SurfaceHeader title="DID 身份" description={`来源：${labelForCode(identity.did.source_of_truth, "企业身份记录")}`} action={<Fingerprint size={17} />} /></CardHeader><CardContent><div className="trusted-did-value"><code>{valueOrDash(identity.did.did_id)}</code><IconButton label="复制 DID" onClick={() => void copyValue(identity.did.did_id)}><Copy size={13} /></IconButton></div><dl className="trusted-definition-list"><div><dt>公钥指纹</dt><dd><code>{valueOrDash(identity.did.public_key_fingerprint)}</code></dd></div><div><dt>外部链地址</dt><dd><code>{valueOrDash(identity.did.chain_address)}</code></dd></div><div><dt>私钥位置</dt><dd><Badge tone="success">企业连接器密钥存储</Badge></dd></div></dl><div className="trusted-note"><LockKeyhole size={14} /><span>企业私钥不进入平台数据库、GitHub 或 API，只在企业连接器密钥存储中使用。</span></div></CardContent></Card><Card id="trusted-identity-connector"><CardHeader><SurfaceHeader title="可信数据空间连接器" description={`来源：${labelForCode(identity.connector.source_of_truth, "数据连接记录")}`} action={<Link2 size={17} />} /></CardHeader><CardContent><dl className="trusted-definition-list"><div><dt>连接器类型</dt><dd>{labelForCode(identity.connector.code, "企业侧连接器")}</dd></div><div><dt>协议版本</dt><dd>{identity.connector.protocol_version}</dd></div><div><dt>已登记数据源</dt><dd>{identity.connector.source_count}</dd></div><div><dt>当前能力</dt><dd><Badge tone="warning" dot>{labelForCode(identity.connector.capability_state, "待配置")}</Badge></dd></div><div><dt>连接状态</dt><dd><StatusBadge value={identity.connector.readiness} /></dd></div></dl><Button variant="secondary" disabled title="请在企业内网连接器中完成配置"><Link2 size={14} />查看连接说明</Button></CardContent></Card></div>
          </div>
          <Card id="trusted-identity-capabilities" className="trusted-capability-card"><CardHeader><SurfaceHeader title="可信能力矩阵" description="能力标签由后端返回；适配器、阻断和演示状态不会被包装成生产连接。" /></CardHeader><CardContent><div className="trusted-capability-table">{Object.entries(identity.capability_matrix).map(([key, item]) => <div className="trusted-capability-row" key={key}><span className="trusted-capability-name"><ShieldCheck size={15} />{capabilityLabel(key)}</span><Badge tone={item.capability_state === "BLOCKED" ? "danger" : item.capability_state === "DEMO" || item.capability_state === "ADAPTER" ? "warning" : "success"}>{labelForCode(item.capability_state, "未配置")}</Badge><span className="trusted-muted">{item.readiness ? labelForCode(item.readiness, "已登记状态") : labelForCode(item.source_of_truth, "未登记来源")}</span><CheckCircle2 size={15} className={item.capability_state === "BLOCKED" ? "trusted-icon-muted" : "trusted-icon-success"} /></div>)}</div></CardContent></Card>
          <Card className="trusted-capability-card tw-mt-4"><CardHeader><SurfaceHeader title="当前账号权限" description="权限由企业最高权限账号授予，不绑定固定岗位名称。" /></CardHeader><CardContent><div className="trusted-function-chips">{(context?.actor.permissions || []).map((permission) => <span key={permission}>{permissionLabels[permission] || "企业授予权限"}</span>)}{!(context?.actor.permissions || []).length && <span>当前账号没有业务权限</span>}</div></CardContent></Card>
        </div>
      </div>
    </>}
  </PageFrame>;
}
