import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Check, ChevronRight, CornerDownLeft, FileSearch, Send, ShieldCheck, X } from "lucide-react";
import { useLocation } from "react-router-dom";
import { ApiError, createIdempotencyKey, prepareIdempotencyKey, type IdempotencyKeyRecord } from "../../../api";
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogTitle, IconButton, Input, RemoteState } from "./ui-primitives";
import { createAssistantSession, loadAssistantMessages, loadAssistantPlans, loadAssistantTools, postAssistantMessage, runAssistantPlanAction, type AssistantMessage, type AssistantPlan, type AssistantSession, type AssistantTool } from "../trusted-space-api";
import { isLatestRun, resolveOnce, retryTransient } from "../assistant-state";
import { ACTION_LABELS, labelForCode } from "../../../types";
import { capabilityLabel } from "../trusted-space-labels";

const SHORTCUTS = [
  { label: "检查资产完整性", icon: FileSearch },
  { label: "查询授权申请状态", icon: ShieldCheck },
  { label: "检查TTC状态", icon: ChevronRight },
  { label: "核验证据摘要", icon: ShieldCheck },
  { label: "解释审计报告", icon: FileSearch },
] as const;

function entityContext(pathname: string) {
  const parts = pathname.split("/").filter(Boolean);
  const trustedIndex = parts.indexOf("trusted-space");
  if (trustedIndex < 0) return {};
  const segment = parts[trustedIndex + 1];
  const id = parts[trustedIndex + 2];
  if (!segment || !id || segment === "audit" && parts[trustedIndex + 2] !== "tasks") return { page_path: pathname };
  if (segment === "audit" && parts[trustedIndex + 3]) return { page_path: pathname, entity_type: "settlement_task", entity_id: parts[trustedIndex + 3] };
  const entityType = ({ assets: "data_asset", apply: "data_asset", authorizations: "data_usage_request", contracts: "data_contract", ttc: "settlement_task", mpc: "privacy_compute_job", results: "settlement_result" } as Record<string, string>)[segment];
  return entityType ? { page_path: pathname, entity_type: entityType, entity_id: decodeURIComponent(id) } : { page_path: pathname };
}

function capabilityTone(value?: string) {
  if (value === "LOCAL_REAL_DETERMINISTIC" || value === "LOCAL_REAL") return "success" as const;
  if (value === "BLOCKED" || value === "PENDING_REVIEW") return "warning" as const;
  return "info" as const;
}

