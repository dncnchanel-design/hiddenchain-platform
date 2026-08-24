import { useRef, useState } from "react";
import { Check, FileKey2, RefreshCw, Settings2, ShieldCheck, SlidersHorizontal, X } from "lucide-react";
import { ApiError, prepareIdempotencyKey, type IdempotencyKeyRecord } from "../../../api";
import { useRemote } from "../../../hooks";
import { useTrustedSpaceContext } from "../trusted-space-context";
import {
  createAccessRule,
  loadAccessRules,
  loadUsageRequests,
  revokeAccessRule,
  transitionUsageRequest,
  type AccessRule,
  type UsageRequest,
  type UsageRequestAction,
} from "../trusted-space-api";
import { purposeLabel, requestStatusLabel, usageModeLabel } from "../trusted-space-labels";
import { Badge, Button, Card, CardContent, CardHeader, FieldLabel, Input, RemoteState, Select, Sheet, StatusBadge, SurfaceHeader } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";

const domains = [
  { value: "electricity", label: "电力" },
  { value: "coal", label: "煤炭" },
  { value: "heat", label: "热能" },
  { value: "gas", label: "天然气" },
  { value: "oil", label: "石油" },
];

const functions = [
  { value: "sum", label: "求和" },
  { value: "average", label: "平均值" },
  { value: "count", label: "计数" },
  { value: "trend", label: "趋势" },
  { value: "group_by", label: "分组汇总" },
  { value: "mpc_aggregation", label: "安全多方聚合" },
];

const modes = [
  { value: "AUTO_CALL", label: "命中后自动调用" },
  { value: "ENTERPRISE_APPROVAL", label: "需要企业审批" },
  { value: "FORBIDDEN", label: "禁止调用" },
];

function ruleStatus(rule: AccessRule) {
  return rule.status === "ACTIVE" ? "已启用" : rule.status === "REVOKED" ? "已停用" : rule.status;
}

function modeLabel(mode: string) {
  return modes.find((item) => item.value === mode)?.label || mode;
}

