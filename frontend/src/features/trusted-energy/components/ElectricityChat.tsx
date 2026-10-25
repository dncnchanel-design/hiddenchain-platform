import { useEffect, useRef, useState } from "react";
import { BookOpen, Bot, Calculator, Check, CheckCircle2, ChevronRight, Download, FileText, FolderOpen, MessageSquarePlus, Send } from "lucide-react";
import { ApiError, createIdempotencyKey } from "../../../api";
import { useAuth } from "../../../auth";
import { createAssistantSession } from "../trusted-space-api";
import { calculateElectricity, formatElectricityValue as numberLabel, loadElectricityCases, loadElectricityCatalog, loadElectricityHistory, prepareElectricityCalculation, saveElectricityCase, type ElectricityCatalog, type ElectricityRecord, type ElectricityScenario } from "../electricity-api";
import { Badge, Button, Input, RemoteState } from "./ui-primitives";
import "./electricity-chat.css";

function downloadResult(record: ElectricityRecord) {
  if (!record.result) return;
  const rows = [["计算项目", "计算过程", "结果", "单位"], ...record.result.steps.map((step) => [step.label, step.expression, step.value, step.unit]), ["计算口径", record.scope], ["规则版本", record.rule_version], ["计算记录", record.id], ["结果摘要", record.result.result_hash]];
  const csv = "\uFEFF" + rows.map((row) => row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `电力计算结果-${record.id.slice(0, 8)}.csv`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function CalculationCard({ record, scenario, busy, onCalculate, onSave, onContinue, onFinish }: { record: ElectricityRecord; scenario: ElectricityScenario; busy: boolean; onCalculate: (values: Record<string, string>) => void; onSave: () => void; onContinue: () => void; onFinish: () => void }) {
  const [values, setValues] = useState(record.parameters);
  const [confirmed, setConfirmed] = useState(false);
  const [saveDismissed, setSaveDismissed] = useState(false);
  const complete = record.status === "SUCCEEDED";
  const missing = scenario.fields.filter((field) => !values[field.key]?.trim());
  const invalid = scenario.fields.some((field) => {
    const value = values[field.key]?.trim() || "";
    return !/^[-+]?\d{1,13}(?:\.\d{1,6})?$/.test(value) || Number(value) < Number(field.min) || Number(value) > Number(field.max);
  });

  return <article className="electricity-turn">
    <div className="electricity-user-message">{record.question}</div>
    <div className="electricity-agent-reply">
      <span className="electricity-avatar"><Bot size={18} aria-hidden="true" /></span>
      <div className="electricity-reply-content">
        <div className="electricity-reply-heading"><strong>{record.title}</strong><Badge tone={complete ? "success" : "warning"}>{complete ? "计算完成" : "待确认数据"}</Badge></div>
        <details className="electricity-details" open={!complete}>
          <summary><BookOpen size={15} />政策依据与计算公式<ChevronRight size={14} /></summary>
          <div className="electricity-sources">{record.sources.map((source) => <a href={source.url} target="_blank" rel="noreferrer" key={source.url}><FileText size={14} /><span>{source.title}<small>{source.reference}</small></span></a>)}</div>
          <ol className="electricity-formulas">{record.formulas.map((formula) => <li key={formula}>{formula}</li>)}</ol>
        </details>
        {!complete && <form onSubmit={(event) => { event.preventDefault(); if (confirmed && !invalid && !busy) onCalculate(values); }}>
          <h3 className="electricity-section-title"><Calculator size={15} />确认计算数据<span>{scenario.fields.length - missing.length}/{scenario.fields.length} 项已填写</span></h3>
          {record.warnings.length > 0 && <div className="electricity-warning" role="status">{record.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
          <div className="electricity-fields">{scenario.fields.map((field) => <label key={field.key} htmlFor={`${record.id}-${field.key}`}><span>{field.label}<small>{field.unit}</small></span><Input id={`${record.id}-${field.key}`} inputMode="decimal" value={values[field.key] || ""} onChange={(event) => { setValues((current) => ({ ...current, [field.key]: event.target.value })); setConfirmed(false); }} placeholder="待补充" disabled={busy} required maxLength={22} title={`${field.min} 至 ${field.max}；${record.origins[field.key] || "未识别到，请手动填写"}`} /><small className="electricity-origin">{values[field.key] !== record.parameters[field.key] ? "手动填写" : record.origins[field.key]?.startsWith("沿用") ? "沿用上次参数" : record.origins[field.key] ? "来自本次输入" : "请填写后确认"}</small></label>)}</div>
          <label className="electricity-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={busy || invalid} /><span>我已核对以上数据、单位和计算公式</span></label>
          <div className="electricity-form-actions"><Button type="submit" variant="primary" busy={busy} disabled={!confirmed || invalid}><Calculator size={15} />确认数据并计算</Button><small>{missing.length ? `还需补充 ${missing.length} 项数据` : invalid ? "请检查数值范围及小数位数" : !confirmed ? "核对后勾选确认，即可计算" : "将按上方公式计算"}</small></div>
        </form>}
        {record.result && <>
          <details className="electricity-details" open>
            <summary><Calculator size={15} />逐步计算过程<ChevronRight size={14} /></summary>
            <ol className="electricity-calculation-steps">{record.result.steps.map((step) => <li key={step.key}><span>{step.label}</span><div><span>{step.expression} = </span><strong>{numberLabel(step.value)} <small>{step.unit}</small></strong></div></li>)}</ol>
          </details>
          <details className="electricity-details"><summary><CheckCircle2 size={15} />结果校验<ChevronRight size={14} /></summary><ul className="electricity-checks">{record.result.checks.map((check) => <li key={check}><Check size={14} />{check}</li>)}</ul></details>
          <section className="electricity-result"><h3><CheckCircle2 size={18} />计算结果</h3><dl>{record.result.summary.map((step) => <div key={step.key}><dt>{step.label}</dt><dd>{numberLabel(step.value)} <small>{step.unit}</small></dd></div>)}</dl></section>
          <div className="electricity-result-actions"><Button size="sm" onClick={() => downloadResult(record)}><Download size={14} />下载结果表</Button><Button size="sm" variant="ghost" onClick={onContinue}>继续提问<ChevronRight size={14} /></Button><Button size="sm" variant="primary" onClick={onFinish}>完成</Button></div>
          {record.saved ? <p className="electricity-saved" role="status"><CheckCircle2 size={15} />已保存到我的案例，可在案例库中复用</p> : !saveDismissed ? <div className="electricity-save-prompt"><span>将本次输入、公式和结果保存为案例？</span><div><Button size="sm" variant="primary" disabled={busy} onClick={onSave}>保存案例</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setSaveDismissed(true)}>暂不保存</Button></div></div> : <Button variant="link" size="sm" disabled={busy} onClick={onSave}>保存本次案例</Button>}
        </>}
      </div>
    </div>
  </article>;
}

export function ElectricityChat({ onFinish, initialQuestion = "" }: { onFinish: () => void; initialQuestion?: string }) {
  const { session: auth } = useAuth();
  const storageKey = `electricity-chat:${auth?.user.user_id || "anonymous"}`;
  const sessionId = useRef(sessionStorage.getItem(storageKey) || "");
  const sessionKey = useRef(createIdempotencyKey("electricity-session"));
  const sessionPromise = useRef<Promise<string> | null>(null);
  const commandLock = useRef(false);
  const keys = useRef<Record<string, string>>({});
  const [catalog, setCatalog] = useState<ElectricityCatalog | null>(null);
  const [records, setRecords] = useState<ElectricityRecord[]>([]);
  const [cases, setCases] = useState<ElectricityRecord[]>([]);
  const [showCases, setShowCases] = useState(false);
  const [message, setMessage] = useState(initialQuestion);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [boot, setBoot] = useState(0);
  const composer = useRef<HTMLTextAreaElement>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      setLoading(true);
      setError("");
      try {
        const [definition, saved] = await Promise.all([loadElectricityCatalog(), loadElectricityCases()]);
        if (!sessionId.current) {
          sessionPromise.current ||= createAssistantSession({ page_path: "/trusted-space/assistant/electricity", entity_type: "electricity_calculation" }, { idempotencyKey: sessionKey.current }).then((created) => created.session_id).finally(() => { sessionPromise.current = null; });
          sessionId.current = await sessionPromise.current;
          sessionStorage.setItem(storageKey, sessionId.current);
        }
        const history = await loadElectricityHistory(sessionId.current);
        if (active) { setCatalog(definition); setCases(saved.items); setRecords(history.items); }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "计算窗口加载失败，请重试。");
        if (reason instanceof ApiError && reason.status === 404) { sessionId.current = ""; sessionStorage.removeItem(storageKey); }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [boot, storageKey]);

  useEffect(() => { bottom.current?.scrollIntoView({ block: "end" }); }, [records, loading, busy]);

  async function command(action: () => Promise<void>) {
    if (commandLock.current) return;
    commandLock.current = true;
    setBusy(true);
    setError("");
    try { await action(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "操作未完成，请重试。"); }
    finally { commandLock.current = false; setBusy(false); }
  }

  async function send(question = message, scenario?: string, baseId?: string) {
    if (!question.trim() || !sessionId.current || !catalog || loading) return;
    await command(async () => {
      const previous = [...records].reverse().find((record) => record.status === "SUCCEEDED");
      const basedOn = baseId || previous?.id;
      const fingerprint = JSON.stringify([sessionId.current, question, scenario, basedOn, records.at(-1)?.id]);
      keys.current[fingerprint] ||= createIdempotencyKey("electricity-prepare");
      const record = await prepareElectricityCalculation({ session_id: sessionId.current, question: question.trim(), scenario, based_on: basedOn }, { idempotencyKey: keys.current[fingerprint] });
      setRecords((current) => current.some((item) => item.id === record.id) ? current : [...current, record]);
      setMessage("");
      setShowCases(false);
    });
  }

  const updateRecord = (record: ElectricityRecord) => setRecords((current) => current.map((item) => item.id === record.id ? record : item));
  const focusComposer = () => { composer.current?.focus(); };

  return <div className="electricity-chat">
    <div className="electricity-toolbar"><div><span className="electricity-avatar"><Calculator size={19} aria-hidden="true" /></span><div><h2>电力交易计算智能体</h2><p>查依据 · 确认数据 · 逐步验算</p></div></div><div><Button size="sm" variant="ghost" disabled={loading || busy} onClick={() => setShowCases((value) => !value)} aria-expanded={showCases}><FolderOpen size={15} />我的案例{cases.length > 0 ? ` (${cases.length})` : ""}</Button><Button size="sm" variant="ghost" disabled={loading || busy} onClick={() => command(async () => { const created = await createAssistantSession({ entity_type: "electricity_calculation", page_path: "/trusted-space/assistant/electricity" }, { idempotencyKey: createIdempotencyKey("electricity-session") }); sessionId.current = created.session_id; sessionStorage.setItem(storageKey, created.session_id); setRecords([]); setMessage(""); setShowCases(false); focusComposer(); })}><MessageSquarePlus size={15} />新对话</Button></div></div>
    <div className="electricity-transcript" aria-label="电力计算对话">
      {loading && <RemoteState loading />}
      {showCases && <section className="electricity-case-library"><h3>我的案例</h3><p>仅当前账号可见；复用后需要重新确认数据。</p>{cases.length ? cases.map((record) => <div key={record.id}><div><strong>{record.title}</strong><small>{new Date(record.created_at + (record.created_at.endsWith("Z") ? "" : "Z")).toLocaleString("zh-CN", { timeZone: "Asia/Taipei" })}</small></div><Button size="sm" disabled={busy} onClick={() => send("复用已保存案例的参数，重新计算。", record.scenario, record.id)}>复用参数</Button></div>) : <p>还没有保存的案例。完成一次计算后即可保存。</p>}</section>}
      {!loading && catalog && !records.length && <section className="electricity-welcome"><span className="electricity-welcome-icon"><Calculator size={28} aria-hidden="true" /></span><h3>把交易参数交给我，<br />每一步计算都有据可查。</h3><p>输入电价、电量和成本参数，核对数据后开始计算。也可以先运行一个完整案例。</p><div className="electricity-examples">{catalog.scenarios.map((scenario) => <button key={scenario.id} disabled={busy} onClick={() => send(scenario.example, scenario.id)}><span><strong>{scenario.title}</strong><small>{scenario.id === "zhejiang_spot" ? "分区电价、机组电费与购电成本" : "固定与可变成本、单位成本与报价"}</small></span><ChevronRight size={18} /></button>)}</div></section>}
      {catalog && records.map((record) => { const scenario = catalog.scenarios.find((item) => item.id === record.scenario); return scenario ? <CalculationCard key={record.id} record={record} scenario={scenario} busy={busy} onContinue={focusComposer} onFinish={onFinish} onCalculate={(values) => command(async () => { updateRecord(await calculateElectricity(record, values)); })} onSave={() => command(async () => { const updated = await saveElectricityCase(record.id); updateRecord(updated); setCases((current) => [updated, ...current.filter((item) => item.id !== updated.id)]); })} /> : null; })}
      {busy && <p className="electricity-working" role="status"><span className="electricity-working-dot" />正在处理，请稍候…</p>}
      <div ref={bottom} />
    </div>
    {error && <div className="electricity-error" role="alert"><span>{error}</span>{!catalog && <Button size="sm" onClick={() => setBoot((value) => value + 1)}>重新加载</Button>}<Button variant="ghost" size="sm" onClick={() => setError("")}>关闭提示</Button></div>}
    <form className="electricity-composer" onSubmit={(event) => { event.preventDefault(); void send(); }}><label className="electricity-sr-only" htmlFor="electricity-question">输入电力交易问题或参数</label><textarea ref={composer} id="electricity-question" rows={3} maxLength={4000} value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} placeholder={records.some((record) => record.result) ? "继续提问，例如：把系统电价改为450元/MWh，重新计算" : "描述你的计算需求，或点击上方案例开始…"} disabled={loading || busy || !catalog} /><div><small>Enter 发送 · Shift + Enter 换行</small><Button type="submit" variant="primary" busy={busy} disabled={loading || !message.trim() || !catalog}><Send size={15} />发送</Button></div></form>
  </div>;
}
