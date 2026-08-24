import { useState } from "react";
import { ArrowRight, CheckCircle2, Database, Fingerprint, LockKeyhole, Play, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
import { api, post, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, DataTable, ErrorState, Field, IdText, LoadingState, Metric, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { TrustedExecutionReviewPanel } from "../components/TrustedExecutionReviewPanel";
import { useRemote } from "../hooks";
import { labelForCode } from "../types";
import type { JsonRecord } from "../types";

const DEFAULT_QUESTION = "分析上月由于电煤库存变化引起的火电出力与电网负荷平衡趋势";

const roleLabels: Record<string, string> = {
  ENERGY_BUREAU: "能源管理部门",
  REGULATOR: "监管分析员",
  PUBLIC: "公开查询方",
};

const purposeLabels: Record<string, string> = {
  CROSS_ENERGY_TREND: "跨能源趋势分析",
  ENERGY_ANALYSIS: "能源数据分析",
};

const granularityLabels: Record<string, string> = {
  MONTH: "月度汇总",
  DAY: "日级汇总",
  "15_MINUTE": "15 分钟级",
  DETAIL: "原始明细",
};

const scopeLabels: Record<string, string> = {
  REGION: "区域",
  ORGANIZATION: "组织",
  METER_POINT: "计量点",
};

const actionLabels: Record<string, string> = {
  AGGREGATE: "汇总提供",
  ALLOW: "直接提供",
  DELAY: "延迟提供",
  COMPUTE_ONLY: "仅参与计算",
  PROHIBIT: "禁止提供",
};

const methodLabels: Record<string, string> = {
  DIRECT_CONTROLLED_API: "受控数据接口",
  DELAYED_CONTROLLED_RELEASE: "延迟交付",
  LOCAL_CONTROLLED_AGGREGATION: "本地受控汇总",
  LOCAL_CONTROLLED_COMPUTE: "本地受控计算（测试适配器）",
  BLOCKED: "未执行",
  PSI_MPC: "隐私集合求交与多方安全计算（候选）",
  TEE_CONFIDENTIAL_COMPUTE: "可信执行环境机密计算（候选）",
};

const stepLabels: Record<string, string> = {
  INGEST: "接收请求",
  AUTHENTICATE: "核验身份",
  RESOLVE: "解析意图",
  ARBITRATE: "策略裁决",
  EXECUTE: "受控执行",
  AUDIT: "结果审查",
  DELIVER: "按范围交付",
  LOG: "写入证据台账",
};

const stepStatusLabels: Record<string, string> = {
  PASSED: "已通过",
  DENIED: "已拦截",
  BLOCKED: "未执行",
  QUEUED: "排队记录",
  SKIPPED: "已跳过",
  FAILED: "执行失败",
};

const fieldOptions = [
  { value: "raw_records", label: "原始记录" },
  { value: "customer_id", label: "客户标识" },
  { value: "meter_point", label: "计量点标识" },
  { value: "exact_coordinates", label: "精确坐标" },
];

type ExecutionConsoleData = { status: JsonRecord; policy: JsonRecord };

function actionLabel(value: unknown) {
  return actionLabels[String(value || "")] || labelForCode(value, "未知策略");
}

function methodLabel(value: unknown) {
  return methodLabels[String(value || "")] || labelForCode(value, "未指定");
}

function textLabel(map: Record<string, string>, value: unknown) {
  return map[String(value || "")] || labelForCode(value, "—");
}

function stepDetail(details: unknown) {
  if (!details || typeof details !== "object") return "";
  const payload = details as JsonRecord;
  if (payload.reason) return String(payload.reason);
  if (Array.isArray(payload.denied_targets)) return `拦截目标：${payload.denied_targets.join("、")}`;
  if (Array.isArray(payload.provider_nodes)) return `节点：${payload.provider_nodes.join("、")}`;
  if (payload.raw_data_returned === false || payload.raw_data_accessed_by_consumer === false) return "原始记录未返回给调用方";
  if (payload.destination) return `记录去向：${String(payload.destination)}`;
  return "";
}

function requestedFieldLabel(value: string) {
  return fieldOptions.find((item) => item.value === value)?.label || value;
}

export function TrustedExecutionPage() {
  const { session } = useAuth();
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [consumerRole, setConsumerRole] = useState("ENERGY_BUREAU");
  const [purpose, setPurpose] = useState("CROSS_ENERGY_TREND");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [granularity, setGranularity] = useState("MONTH");
  const [spatialScope, setSpatialScope] = useState("REGION");
  const [outputMode, setOutputMode] = useState("SUMMARY");
  const [requestedFields, setRequestedFields] = useState<string[]>([]);
  const [translation, setTranslation] = useState<JsonRecord | null>(null);
  const [result, setResult] = useState<JsonRecord | null>(null);
  const [translating, setTranslating] = useState(false);
  const [running, setRunning] = useState(false);
  const [actionError, setActionError] = useState("");

  function resetExecutionState() {
    setTranslation(null);
    setResult(null);
    setActionError("");
  }

  function updateFormValue(setter: (value: string) => void, value: string) {
    setter(value);
    resetExecutionState();
  }

  const remote = useRemote<ExecutionConsoleData>(async (signal) => {
    const request = { signal, timeoutMs: 12000, cache: "no-store" as RequestCache };
    const [status, policy] = await Promise.all([
      api<JsonRecord>("/trusted-execution/status", request),
      api<JsonRecord>("/trusted-execution/policy/catalog", request),
    ]);
    return { status, policy };
  }, []);

  async function translateQuestion(offlineTest = false) {
    if (!question.trim()) return;
    setTranslating(true);
    setActionError("");
    try {
      const next = await post<JsonRecord>("/trusted-execution/translate", {
        question: question.trim(),
        period_start: periodStart || undefined,
        period_end: periodEnd || undefined,
        requested_granularity: granularity,
        spatial_scope: spatialScope,
        group_by: spatialScope === "REGION" ? ["region", "period"] : ["organization", "period"],
        output_mode: outputMode,
        offline_test: offlineTest,
      });
      setTranslation(next);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "DeepSeek 翻译未完成，查询未执行");
    } finally {
      setTranslating(false);
    }
  }

  async function runQuery() {
    if (!question.trim() || !translation?.translation) return;
    setRunning(true);
    setActionError("");
    try {
      const next = await post<JsonRecord>("/trusted-execution/query", {
        question: question.trim(),
        consumer_role: consumerRole,
        purpose,
        period_start: periodStart || undefined,
        period_end: periodEnd || undefined,
        requested_granularity: granularity,
        spatial_scope: spatialScope,
        group_by: spatialScope === "REGION" ? ["region", "period"] : ["organization", "period"],
        requested_fields: requestedFields,
        output_mode: outputMode,
        translation: translation.translation,
        translation_hash: translation.translation_hash,
      });
      setResult(next);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "受控查询未完成，请稍后重试");
    } finally {
      setRunning(false);
    }
  }

  function toggleField(value: string) {
    setRequestedFields((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
    resetExecutionState();
  }

  function setExample(value: string) {
    updateFormValue(setQuestion, value);
  }

  if (remote.loading) return <LoadingState label="正在加载策略与能力边界" variant="page" />;
  if (remote.error || !remote.data) return <ErrorState message={remote.error || "受控执行能力加载失败"} retry={remote.reload} />;

  const status = remote.data.status;
  const policy = remote.data.policy;
  const credentialUnavailable = status.did_verified !== true;
  const unavailable = status.availability === "NOT_CONFIGURED" || credentialUnavailable;
  const policyVersion = String(policy.version || status.policy_engine?.version || "—");
  const resultStatus = String(result?.execution_status || "");
  const resultBody = (result?.result || {}) as JsonRecord;
  const routing = (resultBody.execution_routing || {}) as JsonRecord;
  const policyHits = Array.isArray(result?.policy_hits) ? result.policy_hits as JsonRecord[] : [];
  const steps = Array.isArray(result?.workflow_steps) ? result.workflow_steps as JsonRecord[] : [];
  const series = Array.isArray(resultBody.series) ? resultBody.series as JsonRecord[] : [];
  const canReview = ["EXCHANGE", "REGULATOR", "ADMIN"].includes(session?.user.role_code || "");
  const translatedInstruction = (translation?.translation || {}) as JsonRecord;

  return (
    <>
      <PageHeader
        title="受控数据使用"
        description="把自然语言需求转为可审计的使用策略；智能助手只解析意图，最终裁决由确定性策略引擎完成。"
        actions={<Button icon={RefreshCw} busy={remote.refreshing} onClick={remote.reload}>刷新能力</Button>}
      />

      <section className="trusted-execution-thesis" aria-label="系统主线">
        <div><strong>不是给不给数据</strong><span>而是决定数据怎么被使用</span></div>
        <div className="trusted-execution-thesis-flow"><span>身份</span><ArrowRight size={14} /><span>意图</span><ArrowRight size={14} /><span>策略</span><ArrowRight size={14} /><span>执行</span><ArrowRight size={14} /><span>证据</span></div>
        <div className="trusted-execution-thesis-meta"><span>当前策略 {policyVersion}</span><StatusTag value={status.availability} label={credentialUnavailable ? "身份不可用" : unavailable ? "未配置可执行节点" : "测试节点可用"} /></div>
      </section>

      {unavailable && <Notice tone="warning">{credentialUnavailable ? `当前主体凭证状态为 ${labelForCode(status.credential_status, "未提供" )}，查询入口保持关闭。` : "当前环境未配置受控能源节点，查询入口保持关闭。"}生产环境不会使用内置测试数据代替真实连接器。</Notice>}
      {actionError && <Notice tone="warning">{actionError}</Notice>}

      <div className="trusted-execution-layout">
        <Surface title="发起受控查询" meta="请求本身不携带原始数据">
          <div className="trusted-execution-form">
            <Field label="自然语言需求" hint="例如：分析上月电煤库存变化引起的火电出力与电网负荷平衡趋势">
              <textarea rows={5} value={question} onChange={(event) => updateFormValue(setQuestion, event.target.value)} placeholder="描述你需要使用什么数据、用于什么分析" />
            </Field>
            <div className="suggested-questions" aria-label="示例请求">
              <button type="button" onClick={() => setExample(DEFAULT_QUESTION)}>跨能源趋势</button>
              <button type="button" onClick={() => setExample("查询调度实时出力变化趋势")}>测试延迟策略</button>
              <button type="button" onClick={() => setExample("查询某企业15分钟级原始负荷明细")}>测试高风险请求</button>
            </div>
            <div className="form-grid two">
              <Field label="使用主体"><select value={consumerRole} onChange={(event) => updateFormValue(setConsumerRole, event.target.value)}><option value="ENERGY_BUREAU">能源管理部门</option><option value="REGULATOR">监管分析员</option><option value="PUBLIC">公开查询方</option></select></Field>
              <Field label="使用目的"><select value={purpose} onChange={(event) => updateFormValue(setPurpose, event.target.value)}><option value="CROSS_ENERGY_TREND">跨能源趋势分析</option><option value="ENERGY_ANALYSIS">能源数据分析</option></select></Field>
              <Field label="时间起点" hint="留空则采用上月"><input type="date" value={periodStart} onChange={(event) => updateFormValue(setPeriodStart, event.target.value)} /></Field>
              <Field label="时间终点"><input type="date" value={periodEnd} onChange={(event) => updateFormValue(setPeriodEnd, event.target.value)} /></Field>
              <Field label="请求粒度"><select value={granularity} onChange={(event) => updateFormValue(setGranularity, event.target.value)}>{Object.entries(granularityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
              <Field label="空间范围"><select value={spatialScope} onChange={(event) => updateFormValue(setSpatialScope, event.target.value)}>{Object.entries(scopeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
              <Field label="结果形式"><select value={outputMode} onChange={(event) => updateFormValue(setOutputMode, event.target.value)}><option value="SUMMARY">汇总结果</option><option value="CHART">趋势图表</option><option value="COMPUTE_ONLY">仅返回计算结论</option></select></Field>
            </div>
            <fieldset className="trusted-execution-fields">
              <legend>请求字段</legend>
              <div>{fieldOptions.map((item) => <label key={item.value}><input type="checkbox" checked={requestedFields.includes(item.value)} onChange={() => toggleField(item.value)} />{item.label}</label>)}</div>
              <small>原始字段仅用于验证策略拦截，不会因勾选而获得导出权限。</small>
            </fieldset>
            {translation?.translation && <Surface title="翻译预览" meta={translation.offline_test ? "本地离线测试，不代表 DeepSeek 已接入" : "本地校验通过，尚未执行"}>
              <div className="detail-grid trusted-execution-translation-preview">
                <div><span>固定函数</span><strong>{String(translation.function_label || translatedInstruction.function || "—")}</strong></div>
                <div><span>数据目标</span><strong>{(Array.isArray(translatedInstruction.target_data_types) ? translatedInstruction.target_data_types : []).map((item: unknown) => labelForCode(item, "已登记数据目标")).join("、")}</strong></div>
                <div><span>时间范围</span><strong>{String(translatedInstruction.period_start)} 至 {String(translatedInstruction.period_end)}</strong></div>
                <div><span>粒度与分组</span><strong>{textLabel(granularityLabels, translatedInstruction.requested_granularity)} · {(Array.isArray(translatedInstruction.group_by) ? translatedInstruction.group_by : []).join("、")}</strong></div>
              </div>
              <div className="trusted-execution-submit"><Button icon={CheckCircle2} variant="primary" busy={running} disabled={unavailable || running} onClick={runQuery}>确认并执行固定函数</Button><span>确认后才会触发本地策略、受控计算和审计。</span></div>
            </Surface>}
            <div className="trusted-execution-submit"><Button icon={Play} variant="primary" busy={translating} disabled={unavailable || question.trim().length < 2 || translating || running} onClick={() => translateQuestion(false)}>{translation ? "重新翻译" : "翻译需求"}</Button><span>DeepSeek 只翻译，不访问数据；翻译失败不会执行查询。</span></div>
            {status.availability === "TEST_FIXTURE_ONLY" && <div className="trusted-execution-submit"><Button icon={RefreshCw} variant="secondary" busy={translating} disabled={question.trim().length < 2 || translating || running} onClick={() => translateQuestion(true)}>离线测试翻译</Button><span>仅匹配页面预置示例，不代表 DeepSeek 已接入，也不发送网络请求。</span></div>}
          </div>
        </Surface>

        <Surface title="能力边界" meta="事实状态，不是宣传指标">
          <div className="trusted-execution-boundary-list">
            <BoundaryRow icon={Fingerprint} label="去中心化身份与可验证凭证" value={status.did_verified ? "由请求主体凭证核验" : status.credential_status === "MISSING" ? "未提供主体凭证" : "凭证未通过核验"} state={status.did_verified ? "PASSED" : status.credential_status || "NOT_PROVIDED"} />
            <BoundaryRow icon={LockKeyhole} label="原始数据接口返回" value={status.security_boundary?.api_raw_records_returned === false ? "否" : "未提供"} state={status.security_boundary?.api_raw_records_returned === false ? "PASSED" : "NOT_PROVIDED"} />
            <BoundaryRow icon={Database} label="跨域不出域证明" value={status.security_boundary?.cross_domain_non_export_verified ? "已验证" : "未提供"} state={status.security_boundary?.cross_domain_non_export_verified ? "PASSED" : "NOT_PROVIDED"} />
            <BoundaryRow icon={ShieldCheck} label="结果反推检查" value={status.security_boundary?.anti_inference_check || "未提供"} state="PENDING" />
            <BoundaryRow icon={Database} label="证据后端" value={status.audit?.evidence_backend || "—"} state="RECORDED" />
          </div>
          <div className="trusted-execution-boundary-note"><strong>系统当前能证明什么？</strong><p>能证明请求经过身份、策略、计算、结果审查和本地摘要台账；不能把本地应用进程内的确定性计算表述为真实多方安全计算、可信执行环境、区块链共识或跨主体不出域证明。</p></div>
        </Surface>
      </div>

      {result && <TrustedExecutionResult result={result} resultStatus={resultStatus} resultBody={resultBody} routing={routing} policyHits={policyHits} steps={steps} series={series} />}
      {canReview && <TrustedExecutionReviewPanel refreshKey={result?.request_id ? String(result.request_id) : null} />}
    </>
  );
}

function BoundaryRow({ icon: Icon, label, value, state }: { icon: typeof Fingerprint; label: string; value: string; state: string }) {
  return <div className="trusted-execution-boundary-row"><span className="trusted-execution-boundary-icon"><Icon size={16} /></span><div><strong>{label}</strong><small>{value}</small></div><StatusTag value={state} label={state === "PASSED" ? "已核验" : state === "RECORDED" ? "已记录" : state === "VALID" ? "有效" : "未提供"} /></div>;
}

function TrustedExecutionResult({ result, resultStatus, resultBody, routing, policyHits, steps, series }: { result: JsonRecord; resultStatus: string; resultBody: JsonRecord; routing: JsonRecord; policyHits: JsonRecord[]; steps: JsonRecord[]; series: JsonRecord[] }) {
  const succeeded = resultStatus === "SUCCEEDED";
  const intent = (result.intent || {}) as JsonRecord;
  const identity = (result.caller_identity || {}) as JsonRecord;
  const candidateMethods = Array.isArray(routing.candidate_methods) ? routing.candidate_methods : [];
  const resultReason = resultBody.reason ? String(resultBody.reason) : "";
  return (
    <div className="trusted-execution-result">
      <div className="metrics-grid four">
        <Metric label="执行状态" value={<StatusTag value={resultStatus} />} meta={result.request_id ? `请求 ${shortHash(String(result.request_id), 12)}` : undefined} tone={succeeded ? "green" : "amber"} />
        <Metric label="解析数据目标" value={Array.isArray(intent.target_data_types) ? intent.target_data_types.length : 0} meta={Array.isArray(intent.target_data_types) ? intent.target_data_types.join("、") : "—"} />
        <Metric label="策略命中" value={policyHits.length} meta={policyHits.map((item) => actionLabel(item.action)).join("、") || "—"} />
        <Metric label="人工复核" value={<StatusTag value={result.accuracy_review?.verification_status || "PENDING"} />} meta="自动核验不替代人工确认" />
      </div>

      <div className="trusted-execution-result-layout">
        <Surface title="身份与意图" meta="智能助手解析结果">
          <div className="detail-grid">
            <div><span>调用主体</span><strong>{textLabel(roleLabels, intent.consumer_role)}</strong></div>
            <div><span>使用目的</span><strong>{textLabel(purposeLabels, intent.purpose)}</strong></div>
            <div><span>请求粒度</span><strong>{textLabel(granularityLabels, intent.requested_granularity)}</strong></div>
            <div><span>空间范围</span><strong>{textLabel(scopeLabels, intent.spatial_scope)}</strong></div>
            <div><span>解析目标</span><strong>{(intent.target_data_types || []).map((item: string) => labelForCode(item, "已登记数据目标")).join("、") || "—"}</strong></div>
            <div><span>调用去中心化身份标识</span><IdText value={identity.did} length={18} /></div>
          </div>
          {Array.isArray(intent.requested_fields) && intent.requested_fields.length > 0 && <div className="trusted-execution-requested-fields"><span>请求字段</span>{intent.requested_fields.map((item: string) => <StatusTag key={item} value="DENY" label={requestedFieldLabel(item)} />)}</div>}
        </Surface>

        <Surface title="策略裁决" meta="策略引擎拥有最终权限">
          <div className="trusted-execution-policy-grid">
            {policyHits.map((hit, index) => {
              const permitted = hit.decision === "PERMIT";
              const candidate = Array.isArray(hit.candidate_methods) ? hit.candidate_methods : [];
              return <article className={`trusted-execution-policy-item${permitted ? " permitted" : " denied"}`} key={`${hit.target_data_type}-${index}`}><header><strong>{labelForCode(hit.target_data_type, "数据目标")}</strong><StatusTag value={permitted ? "PERMIT" : "DENY"} label={permitted ? "允许" : "拒绝"} /></header><div className="trusted-execution-policy-action"><span>{actionLabel(hit.action)}</span><small>{String(hit.reason || "—")}</small></div><div className="trusted-execution-policy-method"><span>执行方式</span><strong>{methodLabel(hit.execution_method)}</strong></div>{candidate.length > 0 && <small className="trusted-execution-candidate">候选协议：{candidate.map((item: string) => methodLabel(item)).join("、")}</small>}<small>规则 {shortHash(String(hit.rule_id || "—"), 10)} · {labelForCode(hit.release_mode, "—")}</small></article>;
            })}
          </div>
        </Surface>
      </div>

      <Surface title="八步可信执行链" meta={`${steps.length} 个过程节点`}>
        <div className="trusted-execution-step-list">
          {steps.map((step, index) => {
            const status = String(step.status || "UNKNOWN");
            return <div className={`trusted-execution-step trusted-execution-step-${status.toLowerCase()}`} key={`${step.code}-${index}`}><span className="trusted-execution-step-index">{String(step.step || index + 1).padStart(2, "0")}</span><div><strong>{stepLabels[String(step.code)] || labelForCode(step.code, "执行步骤")}</strong><small>{stepStatusLabels[status] || labelForCode(status, "未登记状态")}{stepDetail(step.details) ? ` · ${stepDetail(step.details)}` : ""}</small></div><StatusIcon status={status} /></div>;
          })}
        </div>
      </Surface>

      <div className="trusted-execution-result-layout">
        <Surface title="执行路由" meta="策略决定使用方式">
          <div className="detail-grid">
            <div><span>实际运行环境</span><strong>{labelForCode(routing.actual_runtime || resultBody.privacy_controls?.compute_environment, "—")}</strong></div>
            <div><span>本次实际方式</span><strong>{methodLabel(routing.actual_method)}</strong></div>
            <div><span>实现状态</span><StatusTag value={String(routing.implementation_status || "NOT_PROVIDED")} /></div>
            <div><span>外部运行时</span><strong>{routing.external_runtime_required ? "仍需接入" : "本次不需要"}</strong></div>
          </div>
          {candidateMethods.length > 0 && <Notice tone="warning">本请求的细粒度策略需要隐私集合求交、多方安全计算或可信执行环境等外部运行时才能形成跨主体不出域证明；当前仅记录本地测试适配器结果。候选：{candidateMethods.map((item: string) => methodLabel(item)).join("、")}。</Notice>}
          {!succeeded && resultReason && <Notice tone="warning">未交付原因：{resultReason}</Notice>}
          <div className="section-links"><span>结果摘要</span><IdText value={result.result_hash} length={18} /><span>请求编号</span><IdText value={result.request_id} length={16} /></div>
        </Surface>

        <Surface title="结果审查" meta={resultBody.raw_data_returned === false ? "聚合结果，原始记录未返回" : "待确认"}>
          {series.length > 0 ? <DataTable<JsonRecord> keyField="row_key" rows={series.slice(0, 12).map((item, index) => ({ ...item, row_key: `${item.period || "period"}-${item.region || "region"}-${index}` }))} label="受控查询结果" columns={[
            { key: "period", label: "周期" },
            { key: "region", label: "区域" },
            { key: "thermal_output_mwh", label: "火电出力", align: "right" },
            { key: "grid_load_mwh", label: "电网负荷", align: "right" },
            { key: "function_result", label: "固定函数结果", align: "right" },
            { key: "balance_status", label: "平衡状态", render: (row) => <StatusTag value={row.balance_status} label={row.balance_status === "SURPLUS" ? "有余量" : row.balance_status === "GAP" ? "存在缺口" : row.balance_status || "—"} /> },
          ]} /> : <div className="trusted-execution-empty-result"><XCircle size={20} /><span>当前请求没有可交付结果。请查看上方策略裁决和执行链。</span></div>}
        </Surface>
      </div>
    </div>
  );
}

function StatusIcon({ status }: { status: string }) {
  if (["PASSED", "QUEUED"].includes(status)) return <CheckCircle2 size={17} />;
  if (["DENIED", "BLOCKED", "FAILED"].includes(status)) return <XCircle size={17} />;
  return <ShieldCheck size={17} />;
}
