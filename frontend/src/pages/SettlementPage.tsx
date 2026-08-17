import { useMemo, useState, type ChangeEvent } from "react";
import { CheckCircle2, Circle, FileJson, Play, Plus, RefreshCw, ShieldCheck, Upload, Users, Workflow } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api, post } from "../api";
import { useAuth } from "../auth";
import { Button, ConfirmDialog, DataTable, DateTimeText, EmptyState, ErrorState, Field, IdText, LoadingState, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { ROLE_IN_TASK_LABELS, type JsonRecord } from "../types";

const stages = [
  ["DRAFT", "待开始"],
  ["AUTHORIZED", "已授权"],
  ["COMPUTING", "计算中"],
  ["EVIDENCED", "已生成凭证"],
  ["AUDITED", "已完成"],
] as const;

export function SettlementPage() {
  const { session } = useAuth();
  const [searchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState(searchParams.get("task") || "");
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [confirmRun, setConfirmRun] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState("");
  const role = session!.user.role_code;
  const loader = async (signal?: AbortSignal) => {
    const request = { signal, timeoutMs: 12000, cache: "no-store" as RequestCache };
    const [tasks, rules, orgs] = await Promise.all([
      api<JsonRecord[]>("/settlement/tasks", request),
      ["EXCHANGE", "REGULATOR", "ADMIN"].includes(role) ? api<JsonRecord[]>("/rules", request) : Promise.resolve([]),
      api<JsonRecord[]>("/system/organizations", request),
    ]);
    return { tasks, rules, orgs };
  };
  const { data, loading, refreshing, error, reload } = useRemote(loader, [role]);

  const effectiveSelectedId = data?.tasks.some((item) => item.task_id === selectedId) ? selectedId : data?.tasks[0]?.task_id || "";
  const selected = useMemo(() => data?.tasks.find((item) => item.task_id === effectiveSelectedId) || null, [data, effectiveSelectedId]);
  const canRun = ["EXCHANGE", "ADMIN"].includes(role);
  const canCreate = role === "EXCHANGE";
  const canImport = ["EXCHANGE", "ADMIN"].includes(role);

  async function runWorkflow() {
    if (!selected) return;
    setRunning(true);
    setMessage("");
    try {
      const result = await post<JsonRecord>(`/settlement/tasks/${selected.task_id}/run`, {});
      const conclusion = result.report?.conclusion === "PASS" ? "通过" : result.report?.conclusion === "REVIEW_REQUIRED" ? "需复核" : result.report?.conclusion || "已生成";
      setMessage(`验证已完成，生成 ${result.evidence?.length ?? 0} 项审计凭证，审计结论为${conclusion}。`);
      await reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "执行失败");
    } finally {
      setRunning(false);
    }
  }

  if (loading) return <LoadingState label="正在加载验证任务" variant="page" />;
  if (error || !data) return <ErrorState message={error || "调用验证加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader title="调用验证" description="创建或导入验证任务，执行受控计算，并查看任务阶段、参与主体与证据产物。" actions={<><Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>{canImport && <Button icon={FileJson} variant="primary" onClick={() => setShowImport(true)}>导入验证文件</Button>}{canCreate && <Button icon={Plus} onClick={() => setShowForm(true)}>新建任务</Button>}</>} />
      {message && <Notice tone={message.includes("失败") || message.includes("缺少") || message.includes("需复核") ? "warning" : "success"}>{message}</Notice>}

      <Surface title="验证任务" meta={`${data.tasks.length} 项`}>
        <DataTable
          keyField="task_id" rows={data.tasks} empty="暂无验证任务" label="调用验证任务列表"
          columns={[
            { key: "task_name", label: "任务名称", minWidth: 190, render: (row) => <button type="button" className="table-link" aria-current={row.task_id === effectiveSelectedId ? "true" : undefined} onClick={() => setSelectedId(row.task_id)}>{row.task_name || "—"}</button> },
            { key: "capsule_id", label: "任务编号", minWidth: 160, render: (row) => <IdText value={row.capsule_id} /> },
            { key: "trade_batch_no", label: "批次编号", minWidth: 145, render: (row) => <IdText value={row.trade_batch_no} length={8} /> },
            { key: "current_stage", label: "当前阶段", minWidth: 130 },
            { key: "risk_level", label: "风险等级", render: (row) => <StatusTag value={row.risk_level} /> },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "created_at", label: "创建时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
            { key: "action", label: "操作", sortable: false, hideable: false, sticky: "right", render: (row) => <Button onClick={() => setSelectedId(row.task_id)}>查看详情</Button> },
          ]}
        />
      </Surface>

      {selected ? <div className="detail-stack">
        <Surface
          title={selected.task_name}
          meta={`${selected.trade_batch_no || "—"} · ${selected.period_start || "—"} 至 ${selected.period_end || "—"}`}
          actions={canRun && selected.status !== "AUDITED" ? <Button icon={Play} variant="primary" busy={running} onClick={() => setConfirmRun(true)}>开始验证</Button> : <StatusTag value={selected.status} />}
        >
          <div className="capsule-banner">
            <div><ShieldCheck size={23} /><span>任务编号</span><IdText value={selected.capsule_id} /></div>
            <div><span>使用规则</span><IdText value={selected.rule_id} /></div>
            <div><span>风险等级</span><StatusTag value={selected.risk_level} /></div>
          </div>
          <div className="stage-track" aria-label="任务处理阶段">
            {stages.map(([code, label], index) => {
              const current = stages.findIndex(([value]) => value === selected.status);
              const done = index <= current;
              return <div key={code} className={done ? "done" : ""}>{done ? <CheckCircle2 size={18} /> : <Circle size={18} />}<span>{label}</span>{index < stages.length - 1 && <i />}</div>;
            })}
          </div>
        </Surface>

        <div className="content-grid two-equal">
          <Surface title="参与主体">
            <div className="participant-list">
              {(selected.participants || []).map((item: JsonRecord) => {
                const org = data.orgs.find((entry) => entry.org_id === item.org_id);
                return <div key={item.participant_id || `${item.org_id}-${item.role_in_task}`}><Users size={18} /><div><strong>{org?.org_name || item.org_id || "—"}</strong><span>{ROLE_IN_TASK_LABELS[item.role_in_task] || item.role_in_task || "—"}</span></div><StatusTag value={item.data_status} /></div>;
              })}
              {!selected.participants?.length && <EmptyState title="暂无参与主体" />}
            </div>
          </Surface>
          <Surface title="处理产物">
            <div className="artifact-stats">
              <div><Workflow size={19} /><span>过程记录</span><strong>{selected.agent_event_count ?? 0}</strong></div>
              <div><ShieldCheck size={19} /><span>审计凭证</span><strong>{selected.evidence_count ?? 0}</strong></div>
              <div><CheckCircle2 size={19} /><span>结果回执</span><strong>{selected.result_count ?? 0}</strong></div>
            </div>
          </Surface>
        </div>

        {selected.scenario_coordination?.length > 0 && <Surface title="场景验证结果">
          <div className="scenario-result-grid">{selected.scenario_coordination.map((item: JsonRecord, index: number) => <div key={item.code || index}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{item.name || "—"}</strong><small>{item.metric || "—"}</small></div><StatusTag value={item.status} /><IdText value={item.artifact} /></div>)}</div>
        </Surface>}
      </div> : <Surface><EmptyState title="请选择验证任务" /></Surface>}

      {showForm && <TaskForm rules={data.rules} orgs={data.orgs} onClose={() => setShowForm(false)} onCreated={async (created) => { setShowForm(false); setMessage("任务已创建。"); await reload(); if (created?.task_id) setSelectedId(created.task_id); }} />}
      {showImport && <ImportSettlementModal onClose={() => setShowImport(false)} onCreated={async (result) => { setShowImport(false); setMessage(`文件已导入，生成 ${result.evidence?.length ?? 0} 项审计凭证。`); await reload(); }} />}
      <ConfirmDialog
        open={confirmRun} title="执行调用验证" objectName={selected?.task_name || selected?.task_id || "—"} currentState={selected?.status}
        consequence="执行将调用当前任务绑定的数据引用和授权规则，生成计算结果、审计凭证及过程记录。请确认批次与规则版本无误。"
        confirmLabel="确认执行" busy={running} onCancel={() => setConfirmRun(false)} onConfirm={async () => { await runWorkflow(); setConfirmRun(false); }}
      />
    </>
  );
}

function ImportSettlementModal({ onClose, onCreated }: { onClose: () => void; onCreated: (result: JsonRecord) => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [fixture, setFixture] = useState<JsonRecord | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] || null;
    setFile(selected);
    setFixture(null);
    setError("");
    if (!selected) return;
    if (!selected.name.toLowerCase().endsWith(".json") || selected.type && selected.type !== "application/json") {
      setError("请选择 JSON 文件。");
      return;
    }
    if (selected.size > 2 * 1024 * 1024) {
      setError("文件大小不能超过 2 MB。");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result));
        if (!parsed?.batch?.trade_batch_no || !Array.isArray(parsed?.data_assets) || !parsed?.business_validation_request) throw new Error("文件缺少批次、数据资产或验证任务信息。");
        setFixture(parsed);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "文件格式无法识别。");
      }
    };
    reader.onerror = () => setError("文件读取失败。");
    reader.readAsText(selected, "utf-8");
  }

  async function submit() {
    if (!fixture) return;
    setBusy(true);
    setError("");
    try {
      const response = await post<JsonRecord>("/settlement/import-and-run", fixture);
      await onCreated(response);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入验证失败");
    } finally {
      setBusy(false);
    }
  }

  return <>
    <Modal title="导入验证文件" onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button icon={Play} variant="primary" disabled={!fixture} onClick={() => setConfirmOpen(true)}>复核并执行</Button></>}>
      <label className="import-dropzone"><input type="file" accept="application/json,.json" onChange={selectFile} /><Upload size={24} /><strong>{file ? file.name : "选择 JSON 文件"}</strong><span>仅支持不超过 2 MB 的 JSON 文件</span></label>
      {fixture && <div className="import-preview"><div><span>数据批次</span><strong>{fixture.batch.trade_batch_no}</strong></div><div><span>数据资产</span><strong>{fixture.data_assets.length} 类</strong></div><div><span>参与主体</span><strong>{fixture.business_validation_request.participants?.length ?? 0} 方</strong></div></div>}
      {error && <Notice tone="warning">{error}</Notice>}
    </Modal>
    <ConfirmDialog
      open={confirmOpen} title="导入并执行验证" objectName={file?.name || "—"} currentState="文件已解析"
      consequence="系统将按文件中的批次、数据资产、参与主体与验证请求创建任务并立即执行。执行后会生成过程记录和审计凭证。"
      confirmLabel="确认导入并执行" busy={busy} onCancel={() => setConfirmOpen(false)} onConfirm={submit}
    />
  </>;
}

