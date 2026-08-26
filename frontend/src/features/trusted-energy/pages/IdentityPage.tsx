import { useEffect, useRef, useState } from "react";
import {
  Building2,
  CheckCircle2,
  ChevronDown,
  Copy,
  Factory,
  FileKey2,
  FileJson2,
  Fingerprint,
  Flame,
  Fuel,
  Landmark,
  Link2,
  LoaderCircle,
  LockKeyhole,
  Network,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  UserRound,
  Waves,
  Zap,
} from "lucide-react";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, Divider, IconButton, MetricBand, RemoteState, StatusBadge, SurfaceHeader } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";
import { loadDidDocument, loadIdentity, loadIdentityDirectory, type DidDocumentPayload, type IdentityDirectoryItem } from "../trusted-space-api";
import { ROLE_LABELS, labelForCode } from "../../../types";
import { useTrustedSpaceContext } from "../trusted-space-context";

const ENERGY_DOMAIN_ORDER = ["electricity", "coal", "heat", "gas", "oil"];

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

function roleLabel(value?: string | null) {
  if (!value) return "未登记主体";
  return ROLE_LABELS[value as keyof typeof ROLE_LABELS] || labelForCode(value, "未登记主体");
}

function domainLabel(value?: string | null) {
  return value ? labelForCode(value, "未分配能源域") : "跨能源监管";
}

function identityGlyph(item: IdentityDirectoryItem) {
  if (item.org_type === "REGULATOR") return <Landmark size={20} />;
  if (item.org_type === "EXCHANGE") return <Building2 size={20} />;
  if (item.org_type === "GENERATOR" || item.org_type === "RETAILER") return <Factory size={20} />;
  if (item.energy_domain === "coal") return <Fuel size={20} />;
  if (item.energy_domain === "heat") return <Flame size={20} />;
  if (item.energy_domain === "gas") return <Waves size={20} />;
  if (item.energy_domain === "oil") return <Fuel size={20} />;
  return <UserRound size={20} />;
}

function domainGlyph(value: string) {
  if (value === "electricity") return <Zap size={17} />;
  if (value === "coal") return <Fuel size={17} />;
  if (value === "heat") return <Flame size={17} />;
  if (value === "gas") return <Waves size={17} />;
  if (value === "oil") return <Fuel size={17} />;
  return <Network size={17} />;
}

