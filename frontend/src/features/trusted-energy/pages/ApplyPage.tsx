import { useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, FileCheck2, LockKeyhole, Network, Search, ShieldCheck } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError, prepareIdempotencyKey, type IdempotencyKeyRecord } from "../../../api";
import { createUsageRequest, loadAsset, type UsageRequest } from "../trusted-space-api";
import { routeForView, trustedEntityId } from "../types";
import { useRemote } from "../../../hooks";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, FieldLabel, Input, RemoteState, Steps } from "../components/ui-primitives";
import { PageFrame } from "../components/PageFrame";

const useCases = [
  { id: "SETTLEMENT_ANALYSIS", title: "结算分析", desc: "按既定规则核验结算电量与价格", icon: FileCheck2 },
  { id: "CROSS_CHECK", title: "交叉分析", desc: "与授权的负荷数据进行聚合比对", icon: Search },
  { id: "MODEL_TRAINING", title: "模型训练", desc: "训练能源预测模型，仅返回模型指标", icon: Network },
  { id: "AUDIT_REVIEW", title: "审计复核", desc: "支持监管审计的口径与证据核验", icon: ShieldCheck },
  { id: "CONTROLLED_OTHER", title: "其他受控用途", desc: "由提供方人工审核用途与处理方式", icon: LockKeyhole },
] as const;

const methods = [
  { id: "MPC_AGGREGATE", title: "MPC 聚合计算", desc: "仅暴露计算结果摘要，不返回原始数据", badge: "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST" },
  { id: "MASKED_QUERY", title: "脱敏查询", desc: "返回预先定义的脱敏统计字段", badge: "ADAPTER" },
] as const;

