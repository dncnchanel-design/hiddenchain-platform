import { useEffect, useMemo, useState } from "react";
import { Bot, CalendarDays, CheckCircle2, ChevronRight, Circle, Play, Plus, RefreshCw, ShieldCheck, Users } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api, formatDate, post, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, CodeValue, DataTable, ErrorState, Field, LoadingState, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { ROLE_IN_TASK_LABELS } from "../types";
import type { JsonRecord } from "../types";

const stages = [
  ["DRAFT", "任务组织"],
  ["AUTHORIZED", "身份与授权"],
  ["COMPUTING", "隐私计算"],
  ["EVIDENCED", "可信存证"],
  ["AUDITED", "监管审计"],
];

export function SettlementPage() {
  const { session } = useAuth();
  const [searchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState(searchParams.get("task") || "");
  const [showForm, setShowForm] = useState(false);
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

  async function runWorkflow() {
    if (!selected) return;
    setRunning(true);
    setMessage("");
    try {
      const result = await post<JsonRecord>(`/settlement/tasks/${selected.task_id}/run`, { compute_mode: "MPC_MOCK", algorithm_code: "ADAPTIVE_MARKET_SETTLEMENT_V2" });
      const conclusion = result.report?.conclusion === "PASS" ? "通过" : result.report?.conclusion === "REVIEW_REQUIRED" ? "需复核" : result.report?.conclusion || "已生成";
      setMessage(`可信闭环完成：${result.evidence.length} 项链上证据、${result.task.agent_event_count} 条 Agent 事件，审计结论${conclusion}。`);
      await reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "执行失败");
    } finally {
      setRunning(false);
    }
  }

  if (loading) return <LoadingState label="正在装载场景验证任务" />;
  if (error || !data) return <ErrorState message={error || "场景验证任务加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader eyebrow="应用验证场景" title="场景验证任务" description="选择一个任务，查看数据调用、隐私计算、结果回执和证据核验进度；电力交易只是当前演示场景。" actions={<><Button icon={RefreshCw} onClick={reload}>刷新</Button>{canCreate && <Button icon={Plus} variant="primary" onClick={() => setShowForm(true)}>发起场景验证</Button>}</>} />
      {message && <Notice tone={message.includes("失败") || message.includes("缺少") ? "warning" : "success"}>{message}</Notice>}
      <div className="master-detail">
        <Surface title="验证任务队列" note={`${data.tasks.length} 个可信验证胶囊`} className="master-panel">
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
              actions={canRun && selected.status !== "AUDITED" ? <Button icon={Play} variant="primary" busy={running} onClick={runWorkflow}>启动场景验证</Button> : <StatusTag value={selected.status} />}
            >
              <div className="capsule-banner">
                <div><ShieldCheck size={25} /><span>可信验证胶囊</span><strong>{selected.capsule_id}</strong></div>
                <div><span>RuleHash</span><CodeValue>{shortHash(selected.rule_id, 14)}</CodeValue></div>
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
              <Surface title="参与主体" note="DID/VC 与任务角色绑定">
                <div className="participant-list">
                  {selected.participants.map((item: JsonRecord) => {
                    const org = data.orgs.find((entry) => entry.org_id === item.org_id);
                    return <div key={item.participant_id}><Users size={18} /><div><strong>{org?.org_name || item.org_id}</strong><span>{ROLE_IN_TASK_LABELS[item.role_in_task] || item.role_in_task}</span></div><StatusTag value={item.data_status} /></div>;
                  })}
                </div>
              </Surface>
              <Surface title="过程产物" note="每一项均可通过胶囊编号关联">
                <div className="artifact-stats">
                  <div><Bot size={19} /><span>Agent 签名事件</span><strong>{selected.agent_event_count}</strong></div>
                  <div><ShieldCheck size={19} /><span>链上证据索引</span><strong>{selected.evidence_count}</strong></div>
                  <div><CheckCircle2 size={19} /><span>结算结果</span><strong>{selected.result_count}</strong></div>
                </div>
              </Surface>
            </div>
            {selected.scenario_coordination?.length > 0 && (
              <Surface title="四场景耦合结果" note="交易偏差先由虚拟电厂资源响应，剩余偏差通过调度安全闸门后方可结算">
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
    </>
  );
}

function TaskForm({ rules, orgs, onClose, onCreated }: { rules: JsonRecord[]; orgs: JsonRecord[]; onClose: () => void; onCreated: () => Promise<void> }) {
  const activeRules = rules.filter((item) => item.status === "ACTIVE");
  const generator = orgs.find((item) => item.org_type === "GENERATOR");
  const retailer = orgs.find((item) => item.org_type === "RETAILER");
  const [name, setName] = useState("2026年7月电力交易场景验证");
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
    <Modal title="发起场景验证任务" onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button icon={ShieldCheck} variant="primary" busy={busy} disabled={!formReady} onClick={submit}>生成可信验证胶囊</Button></>}>
      <div className="form-grid two">
        <Field label="任务名称"><input value={name} onChange={(event) => setName(event.target.value)} /></Field>
        <Field label="验证批次"><input value={batch} onChange={(event) => setBatch(event.target.value)} /></Field>
        <Field label="启用规则版本"><select value={ruleId} onChange={(event) => setRuleId(event.target.value)}>{activeRules.map((item) => <option key={item.rule_id} value={item.rule_id}>{item.rule_version} · {item.rule_name}</option>)}</select></Field>
        <Field label="结算周期"><input value="2026-07-01 至 2026-07-31" disabled /></Field>
      </div>
      <div className="participant-preview">
        <div><span>发电企业</span><strong>{generator?.org_name || "未配置"}</strong></div>
        <div><span>售电企业</span><strong>{retailer?.org_name || "未配置"}</strong></div>
      </div>
      <Notice>创建阶段只组织验证上下文；启动后依次执行身份认证、数据调用授权、隐私策略路由、MPC 计算、结果回执、存证与审计。</Notice>
      {error && <Notice tone="warning">{error}</Notice>}
    </Modal>
  );
}
