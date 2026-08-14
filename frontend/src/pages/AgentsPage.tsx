import { useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, KeyRound, Play, RefreshCw, ShieldCheck, Workflow, Wrench } from "lucide-react";
import { api, formatDate, post, shortHash } from "../api";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { AGENT_LABELS, MESSAGE_TYPE_LABELS, SCENARIO_LABELS, TOOL_LABELS } from "../types";
import type { JsonRecord } from "../types";

type AgentResults = Record<string, JsonRecord>;

function displayCapabilityName(value: unknown) {
  return String(value || "").replace(/\s*Agent\b/gi, "模块").replace(/智能体/g, "能力模块");
}

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
      setActionError(reason instanceof Error ? reason.message : `${agent.name} 执行失败`);
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
      if (!batch.all_succeeded) setActionError(`仅完成 ${batch.success_count}/${batch.expected_count} 个能力模块，请查看异常卡片。`);
      await reload();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "能力模块执行失败");
    } finally {
      setBatchRunning(false);
    }
  }

  if (loading) return <LoadingState label="正在加载受控能力" />;
  if (error || !data) return <ErrorState message={error || "受控能力加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader eyebrow="安全运营" title="能力编排" description="按任务启用受控能力模块；解释服务只提供辅助信息，最终结果仍由确定性规则与审计链负责。" actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>} />
      <div className="agent-boundary"><ShieldCheck size={20} /><div><strong>安全边界</strong><span>只读取授权摘要，不接触业务原始数据；每次执行都保留输入、输出和签名痕迹。</span></div></div>
      <Surface title="服务状态" note="能力模块可以使用本地确定性逻辑，也可以调用已配置的解释服务。">
        <div className="llm-status-panel">
          <StatusTag value={data.llmStatus.configured ? "SUCCESS" : "FAILED"} label={data.llmStatus.configured ? "解释服务已配置" : "解释服务未配置"} />
          <strong>{data.llmStatus.live_verified ? "受控解释服务 · 已连接" : data.llmStatus.configured ? "受控解释服务 · 已配置" : "受控解释服务 · 未配置"}</strong>
          <span>可用能力：{data.llmStatus.supported_agent_count} 项</span>
          <span>{data.llmStatus.live_verified ? "服务可用" : "等待配置"}</span>
          {data.llmStatus.last_success && <CodeValue title={data.llmStatus.last_success.request_id}>最近回执 {shortHash(data.llmStatus.last_success.request_id, 12)} · {data.llmStatus.last_success.duration_ms}ms</CodeValue>}
        </div>
        <div className="agent-run-toolbar">
          <label><span>任务选择</span><select value={taskId} onChange={(event) => { setTaskId(event.target.value); setResults({}); }}>{data.tasks.map((item) => <option key={item.task_id} value={item.task_id}>{item.capsule_id} · {item.task_name}</option>)}</select></label>
          <Button icon={Workflow} variant="primary" busy={batchRunning} disabled={!taskId || Boolean(runningCode)} onClick={invokeAll}>运行全部模块</Button>
        </div>
        {actionError && <Notice tone="warning">{actionError}</Notice>}
      </Surface>
      <Surface title="执行链路" note="模块按顺序留下可核验事件，运行结束后回到任务回执。">
        <div className="agent-workflow">
          {data.definitions.map((agent, index) => <div className="agent-node" key={agent.code}><div><Workflow size={20} /><span>{index + 1}</span></div><strong>{displayCapabilityName(agent.name)}</strong><small>{SCENARIO_LABELS[agent.scenario_code] || agent.scenario_code}</small>{index < data.definitions.length - 1 && <ArrowRight size={18} />}</div>)}
        </div>
      </Surface>
      <div className="agent-grid">
        {data.definitions.map((agent) => {
          const result = results[agent.code];
          return (
            <article className={`agent-card ${result?.success === false ? "agent-card-failed" : result ? "agent-card-verified" : ""}`} key={agent.code}>
              <div className="agent-card-header"><div><Workflow size={20} /><strong>{displayCapabilityName(agent.name)}</strong></div><StatusTag value={result?.success === false ? "FAILED" : result ? "SUCCESS" : "VALID"} label={result?.success === false ? "执行失败" : result ? "已核验" : "DID 有效"} /></div>
              <CodeValue title={agent.did}>{shortHash(agent.did, 16)}</CodeValue>
              <div className="agent-mandate"><span>{SCENARIO_LABELS[agent.scenario_code] || agent.scenario_code}</span>{agent.business_mandate}</div>
              <dl><dt>输入</dt><dd>{agent.input}</dd><dt>输出</dt><dd>{agent.output}</dd></dl>
              <div className="tool-list"><Wrench size={15} />{agent.tools.map((tool: string) => <span key={tool}>{TOOL_LABELS[tool] || tool}</span>)}</div>
              <label className="agent-instruction-label"><span>执行备注（可选）</span><textarea className="agent-instruction" rows={3} maxLength={500} value={instructions[agent.code] || ""} onChange={(event) => setInstructions((current) => ({ ...current, [agent.code]: event.target.value }))} /></label>
              <Button icon={Play} variant="primary" busy={runningCode === agent.code} disabled={!taskId || batchRunning || Boolean(runningCode && runningCode !== agent.code)} onClick={() => invokeOne(agent)}>运行</Button>
              {result?.success === false && <div className="agent-call-error">{result.error}</div>}
              {result && result.success !== false && <div className="agent-call-result">
                <div><CheckCircle2 size={16} /><strong>复核完成</strong></div>
                <p>{result.summary}</p>
                {(result.findings || []).map((finding: JsonRecord, index: number) => <small key={`${finding.title}-${index}`}><b>{finding.title}</b>：{finding.detail}</small>)}
                {result.recommended_next_action && <small><b>下一步</b>：{result.recommended_next_action}</small>}
                <div className="llm-proof-row"><span>{result.model}</span><span>{result.duration_ms}ms</span><span>Token {result.usage?.total_tokens ?? "-"}</span><CodeValue title={result.request_id}>{shortHash(result.request_id, 12)}</CodeValue></div>
              </div>}
            </article>
          );
        })}
      </div>
      <Surface title="能力事件" note="按任务筛选每个模块的输入哈希、输出哈希和签名状态。">
        <div className="filter-bar compact"><label><span>任务筛选</span><select value={taskId} onChange={(event) => setTaskId(event.target.value)}><option value="">全部任务</option>{data.tasks.map((item) => <option key={item.task_id} value={item.task_id}>{item.capsule_id}</option>)}</select></label></div>
        <DataTable
          keyField="event_id"
          rows={events}
          columns={[
            { key: "sequence_no", label: "序号", render: (row) => String(row.sequence_no).padStart(2, "0") },
            { key: "agent_code", label: "能力模块", render: (row) => displayCapabilityName(AGENT_LABELS[row.agent_code] || row.agent_code) },
            { key: "message_type", label: "事件类型", render: (row) => MESSAGE_TYPE_LABELS[row.message_type] || row.message_type },
            { key: "tool_name", label: "受控工具" },
            { key: "provider", label: "来源", render: (row) => row.details_json?.request_id ? `${row.details_json.model} · ${row.details_json.duration_ms}ms` : "本地确定性事件" },
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
