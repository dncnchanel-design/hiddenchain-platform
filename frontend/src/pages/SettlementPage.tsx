import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import { Bot, CalendarDays, CheckCircle2, ChevronRight, Circle, FileJson, Play, Plus, RefreshCw, ShieldCheck, Upload, Users } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api, formatDate, post, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, CodeValue, DataTable, ErrorState, Field, LoadingState, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { ROLE_IN_TASK_LABELS } from "../types";
import type { JsonRecord } from "../types";

const stages = [
  ["DRAFT", "待开始"],
  ["AUTHORIZED", "已授权"],
  ["COMPUTING", "计算中"],
  ["EVIDENCED", "已生成凭证"],
  ["AUDITED", "已完成"],
];

export function SettlementPage() {
  const { session } = useAuth();
  const [searchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState(searchParams.get("task") || "");
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState("");
  const loader = async () => {
    const [tasks, rules, orgs] = await Promise.all([
      api<JsonRecord[]>("/settlement/tasks"),
      session!.user.role_code === "EXCHANGE" || session!.user.role_code === "REGULATOR" || session!.user.role_code === "ADMIN" ? api<JsonRecord[]>("/rules") : Promise.resolve([]),
      api<JsonRecord[]>("/system/organizations"),
    ]);
    return { tasks, rules, orgs };
  };
  const { data, loading, error, reload } = useRemote(loader, [session!.user.role_code]);

  useEffect(() => {
    if (data?.tasks.length && !data.tasks.some((item) => item.task_id === selectedId)) setSelectedId(data.tasks[0].task_id);
  }, [data, selectedId]);

  const selected = useMemo(() => data?.tasks.find((item) => item.task_id === selectedId) || null, [data, selectedId]);
  const canRun = ["EXCHANGE", "ADMIN"].includes(session!.user.role_code);
  const canCreate = session!.user.role_code === "EXCHANGE";
  const canImport = ["EXCHANGE", "ADMIN"].includes(session!.user.role_code);

  async function runWorkflow() {
    if (!selected) return;
    setRunning(true);
    setMessage("");
    try {
      const result = await post<JsonRecord>(`/settlement/tasks/${selected.task_id}/run`, { compute_mode: "MPC_MOCK", algorithm_code: "ADAPTIVE_MARKET_SETTLEMENT_V2" });
      const conclusion = result.report?.conclusion === "PASS" ? "通过" : result.report?.conclusion === "REVIEW_REQUIRED" ? "需复核" : result.report?.conclusion || "已生成";
      setMessage(`验证已完成，生成 ${result.evidence.length} 项可信凭证，审计结论${conclusion}。`);
      await reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "执行失败");
    } finally {
      setRunning(false);
    }
  }

  if (loading) return <LoadingState label="正在加载可信调用验证" />;
  if (error || !data) return <ErrorState message={error || "可信调用验证加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader eyebrow="可信数据调用" title="可信调用验证" description="导入一份场景文件，完成可信采集、安全传输、可控使用、隐私计算和可溯审计。" actions={<><Button icon={RefreshCw} onClick={reload}>刷新</Button>{canImport && <Button icon={FileJson} variant="primary" onClick={() => setShowImport(true)}>导入并自动验证</Button>}{canCreate && <Button icon={Plus} onClick={() => setShowForm(true)}>手动创建任务</Button>}</>} />
      {message && <Notice tone={message.includes("失败") || message.includes("缺少") ? "warning" : "success"}>{message}</Notice>}
      <div className="master-detail">
        <Surface title="验证任务" note={`${data.tasks.length} 个任务`} className="master-panel">
          <div className="task-list">
            {data.tasks.map((task) => (
              <button key={task.task_id} className={task.task_id === selectedId ? "active" : ""} onClick={() => setSelectedId(task.task_id)}>
                <div><strong>{task.task_name}</strong><StatusTag value={task.status} /></div>
                <span className="mono-text">{task.capsule_id}</span>
                <small>{task.current_stage}<ChevronRight size={14} /></small>
              </button>
            ))}
          </div>
        </Surface>
        {selected ? (
          <div className="detail-stack">
              <Surface
              title={selected.task_name}
              note={`${selected.trade_batch_no} · ${selected.period_start} 至 ${selected.period_end}`}
              actions={canRun && selected.status !== "AUDITED" ? <Button icon={Play} variant="primary" busy={running} onClick={runWorkflow}>开始验证</Button> : <StatusTag value={selected.status} />}
            >
              <div className="capsule-banner">
                <div><ShieldCheck size={25} /><span>任务编号</span><strong>{selected.capsule_id}</strong></div>
                <div><span>使用规则</span><CodeValue>{shortHash(selected.rule_id, 14)}</CodeValue></div>
                <div><span>风险等级</span><StatusTag value={selected.risk_level} /></div>
              </div>
              <div className="stage-track">
                {stages.map(([code, label], index) => {
                  const current = stages.findIndex(([value]) => value === selected.status);
                  const done = index <= current;
                  return <div key={code} className={done ? "done" : ""}>{done ? <CheckCircle2 size={19} /> : <Circle size={19} />}<span>{label}</span>{index < stages.length - 1 && <i />}</div>;
                })}
              </div>
            </Surface>
            <div className="content-grid two-equal">
              <Surface title="参与主体">
                <div className="participant-list">
                  {selected.participants.map((item: JsonRecord) => {
                    const org = data.orgs.find((entry) => entry.org_id === item.org_id);
                    return <div key={item.participant_id}><Users size={18} /><div><strong>{org?.org_name || item.org_id}</strong><span>{ROLE_IN_TASK_LABELS[item.role_in_task] || item.role_in_task}</span></div><StatusTag value={item.data_status} /></div>;
                  })}
                </div>
              </Surface>
              <Surface title="处理结果">
                <div className="artifact-stats">
                  <div><Bot size={19} /><span>调用过程</span><strong>{selected.agent_event_count}</strong></div>
                  <div><ShieldCheck size={19} /><span>可核验证据</span><strong>{selected.evidence_count}</strong></div>
                  <div><CheckCircle2 size={19} /><span>最小结果</span><strong>{selected.result_count}</strong></div>
                </div>
              </Surface>
            </div>
            {selected.scenario_coordination?.length > 0 && (
              <Surface title="场景验证结果">
                <div className="scenario-result-grid">
                  {selected.scenario_coordination.map((item: JsonRecord, index: number) => (
                    <div key={item.code}>
                      <span>0{index + 1}</span>
                      <div><strong>{item.name}</strong><small>{item.metric}</small></div>
                      <StatusTag value={item.status} />
                      <CodeValue title={item.artifact}>{shortHash(item.artifact, 8)}</CodeValue>
                    </div>
                  ))}
                </div>
              </Surface>
            )}
          </div>
        ) : <Surface><div className="empty-state">请选择场景验证任务</div></Surface>}
      </div>
      {showForm && <TaskForm rules={data.rules} orgs={data.orgs} onClose={() => setShowForm(false)} onCreated={async () => { setShowForm(false); await reload(); }} />}
      {showImport && <ImportSettlementModal onClose={() => setShowImport(false)} onCreated={async (result) => { setShowImport(false); setMessage(`文件已导入并完成可信调用验证，生成 ${result.evidence?.length || 0} 项可核验证据。`); await reload(); }} />}
    </>
  );
}

