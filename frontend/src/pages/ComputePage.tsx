import { useMemo, useState } from "react";
import { Cpu, Database, EyeOff, Network, Play, Plus, RefreshCw, Route, ShieldCheck } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, formatDate, post, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, CodeValue, DataTable, ErrorState, Field, LoadingState, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

type ComputeTab = "SETTLEMENT" | "LOAD";

const strategyLabels: Record<string, string> = {
  FEDERATED_LEARNING: "联邦学习",
  DIFFERENTIAL_PRIVACY_OUTPUT: "差分隐私输出",
  PSI_MPC: "PSI + MPC",
  DETERMINISTIC_RULE_ENGINE: "确定性规则引擎",
  SECRET_SHARING_HE: "秘密共享 + 同态加密",
  TEE_CONFIDENTIAL_COMPUTE: "TEE 机密计算",
  POLICY_SANDBOX: "策略沙箱",
};

function strategyName(code: unknown) {
  return strategyLabels[String(code)] || String(code || "-");
}

export function ComputePage() {
  const { session } = useAuth();
  const analysisAllowed = ["RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"].includes(session!.user.role_code);
  const canCreateAnalysis = ["RETAILER", "EXCHANGE", "REGULATOR"].includes(session!.user.role_code);
  const [tab, setTab] = useState<ComputeTab>("SETTLEMENT");
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const loader = async () => {
    const [jobs, strategies] = await Promise.all([
      api<JsonRecord[]>("/privacy/jobs"),
      api<JsonRecord[]>("/privacy/strategy/catalog"),
    ]);
    const analyses = analysisAllowed ? await api<JsonRecord[]>("/privacy/analysis/jobs") : [];
    return { jobs, analyses, strategies };
  };
  const { data, loading, error, reload } = useRemote(loader, [analysisAllowed]);

  if (loading) return <LoadingState label="正在读取隐私计算回执" />;
  if (error || !data) return <ErrorState message={error || "隐私计算加载失败"} retry={reload} />;

  const currentRows = tab === "SETTLEMENT" ? data.jobs : data.analyses;

  return (
    <>
      <PageHeader eyebrow="平台核心能力" title="隐私计算" description="控制面只编排 DataPermit 与 ComputePlan，执行面在授权数据域内完成 PSI/MPC、秘密共享或差分隐私计算，并返回可验证回执。" actions={<><Button icon={RefreshCw} onClick={reload}>刷新</Button>{tab === "LOAD" && canCreateAnalysis && <Button icon={Plus} variant="primary" onClick={() => setShowAnalysis(true)}>发起隐私分析</Button>}</>} />
      <div className="segmented" role="tablist">
        <button className={tab === "SETTLEMENT" ? "active" : ""} onClick={() => setTab("SETTLEMENT")}>场景验证 MPC</button>
        {analysisAllowed && <button className={tab === "LOAD" ? "active" : ""} onClick={() => setTab("LOAD")}>用户用电隐私分析</button>}
      </div>
      <div className="privacy-boundaries">
        <div><EyeOff size={19} /><strong>原始数据不出域</strong><span>Agent、业务库与调用方不可读取企业明细</span></div>
        <div><ShieldCheck size={19} /><strong>授权后可计算</strong><span>用途、算法、时效与输出纳入 DataPermit</span></div>
        <div><Cpu size={19} /><strong>结果可验证</strong><span>算法、输入承诺与输出哈希写入 ComputeReceipt</span></div>
      </div>
      <Surface title="场景感知隐私计算策略路由" note="由数据等级、参与主体、时延和精度约束生成 ComputePlan，并固化计划哈希">
        <div className="strategy-grid">
          {data.strategies.map((item: JsonRecord) => (
            <article key={item.scenario_code}>
              <header><Route size={18} /><span>{item.scenario_name}</span><StatusTag value="ACTIVE" label={item.sensitivity_level} /></header>
              <strong>{strategyName(item.primary)}</strong>
              <div>{item.supporting.map((code: string) => <span key={code}>{strategyName(code)}</span>)}</div>
              <p>{item.reason}</p>
              <small>{item.latency_requirement} · {item.participant_count}方 · 仅聚合披露</small>
            </article>
          ))}
        </div>
      </Surface>
      <Surface title={tab === "SETTLEMENT" ? "MPC 场景验证任务" : "负荷隐私分析任务"} note={tab === "SETTLEMENT" ? "PSI 对齐授权数据关系，MPC 验证跨主体计算闭环" : "仅输出聚合曲线、峰谷特征与需求响应潜力"}>
        <DataTable
          keyField={tab === "SETTLEMENT" ? "job_id" : "analysis_id"}
          rows={currentRows}
          columns={tab === "SETTLEMENT" ? [
            { key: "job_id", label: "计算编号", render: (row) => <button className="table-link mono-text" onClick={() => setSelected(row)}>{shortHash(row.job_id, 8)}</button> },
            { key: "task_id", label: "关联任务", render: (row) => <span className="mono-text">{row.task_id}</span> },
            { key: "algorithm_code", label: "算法" },
            { key: "adapter_code", label: "执行适配器" },
            { key: "duration_ms", label: "耗时", render: (row) => `${row.duration_ms || 0} ms` },
            { key: "output_hash", label: "输出哈希", render: (row) => <CodeValue title={row.output_hash}>{shortHash(row.output_hash)}</CodeValue> },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "created_at", label: "执行时间", render: (row) => formatDate(row.created_at) },
          ] : [
            { key: "analysis_name", label: "分析任务", render: (row) => <button className="table-link" onClick={() => setSelected(row)}>{row.analysis_name}</button> },
            { key: "analysis_type", label: "分析类型" },
            { key: "strategy", label: "自适应策略", render: (row) => strategyName(row.result_json?.compute_strategy?.primary) },
            { key: "privacy_level", label: "隐私级别" },
            { key: "privacy_budget", label: "隐私预算" },
            { key: "dataset_ids_json", label: "参与数据域", render: (row) => `${row.dataset_ids_json?.length || 0} 个` },
            { key: "result_hash", label: "结果哈希", render: (row) => <CodeValue title={row.result_hash}>{shortHash(row.result_hash)}</CodeValue> },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "created_at", label: "执行时间", render: (row) => formatDate(row.created_at) },
          ]}
        />
      </Surface>
      {selected && (tab === "SETTLEMENT" ? <ComputeDetail job={selected} onClose={() => setSelected(null)} /> : <AnalysisDetail job={selected} onClose={() => setSelected(null)} />)}
      {showAnalysis && <AnalysisForm strategies={data.strategies} onClose={() => setShowAnalysis(false)} onCreated={async () => { setShowAnalysis(false); await reload(); }} />}
    </>
  );
}