export function StrategyCenterPage() {
  const { context } = useTrustedSpaceContext();
  const rulesRemote = useRemote((signal) => loadAccessRules({}, signal), []);
  const requestsRemote = useRemote((signal) => loadUsageRequests({ inbox: true, page: 1, pageSize: 8 }, signal), []);
  const [selectedRule, setSelectedRule] = useState<AccessRule | null>(null);
  const [selectedRequest, setSelectedRequest] = useState<UsageRequest | null>(null);
  const [ruleCode, setRuleCode] = useState("ENERGY_DAILY_QUERY");
  const [domain, setDomain] = useState("electricity");
  const [resourceId, setResourceId] = useState("load");
  const [functionCode, setFunctionCode] = useState("average");
  const [mode, setMode] = useState<"AUTO_CALL" | "ENTERPRISE_APPROVAL" | "FORBIDDEN">("ENTERPRISE_APPROVAL");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const idempotencyKeys = useRef<Record<string, IdempotencyKeyRecord>>({});
  const canManageRules = context?.actor.permissions?.includes("MANAGE_RULES") === true;
  const canReview = context?.role_capabilities.can_review_inbound_requests === true;

  function commandKey(fingerprint: string, scope: string) {
    const next = prepareIdempotencyKey(idempotencyKeys.current[fingerprint], scope, fingerprint);
    idempotencyKeys.current[fingerprint] = next;
    return next.key;
  }

  async function publishRule() {
    if (!ruleCode.trim() || !resourceId.trim()) {
      setError("规则编号和数据资源不能为空。");
      return;
    }
    setBusy("publish");
    setError("");
    try {
      await createAccessRule({
        rule_code: ruleCode.trim(),
        energy_domain: domain,
        resource_id: resourceId.trim(),
        function_code: functionCode,
        mode,
        scope: { output_mode: "AGGREGATE_ONLY", granularity: "DAY" },
        limits: { minimum_record_count: 3, max_duration_days: 31, output_mode: "AGGREGATE_ONLY" },
      }, { idempotencyKey: commandKey(`publish:${ruleCode}:${domain}:${resourceId}:${functionCode}:${mode}`, "publish-rule") });
      await rulesRemote.reload();
    } catch (reasonValue) {
      setError(reasonValue instanceof ApiError ? reasonValue.message : "规则发布失败，请重试。");
    } finally {
      setBusy("");
    }
  }

  async function toggleRule(rule: AccessRule) {
    setBusy(rule.rule_id);
    setError("");
    try {
      if (rule.status === "ACTIVE") {
        await revokeAccessRule(rule.rule_id, { idempotencyKey: commandKey(`revoke:${rule.rule_id}`, "revoke-rule") });
      } else {
        await createAccessRule({
          rule_code: rule.rule_code,
          energy_domain: rule.energy_domain || undefined,
          asset_id: rule.asset_id || undefined,
          resource_id: rule.resource_id,
          function_code: rule.function_code,
          mode: rule.mode as "AUTO_CALL" | "ENTERPRISE_APPROVAL" | "FORBIDDEN",
          scope: rule.scope,
          limits: rule.limits,
        }, { idempotencyKey: commandKey(`activate:${rule.rule_id}:${rule.version_no}`, "activate-rule") });
      }
      await rulesRemote.reload();
    } catch (reasonValue) {
      setError(reasonValue instanceof ApiError ? reasonValue.message : "规则状态更新失败，请重试。");
    } finally {
      setBusy("");
    }
  }

  async function reviewRequest(action: UsageRequestAction) {
    if (!selectedRequest) return;
    if ((action === "approve" || action === "reject") && !reason.trim()) {
      setError("批准或拒绝前必须填写理由。");
      return;
    }
    setBusy(`request:${action}`);
    setError("");
    try {
      await transitionUsageRequest(selectedRequest.request_id, action, reason.trim(), { idempotencyKey: commandKey(`${action}:${selectedRequest.request_id}:${reason}`, `request-${action}`) });
      setSelectedRequest(null);
      setReason("");
      await requestsRemote.reload();
    } catch (reasonValue) {
      setError(reasonValue instanceof ApiError ? reasonValue.message : "申请状态更新失败，请重试。");
    } finally {
      setBusy("");
    }
  }

  return <PageFrame title="策略中心" action={<Button variant="secondary" onClick={() => { void rulesRemote.reload(); void requestsRemote.reload(); }} busy={rulesRemote.refreshing || requestsRemote.refreshing}><RefreshCw size={14} />刷新</Button>}>
    {error && <div className="trusted-query-error" role="alert"><X size={16} /><span>{error}</span></div>}

    <div className="trusted-strategy-summary">
      <div><span>当前策略</span><strong>{rulesRemote.data?.items.length ?? 0}</strong></div>
      <div><span>待审核申请</span><strong>{requestsRemote.data?.total ?? 0}</strong></div>
      <div><span>当前身份</span><strong>{canManageRules ? "可管理" : "只读"}</strong></div>
      <div><span>默认裁决</span><strong>未命中即拒绝</strong></div>
    </div>

    <div className="trusted-strategy-layout">
      <Card>
        <CardHeader><SurfaceHeader title="策略规则" action={canManageRules ? <Badge tone="info"><SlidersHorizontal size={13} />可配置</Badge> : <Badge tone="neutral">只读</Badge>} /></CardHeader>
        <CardContent>
          <RemoteState loading={rulesRemote.loading && !rulesRemote.data} error={rulesRemote.error && !rulesRemote.data ? rulesRemote.error : undefined} onRetry={() => void rulesRemote.reload()} empty={!rulesRemote.loading && !rulesRemote.error && !rulesRemote.data?.items.length} emptyLabel="暂无策略规则" />
          {rulesRemote.data?.items.length ? <div className="trusted-strategy-rules">{rulesRemote.data.items.map((rule) => <div className="trusted-strategy-rule" key={rule.rule_id}>
            <div className="trusted-strategy-rule-icon"><ShieldCheck size={16} /></div>
            <div className="trusted-strategy-rule-copy"><strong>{rule.rule_code}</strong><span>{rule.resource_id} · {rule.function_code} · {modeLabel(rule.mode)}</span><small>{rule.version} · {rule.owner_org_id}</small></div>
            <StatusBadge value={ruleStatus(rule)} />
            <Button variant="ghost" size="icon" aria-label={`查看规则 ${rule.rule_code}`} title={`查看规则 ${rule.rule_code}`} onClick={() => setSelectedRule(rule)}><Settings2 size={15} /></Button>
            {canManageRules && <button type="button" className={`trusted-switch ${rule.status === "ACTIVE" ? "is-on" : ""}`} aria-pressed={rule.status === "ACTIVE"} aria-label={`${rule.status === "ACTIVE" ? "停用" : "启用"}规则 ${rule.rule_code}`} disabled={busy === rule.rule_id} onClick={() => void toggleRule(rule)}><span /></button>}
          </div>)}</div> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><SurfaceHeader title="发布策略" action={<FileKey2 size={16} />} /></CardHeader>
        <CardContent className="trusted-strategy-form">
          <div><FieldLabel htmlFor="strategy-code">规则编号</FieldLabel><Input id="strategy-code" value={ruleCode} onChange={(event) => setRuleCode(event.target.value)} /></div>
          <div><FieldLabel>能源种类</FieldLabel><Select value={domain} onChange={(event) => setDomain(event.target.value)} options={domains} /></div>
          <div><FieldLabel htmlFor="strategy-resource">数据资源</FieldLabel><Input id="strategy-resource" value={resourceId} onChange={(event) => setResourceId(event.target.value)} /></div>
          <div><FieldLabel>固定函数</FieldLabel><Select value={functionCode} onChange={(event) => setFunctionCode(event.target.value)} options={functions} /></div>
          <div><FieldLabel>调用方式</FieldLabel><Select value={mode} onChange={(event) => setMode(event.target.value as typeof mode)} options={modes} /></div>
          <Button variant="primary" onClick={() => void publishRule()} busy={busy === "publish"} disabled={!canManageRules}><Check size={14} />发布新版本</Button>
        </CardContent>
      </Card>
    </div>

    <Card className="trusted-strategy-requests">
      <CardHeader><SurfaceHeader title="授权申请" action={canReview ? <Badge tone="warning">待我审核</Badge> : <Badge tone="neutral">当前主体不可审核</Badge>} /></CardHeader>
      <CardContent>
        <RemoteState loading={requestsRemote.loading && !requestsRemote.data} error={requestsRemote.error && !requestsRemote.data ? requestsRemote.error : undefined} onRetry={() => void requestsRemote.reload()} empty={!requestsRemote.loading && !requestsRemote.error && !requestsRemote.data?.items.length} emptyLabel="暂无待审核申请" />
        {requestsRemote.data?.items.length ? <div className="trusted-strategy-request-list">{requestsRemote.data.items.map((request) => <button className="trusted-strategy-request" type="button" key={request.request_id} onClick={() => setSelectedRequest(request)}><span><strong>{request.asset.asset_name || "未命名数据资源"}</strong><small>{request.applicant.org_name} → {request.provider.org_name}</small></span><span><b>{purposeLabel(request.purpose)}</b><small>{usageModeLabel(request.usage_mode)}</small></span><StatusBadge value={requestStatusLabel(request.status)} /></button>)}</div> : null}
      </CardContent>
    </Card>

    <Sheet open={Boolean(selectedRule)} onOpenChange={(open) => { if (!open) setSelectedRule(null); }} title="策略详情" side="right" className="trusted-strategy-sheet">
      {selectedRule && <div className="trusted-strategy-detail"><div className="trusted-detail-status"><StatusBadge value={ruleStatus(selectedRule)} /><code>{selectedRule.rule_hash}</code></div><dl><div><dt>规则编号</dt><dd>{selectedRule.rule_code}</dd></div><div><dt>规则版本</dt><dd>{selectedRule.version}</dd></div><div><dt>数据资源</dt><dd>{selectedRule.resource_id}</dd></div><div><dt>能源种类</dt><dd>{domains.find((item) => item.value === selectedRule.energy_domain)?.label || "未限定"}</dd></div><div><dt>固定函数</dt><dd>{functions.find((item) => item.value === selectedRule.function_code)?.label || selectedRule.function_code}</dd></div><div><dt>调用方式</dt><dd>{modeLabel(selectedRule.mode)}</dd></div></dl><Button variant={selectedRule.status === "ACTIVE" ? "danger" : "primary"} busy={busy === selectedRule.rule_id} disabled={!canManageRules} onClick={() => void toggleRule(selectedRule)}>{selectedRule.status === "ACTIVE" ? "停用规则" : "启用规则"}</Button></div>}
    </Sheet>

    <Sheet open={Boolean(selectedRequest)} onOpenChange={(open) => { if (!open) { setSelectedRequest(null); setReason(""); } }} title="申请详情" side="right" className="trusted-strategy-sheet">
      {selectedRequest && <div className="trusted-strategy-detail"><div className="trusted-detail-status"><StatusBadge value={requestStatusLabel(selectedRequest.status)} /><code>{selectedRequest.request_id}</code></div><dl><div><dt>数据资源</dt><dd>{selectedRequest.asset.asset_name || "未命名数据资源"}</dd></div><div><dt>申请主体</dt><dd>{selectedRequest.applicant.org_name}</dd></div><div><dt>提供主体</dt><dd>{selectedRequest.provider.org_name}</dd></div><div><dt>用途</dt><dd>{purposeLabel(selectedRequest.purpose)}</dd></div><div><dt>使用方式</dt><dd>{usageModeLabel(selectedRequest.usage_mode)}</dd></div><div><dt>有效期</dt><dd>{selectedRequest.duration_days} 天</dd></div></dl><FieldLabel htmlFor="strategy-review-reason">处理理由</FieldLabel><Input id="strategy-review-reason" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="填写处理理由" /><div className="trusted-submit-actions"><Button variant="danger" busy={busy === "request:reject"} disabled={!canReview} onClick={() => void reviewRequest("reject")}>拒绝</Button><Button variant="primary" busy={busy === "request:approve"} disabled={!canReview} onClick={() => void reviewRequest("approve")}>批准</Button></div></div>}
    </Sheet>
  </PageFrame>;
}