function ImportSettlementModal({ onClose, onCreated }: { onClose: () => void; onCreated: (result: JsonRecord) => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [fixture, setFixture] = useState<JsonRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<JsonRecord | null>(null);

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] || null;
    setFile(selected);
    setFixture(null);
    setResult(null);
    setError("");
    if (!selected) return;
    if (!selected.name.toLowerCase().endsWith(".json")) {
      setError("请选择 JSON 文件");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result));
        if (!parsed?.batch?.trade_batch_no || !Array.isArray(parsed?.data_assets) || !parsed?.business_validation_request) {
          throw new Error("文件缺少批次、数据资产或验证任务信息");
        }
        setFixture(parsed);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "文件格式无法识别");
      }
    };
    reader.onerror = () => setError("文件读取失败");
    reader.readAsText(selected, "utf-8");
  }

  async function submit() {
    if (!fixture) return;
    setBusy(true);
    setError("");
    try {
      const response = await post<JsonRecord>("/settlement/import-and-run", fixture);
      setResult(response);
      await onCreated(response);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入验证失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="导入文件并自动验证" onClose={onClose} footer={<><Button onClick={onClose}>关闭</Button><Button icon={Play} variant="primary" busy={busy} disabled={!fixture || Boolean(result)} onClick={submit}>开始验证</Button></>}>
      <label className="import-dropzone">
        <input type="file" accept="application/json,.json" onChange={selectFile} />
        <Upload size={24} />
        <strong>{file ? file.name : "选择 JSON 文件"}</strong>
        <span>支持真实场景或虚拟仿真 JSON，导入后自动完成来源校验、数据登记、签名、隐私计算和审计回执。</span>
      </label>
      {fixture && <div className="import-preview"><div><span>数据批次</span><strong>{fixture.batch.trade_batch_no}</strong></div><div><span>数据资产</span><strong>{fixture.data_assets.length} 类</strong></div><div><span>参与主体</span><strong>{fixture.business_validation_request.participants?.length || 0} 方</strong></div></div>}
      {result && <Notice tone="success">文件已导入，可信调用验证已完成。生成 {result.evidence?.length || 0} 项可核验证据。</Notice>}
      {error && <Notice tone="warning">{error}</Notice>}
    </Modal>
  );
}

