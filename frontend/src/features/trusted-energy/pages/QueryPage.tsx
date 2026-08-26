import { useState } from "react";
import { Link } from "react-router-dom";
import { QueryResultChart } from "../components/QueryResultChart";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import {
  confirmTrustedQuery,
  executeTrustedQuery,
  loadCatalog,
  loadUsageRequests,
  parseTrustedQuery,
  type CatalogAsset,
  type ControlledQueryResult,
  type QueryConfirmation,
  type QueryIntent,
  type UsageRequest,
} from "../trusted-space-api";
import { routeForView } from "../types";
import { useTrustedSpaceContext } from "../trusted-space-context";

const EXAMPLES = [
  "查一下6月份各地区的电网负荷，用于运行监测",
  "6月电力交易的成交均价和成交量，用于市场监测",
  "各行业每天的用电量统计，用于负荷预测",
  "6月电力交易成交明细，卖家都是谁",
  "7月风电和光伏的出力情况，做趋势分析",
  "寒潮期间电力负荷和风光出力叠加分析，供应有没有缺口？",
];

type QueryStepStatus = "待处理" | "进行中" | "已完成" | "待选择主体" | "待授权" | "已阻断" | "失败";
type QueryStep = { stage: string; status: QueryStepStatus; detail?: string };

const INITIAL_STEPS: QueryStep[] = [
  { stage: "解析需求", status: "待处理" },
  { stage: "授权确认", status: "待处理" },
  { stage: "连接器计算", status: "待处理" },
  { stage: "返回多点数据", status: "待处理" },
];

function updateStep(steps: QueryStep[], index: number, status: QueryStepStatus, detail?: string) {
  return steps.map((step, stepIndex) => stepIndex === index ? { ...step, status, detail } : step);
}

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof Error ? reason.message : fallback;
}

function providerName(asset: CatalogAsset) {
  return asset.provider.org_name || asset.provider.org_id;
}

function resultObject(result: ControlledQueryResult["result"]): Record<string, number | string> | null {
  return result && typeof result === "object" && !Array.isArray(result) ? result : null;
}

function resultSummary(result: ControlledQueryResult) {
  if (typeof result.result === "number") return `${result.result} ${result.unit}`;
  if (typeof result.result === "string") return result.result;
  const raw = resultObject(result.result);
  if (!raw) return "已返回受控摘要";
  const direction = typeof raw["方向"] === "string" ? raw["方向"] : "";
  const changeRate = typeof raw["变化率"] === "number" ? `${raw["变化率"]}%` : "";
  return [direction, changeRate].filter(Boolean).join(" · ") || "已返回受控摘要";
}

