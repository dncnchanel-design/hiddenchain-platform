import { useEffect, useMemo, useState } from "react";
import { ArrowRight, Bot, CheckCircle2, KeyRound, Play, RefreshCw, ShieldCheck, Sparkles, Wrench } from "lucide-react";
import { api, formatDate, post, shortHash } from "../api";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { AGENT_LABELS, MESSAGE_TYPE_LABELS, SCENARIO_LABELS, TOOL_LABELS } from "../types";
import type { JsonRecord } from "../types";

type AgentResults = Record<string, JsonRecord>;

export function AgentsPage() {
  const [taskId, setTaskId] = useState("");
  const [instructions, setInstructions] = useState<Record<string, string>>({});
  const [results, setResults] = useState<AgentResults>({});
  const [runningCode, setRunningCode] = useState("");
  const [batchRunning, setBatchRunning] = useState(false);
  const [actionError, setActionError] = useState("");
  const loader = async () => {
    const [definitions, events, tasks, llmStatus] = await Promise.all([
      api<JsonRecord[]>("/agents/definitions"),
      api<JsonRecord[]>("/agents/events"),
      api<JsonRecord[]>("/settlement/tasks"),
      api<JsonRecord>("/agents/llm/status"),
    ]);
    return { definitions, events, tasks, llmStatus };
  };
  const { data, loading, error, reload } = useRemote(loader, []);
  const events = useMemo(() => taskId ? data?.events.filter((item) => item.task_id === taskId) || [] : data?.events || [], [data, taskId]);

  useEffect(() => {
    if (!data) return;
    if (!taskId && data.tasks.length) setTaskId(data.tasks[0].task_id);
    setInstructions((current) => {
      const next = { ...current };
      data.definitions.forEach((agent) => {
        if (!next[agent.code]) next[agent.code] = agent.default_instruction;
      });
      return next;
    });
  }, [data, taskId]);

  async function invokeOne(agent: JsonRecord) {
    if (!taskId) return;
    setRunningCode(agent.code);
    setActionError("");
    try {
      const result = await post<JsonRecord>(`/agents/${agent.code}/invoke`, {
        task_id: taskId,
        instruction: instructions[agent.code] || agent.default_instruction,
      });
      setResults((current) => ({ ...current, [agent.code]: result }));
      await reload();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : `${agent.name}调用失败`);
    } finally {
      setRunningCode("");
    }
  }

  async function invokeAll() {
    if (!taskId) return;
    setBatchRunning(true);
    setActionError("");
    try {
      const batch = await post<JsonRecord>("/agents/invoke-all", { task_id: taskId });
      const next: AgentResults = {};
      (batch.results || []).forEach((item: JsonRecord) => { next[item.agent_code] = item; });
      setResults(next);
      if (!batch.all_succeeded) setActionError(`仅成功调用 ${batch.success_count}/${batch.expected_count} 个 Agent，请查看失败卡片。`);
      await reload();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "六Agent调用失败");
    } finally {
      setBatchRunning(false);
    }
  }

  if (loading) return <LoadingState label="正在装载 Agent 能力凭证" />;
  if (error || !data) return <ErrorState message={error || "Agent 数据加载失败"} retry={reload} />;

  return (
    <>
          <PageHeader eyebrow="智能体协作" title="智能体协同" description="平台智能体通过安全网关执行受授权任务，并保留请求凭证、耗时、用量与签名事件。" actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>} />
      <div className="agent-boundary"><ShieldCheck size={20} /><div><strong>三条强制边界</strong><span>不可直读原始数据 · 不可绕过 OPA/ODRL 策略 · 不可修改确定性结算结果</span></div></div>
      <Surface title="DeepSeek 运行状态" note="只有出现请求 ID、耗时和 Token 用量，才算真实调用成功">
        <div className="llm-status-panel">
          <StatusTag value={data.llmStatus.configured ? "SUCCESS" : "FAILED"} label={data.llmStatus.configured ? "DeepSeek 已配置" : "DeepSeek 未配置"} />
          <strong>{data.llmStatus.provider} · {data.llmStatus.model}</strong>
          <span>六 Agent：{data.llmStatus.supported_agent_count} 个</span>
          <span>{data.llmStatus.live_verified ? "已有真实调用凭证" : "尚未完成真实调用"}</span>
          {data.llmStatus.last_success && <CodeValue title={data.llmStatus.last_success.request_id}>{shortHash(data.llmStatus.last_success.request_id, 12)} · {data.llmStatus.last_success.duration_ms}ms</CodeValue>}
        </div>
        <div className="agent-run-toolbar">
          <label><span>调用任务</span><select value={taskId} onChange={(event) => { setTaskId(event.target.value); setResults({}); }}>{data.tasks.map((item) => <option key={item.task_id} value={item.task_id}>{item.capsule_id} · {item.task_name}</option>)}</select></label>
          <Button icon={Sparkles} variant="primary" busy={batchRunning} disabled={!taskId || Boolean(runningCode)} onClick={invokeAll}>依次真实调用六个 Agent</Button>
        </div>
        {actionError && <Notice tone="warning">{actionError}</Notice>}
      </Surface>
          <Surface title="智能体协作" note="每个智能体只执行受授权的任务，并留下可核验的输入输出摘要">
        <div className="agent-workflow">
          {data.definitions.map((agent, index) => <div className="agent-node" key={agent.code}><div><Bot size={20} /><span>{index + 1}</span></div><strong>{agent.name}</strong><small>{SCENARIO_LABELS[agent.scenario_code] || agent.scenario_code}</small>{index < data.definitions.length - 1 && <ArrowRight size={18} />}</div>)}
        </div>
      </Surface>
      <div className="agent-grid">
        {data.definitions.map((agent) => {
          const result = results[agent.code];
          return (
            <article className={`agent-card ${result?.success === false ? "agent-card-failed" : result ? "agent-card-verified" : ""}`} key={agent.code}>
              <div className="agent-card-header"><div><Bot size={20} /><strong>{agent.name}</strong></div><StatusTag value={result?.success === false ? "FAILED" : result ? "SUCCESS" : "VALID"} label={result?.success === false ? "调用失败" : result ? "AI 已验证" : "DID 有效"} /></div>
              <CodeValue title={agent.did}>{shortHash(agent.did, 16)}</CodeValue>
              <div className="agent-mandate"><span>{SCENARIO_LABELS[agent.scenario_code] || agent.scenario_code}</span>{agent.business_mandate}</div>
              <dl><dt>输入</dt><dd>{agent.input}</dd><dt>输出</dt><dd>{agent.output}</dd></dl>
              <div className="tool-list"><Wrench size={15} />{agent.tools.map((tool: string) => <span key={tool}>{TOOL_LABELS[tool] || tool}</span>)}</div>
              <textarea className="agent-instruction" rows={3} maxLength={500} value={instructions[agent.code] || ""} onChange={(event) => setInstructions((current) => ({ ...current, [agent.code]: event.target.value }))} />
              <Button icon={Play} variant="primary" busy={runningCode === agent.code} disabled={!taskId || batchRunning || Boolean(runningCode && runningCode !== agent.code)} onClick={() => invokeOne(agent)}>调用 DeepSeek</Button>
              {result?.success === false && <div className="agent-call-error">{result.error}</div>}
              {result && result.success !== false && <div className="agent-call-result">
                <div><CheckCircle2 size={16} /><strong>真实调用成功</strong></div>
                <p>{result.summary}</p>
                {(result.findings || []).map((finding: JsonRecord, index: number) => <small key={`${finding.title}-${index}`}><b>{finding.title}</b>：{finding.detail}</small>)}
                {result.recommended_next_action && <small><b>下一步</b>：{result.recommended_next_action}</small>}
                <div className="llm-proof-row"><span>{result.model}</span><span>{result.duration_ms}ms</span><span>Token {result.usage?.total_tokens ?? "-"}</span><CodeValue title={result.request_id}>{shortHash(result.request_id, 12)}</CodeValue></div>
              </div>}
            </article>
          );
        })}
      </div>
      <Surface title="签名调用事件" note="输入输出只存哈希；真实 AI 调用事件包含 DeepSeek 请求 ID、耗时和 Token 用量">
        <div className="filter-bar compact"><label><span>任务筛选</span><select value={taskId} onChange={(event) => setTaskId(event.target.value)}><option value="">全部任务</option>{data.tasks.map((item) => <option key={item.task_id} value={item.task_id}>{item.capsule_id}</option>)}</select></label></div>
        <DataTable
          keyField="event_id"
          rows={events}
          columns={[
            { key: "sequence_no", label: "序号", render: (row) => String(row.sequence_no).padStart(2, "0") },
            { key: "agent_code", label: "智能体", render: (row) => AGENT_LABELS[row.agent_code] || row.agent_code },
            { key: "message_type", label: "事件类型", render: (row) => MESSAGE_TYPE_LABELS[row.message_type] || row.message_type },
            { key: "tool_name", label: "受控工具" },
            { key: "provider", label: "AI凭证", render: (row) => row.details_json?.request_id ? <span className="verify-ok"><Sparkles size={14} />{row.details_json.model} · {row.details_json.duration_ms}ms</span> : "本地确定性事件" },
            { key: "input_hash", label: "输入哈希", render: (row) => <CodeValue title={row.input_hash}>{shortHash(row.input_hash)}</CodeValue> },
            { key: "output_hash", label: "输出哈希", render: (row) => <CodeValue title={row.output_hash}>{shortHash(row.output_hash)}</CodeValue> },
            { key: "signed_call", label: "签名调用", render: () => <span className="verify-ok"><KeyRound size={15} />有效</span> },
            { key: "created_at", label: "时间", render: (row) => formatDate(row.created_at) },
          ]}
        />
      </Surface>
    </>
  );
}