export function ApplyPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const assetId = trustedEntityId(location.pathname, "apply");
  const [step, setStep] = useState(0);
  const [purpose, setPurpose] = useState<(typeof useCases)[number]["id"]>(useCases[0].id);
  const [method, setMethod] = useState<(typeof methods)[number]["id"]>(methods[0].id);
  const [durationDays, setDurationDays] = useState<number | null>(null);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [submission, setSubmission] = useState<UsageRequest | null>(null);
  const idempotencyRef = useRef<IdempotencyKeyRecord | null>(null);
  const remote = useRemote(
    (signal) => assetId ? loadAsset(assetId, signal) : Promise.reject(new Error("缺少资产 ID")),
    [assetId],
  );
  const payload = remote.data;
  const asset = payload?.asset;
  const currentVersion = payload?.versions.find((version) => version.version_id === payload.current_version_id) || payload?.versions[0];
  const durationPolicy = payload?.duration_policy;
  const steps = ["选择用途", "使用方式", "确认条件", "提交申请"];

  const effectiveDurationDays = durationDays ?? durationPolicy?.default_days ?? 0;
  const durationValid = Boolean(durationPolicy && effectiveDurationDays >= durationPolicy.min_days && effectiveDurationDays <= durationPolicy.max_days);

  function next() {
    setSubmitError("");
    if (step === 2 && (!termsAccepted || !durationValid)) {
      setSubmitError(!durationValid ? "请填写符合服务端期限策略的申请有效期" : "请先确认数据范围、结果口径与责任边界");
      return;
    }
    if (step < 3) {
      setStep((value) => value + 1);
      return;
    }
    void submitRequest();
  }

  async function submitRequest() {
    if (!asset || !payload?.actions.can_request_usage) {
      setSubmitError("当前账号无权申请此资产");
      return;
    }
    if (!durationPolicy || !durationValid) {
      setSubmitError(durationPolicy ? `申请期限必须在 ${durationPolicy.min_days} 至 ${durationPolicy.max_days} 日之间` : "正在读取资产期限策略，请稍后重试");
      return;
    }
    setSubmitError("");
    const fingerprint = JSON.stringify({ asset: asset.asset_id, version: currentVersion?.version_id || null, purpose, method, duration: effectiveDurationDays });
    const key = prepareIdempotencyKey(idempotencyRef.current, "usage-request", fingerprint);
    idempotencyRef.current = key;
    try {
      const result = await createUsageRequest({
        asset_id: asset.asset_id,
        asset_version_id: currentVersion?.version_id,
        purpose,
        usage_mode: method,
        requested_scope: { purpose_code: purpose, output_mode: method === "MPC_AGGREGATE" ? "AGGREGATE_ONLY" : "MASKED_QUERY", raw_data_export: false },
        requested_fields: ["summary", "quality_metrics"],
        duration_days: effectiveDurationDays,
        terms: { terms_version: "TRUSTED_SPACE_USAGE_V1", accepted: true, human_review_required: true, purpose_code: purpose, usage_mode: method, duration_policy_version: durationPolicy.policy_version },
      }, { idempotencyKey: key.key, retry: 0 });
      setSubmission(result);
    } catch (error) {
      setSubmitError(error instanceof ApiError ? error.message : "申请提交失败，请稍后重试");
    }
  }

  return <PageFrame title="使用申请" description={asset ? `申请访问「${asset.asset_name}」前，请按用途与处理边界完成确认。` : "读取真实资产后开始四步使用申请。"} back={asset ? routeForView("asset", asset.asset_id) : routeForView("catalog")}>
    {remote.loading && !payload && <RemoteState loading />}
    {remote.error && !payload && <RemoteState error={remote.error} onRetry={() => void remote.reload()} />}
    {payload && asset && <>
      <Card className="trusted-application-card"><CardContent><div className="trusted-application-meta"><span><small>申请资产</small><strong>{asset.asset_name}</strong></span><span><small>提供方</small><strong>{asset.provider.org_name || asset.provider.org_id}</strong></span><span><small>敏感等级</small><Badge tone={asset.sensitivity_level === "L4" ? "danger" : "warning"}>{asset.sensitivity_level}</Badge></span><span><small>允许期限</small><strong>{durationPolicy ? `${durationPolicy.min_days}–${durationPolicy.max_days} 日` : "读取中"}</strong><small>{durationPolicy ? `${durationPolicy.source} · ${durationPolicy.policy_version}` : "服务端策略"}</small></span></div></CardContent></Card>
      <Steps steps={steps} current={step} />
      {submission ? <Card className="trusted-submit-success"><CardContent><span className="trusted-success-icon"><Check size={24} /></span><h2>申请已提交至提供方审核</h2><p>申请编号 <code>{submission.request_id}</code> 已生成，当前状态为 <strong>{submission.status}</strong>，版本 {submission.state_version}。</p><p>申请期限 {submission.duration_days} 日 · 来源 {submission.duration_policy?.source || "服务端策略"}。系统不会代替提供方批准，也不会自动执行计算。</p><div className="trusted-submit-actions"><Button variant="secondary" onClick={() => navigate(routeForView("catalog"))}>返回数据目录</Button><Button variant="primary" onClick={() => navigate(`${routeForView("authorizations")}?request=${encodeURIComponent(submission.request_id)}`)}>查看申请记录 <ArrowRight size={14} /></Button></div></CardContent></Card> : <Card className="trusted-step-card"><CardHeader><CardTitle>{steps[step]}</CardTitle><p>{step === 0 ? "请选择本次申请的业务目标，目的将写入后续授权记录。" : step === 1 ? "选择提供方允许的处理方式，最终以提供方审核为准。" : step === 2 ? "确认数据范围、结果口径和责任边界。" : "提交前核对真实资产版本与本地受控能力边界。"}</p></CardHeader><CardContent>
        {step === 0 && <div className="trusted-option-grid">{useCases.map(({ id, title, desc, icon: Icon }) => <button type="button" className={`trusted-option-card${purpose === id ? " is-selected" : ""}`} key={id} onClick={() => setPurpose(id)}><span className="trusted-option-radio">{purpose === id && <i />}</span><Icon size={18} /><span><strong>{title}</strong><small>{desc}</small></span></button>)}</div>}
        {step === 1 && <div className="trusted-option-grid trusted-method-grid">{methods.map(({ id, title, desc, badge }) => <button type="button" className={`trusted-option-card${method === id ? " is-selected" : ""}`} key={id} onClick={() => setMethod(id)}><span className="trusted-option-radio">{method === id && <i />}</span><Network size={18} /><span><strong>{title}</strong><small>{desc}</small><Badge tone={badge === "ADAPTER" ? "warning" : "success"}>{badge}</Badge></span></button>)}</div>}
        {step === 2 && <div className="trusted-confirm-list"><div><span><Check size={14} />用途</span><strong>{useCases.find((item) => item.id === purpose)?.title}</strong></div><div><span><Check size={14} />处理方式</span><strong>{methods.find((item) => item.id === method)?.title}</strong></div><div><span><Check size={14} />结果范围</span><strong>结算摘要、质量指标，不导出原始明细</strong></div><div><span><Check size={14} />保留期限</span><strong>{durationPolicy ? `${effectiveDurationDays} 日` : "读取中"}</strong><small>{durationPolicy ? `范围 ${durationPolicy.min_days}–${durationPolicy.max_days} 日 · ${durationPolicy.source}` : "服务端策略读取中"}</small></div><label className="trusted-check-field"><input type="checkbox" checked={termsAccepted} onChange={(event) => setTermsAccepted(event.target.checked)} />我确认不会尝试推断或导出原始主体数据，且接受提供方人工审核。</label><div><FieldLabel htmlFor="usage-duration-days" hint={durationPolicy ? `${durationPolicy.min_days}–${durationPolicy.max_days} 日` : "服务端约束"}>申请有效期（天）</FieldLabel><Input id="usage-duration-days" type="number" min={durationPolicy?.min_days} max={durationPolicy?.max_days} step={1} value={durationDays ?? durationPolicy?.default_days ?? ""} onChange={(event) => setDurationDays(event.target.value ? Number(event.target.value) : null)} aria-invalid={durationDays !== null && !durationValid} /><small className="trusted-muted">{durationPolicy ? `默认 ${durationPolicy.default_days} 日 · ${durationPolicy.policy_version}` : "读取服务端期限策略后可填写"}</small></div></div>}
        {step === 3 && <div className="trusted-review-box"><div className="trusted-review-label"><ShieldCheck size={16} /><span>提交前核验</span><Badge tone={termsAccepted && durationValid ? "success" : "warning"} dot>{termsAccepted && durationValid ? "信息完整" : "仍需确认条件"}</Badge></div><p>本申请会创建真实的使用申请记录，后续由提供方决定是否授权。当前处理能力标记为 <code>{methods.find((item) => item.id === method)?.badge}</code>，不可作为生产跨域证明。</p><dl className="trusted-definition-list"><div><dt>申请主体</dt><dd>由当前登录会话与后端权限绑定</dd></div><div><dt>目标资产</dt><dd>{asset.asset_name} / {currentVersion ? `V${currentVersion.version_no}` : "未发布版本"}</dd></div><div><dt>目标资产 ID</dt><dd><code>{asset.asset_id}</code></dd></div><div><dt>申请有效期</dt><dd>{effectiveDurationDays} 日 · {durationPolicy?.source || "服务端策略"}</dd></div></dl></div>}
        {submitError && <div className="trusted-inline-status" role="alert">{submitError}</div>}
      </CardContent><div className="trusted-step-footer"><Button variant="secondary" disabled={step === 0} onClick={() => { setSubmitError(""); setStep((value) => Math.max(0, value - 1)); }}><ArrowLeft size={14} />上一步</Button><Button variant="primary" disabled={!payload.actions.can_request_usage || (step === 2 && (!termsAccepted || !durationValid)) || !durationPolicy} onClick={next}>{step === 3 ? "提交申请" : "下一步"}<ArrowRight size={14} /></Button></div></Card>}
    </>}
  </PageFrame>;
}
