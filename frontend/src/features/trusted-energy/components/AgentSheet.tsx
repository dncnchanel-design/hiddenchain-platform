import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, ChevronRight, ClipboardList, CornerDownLeft, Database, FileSearch, FileText, Send, ShieldCheck, X } from "lucide-react";
import { useLocation } from "react-router-dom";
import { ApiError, createIdempotencyKey, prepareIdempotencyKey, type IdempotencyKeyRecord } from "../../../api";
import { Button, Dialog, DialogContent, DialogTitle, IconButton, Input, RemoteState } from "./ui-primitives";
import { createAssistantSession, loadAssistantMessages, loadAssistantPlans, loadAssistantTools, postAssistantMessage, runAssistantPlanAction, type AssistantMessage, type AssistantPlan, type AssistantSession, type AssistantTool } from "../trusted-space-api";
import { isLatestRun, resolveOnce, retryTransient, shouldAutoExecuteRead } from "../assistant-state";
import { ACTION_LABELS } from "../../../types";
import { capabilityLabel } from "../trusted-space-labels";
import { assistantContext, assistantContextKey, type AssistantContext } from "../assistant-context";
import { ElectricityChat } from "./ElectricityChat";
import { AssistantPlanView } from "./AssistantPlanView";

const SHORTCUTS = [
  { label: "我有哪些数据", icon: Database, action: "LIST_DATA_ASSETS" },
  { label: "我能用哪些数据", icon: ShieldCheck, action: "LIST_AUTHORIZED_DATA_ASSETS" },
  { label: "查看可见数据", icon: Database, action: "LIST_VISIBLE_DATA_ASSETS" },
  { label: "查看授权列表", icon: ShieldCheck, action: "LIST_AUTHORIZATIONS" },
  { label: "查看任务列表", icon: ClipboardList, action: "LIST_TASKS" },
  { label: "查看审计报告", icon: FileText, action: "LIST_AUDIT_REPORTS" },
  { label: "查看通知", icon: FileText, action: "LIST_NOTIFICATIONS" },
  { label: "系统运行情况", icon: ShieldCheck, action: "SYSTEM_OVERVIEW" },
  { label: "你能做什么", icon: Bot, action: "ASSISTANT_HELP" },
  { label: "检查资产完整性", icon: FileSearch, action: "CHECK_ASSET_INTEGRITY" },
  { label: "查询授权申请状态", icon: ShieldCheck, action: "QUERY_AUTHORIZATION_STATUS" },
  { label: "检查可信任务状态", icon: ChevronRight, action: "CHECK_TTC_STATUS" },
  { label: "核验证据摘要", icon: ShieldCheck, action: "VERIFY_EVIDENCE_SUMMARY" },
  { label: "解释审计报告", icon: FileSearch, action: "EXPLAIN_AUDIT" },
] as const;

const AGENT_NAV = [
  { label: "资产检查", icon: FileSearch, command: "检查资产完整性" },
  { label: "授权查询", icon: Database, command: "查询授权申请状态" },
  { label: "任务状态", icon: ClipboardList, command: "检查可信任务状态" },
  { label: "审计解释", icon: FileText, command: "解释审计报告" },
  { label: "证据核验", icon: ShieldCheck, command: "核验证据摘要" },
] as const;

type AgentSheetProps = { open: boolean; onOpenChange: (open: boolean) => void; mode: "business" | "electricity"; onModeChange: (mode: "business" | "electricity") => void; operationsOnly?: boolean };

export function AgentSheet(props: AgentSheetProps) {
  const location = useLocation();
  const context = useMemo(() => assistantContext(location.pathname, location.search), [location.pathname, location.search]);
  // A different page/selection owns separate refs and pending requests. Closing
  // and reopening the same page retains its session; old-page responses cannot
  // populate the newly selected business object.
  return <AgentSessionSheet key={assistantContextKey(context)} {...props} context={context} />;
}