function ComputeDetail({ job, onClose }: { job: JsonRecord; onClose: () => void }) {
  return (
    <Modal title="ComputeReceipt 隐私计算回执" onClose={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
      <div className="detail-grid">
        <div><span>执行适配器</span><strong>{job.adapter_code}</strong></div>
        <div><span>计算耗时</span><strong>{job.duration_ms} ms</strong></div>
        <div><span>输出哈希</span><CodeValue>{job.output_hash}</CodeValue></div>
        <div><span>状态</span><StatusTag value={job.status} /></div>
      </div>
      <div className="log-console">
        {(job.logs_json || []).map((line: string, index: number) => <div key={`${line}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span>{line}</div>)}
      </div>
      <Notice tone="success">回执包含输入承诺、算法标识、执行证明与输出哈希，不包含任一参与方原始记录，可供后续审计和场景验证引用。</Notice>
    </Modal>
  );
}

function AnalysisDetail({ job, onClose }: { job: JsonRecord; onClose: () => void }) {
  const result = job.result_json || job.output_json || {};
  const strategy = result.compute_strategy || {};
  const points = (result.aggregate_curve || []).map((value: number, hour: number) => ({ hour: `${hour}:00`, value }));
  return (
    <Modal title={job.analysis_name} onClose={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
      <div className="analysis-kpis">
        <div><span>峰值负荷</span><strong>{result.peak_load_mw ?? "-"} MW</strong></div>
        <div><span>谷值负荷</span><strong>{result.valley_load_mw ?? "-"} MW</strong></div>
        <div><span>峰谷比</span><strong>{result.peak_valley_ratio ?? "-"}</strong></div>
        <div><span>响应潜力</span><strong>{result.demand_response_potential_mw ?? "-"} MW</strong></div>
      </div>
      <div className="strategy-receipt"><Route size={18} /><div><span>执行策略</span><strong>{strategyName(strategy.primary)}</strong><small>{strategy.reason}</small></div><CodeValue>{shortHash(strategy.plan_hash, 12)}</CodeValue></div>
      {points.length > 0 && <div className="chart-block"><ResponsiveContainer width="100%" height={250}><LineChart data={points}><CartesianGrid stroke="#d7e3ef" vertical={false} /><XAxis dataKey="hour" interval={3} tick={{ fontSize: 11, fill: "#63778e" }} /><YAxis tick={{ fontSize: 11, fill: "#63778e" }} /><Tooltip /><Line type="monotone" dataKey="value" stroke="#0b5cab" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div>}
      <Notice tone="success">返回值为群组聚合结果；用户标识、单户曲线和原始测点均未返回。</Notice>
    </Modal>
  );
}

function AnalysisForm({ strategies, onClose, onCreated }: { strategies: JsonRecord[]; onClose: () => void; onCreated: () => Promise<void> }) {
  const { data, loading, error } = useRemote<JsonRecord[]>(() => api("/data/uploads?asset_type=USER_LOAD_CURVE"), []);
  const [selected, setSelected] = useState<string[]>([]);
  const [name, setName] = useState("园区用户群需求响应潜力分析");
  const [privacy, setPrivacy] = useState("DIFFERENTIAL_PRIVACY");
  const [scenario, setScenario] = useState("VPP_AGGREGATION");
  const [sensitivity, setSensitivity] = useState("L4");
  const [latency, setLatency] = useState("MINUTE");
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const formReady = name.trim().length >= 2 && selected.length > 0;

  function toggle(id: string) {
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  async function submit() {
    setBusy(true);
    setSubmitError("");
    try {
      await post("/privacy/analysis/jobs", {
        analysis_name: name,
        dataset_ids: selected,
        analysis_type: "DR_POTENTIAL",
        privacy_level: privacy,
        privacy_budget: 1.0,
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
        <Field label="业务场景"><select value={scenario} onChange={(event) => setScenario(event.target.value)}>{strategies.map((item) => <option key={item.scenario_code} value={item.scenario_code}>{item.scenario_name}</option>)}</select></Field>
        <Field label="数据敏感等级"><select value={sensitivity} onChange={(event) => setSensitivity(event.target.value)}><option value="L2">L2 内部数据</option><option value="L3">L3 敏感数据</option><option value="L4">L4 核心敏感</option></select></Field>
        <Field label="时延要求"><select value={latency} onChange={(event) => setLatency(event.target.value)}><option value="BATCH">批处理</option><option value="MINUTE">分钟级</option><option value="REAL_TIME">实时</option></select></Field>
        <Field label="隐私级别"><select value={privacy} onChange={(event) => setPrivacy(event.target.value)}><option value="AGGREGATED">聚合披露</option><option value="K_ANONYMIZED">K 匿名</option><option value="DIFFERENTIAL_PRIVACY">差分隐私</option></select></Field>
      </div>
      <h3 className="subheading">选择授权数据引用</h3>
      {loading ? <LoadingState /> : error ? <Notice tone="warning">{error}</Notice> : <div className="dataset-picker">{(data || []).map((item) => <label key={item.upload_id}><input type="checkbox" checked={selected.includes(item.upload_id)} onChange={() => toggle(item.upload_id)} /><Database size={18} /><div><strong>{item.label}</strong><span>{item.owner_org_name} · {item.summary_json?.record_count} 条</span></div></label>)}</div>}
      <Notice>策略路由器将业务场景、敏感等级、参与方数量和时延要求固化为 ComputePlan；计算节点只返回聚合序列、统计特征和可验证回执。</Notice>
      {submitError && <Notice tone="warning">{submitError}</Notice>}
    </Modal>
  );
}
