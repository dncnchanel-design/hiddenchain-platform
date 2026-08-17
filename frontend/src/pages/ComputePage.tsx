import { useEffect, useState } from "react";
import { ArrowLeft, Database, Eye, Play, Plus, RefreshCw, Route } from "lucide-react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, formatNumber, post } from "../api";
import { useAuth } from "../auth";
import { AmountText, Button, DataTable, DateTimeText, DetailDrawer, ErrorState, Field, IdText, LoadingState, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { ALGORITHM_LABELS, SCENARIO_LABELS } from "../types";
import type { JsonRecord } from "../types";

type ComputeTab = "SETTLEMENT" | "LOAD";

function strategyName(code: unknown) {
  return ALGORITHM_LABELS[String(code)] || String(code || "—");
}

function purposeName(code: unknown) {
  return ({ POWER_SETTLEMENT: "电力结算", MARKET_SETTLEMENT: "市场结算" } as Record<string, string>)[String(code)] || "任务约定用途";
}

function outputModeName(code: unknown) {
  return code === "AGGREGATE_ONLY" ? "仅披露聚合结算结果" : "未提供披露策略";
}

function authorizationSummary(items: JsonRecord[] = []) {
  const purposes = Array.from(new Set(items.map((item) => purposeName(item.purpose))));
  return `${items.length} 份${purposes.length ? ` · ${purposes.join("、")}` : ""}`;
}

export function ComputePage() {
  const { session } = useAuth();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const taskId = searchParams.get("task_id") || "";
  const analysisAllowed = ["RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"].includes(session!.user.role_code);
  const canCreateAnalysis = ["RETAILER", "EXCHANGE", "REGULATOR"].includes(session!.user.role_code);
  const tab: ComputeTab = searchParams.get("tab") === "analysis" && analysisAllowed ? "LOAD" : "SETTLEMENT";
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const loader = async (signal?: AbortSignal) => {
    const request = { signal, timeoutMs: 12000, cache: "no-store" as RequestCache };
    const [jobs, strategies] = await Promise.all([
      api<JsonRecord[]>(taskId ? `/privacy/jobs?task_id=${encodeURIComponent(taskId)}` : "/privacy/jobs", request),
      api<JsonRecord[]>("/privacy/strategy/catalog", request),
    ]);
    const analyses = analysisAllowed ? await api<JsonRecord[]>("/privacy/analysis/jobs", request) : [];
    return { jobs, analyses, strategies };
  };
  const { data, loading, refreshing, error, reload } = useRemote(loader, [analysisAllowed, taskId]);

  useEffect(() => {
    if (loading || location.hash !== "#compute-strategies") return;
    const frame = window.requestAnimationFrame(() => document.getElementById("compute-strategies")?.scrollIntoView());
    return () => window.cancelAnimationFrame(frame);
  }, [loading, location.hash]);

  function selectTab(nextTab: ComputeTab) {
    const next = new URLSearchParams(searchParams);
    next.set("tab", nextTab === "LOAD" ? "analysis" : "tasks");
    setSearchParams(next, { replace: true });
  }

  if (loading) return <LoadingState label="正在加载计算任务" variant="page" />;
  if (error || !data) return <ErrorState message={error || "隐私计算加载失败"} retry={reload} />;

  const currentRows = tab === "SETTLEMENT" ? data.jobs : data.analyses;

  return (
    <>
      <PageHeader title="隐私计算" actions={<>{taskId && <Link className="button button-secondary" to={`/settlements/${taskId}`}><ArrowLeft size={16} />返回结算任务</Link>}<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>{!taskId && tab === "LOAD" && canCreateAnalysis && <Button icon={Plus} variant="primary" onClick={() => setShowAnalysis(true)}>发起分析</Button>}</>} />
      {taskId && <div className="association-context"><span>关联结算任务</span><Link to={`/settlements/${taskId}`}>{taskId}</Link></div>}
      <div className="segmented" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "SETTLEMENT"} className={tab === "SETTLEMENT" ? "active" : ""} onClick={() => selectTab("SETTLEMENT")}>调用计算</button>
        {analysisAllowed && <button type="button" role="tab" aria-selected={tab === "LOAD"} className={tab === "LOAD" ? "active" : ""} onClick={() => selectTab("LOAD")}>用电分析</button>}
      </div>
      <Surface id="compute-strategies" title="计算方案" meta="候选方案不代表运行环境已接入对应协议">
        <DataTable keyField="scenario_code" rows={data.strategies} label="计算方式目录" pageSize={20} columns={[
          { key: "scenario_code", label: "业务场景", minWidth: 170, render: (row) => SCENARIO_LABELS[row.scenario_code] || row.scenario_name || row.scenario_code || "—" },
          { key: "primary", label: "建议主要方式", minWidth: 180, render: (row) => strategyName(row.primary) },
          { key: "supporting", label: "建议辅助方式", minWidth: 240, render: (row) => (row.supporting || []).map((code: string) => strategyName(code)).join("、") || "—" },
          { key: "implementation_status", label: "运行能力", minWidth: 90, render: (row) => <StatusTag value={row.implementation_status} label={row.execution_capability ? "可执行" : "未接入"} /> },
          { key: "sensitivity_level", label: "敏感等级", render: (row) => <StatusTag value={row.sensitivity_level} /> },
          { key: "latency_requirement", label: "时延要求", render: (row) => <StatusTag value={row.latency_requirement} /> },
          { key: "participant_count", label: "参与方", align: "right", render: (row) => row.participant_count === undefined ? "—" : `${row.participant_count} 方` },
        ]} />
      </Surface>
      <Surface title={tab === "SETTLEMENT" ? "调用计算任务" : "用电分析任务"}>
        <DataTable
          keyField={tab === "SETTLEMENT" ? "job_id" : "analysis_id"}
          rows={currentRows}
          columns={tab === "SETTLEMENT" ? [
            { key: "task_id", label: "关联结算任务", minWidth: 200, render: (row) => <div className="task-name-cell"><Link to={`/settlements/${row.task_id}`}>{row.task_name || "结算任务"}</Link><IdText value={row.task_id} /></div> },
            { key: "trade_batch_no", label: "数据批次", minWidth: 125, render: (row) => <IdText value={row.trade_batch_no} length={8} /> },
            { key: "participants", label: "参与主体", minWidth: 200, sortable: false, render: (row) => (row.participants || []).map((item: JsonRecord) => item.org_name || item.org_id).join("、") || "—" },
            { key: "authorization_basis", label: "授权依据", minWidth: 125, sortable: false, render: (row) => authorizationSummary(row.authorization_basis) },
            { key: "algorithm_code", label: "计算方案", minWidth: 130, render: (row) => strategyName(row.algorithm_code) },
            { key: "disclosure", label: "结果披露", minWidth: 140, sortable: false, render: (row) => outputModeName(row.disclosure?.output_mode) },
            { key: "output_hash", label: "输出摘要", minWidth: 135, render: (row) => <IdText value={row.output_hash} /> },
            { key: "evidence_count", label: "证据", align: "right", render: (row) => `${row.evidence_count || 0} 项` },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "created_at", label: "执行时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
            { key: "duration_ms", label: "耗时", align: "right", render: (row) => row.duration_ms === null || row.duration_ms === undefined ? "—" : `${formatNumber(row.duration_ms, 0)} ms` },
            { key: "action", label: "操作", minWidth: 100, sortable: false, hideable: false, sticky: "right", render: (row) => <Button icon={Eye} onClick={() => setSelected(row)}>查看回执</Button> },
          ] : [
            { key: "analysis_name", label: "分析任务", minWidth: 180, render: (row) => <button className="table-link" type="button" onClick={() => setSelected(row)}>{row.analysis_name}</button> },
            { key: "analysis_type", label: "分析类型", render: (row) => ({ PEAK_VALLEY: "峰谷特征", LOAD_CLUSTER: "负荷聚类", DR_POTENTIAL: "响应潜力" } as Record<string, string>)[row.analysis_type] || row.analysis_type },
            { key: "strategy", label: "自适应策略", render: (row) => strategyName(row.result_json?.compute_strategy?.primary) },
            { key: "privacy_level", label: "隐私级别", render: (row) => ({ AGGREGATED: "聚合输出", K_ANONYMIZED: "匿名化输出", DIFFERENTIAL_PRIVACY: "差分隐私输出" } as Record<string, string>)[row.privacy_level] || row.privacy_level },
            { key: "privacy_budget", label: "隐私预算" },
            { key: "dataset_ids_json", label: "参与数据域", render: (row) => `${row.dataset_ids_json?.length || 0} 个` },
            { key: "result_hash", label: "结果摘要", minWidth: 150, render: (row) => <IdText value={row.result_hash} /> },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "created_at", label: "执行时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
          ]}
        />
      </Surface>
      {selected && (tab === "SETTLEMENT" ? <ComputeDetail job={selected} onClose={() => setSelected(null)} /> : <AnalysisDetail job={selected} onClose={() => setSelected(null)} />)}
      {showAnalysis && <AnalysisForm strategies={data.strategies} onClose={() => setShowAnalysis(false)} onCreated={async () => { setShowAnalysis(false); await reload(); }} />}
    </>
  );
}