function QueryOutput({
  intent,
  steps,
  providers,
  selectedProviderId,
  onProviderChange,
  onExecute,
  executeBusy,
  execution,
  error,
  identity,
}: {
  intent: QueryIntent;
  steps: QueryStep[];
  providers: CatalogAsset[];
  selectedProviderId: string;
  onProviderChange: (assetId: string) => void;
  onExecute: () => void;
  executeBusy: boolean;
  execution: ControlledQueryResult | null;
  error: string;
  identity: { name: string; did: string };
}) {
  const selectedProvider = providers.find((item) => item.asset_id === selectedProviderId);
  const trend = (execution?.trend || []).filter((point) => point && point.date && Number.isFinite(point.value));
  const aiLabel = intent.provider === "deepseek" ? `DeepSeek${intent.model ? ` · ${intent.model}` : ""}` : "手动规则预览";
  const canExecute = Boolean(intent.ready && selectedProvider && !executeBusy);
  const applyPath = selectedProvider ? routeForView("apply", selectedProvider.asset_id) : routeForView("catalog");

  return <section className="prototype-card prototype-query-output">
    <PrototypeCardTitle>问数结果 <span className="prototype-inline-state">身份 {identity.did || "未登记"} · {aiLabel} · 原始数据未返回</span></PrototypeCardTitle>
    <div className="prototype-pipeline">{steps.map((item, index) => {
      const blocked = item.status === "已阻断" || item.status === "失败";
      const running = item.status === "进行中";
      const done = item.status === "已完成";
      return <div className={`prototype-pipeline-step ${done ? "is-done" : blocked ? "is-blocked" : running ? "is-running" : "is-pending"}`} key={`${item.stage}-${index}`}><strong>{index + 1}. {item.stage}</strong><small>{item.status}</small>{item.detail && <em>{item.detail}</em>}</div>;
    })}</div>

    <div className="prototype-query-preview">
      <div><span>能源范围</span><strong>{intent.energy_domain_name || "未识别"}</strong></div>
      <div><span>数据资源</span><strong>{intent.resource || "未识别"}</strong></div>
      <div><span>固定函数</span><strong>{intent.function_name || "未识别"}</strong></div>
      <div><span>查询期间</span><strong>{intent.start_date && intent.end_date ? `${intent.start_date} 至 ${intent.end_date}` : "未补齐"}</strong></div>
    </div>

    {providers.length > 0 && <div className="prototype-query-provider">
      <label htmlFor="query-provider"><span>数据主体</span><select id="query-provider" value={selectedProviderId} onChange={(event) => onProviderChange(event.target.value)}>{providers.map((asset) => <option value={asset.asset_id} key={asset.asset_id}>{providerName(asset)} · {asset.asset_name}</option>)}</select></label>
      <small>授权只绑定到选定主体，计算在该主体连接器内完成。</small>
    </div>}

    {intent.ready && providers.length > 0 && <div className="prototype-query-execute">
      <button type="button" className="prototype-primary-button" disabled={!canExecute} onClick={onExecute}>{executeBusy ? "正在确认并计算…" : "确认授权并执行连接器计算"}</button>
      <span>确认后才会向主体连接器发送签名计算请求。</span>
    </div>}

    {error && <div className="prototype-deny-message">⛔ {error}{selectedProvider && <Link to={applyPath}>前往申请授权</Link>}</div>}

    {execution ? <>
      <div className="prototype-query-result">
        <div><span>受控结果</span><strong>{resultSummary(execution)}</strong></div>
        <div><span>连接器记录数</span><strong>{execution.record_count ?? "—"}</strong></div>
        <div><span>结果单位</span><strong>{execution.unit || "—"}</strong></div>
      </div>
      {trend.length > 1 ? <QueryResultChart result={{ ...execution, trend }} /> : <div className="prototype-query-proof"><span>结果依据</span><strong>连接器已返回签名受控汇总，但没有足够的多日期数据绘制趋势图。</strong></div>}
      <div className="prototype-query-proof"><span>可信留痕</span><strong>任务 {execution.task_id} · 连接器签名{execution.digital_signature} · 原始记录未返回</strong>{execution.job_id && <Link to={routeForView("mpc", execution.job_id)}>查看隐私计算任务</Link>}</div>
    </> : !error && <div className="prototype-empty">解析完成后，请选择数据主体并确认授权，系统才会执行连接器计算。</div>}
    <div className="prototype-audit-id">{execution ? `受控任务 ${execution.task_id}` : `AI解析 ${aiLabel}`} · {identity.name || "当前主体"}</div>
  </section>;
}

