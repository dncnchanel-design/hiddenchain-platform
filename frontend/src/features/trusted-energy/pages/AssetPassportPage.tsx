import { useMemo, useState } from "react";
import { ArrowRight, BarChart3, Clock3, Copy, Database, FileCheck2, GitBranch, ShieldCheck } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { formatDate, shortHash } from "../../../api";
import { loadAsset, type AssetVersion, type UsageRequestSummary } from "../trusted-space-api";
import { routeForView, trustedEntityId } from "../types";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, Divider, IconButton, MetricBand, RemoteState, StatusBadge, SurfaceHeader, Tabs, TabsContent, TabsList, TabsTrigger, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";

function printable(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function objectRows(value: Record<string, unknown> | null | undefined) {
  return Object.entries(value || {});
}

function qualityValue(version: AssetVersion | undefined, key: string) {
  const value = version?.quality?.metrics?.[key];
  return value === undefined ? "—" : printable(value);
}

export function AssetPassportPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const assetId = trustedEntityId(location.pathname, "assets");
  const [tab, setTab] = useState("passport");
  const remote = useRemote(
    (signal) => assetId ? loadAsset(assetId, signal) : Promise.reject(new Error("缺少资产 ID")),
    [assetId],
  );
  const payload = remote.data;
  const asset = payload?.asset;
  const currentVersion = useMemo(() => payload?.versions.find((version) => version.version_id === payload.current_version_id) || payload?.versions[0], [payload]);

  function copyAssetId() {
    if (asset?.asset_id) void navigator.clipboard?.writeText(asset.asset_id);
  }

  return <PageFrame title="数据资产护照" description={asset ? `资产元数据、质量口径、使用规则和存证引用保持在同一份可追溯视图：${asset.asset_name}。` : "读取真实资产元数据、质量口径、使用规则和存证引用。"} back={routeForView("catalog")} action={asset && <div className="tw-flex tw-items-center tw-gap-2">{payload.actions.can_review_inbound && <Button variant="secondary" onClick={() => navigate(`${routeForView("authorizations")}?view=inbox`)}>查看入站授权</Button>}{payload.actions.can_request_usage ? <Button variant="primary" onClick={() => navigate(routeForView("apply", asset.asset_id))}>申请使用 <ArrowRight size={14} /></Button> : <Button variant="secondary" disabled title="当前角色或组织无权申请此资产">申请使用</Button>}</div>}>
    {remote.loading && !payload && <RemoteState loading />}
    {remote.error && !payload && <RemoteState error={remote.error} onRetry={() => void remote.reload()} />}
    {payload && asset && <>
      <Card className="trusted-asset-hero"><CardContent><div className="trusted-passport-title"><span className="trusted-asset-icon"><Database size={21} /></span><div><div className="trusted-heading-title-row"><h2>{asset.asset_name}</h2><StatusBadge value={asset.status} /></div><p>{asset.asset_code} · {asset.domain || "未标注领域"}</p><div className="trusted-asset-meta"><span><strong>资产 ID</strong><code>{asset.asset_id}</code><IconButton label="复制资产 ID" onClick={copyAssetId}><Copy size={12} /></IconButton></span><span><strong>提供方</strong><code>{asset.provider.org_name || asset.provider.org_id}</code></span></div></div></div><div className="trusted-passport-tags"><Badge tone="brand">{asset.asset_type}</Badge><Badge tone="neutral">{asset.classification}</Badge><Badge tone={asset.sensitivity_level === "L4" ? "danger" : "warning"}>敏感分级 {asset.sensitivity_level}</Badge><Badge tone="info">{currentVersion ? `V${currentVersion.version_no}` : "无版本"}</Badge></div></CardContent></Card>
      <MetricBand items={[{ label: "质量决策", value: currentVersion?.quality?.decision || "未评估", detail: currentVersion?.quality ? formatDate(currentVersion.quality.evaluated_at) : "没有质量记录", tone: currentVersion?.quality?.decision === "PASS" ? "success" : "warning" }, { label: "当前版本", value: currentVersion ? `V${currentVersion.version_no}` : "—", detail: currentVersion?.schema_version || "未配置", tone: "info" }, { label: "记录数", value: currentVersion?.record_count === null || currentVersion?.record_count === undefined ? "—" : String(currentVersion.record_count), detail: "以版本登记为准", tone: "brand" }, { label: "来源能力", value: payload.source.capability_label, detail: payload.source.status, tone: payload.source.status === "READY" ? "success" : "warning" }]} />
      <Tabs value={tab} onValueChange={setTab} className="trusted-detail-tabs"><TabsList><TabsTrigger value="passport">资产护照</TabsTrigger><TabsTrigger value="versions">版本历史</TabsTrigger><TabsTrigger value="rules">使用规则</TabsTrigger><TabsTrigger value="evidence">存证链</TabsTrigger></TabsList><TabsContent value="passport"><div className="trusted-detail-grid"><Card><CardHeader><SurfaceHeader title="数据来源" description="来源、版本和当前质量指标" action={<BarChart3 size={16} />} /></CardHeader><CardContent><dl className="trusted-definition-list"><div><dt>来源系统</dt><dd>{payload.source.source_code || payload.source.source_id || "未登记"}</dd></div><div><dt>提供方组织</dt><dd>{asset.provider.org_name || asset.provider.org_id}</dd></div><div><dt>数据域</dt><dd>{asset.domain || "未标注"}</dd></div><div><dt>当前数据哈希</dt><dd><code>{shortHash(currentVersion?.data_hash)}</code></dd></div></dl><Divider /><div className="trusted-quality-row"><div><small>完整性</small><strong>{qualityValue(currentVersion, "completeness")}</strong></div><div><small>及时性</small><strong>{qualityValue(currentVersion, "timeliness")}</strong></div><div><small>一致性</small><strong>{qualityValue(currentVersion, "consistency")}</strong></div><div><small>质量哈希</small><strong>{shortHash(currentVersion?.quality?.quality_hash)}</strong></div></div></CardContent></Card><Card><CardHeader><SurfaceHeader title="可信引用" description="只展示后端已登记的摘要和规则引用" action={<ShieldCheck size={16} />} /></CardHeader><CardContent><div className="trusted-evidence-list"><div><span>版本摘要</span><code>{shortHash(currentVersion?.immutable_hash || currentVersion?.data_hash)}</code><Badge tone={currentVersion ? "success" : "warning"}>{currentVersion ? "已登记" : "缺失"}</Badge></div><div><span>护照状态</span><Badge tone={currentVersion?.passport?.status === "ACTIVE" ? "success" : "warning"}>{currentVersion?.passport?.status || "未登记"}</Badge></div><div><span>证据引用数</span><strong>{payload.evidence_summary.passport_evidence_refs.length}</strong></div><div><span>链上状态</span><Badge tone="warning">{payload.evidence_summary.source_of_truth || "未配置"}</Badge></div></div><p className="trusted-inline-status">没有后端返回的 TxHash 或区块高度时，此页面不会生成或展示伪造链上值。</p></CardContent></Card></div><Card className="tw-mt-4"><CardHeader><SurfaceHeader title="登记元数据" description="资产注册时写入的可追溯字段" /></CardHeader><CardContent><dl className="trusted-definition-list">{objectRows(asset.metadata).map(([key, value]) => <div key={key}><dt>{key}</dt><dd><code>{printable(value)}</code></dd></div>)}{!Object.keys(asset.metadata || {}).length && <div><dt>状态</dt><dd>暂无额外元数据</dd></div>}</dl></CardContent></Card></TabsContent><TabsContent value="versions"><Card><CardHeader><SurfaceHeader title="版本历史" description="版本变更需要重新进行用途与授权检查" /></CardHeader><CardContent className="trusted-table-wrap"><Table><TableHeader><TableRow><TableHead>版本</TableHead><TableHead>发布时间/状态</TableHead><TableHead>数据哈希</TableHead><TableHead>质量决策</TableHead><TableHead>护照</TableHead></TableRow></TableHeader><TableBody>{payload.versions.map((version) => <TableRow key={version.version_id}><TableCell><code>V{version.version_no}</code><div>{version.schema_version}</div></TableCell><TableCell><StatusBadge value={version.status} /></TableCell><TableCell><code>{shortHash(version.data_hash)}</code></TableCell><TableCell>{version.quality?.decision || "未评估"}</TableCell><TableCell>{version.passport ? <Badge tone="success">V{version.passport.passport_version}</Badge> : <Badge tone="warning">未登记</Badge>}</TableCell></TableRow>)}{!payload.versions.length && <TableRow><TableCell colSpan={5}>暂无版本记录</TableCell></TableRow>}</TableBody></Table></CardContent></Card></TabsContent><TabsContent value="rules"><Card><CardHeader><SurfaceHeader title="使用规则" description="申请用途必须落在提供方登记的规则范围内" /></CardHeader><CardContent><div className="trusted-rule-list">{objectRows(payload.usage_rules).map(([key, value]) => <div key={key}><strong>{key}</strong><span>{printable(value)}</span></div>)}{!Object.keys(payload.usage_rules || {}).length && <div><strong>规则状态</strong><span>提供方尚未登记结构化使用规则，需人工审核。</span></div>}</div><Divider /><div className="trusted-asset-meta"><span>政策引用：{payload.policy_refs.length ? payload.policy_refs.join("、") : "未登记"}</span></div></CardContent></Card></TabsContent><TabsContent value="evidence"><Card><CardHeader><SurfaceHeader title="存证链" description="仅展示真实后端登记的证据引用；外部链锚定未配置时保持明确边界。" /></CardHeader><CardContent><div className="trusted-chain-list"><div><GitBranch size={15} /><span>护照证据引用</span><code>{payload.evidence_summary.passport_evidence_refs.length ? payload.evidence_summary.passport_evidence_refs.join("、") : "—"}</code><Badge tone={payload.evidence_summary.passport_evidence_refs.length ? "success" : "warning"}>{payload.evidence_summary.passport_evidence_refs.length ? "已登记" : "缺失"}</Badge></div><div><FileCheck2 size={15} /><span>数据空间协议</span><strong>{payload.evidence_summary.active_agreement_count}</strong><Badge tone="info">真实记录</Badge></div><div><Clock3 size={15} /><span>合同记录</span><strong>{payload.evidence_summary.contract_count}</strong><Badge tone="info">真实记录</Badge></div></div><p className="trusted-inline-status">{payload.source.capability_label} · {payload.source.status}。未返回 TxHash/块高，未显示 DEMO 链值。</p></CardContent></Card></TabsContent></Tabs>
      <UsageRequestCard requests={payload.usage_requests} onOpen={(requestId) => navigate(`${routeForView("authorizations")}?request=${encodeURIComponent(requestId)}`)} />
    </>}
  </PageFrame>;
}

