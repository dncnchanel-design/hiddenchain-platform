import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, createIdempotencyKey } from "../../../api";
import { commandPollingRetryDelay, MAX_CONSECUTIVE_POLLING_FAILURES, shouldRetryCommandPolling, shouldStopCommandPolling } from "../../../hooks";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { VisibleModuleBoundary } from "../components/VisibleModuleBoundary";
import {
  confirmTrustedQuery,
  executeTrustedQuery,
  loadCatalog,
  loadTrustedQueryResult,
  loadTrustedQueryTask,
  loadUsageRequests,
  parseTrustedQuery,
  type CatalogAsset,
  type ControlledQueryResult,
  type QueryConfirmation,
  type QueryIntent,
  type TrustedQueryTask,
  type UsageRequest,
} from "../trusted-space-api";
import {
  clearPendingQueryTask,
  readPendingQueryTask,
  recoverPendingQuerySubmission,
  writePendingQueryTask,
  type PendingQueryTask,
  type PendingQuerySubmission,
} from "../query-task-lifecycle";
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

type QueryResultChartModule = typeof import("../components/QueryResultChart");

let queryResultChartPromise: Promise<QueryResultChartModule> | undefined;

function loadQueryResultChart() {
  queryResultChartPromise ||= import("../components/QueryResultChart").catch((error) => {
    queryResultChartPromise = undefined;
    throw error;
  });
  return queryResultChartPromise;
}

type QueryStepStatus = "待处理" | "进行中" | "已完成" | "待选择主体" | "待授权" | "已阻断" | "失败";
type QueryStep = { stage: string; status: QueryStepStatus; detail?: string };
type ExecuteBody = Parameters<typeof executeTrustedQuery>[0];
type RetrySubmission = { body: ExecuteBody; metadata: PendingQuerySubmission; idempotencyKey: string };

const INITIAL_STEPS: QueryStep[] = [
  { stage: "解析需求", status: "待处理" },
  { stage: "授权确认", status: "待处理" },
  { stage: "连接器计算", status: "待处理" },
  { stage: "返回多点数据", status: "待处理" },
];

const QUERY_STATUS_LABELS: Record<TrustedQueryTask["status"], string> = {
  QUEUED: "排队中",
  RUNNING: "执行中",
  PENDING_RETRY: "等待自动重试",
  SUCCEEDED: "已完成",
  FAILED: "执行失败",
};

function updateStep(steps: QueryStep[], index: number, status: QueryStepStatus, detail?: string) {
  return steps.map((step, stepIndex) => stepIndex === index ? { ...step, status, detail } : step);
}

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof Error ? reason.message : fallback;
}

function errorStatus(reason: unknown) {
  return reason instanceof ApiError ? reason.status : null;
}

function retryableSubmission(reason: unknown) {
  return reason instanceof TypeError || (reason instanceof ApiError && reason.retryable);
}

function providerName(asset: CatalogAsset) {
  return asset.provider.org_name || asset.provider.org_id;
}

function resultObject(result: ControlledQueryResult["result"]): Record<string, number | string> | null {
  return result && typeof result === "object" && !Array.isArray(result) ? result : null;
}

function resultSummary(result: ControlledQueryResult) {
  if (typeof result.result === "number") return `${result.result} ${result.unit || ""}`.trim();
  if (typeof result.result === "string") return result.result;
  const raw = resultObject(result.result);
  if (!raw) return "已返回受控摘要";
  const direction = typeof raw["方向"] === "string" ? raw["方向"] : "";
  const changeRate = typeof raw["变化率"] === "number" ? `${raw["变化率"]}%` : "";
  return [direction, changeRate].filter(Boolean).join(" · ") || "已返回受控摘要";
}

function QueryTaskState({ task }: { task: TrustedQueryTask | null }) {
  if (!task) return <div className="prototype-query-proof" role="status"><span>任务状态</span><strong>正在恢复持久化任务…</strong></div>;
  return <div className="prototype-query-proof" role="status">
    <span>任务状态</span>
    <strong>{QUERY_STATUS_LABELS[task.status]} · 第 {task.attempt}/{task.max_attempts} 次尝试</strong>
    {task.failure_summary && <small>{task.failure_code ? `${task.failure_code} · ` : ""}{task.failure_summary}</small>}
  </div>;
}

