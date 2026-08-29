import { useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, Database, Gavel, Network, RotateCcw, Save, UsersRound } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, post, prepareIdempotencyKey, type ApiResponseMetadata, type IdempotencyKeyRecord } from "../api";
import { Button, ErrorState, Field, IdText, LoadingState, Notice, PageHeader, SectionHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

type CreateData = { organizations: JsonRecord[]; rules: JsonRecord[]; catalog: JsonRecord };

const steps = [
  { code: "BASIC", label: "基本信息" },
  { code: "PARTIES", label: "参与主体" },
  { code: "DATA", label: "数据准备" },
  { code: "RULE", label: "规则与计算" },
  { code: "REVIEW", label: "提交复核" },
] as const;

const EMPTY_ENTRIES: JsonRecord[] = [];

export function SettlementCreatePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const isReadyTemplate = searchParams.get("template") === "ready";
  const [step, setStep] = useState(0);
  const readyTemplateSuffix = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
  const [taskName, setTaskName] = useState(() => isReadyTemplate ? `2026年7月月度结算流程（重新开始 ${readyTemplateSuffix}）` : "");
  const [description, setDescription] = useState(() => isReadyTemplate ? "使用已登记的数据引用跑通一笔完整的结算、确认与审计流程。" : "");
  const [batch, setBatch] = useState("");
  const [periodStart, setPeriodStart] = useState(() => isReadyTemplate ? "2026-07-01" : "");
  const [periodEnd, setPeriodEnd] = useState(() => isReadyTemplate ? "2026-07-31" : "");
  const [generatorId, setGeneratorId] = useState("");
  const [retailerId, setRetailerId] = useState("");
  const [ruleId, setRuleId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const createRequestRef = useRef<IdempotencyKeyRecord | null>(null);
  const { data, loading, error: loadError, reload } = useRemote(async (signal): Promise<CreateData> => {
    const options = { signal, cache: "no-store" as RequestCache };
    const [organizations, rules, catalog] = await Promise.all([
      api<JsonRecord[]>("/system/organizations", options),
      api<JsonRecord[]>("/rules", options),
      api<JsonRecord>("/data/catalog", options),
    ]);
    return { organizations, rules, catalog };
  }, []);

  const activeRules = data?.rules.filter((item) => item.status === "ACTIVE") || [];
  const generators = data?.organizations.filter((item) => item.org_type === "GENERATOR") || [];
  const retailers = data?.organizations.filter((item) => item.org_type === "RETAILER") || [];
  const rawEntries = data?.catalog.entries;
  const entries: JsonRecord[] = Array.isArray(rawEntries) ? rawEntries : EMPTY_ENTRIES;
  const selectedGeneratorId = generatorId || (isReadyTemplate ? generators[0]?.org_id || "" : "");
  const selectedRetailerId = retailerId || (isReadyTemplate ? retailers[0]?.org_id || "" : "");
  const selectedRuleId = ruleId || (isReadyTemplate ? activeRules[0]?.rule_id || "" : "");
  const selectedRule = activeRules.find((item) => item.rule_id === selectedRuleId);
  const generator = generators.find((item) => item.org_id === selectedGeneratorId);
  const retailer = retailers.find((item) => item.org_id === selectedRetailerId);
  const readyBatch = useMemo(() => {
    if (!isReadyTemplate) return "";
    const candidateBatches: string[] = Array.from(new Set(entries.map((item: JsonRecord) => String(item.trade_batch_no || "")).filter(Boolean)));
    return candidateBatches.find((candidate) => {
      const candidateEntries = entries.filter((item: JsonRecord) => item.trade_batch_no === candidate);
      return candidateEntries.some((item: JsonRecord) => item.asset_type === "GENERATION_DATA" && item.commitment_confirmed)
        && candidateEntries.some((item: JsonRecord) => item.asset_type === "RETAIL_DATA" && item.commitment_confirmed);
    }) || "";
  }, [entries, isReadyTemplate]);
  const effectiveBatch = batch || readyBatch;
  const generationData = entries.find((item: JsonRecord) => item.asset_type === "GENERATION_DATA" && item.owner_org_id === selectedGeneratorId && item.trade_batch_no === effectiveBatch);
  const retailData = entries.find((item: JsonRecord) => item.asset_type === "RETAIL_DATA" && item.owner_org_id === selectedRetailerId && item.trade_batch_no === effectiveBatch);
  const preflightBlockers: string[] = [];
  if (!generationData) preflightBlockers.push("发电企业尚未登记当前批次的已校验计量数据");
  else if (!generationData.commitment_confirmed) preflightBlockers.push("发电企业尚未确认数据承诺");
  if (!retailData) preflightBlockers.push("售电企业尚未登记当前批次的已校验履约数据");
  else if (!retailData.commitment_confirmed) preflightBlockers.push("售电企业尚未确认数据承诺");
  if (!selectedRule) preflightBlockers.push("尚未选择可用的结算规则版本");

  if (loading) return <LoadingState label="正在准备结算任务" variant="page" />;
  if (loadError || !data) return <ErrorState message={loadError || "创建页加载失败"} retry={reload} />;

  const basicReady = taskName.trim().length >= 2 && effectiveBatch.trim().length >= 3 && Boolean(periodStart && periodEnd) && periodStart <= periodEnd;
  const partiesReady = Boolean(selectedGeneratorId && selectedRetailerId && selectedGeneratorId !== selectedRetailerId);
  const ruleReady = Boolean(selectedRule);
  const canAdvance = [basicReady, partiesReady, true, ruleReady, true][step];
  const canSubmit = basicReady && partiesReady && ruleReady;

  async function submit() {
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    try {
      const payload = {
        task_name: taskName.trim(),
        trade_batch_no: effectiveBatch.trim(),
        period_start: periodStart,
        period_end: periodEnd,
        rule_id: selectedRuleId,
        participants: [
          { org_id: selectedGeneratorId, role_in_task: "GENERATOR" },
          { org_id: selectedRetailerId, role_in_task: "RETAILER" },
        ],
        scenario_code: "MARKET_SETTLEMENT",
        business_description: description.trim(),
        compute_mode: "LOCAL_CONTROLLED",
        algorithm_code: "CONTROLLED_SETTLEMENT_V1",
        output_mode: "AGGREGATE_ONLY",
      };
      const fingerprint = JSON.stringify(payload);
      createRequestRef.current = prepareIdempotencyKey(createRequestRef.current, "settlement-create", fingerprint);
      let responseMetadata: ApiResponseMetadata | undefined;
      const created = await post<JsonRecord>("/settlement/tasks", payload, {
        idempotencyKey: createRequestRef.current.key,
        onResponseMetadata: (metadata) => { responseMetadata = metadata; },
      });
      navigate(`/settlements/${created.task_id}`, {
        replace: true,
        state: {
          created: true,
          etag: responseMetadata?.etag,
          idempotencyReplayed: responseMetadata?.idempotencyReplayed,
        },
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "结算任务创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="发起结算任务" actions={<Link className="button button-secondary" to="/settlements"><ArrowLeft size={16} />返回任务中心</Link>} />

      {isReadyTemplate && <Notice tone="success"><RotateCcw size={15} />已带入一笔可运行的验收起点。系统只复用数据引用和规则，不复用历史结果；提交后仍需按角色完成确认和审计。</Notice>}

      <div className="wizard-layout">
        <nav className="wizard-steps" aria-label="创建步骤">
          {steps.map((item, index) => (
            <button key={item.code} type="button" className={`${index === step ? "active" : ""}${index < step ? " complete" : ""}`} onClick={() => index <= step && setStep(index)} disabled={index > step}>
              <span>{index < step ? <Check size={14} /> : index + 1}</span><strong>{item.label}</strong>
            </button>
          ))}
        </nav>

        <Surface className="wizard-panel">
          {step === 0 && <div className="wizard-section">
            <SectionHeader icon={Network} title="基本信息" description="明确交易批次与结算周期。" />
            <div className="form-grid two">
              <Field label="任务名称"><input value={taskName} onChange={(event) => setTaskName(event.target.value)} placeholder="例如：2026年8月月度电量结算" autoFocus /></Field>
              <Field label="交易批次"><input value={effectiveBatch} onChange={(event) => setBatch(event.target.value)} placeholder="例如：TB-2026-08-001" /></Field>
              <Field label="周期开始"><input type="date" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} /></Field>
              <Field label="周期结束" error={periodStart && periodEnd && periodStart > periodEnd ? "结束日期不能早于开始日期" : undefined}><input type="date" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} /></Field>
              <Field label="业务说明"><textarea value={description} onChange={(event) => setDescription(event.target.value)} maxLength={1000} rows={4} placeholder="可选：记录合同范围、特殊结算事项或业务联系人" /></Field>
            </div>
          </div>}

          {step === 1 && <div className="wizard-section">
            <SectionHeader icon={UsersRound} title="参与主体" description="每个任务包含一个发电主体和一个售电主体。" />
            <div className="form-grid two">
              <Field label="发电企业"><select value={selectedGeneratorId} onChange={(event) => setGeneratorId(event.target.value)} autoFocus><option value="">请选择</option>{generators.map((item) => <option key={item.org_id} value={item.org_id}>{item.org_name}</option>)}</select></Field>
              <Field label="售电企业"><select value={selectedRetailerId} onChange={(event) => setRetailerId(event.target.value)}><option value="">请选择</option>{retailers.map((item) => <option key={item.org_id} value={item.org_id}>{item.org_name}</option>)}</select></Field>
            </div>
            {selectedGeneratorId && selectedRetailerId && selectedGeneratorId === selectedRetailerId && <Notice tone="warning">发电主体与售电主体不能相同。</Notice>}
          </div>}

          {step === 2 && <div className="wizard-section">
            <SectionHeader icon={Database} title="数据准备" description="按参与主体和交易批次核对数据引用。" />
            <div className="readiness-list">
              <DataReadiness label="发电计量数据" organization={generator?.org_name} entry={generationData} />
              <DataReadiness label="售电履约数据" organization={retailer?.org_name} entry={retailData} />
            </div>
            {!effectiveBatch && <Notice tone="warning">请先填写交易批次，系统才能匹配数据。</Notice>}
          </div>}

          {step === 3 && <div className="wizard-section">
            <SectionHeader icon={Gavel} title="规则与计算" description="选择可用规则；执行边界将写入单笔回执。" />
            <div className="form-grid two">
              <Field label="结算规则版本"><select value={selectedRuleId} onChange={(event) => setRuleId(event.target.value)} autoFocus><option value="">请选择</option>{activeRules.map((item) => <option key={item.rule_id} value={item.rule_id}>{item.rule_version} · {item.rule_name}</option>)}</select></Field>
              <Field label="计算方式"><select value="LOCAL_CONTROLLED" disabled><option value="LOCAL_CONTROLLED">本地受控计算</option></select></Field>
              <Field label="输出范围"><select value="AGGREGATE_ONLY" disabled><option value="AGGREGATE_ONLY">聚合结算结果</option></select></Field>
            </div>
            <Notice>当前执行方式为应用进程内确定性计算；跨域隐私协议与远程可信执行证明未配置。</Notice>
          </div>}

          {step === 4 && <div className="wizard-section">
            <SectionHeader icon={Save} title="提交复核" description="创建后进入任务详情继续处理。" />
            <dl className="review-grid">
              <div><dt>任务名称</dt><dd>{taskName || "—"}</dd></div>
              <div><dt>交易批次</dt><dd><IdText value={effectiveBatch} /></dd></div>
              <div><dt>结算周期</dt><dd>{periodStart} 至 {periodEnd}</dd></div>
              <div><dt>发电企业</dt><dd>{generator?.org_name || "—"}</dd></div>
              <div><dt>售电企业</dt><dd>{retailer?.org_name || "—"}</dd></div>
              <div><dt>规则版本</dt><dd>{selectedRule ? `${selectedRule.rule_version} · ${selectedRule.rule_name}` : "—"}</dd></div>
            </dl>
            {preflightBlockers.length ? <div className="preflight-blockers"><strong>算前待办</strong><ul>{preflightBlockers.map((item) => <li key={item}>{item}</li>)}</ul><p>可以先创建待准备任务，补齐后再启动结算。</p></div> : <Notice tone="success">算前数据、主体和规则检查已通过。</Notice>}
          </div>}

          {error && <Notice tone="warning">{error}</Notice>}
          {!canAdvance && <div className="wizard-action-hint" role="status">{step === 0 ? "请填写任务名称、交易批次和完整结算周期。" : step === 1 ? "请选择一个发电企业和一个售电企业。" : step === 3 ? "请选择可用的结算规则版本。" : "当前步骤还有未完成条件。"}</div>}
          <div className="wizard-actions">
            <Button disabled={step === 0 || busy} onClick={() => setStep((value) => Math.max(0, value - 1))}><ArrowLeft size={16} />上一步</Button>
            {step < steps.length - 1
              ? <Button variant="primary" disabled={!canAdvance} onClick={() => setStep((value) => Math.min(steps.length - 1, value + 1))}>下一步<ArrowRight size={16} /></Button>
              : <Button icon={Save} variant="primary" busy={busy} disabled={!canSubmit} onClick={submit}>{preflightBlockers.length ? "创建待准备任务" : "创建结算任务"}</Button>}
          </div>
        </Surface>
      </div>
    </>
  );
}

function DataReadiness({ label, organization, entry }: { label: string; organization?: string; entry?: JsonRecord }) {
  const ready = entry?.quality?.validation_status === "PASSED" && entry?.commitment_confirmed;
  return (
    <div className="readiness-item">
      <div><strong>{label}</strong><span>{organization || "尚未选择主体"}</span></div>
      <div><span>{entry?.label || "未匹配当前批次数据"}</span>{entry?.upload_id && <IdText value={entry.upload_id} />}</div>
      <StatusTag value={ready ? "READY" : entry ? "UNCONFIRMED" : "NOT_CONFIGURED"} />
    </div>
  );
}