function UsageRequestCard({ requests, onOpen }: { requests: UsageRequestSummary[]; onOpen: (requestId: string) => void }) {
  return <Card className="tw-mt-4"><CardHeader><SurfaceHeader title="授权记录" description="仅显示当前主体按后端权限可见的使用申请" action={<Button variant="ghost" size="sm" onClick={() => onOpen("")}>查看全部</Button>} /></CardHeader><CardContent className="trusted-table-wrap"><Table><TableHeader><TableRow><TableHead>申请</TableHead><TableHead>申请方</TableHead><TableHead>用途/方式</TableHead><TableHead>状态</TableHead><TableHead>动作</TableHead></TableRow></TableHeader><TableBody>{requests.map((request) => <TableRow key={request.request_id}><TableCell><code>{request.request_id}</code></TableCell><TableCell>{request.applicant_org_name || request.applicant_org_id}</TableCell><TableCell>{request.purpose} · {request.usage_mode}</TableCell><TableCell><StatusBadge value={request.status} /></TableCell><TableCell><Button variant="link" size="sm" onClick={() => onOpen(request.request_id)}>查看</Button></TableCell></TableRow>)}{!requests.length && <TableRow><TableCell colSpan={5}>当前主体暂无可见授权记录</TableCell></TableRow>}</TableBody></Table></CardContent></Card>;
}