function TaskForm({ rules, orgs, onClose, onCreated }: { rules: JsonRecord[]; orgs: JsonRecord[]; onClose: () => void; onCreated: () => Promise<void> }) {
  const activeRules = rules.filter((item) => item.status === "ACTIVE");
  const generator = orgs.find((item) => item.org_type === "GENERATOR");
  const retailer = orgs.find((item) => item.org_type === "RETAILER");
  const [name, setName] = useState("2026年7月可信调用验证");
  const [batch, setBatch] = useState("TB-2026-07-DEMO");
  const [ruleId, setRuleId] = useState(activeRules[0]?.rule_id || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const formReady = name.trim().length >= 2 && batch.trim().length >= 3 && Boolean(ruleId && generator?.org_id && retailer?.org_id);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await post("/settlement/tasks", {
        task_name: name,
        trade_batch_no: batch,
        period_start: "2026-07-01",
        period_end: "2026-07-31",
        rule_id: ruleId,
        participants: [
          { org_id: generator?.org_id, role_in_task: "GENERATOR" },
          { org_id: retailer?.org_id, role_in_task: "RETAILER" },
        ],
      });
      await onCreated();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="新建可信调用任务" onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button icon={ShieldCheck} variant="primary" busy={busy} disabled={!formReady} onClick={submit}>创建任务</Button></>}>
      <div className="form-grid two">
        <Field label="任务名称"><input value={name} onChange={(event) => setName(event.target.value)} /></Field>
        <Field label="验证批次"><input value={batch} onChange={(event) => setBatch(event.target.value)} /></Field>
        <Field label="启用规则版本"><select value={ruleId} onChange={(event) => setRuleId(event.target.value)}>{activeRules.map((item) => <option key={item.rule_id} value={item.rule_id}>{item.rule_version} · {item.rule_name}</option>)}</select></Field>
        <Field label="验证周期"><input value="2026-07-01 至 2026-07-31" disabled /></Field>
      </div>
      <div className="participant-preview">
        <div><span>发电企业</span><strong>{generator?.org_name || "未配置"}</strong></div>
        <div><span>售电企业</span><strong>{retailer?.org_name || "未配置"}</strong></div>
      </div>
      {error && <Notice tone="warning">{error}</Notice>}
    </Modal>
  );
}