function AgentSessionSheet({ open, onOpenChange, mode, onModeChange: setMode, context, operationsOnly = false }: AgentSheetProps & { context: AssistantContext }) {
  const [session, setSession] = useState<AssistantSession | null>(null);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [plans, setPlans] = useState<AssistantPlan[]>([]);
  const [tools, setTools] = useState<AssistantTool[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [bootNonce, setBootNonce] = useState(0);
  const [electricityQuestion, setElectricityQuestion] = useState("");
  const idempotencyKeys = useRef<Record<string, IdempotencyKeyRecord>>({});
  const sessionKey = useRef(createIdempotencyKey("assistant-session"));
  const sessionRef = useRef<AssistantSession | null>(null);
  const sessionPromiseRef = useRef<Promise<AssistantSession> | null>(null);
  const latestRunRef = useRef(0);
  const latestPlan = plans[0];
  const supportedActions = new Set(tools.filter((tool) => tool.enabled).flatMap((tool) => tool.assistant_actions));
  const electricityOpen = mode === "electricity" && !operationsOnly;
  const agentNav = AGENT_NAV.filter((item) => supportedActions.has(SHORTCUTS.find((shortcut) => shortcut.label === item.command)?.action || ""));

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
    // Consume only the submitted draft now; a later reply must not erase the
    // next question the user types while this request is in flight.
    setMessage((draft) => draft.trim() === text ? "" : draft);
    const fingerprint = `${session.session_id}:${session.state_version}:${text}`;
    const key = prepareIdempotencyKey(idempotencyKeys.current[fingerprint], "assistant-message", fingerprint);
    idempotencyKeys.current[fingerprint] = key;
    try {
      const response = await postAssistantMessage(session.session_id, text, { ifMatch: `"${session.state_version}"`, idempotencyKey: key.key });
      sessionRef.current = response.session;
      setSession(response.session);
      if (shouldAutoExecuteRead(response.plan) && response.plan) {
        await runAssistantPlanAction(session.session_id, response.plan.plan_id, "execute", { ifMatch: `"${response.plan.state_version}"`, idempotencyKey: createIdempotencyKey("assistant-read") }, response.plan.steps[0].step_id);
      }
      await refreshSession(session.session_id);
    } catch (reason) {
      if (message.trim() === text) setMessage((draft) => draft || message);
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
    <DialogContent className={`trusted-space-shell energy-agent-sheet${electricityOpen ? " energy-agent-sheet-electricity" : ""}`}>
      <div className="energy-agent-heading"><div className="energy-agent-title"><span className="energy-agent-icon"><Bot size={17} /></span><div><DialogTitle>隐链智能助手</DialogTitle></div></div><IconButton label="关闭智能助手" onClick={() => onOpenChange(false)}><X size={16} /></IconButton></div>
      <div className="energy-agent-modes" role="group" aria-label="选择助手窗口"><Button variant="ghost" aria-pressed={!electricityOpen} onClick={() => setMode("business")}>{operationsOnly ? "运维助手" : "业务助手"}</Button>{!operationsOnly && <Button variant="ghost" aria-pressed={electricityOpen} onClick={() => setMode("electricity")}>电力交易计算</Button>}</div>
      {electricityOpen ? <ElectricityChat initialQuestion={electricityQuestion} onFinish={() => onOpenChange(false)} /> : <>
      <div className="energy-agent-body">
        {loading && <RemoteState loading />}
        {error && <RemoteState error={error} onRetry={() => { setError(""); setSession(null); sessionRef.current = null; sessionPromiseRef.current = null; setBootNonce((value) => value + 1); }} />}
        {!loading && !error && <>
          <div className="energy-agent-message energy-agent-message-bot"><span className="energy-agent-avatar"><Bot size={14} /></span><div><p>{operationsOnly ? "可以帮你查看平台服务状态、组织与身份登记数量。选择下方指令，或直接告诉我你想查什么。" : "可以帮你查看本方数据、查询授权和任务进度。选择下方指令，或直接告诉我你想查什么。"}</p></div></div>
          {messages.slice(-8).map((item) => item.role === "USER"
            ? <div className="energy-agent-message energy-agent-message-user" key={item.message_id}><span>{item.content}</span></div>
            : <div className="energy-agent-message energy-agent-message-bot" key={item.message_id}><span className="energy-agent-avatar"><Bot size={14} /></span><div><p>{item.intent_code === "UNKNOWN_INTENT" ? "还没识别出要处理的内容。可以试试“你能做什么”，或选择下方常用指令。" : item.content}</p></div></div>)}
          {latestPlan && <AssistantPlanView plan={latestPlan} busy={busy} onAction={(action) => void runPlanAction(latestPlan, action)} onNavigate={() => onOpenChange(false)} onSuggest={(content) => void send(content)} onOpenElectricity={operationsOnly ? undefined : (question) => { setElectricityQuestion(question); setMode("electricity"); }} />}
          <section className="energy-agent-shortcuts"><h3>常用指令</h3><div>{SHORTCUTS.filter((item) => supportedActions.has(item.action)).map(({ icon: Icon, label }) => <button type="button" key={label} disabled={busy || !session} aria-busy={busy || undefined} onClick={() => send(label)}><Icon size={14} />{label}</button>)}</div></section>
          <section className="energy-agent-shortcuts"><h3>可用工具</h3><div>{tools.filter((tool) => tool.enabled && tool.assistant_actions.length > 0).map((tool) => <span className="trusted-muted" key={tool.tool_code}>{tool.assistant_actions.map((action) => ACTION_LABELS[action] || "受控查询").join("、")}</span>)}{!supportedActions.size && <span className="trusted-muted">当前角色暂无可用查询工具</span>}</div></section>
        </>}
      </div>
      <div className="energy-agent-composer"><Input value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.nativeEvent.isComposing) void send(); }} placeholder={operationsOnly ? "输入想了解的平台运行情况" : "输入想查询的数据、授权或任务"} aria-label="输入智能助手指令" disabled={loading || Boolean(error) || !session} /><Button variant="primary" size="icon" busy={busy} disabled={!message.trim() || !session} onClick={() => send()} aria-label="发送"><Send size={15} aria-hidden="true" /></Button></div>
      {agentNav.length > 0 && <nav className="energy-agent-nav" aria-label="助手快捷入口">
        {agentNav.map(({ label, icon: Icon, command }) => <button type="button" key={label} disabled={busy || !session} aria-busy={busy || undefined} onClick={() => send(command)}><Icon size={14} /><span>{label}</span></button>)}
      </nav>}
      <footer className="energy-agent-footer"><span><span className="energy-status-dot" />{capabilityLabel(session?.capability_state)}</span><span>{session?.state_version ? `会话 V${session.state_version}` : "会话未建立"}</span><CornerDownLeft size={13} /></footer>
      </>}
    </DialogContent>
  </Dialog>;
}
