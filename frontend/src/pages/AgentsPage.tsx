import { useMemo, useState } from "react";
import { Eye, Play, RefreshCw, Workflow } from "lucide-react";
import { api, post } from "../api";
import { Button, ConfirmDialog, DataTable, DateTimeText, DetailDrawer, ErrorState, FilterBar, IdText, LoadingState, Metric, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { AGENT_LABELS, MESSAGE_TYPE_LABELS, SCENARIO_LABELS, TOOL_LABELS, labelForCode, type JsonRecord } from "../types";

type AgentResults = Record<string, JsonRecord>;

function capabilityName(value: unknown) {
  return String(value || "").replace(/\s*Agent\b/gi, "服务").replace(/智能体/g, "能力服务");
}

export function AgentsPage() {
  const [taskId, setTaskId] = useState("");
  const [results, setResults] = useState<AgentResults>({});
  const [selectedResult, setSelectedResult] = useState<{ agent: JsonRecord; result: JsonRecord } | null>(null);
  const [runningCode, setRunningCode] = useState("");
  const [batchRunning, setBatchRunning] = useState(false);
  const [confirmBatch, setConfirmBatch] = useState(false);
  const [actionError, setActionError] = useState("");
  const loader = async (signal?: AbortSignal) => {
    const request = { signal, timeoutMs: 12000, cache: "no-store" as RequestCache };
    const [definitions, events, tasks, serviceStatus] = await Promise.all([
      api<JsonRecord[]>("/agents/definitions", request),
      api<JsonRecord[]>("/agents/events", request),
      api<JsonRecord[]>("/settlement/tasks", request),
      api<JsonRecord>("/agents/llm/status", request),
    ]);
    return { definitions, events, tasks, serviceStatus };
  };
  const { data, loading, refreshing, error, reload } = useRemote(loader, []);
  const effectiveTaskId = taskId;
  const events = useMemo(() => effectiveTaskId ? data?.events.filter((item) => item.task_id === effectiveTaskId) || [] : [], [data, effectiveTaskId]);
  const selectedTask = data?.tasks.find((item) => item.task_id === effectiveTaskId);

  async function invokeOne(agent: JsonRecord) {
    if (!effectiveTaskId) return;
    setRunningCode(agent.code);
    setActionError("");
    try {
      const result = await post<JsonRecord>(`/agents/${agent.code}/invoke`, { task_id: effectiveTaskId, instruction: agent.default_instruction });
      setResults((current) => ({ ...current, [agent.code]: result }));
      setSelectedResult({ agent, result });
      await reload();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : `${capabilityName(agent.name)}执行失败`);
    } finally {
      setRunningCode("");
    }
  }

  async function invokeAll() {
    if (!effectiveTaskId) return;
    setBatchRunning(true);
    setActionError("");
    try {
      const batch = await post<JsonRecord>("/agents/invoke-all", { task_id: effectiveTaskId });
      const next: AgentResults = {};
      (batch.results || []).forEach((item: JsonRecord) => { next[item.agent_code] = item; });
      setResults(next);
      if (!batch.all_succeeded) setActionError(`已完成 ${batch.success_count}/${batch.expected_count} 项能力调用，请查看失败结果。`);
      await reload();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "能力链执行失败");
    } finally {
      setBatchRunning(false);
    }
  }

  if (loading) return <LoadingState label="正在加载能力与服务" variant="page" />;
  if (error || !data) return <ErrorState message={error || "能力与服务加载失败"} retry={reload} />;

  const serviceReady = data.serviceStatus.live_verified ? "SUCCESS" : data.serviceStatus.configured ? "PENDING" : "FAILED";
  return (
    <>
      <PageHeader title="能力与服务" description="管理受控能力定义、任务级调用与过程事件；调用指令由服务端固定配置。" actions={<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>} />
      <div className="metrics-grid three">
        <Metric label="已登记能力" value={data.definitions.length} />
        <Metric label="当前任务事件" value={events.length} />
        <Metric label="解释服务" value={<StatusTag value={serviceReady} label={data.serviceStatus.live_verified ? "最近核验成功" : data.serviceStatus.configured ? "已配置" : "未配置"} />} />
      </div>

      <FilterBar actions={<Button icon={Workflow} variant="primary" busy={batchRunning} disabled={!effectiveTaskId || Boolean(runningCode)} onClick={() => setConfirmBatch(true)}>运行任务能力链</Button>}>
        <label><span>关联任务</span><select value={effectiveTaskId} onChange={(event) => { setTaskId(event.target.value); setResults({}); }}><option value="">请选择</option>{data.tasks.map((item) => <option key={item.task_id} value={item.task_id}>{labelForCode(item.capsule_id, "已登记任务")} · {item.task_name}</option>)}</select></label>
      </FilterBar>
      {!effectiveTaskId && <Notice tone="info">请先选择一个真实任务；未选择任务时不会执行能力服务或展示其他任务事件。</Notice>}
      {actionError && <Notice tone="warning">{actionError}</Notice>}

      <Surface title="能力服务目录" meta={`${data.definitions.length} 项`}>
        <DataTable
          keyField="code" rows={data.definitions} label="能力服务目录"
          columns={[
            { key: "name", label: "能力服务", minWidth: 170, render: (row) => AGENT_LABELS[row.code] || capabilityName(row.name) || labelForCode(row.code, "已登记能力") },
            { key: "scenario_code", label: "业务场景", minWidth: 150, render: (row) => SCENARIO_LABELS[row.scenario_code] || labelForCode(row.scenario_code, "已登记场景") },
            { key: "input", label: "输入", minWidth: 170, render: (row) => labelForCode(row.input, "已登记输入") },
            { key: "output", label: "输出", minWidth: 170, render: (row) => labelForCode(row.output, "已登记输出") },
            { key: "tools", label: "受控工具", align: "right", render: (row) => `${row.tools?.length ?? 0} 项` },
            { key: "status", label: "状态", render: (row) => <StatusTag value={results[row.code]?.success === false ? "FAILED" : results[row.code] ? "SUCCESS" : "ACTIVE"} label={results[row.code]?.success === false ? "调用失败" : results[row.code] ? "本次已完成" : "已登记"} /> },
            { key: "action", label: "操作", sortable: false, hideable: false, sticky: "right", render: (row) => <div className="inline-actions"><Button icon={Play} variant="primary" busy={runningCode === row.code} disabled={!effectiveTaskId || batchRunning || Boolean(runningCode && runningCode !== row.code)} onClick={() => invokeOne(row)}>运行</Button>{results[row.code] && <Button icon={Eye} onClick={() => setSelectedResult({ agent: row, result: results[row.code] })}>结果</Button>}</div> },
          ]}
        />
      </Surface>

      <Surface title="能力事件" meta={`${events.length} 条`}>
        <DataTable
          keyField="event_id" rows={events} empty="当前任务暂无能力事件" label="能力事件列表"
          columns={[
            { key: "sequence_no", label: "序号", align: "right", render: (row) => row.sequence_no === undefined ? "—" : String(row.sequence_no).padStart(2, "0") },
            { key: "agent_code", label: "能力服务", minWidth: 150, render: (row) => capabilityName(AGENT_LABELS[row.agent_code] || row.agent_code) },
            { key: "message_type", label: "事件类型", minWidth: 140, render: (row) => MESSAGE_TYPE_LABELS[row.message_type] || labelForCode(row.message_type, "已登记事件") },
            { key: "tool_name", label: "受控工具", minWidth: 140, render: (row) => TOOL_LABELS[row.tool_name] || labelForCode(row.tool_name, "已登记工具") },
            { key: "input_hash", label: "输入摘要", minWidth: 150, render: (row) => <IdText value={row.input_hash} /> },
            { key: "output_hash", label: "输出摘要", minWidth: 150, render: (row) => <IdText value={row.output_hash} /> },
            { key: "signed_call", label: "签名记录", render: (row) => row.signed_call ? <StatusTag value="CONFIRMED" label="已记录" /> : "—" },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "created_at", label: "时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
          ]}
        />
      </Surface>

      {selectedResult && <DetailDrawer title={`${capabilityName(selectedResult.agent.name)}调用结果`} onClose={() => setSelectedResult(null)} footer={<Button onClick={() => setSelectedResult(null)}>关闭</Button>}>
        <div className="detail-grid"><div><span>能力服务</span><strong>{AGENT_LABELS[selectedResult.agent.code] || capabilityName(selectedResult.agent.name)}</strong></div><div><span>业务场景</span><strong>{SCENARIO_LABELS[selectedResult.agent.scenario_code] || labelForCode(selectedResult.agent.scenario_code, "已登记场景")}</strong></div><div><span>调用状态</span><StatusTag value={selectedResult.result.success === false ? "FAILED" : "SUCCESS"} /></div><div><span>请求编号</span><IdText value={selectedResult.result.request_id} /></div></div>
        {selectedResult.result.summary && <div className="detail-section"><h3>执行摘要</h3><p>{selectedResult.result.summary}</p></div>}
        {(selectedResult.result.findings || []).length > 0 && <div className="detail-section"><h3>检查结果</h3><ul className="finding-list">{selectedResult.result.findings.map((finding: JsonRecord, index: number) => <li key={`${finding.title}-${index}`}><strong>{finding.title}</strong><span>{finding.detail}</span></li>)}</ul></div>}
        {selectedResult.result.recommended_next_action && <div className="detail-section"><h3>建议动作</h3><p>{selectedResult.result.recommended_next_action}</p></div>}
        <details className="secondary-details"><summary>服务技术信息</summary><div className="detail-grid"><div><span>能力标识</span><IdText value={selectedResult.agent.did} /></div><div><span>处理耗时</span><strong>{selectedResult.result.duration_ms === undefined ? "—" : `${selectedResult.result.duration_ms} 毫秒`}</strong></div><div><span>受控工具</span><strong>{(selectedResult.agent.tools || []).map((tool: string) => TOOL_LABELS[tool] || labelForCode(tool, "已登记工具")).join("、") || "—"}</strong></div></div></details>
      </DetailDrawer>}

      <ConfirmDialog
        open={confirmBatch} title="运行任务能力链" objectName={selectedTask?.task_name || selectedTask?.task_id || "—"} currentState={selectedTask?.status}
        consequence="系统将按既定顺序调用该任务的全部受控能力，并追加过程事件与调用回执。"
        confirmLabel="确认运行" busy={batchRunning} onCancel={() => setConfirmBatch(false)} onConfirm={async () => { await invokeAll(); setConfirmBatch(false); }}
      />
    </>
  );
}