function TaskForm({ rules, orgs, onClose, onCreated }: { rules: JsonRecord[]; orgs: JsonRecord[]; onClose: () => void; onCreated: (created?: JsonRecord) => Promise<void> }) {
  const activeRules = rules.filter((item) => item.status === "ACTIVE");
  const generators = orgs.filter((item) => item.org_type === "GENERATOR");
  const retailers = orgs.filter((item) => item.org_type === "RETAILER");
  const [name, setName] = useState("");
  const [batch, setBatch] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [ruleId, setRuleId] = useState("");
  const [generatorId, setGeneratorId] = useState("");
  const [retailerId, setRetailerId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const formReady = name.trim().length >= 2 && batch.trim().length >= 3 && Boolean(ruleId && generatorId && retailerId && periodStart && periodEnd) && periodStart <= periodEnd;

  async function submit() {
    setBusy(true);
    setError("");
    try {
      const created = await post<JsonRecord>("/settlement/tasks", {
        task_name: name.trim(), trade_batch_no: batch.trim(), period_start: periodStart, period_end: periodEnd, rule_id: ruleId,
        participants: [{ org_id: generatorId, role_in_task: "GENERATOR" }, { org_id: retailerId, role_in_task: "RETAILER" }],
      });
      await onCreated(created);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="新建调用验证任务" onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button icon={ShieldCheck} variant="primary" busy={busy} disabled={!formReady} onClick={submit}>创建任务</Button></>}>
      {!activeRules.length && <Notice tone="warning">当前没有可用的启用规则，暂不能创建任务。</Notice>}
      <div className="form-grid two">
        <Field label="任务名称"><input value={name} onChange={(event) => setName(event.target.value)} /></Field>
        <Field label="验证批次"><input value={batch} onChange={(event) => setBatch(event.target.value)} /></Field>
        <Field label="周期开始"><input type="date" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} /></Field>
        <Field label="周期结束" error={periodStart && periodEnd && periodStart > periodEnd ? "结束日期不能早于开始日期" : undefined}><input type="date" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} /></Field>
        <Field label="启用规则版本"><select value={ruleId} onChange={(event) => setRuleId(event.target.value)}><option value="">请选择</option>{activeRules.map((item) => <option key={item.rule_id} value={item.rule_id}>{item.rule_version} · {item.rule_name}</option>)}</select></Field>
        <Field label="发电企业"><select value={generatorId} onChange={(event) => setGeneratorId(event.target.value)}><option value="">请选择</option>{generators.map((item) => <option key={item.org_id} value={item.org_id}>{item.org_name}</option>)}</select></Field>
        <Field label="售电企业"><select value={retailerId} onChange={(event) => setRetailerId(event.target.value)}><option value="">请选择</option>{retailers.map((item) => <option key={item.org_id} value={item.org_id}>{item.org_name}</option>)}</select></Field>
      </div>
      {error && <Notice tone="warning">{error}</Notice>}
    </Modal>
  );
}