export function QueryPage() {
  const { context } = useTrustedSpaceContext();
  const [question, setQuestion] = useState("");
  const [intent, setIntent] = useState<QueryIntent | null>(null);
  const [providers, setProviders] = useState<CatalogAsset[]>([]);
  const [approvedAuthorizations, setApprovedAuthorizations] = useState<UsageRequest[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [steps, setSteps] = useState<QueryStep[]>(INITIAL_STEPS);
  const [execution, setExecution] = useState<ControlledQueryResult | null>(null);
  const [busy, setBusy] = useState<"parsing" | "executing" | "">("");
  const [error, setError] = useState("");

  function setStep(index: number, status: QueryStepStatus, detail?: string) {
    setSteps((current) => updateStep(current, index, status, detail));
  }

  async function ask() {
    const text = question.trim();
    if (!text || busy) return;
    setBusy("parsing");
    setError("");
    setIntent(null);
    setProviders([]);
    setApprovedAuthorizations([]);
    setSelectedProviderId("");
    setExecution(null);
    setSteps(updateStep(INITIAL_STEPS, 0, "进行中"));
    try {
      const parsed = await parseTrustedQuery(text);
      setIntent(parsed);
      setStep(0, "已完成", parsed.provider === "deepseek" ? "DeepSeek 已完成固定字段解析" : "AI 不可用，当前仅为规则预览");
      if (!parsed.ready || !parsed.energy_domain || !parsed.resource || !parsed.function || !parsed.start_date || !parsed.end_date) {
        setStep(1, "已阻断", "查询条件未补齐");
        setError(parsed.notice || "请补充能源范围、数据资源、固定函数和时间范围");
        return;
      }

      setStep(1, "进行中", "正在查找可授权的数据主体");
      const catalog = await loadCatalog({ domain: parsed.energy_domain, page: 1, pageSize: 100 });
      const matches = catalog.items.filter((item) => item.status === "ACTIVE" && item.metadata?.resource_id === parsed.resource && item.source.status === "ACTIVE");
      if (!matches.length) {
        setStep(1, "已阻断", "目录中没有可用主体资源");
        setError("数据目录中没有可用于该查询的主体连接器资源，系统没有生成占位结果");
        return;
      }
      setProviders(matches);
      setSelectedProviderId(matches[0].asset_id);
      try {
        const approved = await loadUsageRequests({ mine: true, status: "APPROVED", page: 1, pageSize: 100 });
        setApprovedAuthorizations(approved.items);
      } catch {
        // The confirmation endpoint remains the source of truth for subject rules.
      }
      setStep(1, "待授权", matches.length > 1 ? "请选择主体后确认授权" : "请确认主体授权");
    } catch (reason) {
      setStep(0, "失败");
      setError(errorMessage(reason, "AI 查询解析失败，查询未执行"));
    } finally {
      setBusy("");
    }
  }

  async function confirmAndExecute() {
    const selectedProvider = providers.find((item) => item.asset_id === selectedProviderId);
    if (!intent || !selectedProvider || !intent.energy_domain || !intent.resource || !intent.function || !intent.start_date || !intent.end_date || busy) return;
    const approved = approvedAuthorizations.find((item) => item.asset.asset_id === selectedProvider.asset_id && item.provider.org_id === selectedProvider.provider.org_id && item.status === "APPROVED");
    const baseRequest = {
      authorization_id: approved?.request_id,
      provider_org_id: selectedProvider.provider.org_id,
      energy_domain: intent.energy_domain,
      resource: intent.resource,
      function: intent.function,
      start_date: intent.start_date,
      end_date: intent.end_date,
      region: intent.region || undefined,
      decimals: 2,
    };
    setBusy("executing");
    setError("");
    setExecution(null);
    setStep(1, "进行中", approved ? "正在核对已有授权" : "正在核对主体批准规则");
    let failedStep = 1;
    try {
      const confirmation: QueryConfirmation = await confirmTrustedQuery(baseRequest);
      setStep(1, "已完成", "授权范围与查询条件已锁定");
      setStep(2, "进行中", "主体连接器正在计算");
      failedStep = 2;
      const next = await executeTrustedQuery({ ...baseRequest, confirmation_token: confirmation.confirmation_token });
      if (next.raw_records_returned) throw new Error("连接器返回了原始记录，平台已拒绝交付");
      setExecution(next);
      setStep(2, "已完成", `任务 ${next.task_id} · 签名${next.digital_signature}`);
      setStep(3, "已完成", next.trend && next.trend.length > 1 ? `已返回 ${next.trend.length} 个日度数据点` : "已返回受控汇总");
    } catch (reason) {
      setStep(failedStep, "失败");
      setSteps((current) => current.map((step, index) => index > failedStep ? { ...step, status: "已阻断" } : step));
      setError(errorMessage(reason, failedStep === 1 ? "授权确认未完成，查询未执行" : "连接器计算未完成，未交付结果"));
    } finally {
      setBusy("");
    }
  }

  const identity = {
    name: context?.current_subject.org_name || "当前主体",
    did: context?.identity_ref.did || "未登记",
  };

  return <PrototypePageFrame className="prototype-query-page">
    <div className="prototype-query-layout">
      <main className="prototype-query-main">
        <section className="prototype-card prototype-query-entry">
          <PrototypeCardTitle>对话式问数</PrototypeCardTitle>
          <div className="prototype-chat-input"><input value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void ask(); }} placeholder="用自然语言描述你的数据需求，例如：查一下6月份各地区的电网负荷，用于运行监测" /><button type="button" disabled={busy !== "" || !question.trim()} onClick={() => void ask()}>{busy === "parsing" ? "AI解析中…" : "发送"}</button></div>
          <div className="prototype-query-examples" aria-label="快捷提问">{EXAMPLES.map((item) => <button type="button" key={item} onClick={() => setQuestion(item)}>{item}</button>)}</div>
        </section>
        {intent && <QueryOutput intent={intent} steps={steps} providers={providers} selectedProviderId={selectedProviderId} onProviderChange={setSelectedProviderId} onExecute={() => void confirmAndExecute()} executeBusy={busy === "executing"} execution={execution} error={error} identity={identity} />}
        {error && !intent && <div className="prototype-error" role="alert">{error}</div>}
      </main>
      <aside className="prototype-query-side">
        <section className="prototype-card">
          <PrototypeCardTitle>问数说明</PrototypeCardTitle>
          <div className="prototype-query-info">
            <p><b>1.</b> DeepSeek 只解析自然语言，不访问原始数据</p>
            <p><b>2.</b> 确定性策略引擎校验主体授权与查询范围</p>
            <p><b>3.</b> 平台向选定主体连接器发送签名计算请求</p>
            <p><b>4.</b> 连接器只返回受控汇总和多点趋势，不返回原始记录</p>
            <p><b>5.</b> 结果签名校验后写入任务与审计记录</p>
          </div>
        </section>
      </aside>
    </div>
  </PrototypePageFrame>;
}