function QueryResultDetails({ execution }: { execution: ControlledQueryResult }) {
  const trend = (execution.trend || []).filter((point) => point && point.date && Number.isFinite(point.value));
  return <>
    <div className="prototype-query-result">
      <div><span>受控结果</span><strong>{resultSummary(execution)}</strong></div>
      <div><span>连接器记录数</span><strong>{execution.record_count ?? "—"}</strong></div>
      <div><span>结果单位</span><strong>{execution.unit || "—"}</strong></div>
    </div>
    {trend.length > 1
      ? <VisibleModuleBoundary loader={loadQueryResultChart} className="trusted-query-chart" ariaLabel="查询结果图表正在加载" renderLoaded={({ QueryResultChart }) => <QueryResultChart result={{ ...execution, trend }} />} />
      : <div className="prototype-query-proof"><span>结果依据</span><strong>连接器已返回签名受控汇总，但没有足够的多日期数据绘制趋势图。</strong></div>}
    <div className="prototype-query-proof"><span>可信留痕</span><strong>任务 {execution.task_id} · 连接器签名{execution.digital_signature} · 原始记录未返回 · {execution.privacy_verification?.status === "VERIFIED" ? "签名不出域证明已验证" : "不出域证明未提供"}</strong>{execution.job_id && <Link to={routeForView("mpc", execution.job_id)}>查看隐私计算任务</Link>}</div>
  </>;
}