function ComputeDetail({ job, onClose }: { job: JsonRecord; onClose: () => void }) {
  const guarantees = job.privacy_guarantees || {};
  const result = job.result_json || {};
  const participants = job.participants || [];
  const authorization = job.authorization_basis || [];
  return (
    <DetailDrawer title="隐私计算回执" onClose={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
      <div className="detail-grid">
        <div><span>计算编号</span><IdText value={job.job_id} /></div>
        <div><span>关联结算任务</span><Link className="text-link" to={`/settlements/${job.task_id}`}>{job.task_name || <IdText value={job.task_id} />}</Link></div>
        <div><span>数据批次</span><IdText value={job.trade_batch_no} /></div>
        <div><span>计算方式</span><strong>{strategyName(job.algorithm_code)}</strong></div>
        <div><span>结算规则</span><strong>{job.rule ? `${job.rule.rule_version} · ${job.rule.rule_name}` : "未提供"}</strong></div>
        <div><span>结果披露</span><strong>{outputModeName(job.disclosure?.output_mode)}</strong></div>
        <div><span>计算耗时</span><strong>{job.duration_ms === null || job.duration_ms === undefined ? "—" : `${formatNumber(job.duration_ms, 0)} ms`}</strong></div>
        <div><span>输出摘要</span><IdText value={job.output_hash} /></div>
        <div><span>状态</span><StatusTag value={job.status} /></div>
      </div>

      <div className="detail-section">
        <h3>参与主体</h3>
        <div className="detail-grid">{participants.map((item: JsonRecord) => <div key={item.org_id}><span>{item.role_in_task === "GENERATOR" ? "发电企业" : "售电企业"}</span><strong>{item.org_name || item.org_id}</strong></div>)}</div>
      </div>

      <div className="detail-section">
        <h3>授权依据</h3>
        <div className="detail-grid">{authorization.map((item: JsonRecord, index: number) => <div key={item.agreement_id}><span>协议 {index + 1} · {purposeName(item.purpose)}</span><strong>{item.provider_org_name || item.provider_org_id} → {item.consumer_org_name || item.consumer_org_id}</strong><IdText value={item.policy_hash} length={9} /></div>)}</div>
      </div>

      <div className="detail-section">
        <h3>输出与证据</h3>
        <div className="detail-grid">
          <div><span>结算电量</span><strong>{result.settlement_energy_mwh === undefined ? "按角色范围披露" : `${formatNumber(result.settlement_energy_mwh, 2)} MWh`}</strong></div>
          <div><span>应结金额</span>{result.payable_amount_yuan === undefined ? <strong>按角色范围披露</strong> : <AmountText value={result.payable_amount_yuan} />}</div>
          <div><span>证据记录</span><strong>{job.evidence_count || 0} 项</strong></div>
          <div><span>原始记录接口返回</span><strong>{job.disclosure?.api_raw_records_returned === false ? "否" : "未提供验证信息"}</strong></div>
        </div>
        <div className="section-links"><Link to={`/results?task_id=${job.task_id}`}>查看结算结果</Link><Link to={`/evidence?task_id=${job.task_id}`}>查看审计证据</Link><Link to={`/audit?task_id=${job.task_id}`}>进入审计复核</Link></div>
      </div>

      {Object.keys(guarantees).length > 0 && <details className="secondary-details"><summary>技术执行边界</summary><div className="detail-grid"><div><span>执行环境</span><strong>{guarantees.execution_environment === "APPLICATION_PROCESS" ? "应用进程内" : "未提供"}</strong></div><div><span>远程证明</span><strong>{guarantees.attestation_status === "NOT_PROVIDED" ? "未提供" : guarantees.attestation_status || "未提供"}</strong></div><div><span>跨域不出域证明</span><strong>{guarantees.cross_domain_non_export_verified ? "已验证" : "未提供验证信息"}</strong></div><div><span>执行适配器</span><strong>{guarantees.strategy || "未提供"}</strong></div></div></details>}
      {(job.logs_json || []).length > 0 && <details className="secondary-details"><summary>查看执行记录</summary><div className="log-console">{job.logs_json.map((line: string, index: number) => <div key={`${line}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span>{line}</div>)}</div></details>}
    </DetailDrawer>
  );
}

function AnalysisDetail({ job, onClose }: { job: JsonRecord; onClose: () => void }) {
  const result = job.result_json || job.output_json || {};
  const strategy = result.compute_strategy || {};
  const points = (result.aggregate_curve || []).map((value: number, hour: number) => ({ hour: `${hour}:00`, value }));
  return (
    <DetailDrawer title={job.analysis_name} onClose={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
      <div className="analysis-kpis">
        <div><span>峰值负荷</span><strong>{result.peak_load_mw ?? "—"} {result.peak_load_mw === undefined ? "" : "MW"}</strong></div>
        <div><span>谷值负荷</span><strong>{result.valley_load_mw ?? "—"} {result.valley_load_mw === undefined ? "" : "MW"}</strong></div>
        <div><span>峰谷比</span><strong>{result.peak_valley_ratio ?? "—"}</strong></div>
        <div><span>响应潜力</span><strong>{result.demand_response_potential_mw ?? "—"} {result.demand_response_potential_mw === undefined ? "" : "MW"}</strong></div>
      </div>
      <div className="strategy-receipt"><Route size={18} /><div><span>执行策略</span><strong>{strategyName(strategy.primary)}</strong></div><IdText value={strategy.plan_hash} /></div>
      {points.length > 0 && <div className="chart-block"><ResponsiveContainer width="100%" height={250}><LineChart data={points}><CartesianGrid stroke="#d7e3ef" vertical={false} /><XAxis dataKey="hour" interval={3} tick={{ fontSize: 11, fill: "#63778e" }} /><YAxis tick={{ fontSize: 11, fill: "#63778e" }} /><Tooltip /><Line type="monotone" dataKey="value" stroke="#0b5cab" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div>}
      {result.privacy_controls && <div className="detail-grid privacy-receipt-grid">
        <div><span>隐私引擎</span><strong>{result.privacy_controls.engine || "—"}</strong></div>
        <div><span>噪声机制</span><strong>{result.privacy_controls.mechanism || "—"}</strong></div>
        <div><span>每小时预算</span><strong>{result.privacy_controls.epsilon_per_hour_release ?? "—"}</strong></div>
        <div><span>边界约束</span><strong>{result.privacy_controls.bound_mw ? `${result.privacy_controls.bound_mw} MW` : "—"}</strong></div>
      </div>}
    </DetailDrawer>
  );
}

function AnalysisForm({ strategies, onClose, onCreated }: { strategies: JsonRecord[]; onClose: () => void; onCreated: () => Promise<void> }) {
  const { data, loading, error } = useRemote<JsonRecord[]>((signal) => api("/data/uploads?asset_type=USER_LOAD_CURVE", { signal, timeoutMs: 12000, cache: "no-store" }), []);
  const [selected, setSelected] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [analysisType, setAnalysisType] = useState("DR_POTENTIAL");
  const [privacy, setPrivacy] = useState("DIFFERENTIAL_PRIVACY");
  const [privacyBudget, setPrivacyBudget] = useState("1");
  const [scenario, setScenario] = useState(String(strategies[0]?.scenario_code || "VPP_AGGREGATION"));
  const [sensitivity, setSensitivity] = useState("L4");
  const [latency, setLatency] = useState("MINUTE");
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const formReady = name.trim().length >= 2 && selected.length > 0 && Number(privacyBudget) > 0 && Number(privacyBudget) <= 10;

  function toggle(id: string) {
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  async function submit() {
    setBusy(true);
    setSubmitError("");
    try {
      await post("/privacy/analysis/jobs", {
        analysis_name: name.trim(),
        dataset_ids: selected,
        analysis_type: analysisType,
        privacy_level: privacy,
        privacy_budget: Number(privacyBudget),
        scenario_code: scenario,
        sensitivity_level: sensitivity,
        latency_requirement: latency,
      });
      await onCreated();
    } catch (reason) {
      setSubmitError(reason instanceof Error ? reason.message : "分析失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="发起用户用电隐私分析" onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button icon={Play} variant="primary" busy={busy} disabled={!formReady} onClick={submit}>执行隐私分析</Button></>}>
      <div className="form-grid two">
        <Field label="分析任务"><input value={name} onChange={(event) => setName(event.target.value)} /></Field>
        <Field label="分析类型"><select value={analysisType} onChange={(event) => setAnalysisType(event.target.value)}><option value="PEAK_VALLEY">峰谷特征</option><option value="LOAD_CLUSTER">负荷聚类</option><option value="DR_POTENTIAL">响应潜力</option></select></Field>
        <Field label="业务场景"><select value={scenario} onChange={(event) => setScenario(event.target.value)}>{strategies.map((item) => <option key={item.scenario_code} value={item.scenario_code}>{SCENARIO_LABELS[item.scenario_code] || item.scenario_name}</option>)}</select></Field>
        <Field label="数据敏感等级"><select value={sensitivity} onChange={(event) => setSensitivity(event.target.value)}><option value="L2">L2 内部数据</option><option value="L3">L3 敏感数据</option><option value="L4">L4 核心敏感</option></select></Field>
        <Field label="时延要求"><select value={latency} onChange={(event) => setLatency(event.target.value)}><option value="BATCH">批处理</option><option value="MINUTE">分钟级</option><option value="REAL_TIME">实时</option></select></Field>
        <Field label="隐私级别"><select value={privacy} onChange={(event) => setPrivacy(event.target.value)}><option value="AGGREGATED">聚合披露</option><option value="K_ANONYMIZED">K 匿名</option><option value="DIFFERENTIAL_PRIVACY">差分隐私</option></select></Field>
        <Field label="隐私预算" hint="取值范围 0–10"><input type="number" min="0.01" max="10" step="0.01" value={privacyBudget} onChange={(event) => setPrivacyBudget(event.target.value)} /></Field>
      </div>
      <h3 className="subheading">选择授权数据引用</h3>
      {loading ? <LoadingState /> : error ? <Notice tone="warning">{error}</Notice> : <div className="dataset-picker">{(data || []).map((item) => <label key={item.upload_id}><input type="checkbox" checked={selected.includes(item.upload_id)} onChange={() => toggle(item.upload_id)} /><Database size={18} /><div><strong>{item.label}</strong><span>{item.owner_org_name} · {item.summary_json?.record_count} 条</span></div></label>)}</div>}
      {submitError && <Notice tone="warning">{submitError}</Notice>}
    </Modal>
  );
}