function capabilityTone(state?: string) {
  if (state === "BLOCKED") return "danger" as const;
  if (state === "DEMO" || state === "ADAPTER" || state === "NOT_CONFIGURED") return "warning" as const;
  return "success" as const;
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

function IdentityTopology({ items }: { items: IdentityDirectoryItem[] }) {
  const domains = Array.from(new Set(items.map((item) => item.energy_domain).filter((value): value is string => Boolean(value))))
    .sort((left, right) => (ENERGY_DOMAIN_ORDER.indexOf(left) + 10) - (ENERGY_DOMAIN_ORDER.indexOf(right) + 10));
  const regulators = items.filter((item) => item.org_type === "REGULATOR");
  const domainGroups = domains.map((domain) => ({ domain, items: items.filter((item) => item.energy_domain === domain) }));

  return <Card id="trusted-identity-topology" className="trusted-identity-architecture"><CardHeader><SurfaceHeader title="联邦式架构拓扑" description="各主体建设维护自己的数据域，统一底座只负责协同、裁决和留痕。" action={<ScanLine size={17} />} /></CardHeader><CardContent>
    <div className="trusted-identity-topology" aria-label="参与主体与可信数据空间连接拓扑">
      <div className="trusted-identity-topology-grid">
        <article className="trusted-identity-node trusted-identity-node-regulator">
          <span className="trusted-identity-node-kicker">数据使用方</span>
          <div className="trusted-identity-node-title"><Landmark size={18} /><strong>监管方</strong></div>
          <p>{regulators.length ? regulators.map((item) => item.org_name || item.org_id).join("、") : "当前没有登记监管主体"}</p>
          <span className="trusted-identity-node-meta">{regulators.length} 个已登记主体 · 可发起跨能源查询</span>
        </article>

        <article className="trusted-identity-node trusted-identity-node-execution">
          <span className="trusted-identity-node-kicker">可信智能执行层</span>
          <div className="trusted-identity-node-title"><Network size={18} /><strong>受控协同底座</strong></div>
          <div className="trusted-identity-layer-list"><span>请求解析</span><span>确定性策略裁决</span><span>结果审查与隐私计算</span><span>哈希链存证</span></div>
          <span className="trusted-identity-node-meta">原始数据留在企业连接器内</span>
        </article>

        <div className="trusted-identity-domain-stack">
          {domainGroups.map(({ domain, items: group }) => {
            const enterprises = group.filter((item) => item.org_type !== "EXCHANGE");
            const exchanges = group.filter((item) => item.org_type === "EXCHANGE");
            return <article className="trusted-identity-node trusted-identity-node-domain" data-domain={domain} key={domain}>
              <span className="trusted-identity-domain-icon">{domainGlyph(domain)}</span>
              <div className="trusted-identity-domain-copy"><strong>{domainLabel(domain)}连接器域</strong><small>{group.length} 个主体 · 数据不出域</small><span>{enterprises.length} 个企业 · {exchanges.length} 个交易中心</span></div>
              <Badge tone="success" dot>域内计算</Badge>
            </article>;
          })}
          {!domainGroups.length && <div className="trusted-identity-domain-empty">暂无已登记能源域</div>}
        </div>
      </div>
      <span className="trusted-identity-flow-line trusted-identity-flow-line-a" aria-hidden="true" />
      <span className="trusted-identity-flow-line trusted-identity-flow-line-b" aria-hidden="true" />
      <span className="trusted-identity-flow-particle trusted-identity-flow-particle-a" aria-hidden="true" />
      <span className="trusted-identity-flow-particle trusted-identity-flow-particle-b" aria-hidden="true" />
    </div>
    <div className="trusted-identity-legend"><span><i className="trusted-dot trusted-dot-brand" />数据使用方发起请求</span><span><i className="trusted-dot trusted-dot-info" />可信执行层裁决</span><span><i className="trusted-dot trusted-dot-success" />连接器域内计算</span><span><i className="trusted-dot trusted-dot-audit" />全程可追溯审计</span></div>
  </CardContent></Card>;
}

function DidDocumentDisclosure({ item }: { item: IdentityDirectoryItem }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [document, setDocument] = useState<DidDocumentPayload | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  async function readDocument() {
    if (document || loading) return;
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    setLoading(true);
    setError("");
    try {
      setDocument(await loadDidDocument(item.did_id, controller.signal));
    } catch (reason) {
      if ((reason instanceof DOMException || reason instanceof Error) && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "DID 文档读取失败");
    } finally {
      setLoading(false);
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }

  async function toggleDocument() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    await readDocument();
  }

  async function handleCopy() {
    await copyValue(item.did_id);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return <>
    <div className="trusted-identity-record-did"><code>{item.did_id}</code><IconButton label="复制 DID" onClick={handleCopy}><Copy size={13} /></IconButton>{copied && <span className="trusted-identity-copy-feedback" role="status">已复制</span>}</div>
    <button className="trusted-identity-document-trigger" type="button" onClick={() => toggleDocument()} aria-busy={loading || undefined} disabled={loading} aria-expanded={open} aria-controls={`did-document-${item.did_id}`}><FileJson2 size={14} />{loading ? "正在读取 DID 文档" : open ? "收起 DID 文档" : "查看 DID 文档（W3C 风格）"}<ChevronDown size={14} className={open ? "is-open" : ""} /></button>
    {open && <div className="trusted-identity-document" id={`did-document-${item.did_id}`}>
      {loading && <div className="trusted-identity-document-loading" role="status"><LoaderCircle className="energy-spin" size={15} />正在从身份记录读取文档</div>}
      {error && <div className="trusted-identity-document-error" role="alert"><span>{error}</span><Button variant="link" size="sm" onClick={() => { setDocument(null); setError(""); setOpen(true); return readDocument(); }}>重试</Button></div>}
      {document && <><div className="trusted-identity-document-meta"><StatusBadge value={document.credential_status} /><span>验证来源：{labelForCode(document.source_of_truth, "DID 身份记录")}</span></div><pre>{JSON.stringify(document.document, null, 2)}</pre></>}
    </div>}
  </>;
}

function IdentityRecord({ item }: { item: IdentityDirectoryItem }) {
  return <article className="trusted-identity-record">
    <div className="trusted-identity-record-header"><span className="trusted-identity-record-avatar">{identityGlyph(item)}</span><div className="trusted-identity-record-title"><strong>{valueOrDash(item.org_name)}</strong><span>{roleLabel(item.org_type)} · {domainLabel(item.energy_domain)}</span></div><StatusBadge value={item.credential_status} /></div>
    <div className="trusted-identity-record-facts"><span><small>主体标识</small><code>{item.org_id}</code></span><span><small>企业账号</small><b>{item.member_count || 0}</b></span><span><small>状态</small><b>{labelForCode(item.status, "未登记")}</b></span></div>
    <DidDocumentDisclosure item={item} />
  </article>;
}

function IdentityDirectory({ remote }: { remote: ReturnType<typeof useRemote<Awaited<ReturnType<typeof loadIdentityDirectory>>>> }) {
  const items = remote.data?.items || [];
  const domainCount = remote.data?.energy_domains.length || 0;
  const memberCount = items.reduce((sum, item) => sum + item.member_count, 0);
  return <Card id="trusted-identity-directory" className="trusted-identity-directory-card"><CardHeader><SurfaceHeader title="主体身份注册表" description="主体清单来自后端组织与 DID 记录；文档按需读取，不把企业私钥带入平台。" action={<div className={`trusted-identity-sync-state${remote.refreshing ? " is-refreshing" : ""}`} role="status"><i /><span>{remote.refreshing ? "正在同步" : "目录已同步"}</span></div>} /></CardHeader><CardContent>
    <MetricBand items={[{ label: "已登记主体", value: String(remote.data?.total ?? 0), detail: "组织 DID 记录", tone: "brand" }, { label: "已验证凭证", value: String(remote.data?.verified_count ?? 0), detail: "状态来自身份记录", tone: "success" }, { label: "能源域", value: String(domainCount), detail: "按企业域拆分", tone: "info" }, { label: "企业账号", value: String(memberCount), detail: "归属于各企业", tone: "warning" }]} />
    {remote.error && <RemoteState error={remote.error} onRetry={() => void remote.reload()} />}
    {remote.loading && <div className="trusted-identity-directory-grid" aria-label="正在加载主体身份"><div className="trusted-identity-skeleton" /><div className="trusted-identity-skeleton" /><div className="trusted-identity-skeleton" /><div className="trusted-identity-skeleton" /></div>}
    {!remote.loading && !remote.error && <>{remote.data?.empty_state ? <RemoteState empty emptyLabel="暂无已登记主体；请先由企业完成身份注册" /> : <div className="trusted-identity-directory-grid">{items.map((item) => <IdentityRecord item={item} key={item.did_id} />)}</div>}</>}
  </CardContent></Card>;
}

export function IdentityPage() {
  const remote = useRemote(loadIdentity, []);
  const directoryRemote = useRemote(loadIdentityDirectory, []);
  const { context } = useTrustedSpaceContext();
  const identity = remote.data;
  const directoryItems = directoryRemote.data?.items || [];
  return <PageFrame title="身份拓扑" action={<Button variant="secondary" onClick={() => Promise.all([remote.reload(), directoryRemote.reload()])} busy={remote.refreshing || directoryRemote.refreshing}><RefreshCw size={14} />刷新主体状态</Button>}>
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    {identity && <>
      <div className="trusted-identity-layout">
        <nav className="trusted-identity-nav" aria-label="参与主体分区">
          <a className="is-active" href="#trusted-identity-subject"><UserRound size={14} />主体概览</a>
          <a href="#trusted-identity-topology"><Network size={14} />身份拓扑</a>
          <a href="#trusted-identity-directory"><Building2 size={14} />主体注册表</a>
          <a href="#trusted-identity-did"><Fingerprint size={14} />DID 身份</a>
          <a href="#trusted-identity-connector"><Link2 size={14} />连接器绑定</a>
          <a href="#trusted-identity-certificate"><FileKey2 size={14} />数字证书</a>
          <a href="#trusted-identity-capabilities"><ShieldCheck size={14} />能力矩阵</a>
        </nav>
        <div className="trusted-identity-content">
          <div className="trusted-detail-grid trusted-identity-grid">
            <div className="trusted-detail-main"><Card id="trusted-identity-subject"><CardHeader><SurfaceHeader title="主体信息" description={`来源：${labelForCode(identity.source_of_truth, "组织与用户记录")}`} action={<StatusBadge value={identity.subject.status} />} /></CardHeader><CardContent><div className="trusted-profile-block"><span className="trusted-profile-avatar"><UserRound size={24} /></span><div><h3>{identity.subject.org_name || "未配置组织"}</h3><div className="trusted-profile-badges"><Badge tone="brand">{identity.subject.org_id}</Badge><Badge tone="neutral">{ROLE_LABELS[identity.actor.role_code as keyof typeof ROLE_LABELS] || labelForCode(identity.actor.role_code, "未登记角色")}</Badge></div></div></div><Divider /><dl className="trusted-definition-grid"><div><dt>主体名称</dt><dd>{valueOrDash(identity.subject.org_name)}</dd></div><div><dt>主体类型</dt><dd>{ROLE_LABELS[identity.subject.org_type as keyof typeof ROLE_LABELS] || labelForCode(identity.subject.org_type, "未登记主体类型")}</dd></div><div><dt>组织标识</dt><dd><code>{identity.subject.org_id}</code><IconButton label="复制组织标识" onClick={() => copyValue(identity.subject.org_id)}><Copy size={13} /></IconButton></dd></div><div><dt>当前用户</dt><dd>{identity.actor.display_name}</dd></div><div><dt>凭证状态</dt><dd><StatusBadge value={identity.did.credential_status} /></dd></div><div><dt>信用代码</dt><dd>{valueOrDash(identity.subject.credit_code)}</dd></div></dl></CardContent></Card><Card id="trusted-identity-certificate"><CardHeader><SurfaceHeader title="数字证书" description="后端只返回凭证元数据与验证结果，不返回私钥或下载文件" action={<FileKey2 size={17} />} /></CardHeader><CardContent><dl className="trusted-definition-grid"><div><dt>证书颁发方</dt><dd>{valueOrDash(identity.did.issuer)}</dd></div><div><dt>凭证类型</dt><dd>{identity.did.credential_type?.map((item) => labelForCode(item, "已登记凭证类型")).join(" / ") || "—"}</dd></div><div><dt>生效时间</dt><dd className="trusted-mono">{formatTime(identity.did.issued_at)}</dd></div><div><dt>有效期至</dt><dd className="trusted-mono">{formatTime(identity.did.expires_at)}</dd></div></dl><span className="trusted-muted">证书摘要已展示；证书文件下载需在企业内网完成配置。</span></CardContent></Card></div>
            <div className="trusted-detail-side"><Card id="trusted-identity-did"><CardHeader><SurfaceHeader title="DID 身份" description={`来源：${labelForCode(identity.did.source_of_truth, "企业身份记录")}`} action={<Fingerprint size={17} />} /></CardHeader><CardContent><div className="trusted-did-value"><code>{valueOrDash(identity.did.did_id)}</code><IconButton label="复制 DID" onClick={() => copyValue(identity.did.did_id)}><Copy size={13} /></IconButton></div><dl className="trusted-definition-list"><div><dt>公钥指纹</dt><dd><code>{valueOrDash(identity.did.public_key_fingerprint)}</code></dd></div><div><dt>外部链地址</dt><dd><code>{valueOrDash(identity.did.chain_address)}</code></dd></div><div><dt>私钥位置</dt><dd><Badge tone="success">企业连接器密钥存储</Badge></dd></div></dl><div className="trusted-note"><LockKeyhole size={14} /><span>企业私钥不进入平台数据库、GitHub 或 API，只在企业连接器密钥存储中使用。</span></div></CardContent></Card><Card id="trusted-identity-connector"><CardHeader><SurfaceHeader title="可信数据空间连接器" description={`来源：${labelForCode(identity.connector.source_of_truth, "数据连接记录")}`} action={<Link2 size={17} />} /></CardHeader><CardContent><dl className="trusted-definition-list"><div><dt>连接器类型</dt><dd>{labelForCode(identity.connector.code, "企业侧连接器")}</dd></div><div><dt>协议版本</dt><dd>{identity.connector.protocol_version}</dd></div><div><dt>已登记数据源</dt><dd>{identity.connector.source_count}</dd></div><div><dt>当前能力</dt><dd><Badge tone="warning" dot>{labelForCode(identity.connector.capability_state, "待配置")}</Badge></dd></div><div><dt>连接状态</dt><dd><StatusBadge value={identity.connector.readiness} /></dd></div></dl><span className="trusted-muted">连接器配置说明需在企业内网完成，不在平台侧提供下载动作。</span></CardContent></Card></div>
          </div>

          <IdentityTopology items={directoryItems} />
          <IdentityDirectory remote={directoryRemote} />

          <Card id="trusted-identity-capabilities" className="trusted-capability-card"><CardHeader><SurfaceHeader title="可信能力矩阵" description="能力标签由后端返回；适配器、阻断和演示状态不会被包装成生产连接。" /></CardHeader><CardContent><div className="trusted-capability-table">{Object.entries(identity.capability_matrix).map(([key, item]) => <div className="trusted-capability-row" key={key}><span className="trusted-capability-name"><ShieldCheck size={15} />{capabilityLabel(key)}</span><Badge tone={capabilityTone(item.capability_state)}>{labelForCode(item.capability_state, "未配置")}</Badge><span className="trusted-muted">{item.readiness ? labelForCode(item.readiness, "已登记状态") : labelForCode(item.source_of_truth, "未登记来源")}</span><CheckCircle2 size={15} className={item.capability_state === "BLOCKED" ? "trusted-icon-muted" : "trusted-icon-success"} /></div>)}</div></CardContent></Card>
          <Card className="trusted-capability-card tw-mt-4"><CardHeader><SurfaceHeader title="当前账号权限" description="权限由企业最高权限账号授予，不绑定固定岗位名称。" /></CardHeader><CardContent><div className="trusted-function-chips">{(context?.actor.permissions || []).map((permission) => <span key={permission}>{permissionLabels[permission] || "企业授予权限"}</span>)}{!(context?.actor.permissions || []).length && <span>当前账号没有业务权限</span>}</div></CardContent></Card>
        </div>
      </div>
    </>}
  </PageFrame>;
}