function QueryOutput({
  intent,
  steps,
  providers,
  selectedProviderId,
  onProviderChange,
  onExecute,
  executeBusy,
  task,
  taskActive,
  execution,
  error,
  pollingError,
  retryLabel,
  onRetry,
  identity,
}: {
  intent: QueryIntent;
  steps: QueryStep[];
  providers: CatalogAsset[];
  selectedProviderId: string;
  onProviderChange: (assetId: string) => void;
  onExecute: () => void;
  executeBusy: boolean;
  task: TrustedQueryTask | null;
  taskActive: boolean;
  execution: ControlledQueryResult | null;
  error: string;
  pollingError: string;
  retryLabel: string;
  onRetry: () => void;
  identity: { name: string; did: string };
}) {
  const selectedProvider = providers.find((item) => item.asset_id === selectedProviderId);
  const aiLabel = intent.provider === "deepseek" ? `DeepSeek${intent.model ? ` · ${intent.model}` : ""}` : "手动规则预览";
  const canExecute = Boolean(intent.ready && selectedProvider && !executeBusy && !taskActive);
  const needsAuthorization = steps[1]?.status === "失败" || steps[1]?.status === "待授权";
  const applyPath = selectedProvider ? routeForView("apply", selectedProvider.asset_id) : routeForView("catalog");

  return <section className="prototype-card prototype-query-output">
    <PrototypeCardTitle>问数结果 <span className="prototype-inline-state" title={`身份 ${identity.did || "未登记"} · ${aiLabel} · 原始数据未返回`}>身份 {identity.did || "未登记"} · {aiLabel} · 原始数据未返回</span></PrototypeCardTitle>
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
      <button type="button" className="prototype-primary-button" disabled={!canExecute} onClick={onExecute}>{executeBusy ? "正在提交持久化任务…" : taskActive ? "任务执行中" : "确认授权并执行连接器计算"}</button>
      <span>确认后创建持久化任务；页面只轮询任务状态，成功后才读取结果。</span>
    </div>}

    {task && <QueryTaskState task={task} />}
    {error && <div className="prototype-error prototype-deny-message" role="alert">⛔ {error}{selectedProvider && needsAuthorization && <Link to={applyPath}>前往申请授权</Link>}{retryLabel && <button type="button" className="prototype-secondary-button" disabled={executeBusy} onClick={onRetry}>{retryLabel}</button>}</div>}
    {pollingError && <div className="prototype-error prototype-deny-message" role="alert">⛔ {pollingError}{retryLabel && <button type="button" className="prototype-secondary-button" disabled={executeBusy} onClick={onRetry}>{retryLabel}</button>}</div>}
    {execution ? <QueryResultDetails execution={execution} /> : !error && !pollingError && !task && <div className="prototype-empty">解析完成后，请选择数据主体并确认授权，系统才会创建受控查询任务。</div>}
    <div className="prototype-audit-id">{task ? `受控任务 ${task.task_id}` : `AI解析 ${aiLabel}`} · {identity.name || "当前主体"}</div>
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
  const [task, setTask] = useState<TrustedQueryTask | null>(null);
  const [initialPending] = useState<PendingQueryTask | null>(() => {
    const value = readPendingQueryTask(sessionStorage);
    if (!value) clearPendingQueryTask(sessionStorage);
    return value;
  });
  const [pendingTask, setPendingTask] = useState<PendingQueryTask | null>(initialPending);
  const [restoredPreflight, setRestoredPreflight] = useState(Boolean(initialPending?.taskId === null && initialPending.submission));
  const [retrySubmission, setRetrySubmission] = useState<RetrySubmission | null>(null);
  const [preflightRetryNonce, setPreflightRetryNonce] = useState(0);
  const [pollRetryNonce, setPollRetryNonce] = useState(0);
  const [pollingPaused, setPollingPaused] = useState(false);
  const [pollingError, setPollingError] = useState("");
  const [busy, setBusy] = useState<"parsing" | "executing" | "">("");
  const [error, setError] = useState("");

  const pendingTaskId = pendingTask?.taskId || null;
  const taskActive = Boolean(pendingTaskId && task?.status !== "FAILED" && task?.status !== "SUCCEEDED") || Boolean(pendingTaskId && !task);

  function rememberPending(value: PendingQueryTask) {
    const persisted = writePendingQueryTask(sessionStorage, value);
    setPendingTask(value);
    return persisted;
  }

  function forgetPending() {
    clearPendingQueryTask(sessionStorage);
    setPendingTask(null);
    setRestoredPreflight(false);
  }

  function setStep(index: number, status: QueryStepStatus, detail?: string) {
    setSteps((current) => updateStep(current, index, status, detail));
  }

  useEffect(() => {
    if (!pendingTaskId) return undefined;
    let active = true;
    let inFlight = false;
    let timer: number | undefined;
    let controller: AbortController | null = null;
    let failures = 0;

    const clearTimer = () => {
      if (timer !== undefined) window.clearTimeout(timer);
      timer = undefined;
    };
    const schedule = (delay: number) => {
      if (!active) return;
      clearTimer();
      timer = window.setTimeout(() => void poll(), delay);
    };
    const stopWithError = (message: string) => {
      setPollingError(message);
      setPollingPaused(true);
    };
    const poll = async () => {
      if (!active || inFlight || document.visibilityState === "hidden") return;
      inFlight = true;
      controller = new AbortController();
      try {
        const next = await loadTrustedQueryTask(pendingTaskId, controller.signal);
        if (!active) return;
        if (next.task_id !== pendingTaskId) {
          forgetPending();
          stopWithError("任务状态响应与请求编号不一致，自动轮询已停止");
          return;
        }
        setTask(next);
        if (next.status === "FAILED") {
          setPollingError("");
          setPollingPaused(false);
          forgetPending();
          setStep(2, "失败", next.failure_summary || "连接器计算失败");
          setSteps((current) => updateStep(current, 3, "已阻断", "任务未成功，不读取结果"));
          setError(next.failure_summary || "连接器计算未完成，未交付结果");
          return;
        }
        if (next.status === "SUCCEEDED") {
          const result = await loadTrustedQueryResult(pendingTaskId, controller.signal);
          if (!active) return;
          if (result.task_id !== pendingTaskId) {
            forgetPending();
            stopWithError("查询结果与持久化任务编号不一致，平台已拒绝展示");
            return;
          }
          if (result.raw_records_returned) {
            forgetPending();
            stopWithError("连接器返回了原始记录，平台已拒绝交付");
            return;
          }
          setExecution(result);
          setPollingError("");
          setPollingPaused(false);
          failures = 0;
          forgetPending();
          setStep(2, "已完成", `任务 ${next.task_id} · 签名${result.digital_signature}`);
          setStep(3, "已完成", result.trend && result.trend.length > 1 ? `已返回 ${result.trend.length} 个日度数据点` : "已返回受控汇总");
          return;
        }
        setPollingError("");
        setPollingPaused(false);
        failures = 0;
        const detail = next.status === "PENDING_RETRY"
          ? `${next.failure_summary || "连接器暂不可用"} · 将自动重试（${next.attempt}/${next.max_attempts}）`
          : `${QUERY_STATUS_LABELS[next.status]} · 第 ${next.attempt}/${next.max_attempts} 次尝试`;
        setStep(2, "进行中", detail);
        schedule(1_500);
      } catch (reason) {
        if (!active || ((reason instanceof DOMException || reason instanceof Error) && reason.name === "AbortError")) return;
        const status = errorStatus(reason);
        if (shouldStopCommandPolling(status)) {
          if (status === 403 || status === 404) forgetPending();
          stopWithError(errorMessage(reason, "任务已不可访问，自动轮询已停止"));
          return;
        }
        if (!shouldRetryCommandPolling(status)) {
          stopWithError(errorMessage(reason, "任务状态无法继续读取，自动轮询已停止"));
          return;
        }
        failures += 1;
        if (failures >= MAX_CONSECUTIVE_POLLING_FAILURES) {
          stopWithError(`${errorMessage(reason, "任务状态读取失败")}；已停止自动重试，请手动重试。`);
          return;
        }
        setPollingError(`${errorMessage(reason, "任务状态读取失败")}；正在进行有限重试（${failures}/${MAX_CONSECUTIVE_POLLING_FAILURES}）。`);
        schedule(commandPollingRetryDelay(failures));
      } finally {
        inFlight = false;
      }
    };
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        clearTimer();
        void poll();
      } else {
        clearTimer();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    void poll();
    return () => {
      active = false;
      clearTimer();
      controller?.abort();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  // The nonce is an explicit manual retry trigger for the same durable task.
  }, [pendingTaskId, pollRetryNonce]);

  useEffect(() => {
    const candidate = pendingTask;
    if (!restoredPreflight || !candidate || candidate.taskId !== null || !candidate.submission) return undefined;
    let active = true;
    const controller = new AbortController();
    const recover = async () => {
      setBusy("executing");
      setError("");
      setPollingError("");
      setStep(1, "进行中", "正在重新核对已保存的查询条件");
      setStep(2, "进行中", "正在恢复未确认响应的持久化任务");
      try {
        const next = await recoverPendingQuerySubmission(
          candidate,
          confirmTrustedQuery,
          executeTrustedQuery,
          controller.signal,
        );
        if (!active) return;
        setStep(1, "已完成", "已重新获取未落盘的短时确认令牌");
        rememberPending({ taskId: next.task_id, idempotencyKey: candidate.idempotencyKey, submission: candidate.submission });
        setTask(next);
        setRetrySubmission(null);
        setStep(2, "进行中", `${QUERY_STATUS_LABELS[next.status]} · 任务 ${next.task_id}`);
        setPollRetryNonce((value) => value + 1);
      } catch (reason) {
        if (!active || ((reason instanceof DOMException || reason instanceof Error) && reason.name === "AbortError")) return;
        setStep(2, "失败", "崩溃窗口任务恢复尚未确认");
        setError(errorMessage(reason, "已保存查询任务恢复失败，可使用原幂等键重试"));
        if (!retryableSubmission(reason)) forgetPending();
      } finally {
        if (active) setBusy("");
      }
    };
    void recover();
    return () => {
      active = false;
      controller.abort();
    };
  // The nonce is the explicit retry trigger for a restored pre-submit crash window.
  }, [pendingTask, preflightRetryNonce, restoredPreflight]);

  async function ask() {
    const text = question.trim();
    if (!text || busy || pendingTask) return;
    setBusy("parsing");
    setError("");
    setPollingError("");
    setIntent(null);
    setProviders([]);
    setApprovedAuthorizations([]);
    setSelectedProviderId("");
    setExecution(null);
    setTask(null);
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

  async function submitTrustedTask(submission: RetrySubmission) {
    setBusy("executing");
    setError("");
    setPollingError("");
    setStep(2, "进行中", "正在创建持久化查询任务");
    try {
      const next = await executeTrustedQuery(submission.body, submission.idempotencyKey);
      rememberPending({ taskId: next.task_id, idempotencyKey: submission.idempotencyKey, submission: submission.metadata });
      setTask(next);
      setRetrySubmission(null);
      setStep(2, "进行中", `${QUERY_STATUS_LABELS[next.status]} · 任务 ${next.task_id}`);
      setPollRetryNonce((value) => value + 1);
    } catch (reason) {
      setStep(2, "失败", "任务提交响应未确认");
      setSteps((current) => updateStep(current, 3, "已阻断", "尚未取得持久化任务结果"));
      setError(errorMessage(reason, "查询任务提交失败，未交付结果"));
      if (retryableSubmission(reason)) {
        setRetrySubmission(submission);
      } else {
        setRetrySubmission(null);
        forgetPending();
      }
    } finally {
      setBusy("");
    }
  }

  async function confirmAndExecute() {
    const selectedProvider = providers.find((item) => item.asset_id === selectedProviderId);
    if (!intent || !selectedProvider || !intent.energy_domain || !intent.resource || !intent.function || !intent.start_date || !intent.end_date || busy || pendingTask) return;
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
    try {
      const confirmation: QueryConfirmation = await confirmTrustedQuery(baseRequest);
      setStep(1, "已完成", "授权范围与查询条件已锁定");
      const idempotencyKey = createIdempotencyKey("trusted-query");
      const metadata: PendingQuerySubmission = baseRequest;
      const submission: RetrySubmission = {
        body: { ...baseRequest, confirmation_token: confirmation.confirmation_token },
        metadata,
        idempotencyKey,
      };
      if (!rememberPending({ taskId: null, idempotencyKey, submission: metadata })) {
        forgetPending();
        throw new Error("浏览器无法保存任务恢复信息，已安全停止提交");
      }
      setRetrySubmission(submission);
      setBusy("");
      await submitTrustedTask(submission);
    } catch (reason) {
      setStep(1, "失败");
      setSteps((current) => current.map((step, index) => index > 1 ? { ...step, status: "已阻断" } : step));
      setError(errorMessage(reason, "授权确认未完成，查询未执行"));
      setBusy("");
    }
  }

  const identity = {
    name: context?.current_subject.org_name || "当前主体",
    did: context?.identity_ref.did || "未登记",
  };
  const retryLabel = retrySubmission
    ? "使用同一幂等键重试提交"
    : restoredPreflight && pendingTask?.taskId === null && pendingTask.submission
      ? "恢复并重提任务"
      : pollingPaused && pendingTaskId ? "重试读取任务状态" : "";
  const retry = () => {
    if (busy) return;
    if (retrySubmission) void submitTrustedTask(retrySubmission);
    else if (restoredPreflight && pendingTask?.taskId === null && pendingTask.submission) {
      setError("");
      setPreflightRetryNonce((value) => value + 1);
    }
    else if (pendingTaskId) {
      setPollingPaused(false);
      setPollingError("");
      setPollRetryNonce((value) => value + 1);
    }
  };
  const restoringPreflight = Boolean(restoredPreflight && pendingTask?.taskId === null && pendingTask.submission);

  return <PrototypePageFrame className="prototype-query-page">
    <div className="prototype-query-layout">
      <div className="prototype-query-main">
        <section className="prototype-card prototype-query-entry">
          <PrototypeCardTitle>对话式问数</PrototypeCardTitle>
          <div className="prototype-chat-input"><input value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.nativeEvent.isComposing) void ask(); }} placeholder="用自然语言描述你的数据需求，例如：查一下6月份各地区的电网负荷，用于运行监测" /><button type="button" disabled={busy !== "" || !question.trim() || Boolean(pendingTask)} onClick={() => void ask()}>{busy === "parsing" ? "AI解析中…" : "发送"}</button></div>
          <div className="prototype-query-examples" aria-label="快捷提问">{EXAMPLES.map((item) => <button type="button" key={item} onClick={() => setQuestion(item)}>{item}</button>)}</div>
        </section>
        {intent && <QueryOutput intent={intent} steps={steps} providers={providers} selectedProviderId={selectedProviderId} onProviderChange={setSelectedProviderId} onExecute={() => void confirmAndExecute()} executeBusy={busy === "executing"} task={task} taskActive={taskActive} execution={execution} error={error} pollingError={pollingError} retryLabel={retryLabel} onRetry={retry} identity={identity} />}
        {!intent && (pendingTaskId || restoringPreflight || task || execution || pollingError) && <section className="prototype-card prototype-query-output">
          <PrototypeCardTitle>恢复中的受控查询 <span className="prototype-inline-state">仅恢复任务元数据，不保存查询结果或原始数据</span></PrototypeCardTitle>
          {(pendingTaskId || restoringPreflight || task) && <QueryTaskState task={task} />}
          {pollingError && <div className="prototype-error prototype-deny-message" role="alert">⛔ {pollingError}{retryLabel && <button type="button" className="prototype-secondary-button" disabled={busy !== ""} onClick={retry}>{retryLabel}</button>}</div>}
          {execution && <QueryResultDetails execution={execution} />}
        </section>}
        {error && !intent && <div className="prototype-error" role="alert">{error}{retryLabel && <button type="button" className="prototype-secondary-button" disabled={busy !== ""} onClick={retry}>{retryLabel}</button>}</div>}
      </div>
      <aside className="prototype-query-side">
        <section className="prototype-card">
          <PrototypeCardTitle>问数说明</PrototypeCardTitle>
          <div className="prototype-query-info">
            <p><b>1.</b> DeepSeek 只解析自然语言，不访问原始数据</p>
            <p><b>2.</b> 确定性策略引擎校验主体授权与查询范围</p>
            <p><b>3.</b> 平台创建可恢复任务，再向主体连接器发送签名计算请求</p>
            <p><b>4.</b> 连接器只返回受控汇总和多点趋势，不返回原始记录</p>
            <p><b>5.</b> 任务成功后才读取结果，并记录签名校验与审计留痕</p>
          </div>
        </section>
      </aside>
    </div>
  </PrototypePageFrame>;
}