export function AgentSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const location = useLocation();
  const [session, setSession] = useState<AssistantSession | null>(null);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [plans, setPlans] = useState<AssistantPlan[]>([]);
  const [tools, setTools] = useState<AssistantTool[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [bootNonce, setBootNonce] = useState(0);
  const idempotencyKeys = useRef<Record<string, IdempotencyKeyRecord>>({});
  const sessionKey = useRef(createIdempotencyKey("assistant-session"));
  const sessionRef = useRef<AssistantSession | null>(null);
  const sessionPromiseRef = useRef<Promise<AssistantSession> | null>(null);
  const latestRunRef = useRef(0);
  const context = useMemo(() => entityContext(location.pathname), [location.pathname]);
  const latestPlan = plans[0];

  async function refreshSession(sessionId: string, isActive: () => boolean = () => true) {
    const [messagePayload, planPayload, toolPayload] = await Promise.all([
      loadAssistantMessages(sessionId),
      loadAssistantPlans(sessionId),
      loadAssistantTools(),
    ]);
    if (!isActive()) return;
    setSession(messagePayload.session);
    sessionRef.current = messagePayload.session;
    setMessages(messagePayload.items);
    setPlans(planPayload.items);
    setTools(toolPayload.items);
  }

  useEffect(() => {
    if (!open) return undefined;
    let active = true;
    const runId = latestRunRef.current + 1;
    latestRunRef.current = runId;
    const isActive = () => isLatestRun(active, runId, latestRunRef.current);
    void (async () => {
      if (isActive()) {
        setLoading(true);
        setError("");
      }
      try {
        const current = sessionRef.current || await resolveOnce(
          sessionRef,
          sessionPromiseRef,
          () => retryTransient(
            () => createAssistantSession(context, { idempotencyKey: sessionKey.current }),
          ),
        );
        if (isActive()) setSession(current);
        await refreshSession(current.session_id, isActive);
      } catch (reason) {
        if (isActive()) {
          const diagnostic = reason instanceof ApiError
            ? reason.message
            : reason instanceof Error
              ? `智能助手会话加载失败（${reason.name}: ${reason.message.slice(0, 120)}），请重试。`
              : "智能助手会话加载失败，请重试。";
          setError(diagnostic);
        }
      } finally {
        if (isActive()) setLoading(false);
      }
    })();
    return () => { active = false; };
    // The mounted shell keeps the session when the sheet is closed and reopened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bootNonce, open]);

  async function send(content = message) {
    if (!session || !content.trim() || busy) return;
    setBusy(true);
    setError("");
    const text = content.trim();
    const fingerprint = `${session.session_id}:${session.state_version}:${text}`;
    const key = prepareIdempotencyKey(idempotencyKeys.current[fingerprint], "assistant-message", fingerprint);
    idempotencyKeys.current[fingerprint] = key;
    try {
      await postAssistantMessage(session.session_id, text, { ifMatch: `"${session.state_version}"`, idempotencyKey: key.key });
      setMessage("");
      sessionRef.current = session;
      await refreshSession(session.session_id);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "智能助手指令未记录，请重试。");
    } finally {
      setBusy(false);
    }
  }

  async function runPlanAction(plan: AssistantPlan, action: "execute" | "cancel" | "retry") {
    if (!session || !plan.allowed_actions?.includes(action) || busy) return;
    setBusy(true);
    setError("");
    const fingerprint = `${session.session_id}:${plan.plan_id}:${plan.state_version}:${action}`;
    const key = prepareIdempotencyKey(idempotencyKeys.current[fingerprint], `assistant-${action}`, fingerprint);
    idempotencyKeys.current[fingerprint] = key;
    try {
      await runAssistantPlanAction(session.session_id, plan.plan_id, action, { ifMatch: `"${plan.state_version}"`, idempotencyKey: key.key }, plan.steps[0]?.step_id);
      sessionRef.current = session;
      await refreshSession(session.session_id);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "智能助手计划动作失败，请刷新后重试。");
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="energy-agent-sheet">
      <div className="energy-agent-heading"><div className="energy-agent-title"><span className="energy-agent-icon"><Bot size={17} /></span><div><DialogTitle>隐链智能助手</DialogTitle><DialogDescription>确定性本地规划器；写动作只进入人工复核</DialogDescription></div></div><IconButton label="关闭智能助手" onClick={() => onOpenChange(false)}><X size={16} /></IconButton></div>
      <div className="energy-agent-body">
        {loading && <RemoteState loading />}
        {error && <RemoteState error={error} onRetry={() => { setError(""); setSession(null); sessionRef.current = null; sessionPromiseRef.current = null; setBootNonce((value) => value + 1); }} />}
        {!loading && !error && <>
          <div className="energy-agent-message energy-agent-message-bot"><span className="energy-agent-avatar"><Bot size={14} /></span><div><p>我只会调用后端动作白名单中的真实查询或生成待复核计划，不会伪造执行结果。</p><small>会话主体：<code>{session?.entity_id || "当前登录主体"}</code></small></div></div>
          {messages.filter((item) => item.role === "USER").map((item) => <div className="energy-agent-message energy-agent-message-user" key={item.message_id}><span>{item.content}</span></div>)}
          {messages.filter((item) => item.role === "ASSISTANT").slice(-3).map((item) => <div className="energy-agent-message energy-agent-message-bot" key={item.message_id}><span className="energy-agent-avatar"><Bot size={14} /></span><div><p>{item.content}</p><small>{labelForCode(item.intent_code, "智能助手消息")} · {capabilityLabel(item.capability_state)}</small></div></div>)}
          {latestPlan && <section className="energy-agent-plan"><div className="energy-agent-section-heading"><div><span className="energy-section-kicker">本地计划</span><h3>真实计划 · {labelForCode(latestPlan.intent_code, "未登记意图")}</h3></div><Badge tone={capabilityTone(latestPlan.capability_state)} dot>{labelForCode(latestPlan.status, "未登记状态")}</Badge></div><ol>{latestPlan.steps.map((step) => <li key={step.step_id}><span className={step.status === "SUCCEEDED" ? "energy-plan-done" : ""}>{step.status === "SUCCEEDED" ? <Check size={13} /> : step.sequence_no}</span><span>{ACTION_LABELS[step.action_code] || labelForCode(step.action_code, "审计动作")} · {labelForCode(step.status, "未登记状态")}{step.request_id ? ` · ${step.request_id}` : ""}{step.output && Object.keys(step.output).length ? <small>{JSON.stringify(step.output)}</small> : null}</span></li>)}</ol><div className="energy-agent-plan-note"><ShieldCheck size={14} /><span>来源：<code>{labelForCode(latestPlan.source_of_truth, "智能助手规划器")}</code> · 能力：<code>{capabilityLabel(latestPlan.capability_state)}</code></span></div><div className="trusted-submit-actions">{latestPlan.allowed_actions?.includes("execute") && <Button variant="primary" size="sm" busy={busy} onClick={() => void runPlanAction(latestPlan, "execute")}>执行计划</Button>}{latestPlan.allowed_actions?.includes("cancel") && <Button variant="secondary" size="sm" disabled={busy} onClick={() => void runPlanAction(latestPlan, "cancel")}>取消计划</Button>}{latestPlan.allowed_actions?.includes("retry") && <Button variant="secondary" size="sm" disabled={busy} onClick={() => void runPlanAction(latestPlan, "retry")}>重试计划</Button>}</div></section>}
          <section className="energy-agent-shortcuts"><h3>常用指令</h3><div>{SHORTCUTS.map(({ icon: Icon, label }) => <button type="button" key={label} disabled={busy || !session} onClick={() => void send(label)}><Icon size={14} />{label}</button>)}</div></section>
          <section className="energy-agent-shortcuts"><h3>可用工具</h3><div>{tools.map((tool) => <span className="trusted-muted" key={tool.tool_code}>{tool.tool_name || labelForCode(tool.tool_code, "已登记工具")}</span>)}{!tools.length && <span className="trusted-muted">当前角色暂无登记工具</span>}</div></section>
        </>}
      </div>
      <div className="energy-agent-composer"><Input value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void send(); }} placeholder="输入受支持的本地查询或需求…" aria-label="输入智能助手指令" disabled={loading || Boolean(error) || !session} /><Button variant="primary" size="icon" busy={busy} disabled={!message.trim() || !session} onClick={() => void send()} aria-label="发送"><Send size={15} /></Button></div>
      <footer className="energy-agent-footer"><span><span className="energy-status-dot" />{capabilityLabel(session?.capability_state)}</span><span>{session?.state_version ? `会话 V${session.state_version}` : "会话未建立"}</span><CornerDownLeft size={13} /></footer>
    </DialogContent>
  </Dialog>;
}
