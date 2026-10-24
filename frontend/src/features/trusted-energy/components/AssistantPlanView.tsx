import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { ACTION_LABELS, ASSET_TYPE_LABELS, labelForCode } from "../../../types";
import type { AssistantPlan, AssistantPlanStep } from "../trusted-space-api";
import { Badge, Button } from "./ui-primitives";

const TARGET_LINKS: Record<string, { path: string; label: string }> = {
  CHECK_ASSET_INTEGRITY: { path: "/trusted-space/catalog", label: "选择数据资产" },
  QUERY_AUTHORIZATION_STATUS: { path: "/trusted-space/authorizations", label: "选择授权申请" },
  CHECK_TTC_STATUS: { path: "/trusted-space/mpc", label: "选择计算任务" },
  VERIFY_EVIDENCE_SUMMARY: { path: "/trusted-space/ttc", label: "选择结算任务" },
  EXPLAIN_AUDIT: { path: "/trusted-space/ttc", label: "选择结算任务" },
};

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function needsAttention(step: AssistantPlanStep): boolean {
  const output = step.output || {};
  const integrity = record(output.integrity);
  return ["version_present", "passport_present", "quality_present"].some((key) => integrity[key] === false)
    || ["FAIL", "FAILED", "REJECT", "REJECTED", "BLOCKED"].includes(text(record(output.quality).decision))
    || (Array.isArray(output.items) && output.items.some((item) => record(record(item).verify).matched === false));
}

function ReadResult({ step, onNavigate }: { step: AssistantPlanStep; onNavigate: () => void }) {
  const output = step.output || {};
  if (step.action_code === "LIST_DATA_ASSETS") {
    const items = Array.isArray(output.items) ? output.items as Record<string, unknown>[] : [];
    return <div className="energy-agent-read-result" role="status">
      <p>{output.total ? `当前账号登记了 ${text(output.total)} 项本方数据。` : "当前账号尚未登记本方数据。"}</p>
      {items.length > 0 && <ul className="energy-agent-data-list">{items.map((item) => <li key={text(item.asset_id)}>
        <Link to={`/trusted-space/assets/${encodeURIComponent(text(item.asset_id))}`} onClick={onNavigate}>{text(item.asset_name)}</Link>
        <span>{ASSET_TYPE_LABELS[text(item.asset_type)] || "数据资源"}{typeof item.record_count === "number" ? ` · ${item.record_count.toLocaleString("zh-CN")} 条记录` : ""}</span>
        {item.period_start && item.period_end ? <span>{text(item.period_start)} 至 {text(item.period_end)}</span> : null}
      </li>)}</ul>}
      {output.has_more === true && <p>当前显示前 {items.length} 项，可打开数据目录继续查看。</p>}
      <Link to="/trusted-space/catalog" onClick={onNavigate}>打开数据目录</Link>
    </div>;
  }
  const fields = [["asset_name", "数据资产"], ["task_name", "任务名称"], ["status_value", "当前状态"], ["ttc_state", "任务阶段"], ["job_id", "计算编号"], ["task_id", "任务编号"], ["request_id", "申请编号"], ["contract_id", "合同编号"], ["audit_log_count", "审计日志数"], ["report_count", "审计报告数"], ["evidence_count", "证据数"]];
  return <div className="energy-agent-read-result" role="status">
    {typeof output.explanation === "string" && <p>{output.explanation}</p>}
    <dl>{fields.filter(([key]) => text(output[key])).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{labelForCode(text(output[key]), text(output[key]))}</dd></div>)}</dl>
    {step.action_code === "CHECK_ASSET_INTEGRITY" && <dl>{[["version_present", "数据版本"], ["passport_present", "资产护照"], ["quality_present", "质量记录"]].map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{record(output.integrity)[key] === true ? "已登记" : record(output.integrity)[key] === false ? "未登记" : "待核验"}</dd></div>)}{record(output.quality).decision ? <div><dt>质量判定</dt><dd>{labelForCode(text(record(output.quality).decision), text(record(output.quality).decision))}</dd></div> : null}</dl>}
    {step.action_code === "CHECK_ASSET_INTEGRITY" && <Link to={`/trusted-space/assets/${encodeURIComponent(text(output.asset_id))}`} onClick={onNavigate}>查看资产护照与完整性详情</Link>}
    {step.action_code === "VERIFY_EVIDENCE_SUMMARY" && Array.isArray(output.items) && <><p>证据摘要 {output.items.length} 条：{output.items.filter((item) => record(record(item).verify).matched === true).length} 条一致、{output.items.filter((item) => record(record(item).verify).matched === false).length} 条不一致、{output.items.filter((item) => typeof record(record(item).verify).matched !== "boolean").length} 条待核验。</p><Link to={`/trusted-space/ttc/${encodeURIComponent(text(output.task_id))}`} onClick={onNavigate}>查看关联结算任务</Link></>}
  </div>;
}

export function AssistantPlanView({ plan, busy, onAction, onNavigate, onSuggest }: {
  plan: AssistantPlan; busy: boolean;
  onAction: (action: "execute" | "cancel" | "retry") => void;
  onNavigate: () => void; onSuggest: (content: string) => void;
}) {
  const resultRef = useRef<HTMLElement>(null);
  useEffect(() => {
    resultRef.current?.scrollIntoView({ block: "nearest" });
  }, [plan.plan_id, plan.state_version]);
  const unknown = plan.intent_code === "UNKNOWN_INTENT";
  const step = plan.steps[0];
  const needsTarget = step?.error_code === "ASSISTANT_TARGET_REQUIRED" || step?.error_code === "ASSISTANT_TARGET_TYPE_MISMATCH";
  const targetLink = needsTarget ? TARGET_LINKS[plan.intent_code] : null;
  const attention = plan.steps.some(needsAttention);
  const review = plan.status === "PENDING_REVIEW" ? plan.steps.find((item) => item.output?.review_requested === true) : undefined;
  const status = unknown ? "换个说法试试" : needsTarget ? "待选择" : review ? "待人工复核" : attention ? "存在待处理项" : labelForCode(plan.status, "待处理");
  return <section ref={resultRef} className="energy-agent-plan" aria-label="助手查询结果">
    <div className="energy-agent-section-heading"><h3>{unknown ? "你想查询什么？" : ACTION_LABELS[plan.intent_code] || "处理结果"}</h3><Badge tone={plan.status === "SUCCEEDED" && !attention ? "success" : unknown || needsTarget ? "info" : "warning"}>{status}</Badge></div>
    {unknown ? <><p>可以直接查询本方数据，也可以选择下方常用指令。</p><Button size="sm" disabled={busy} onClick={() => onSuggest("我有哪些数据")}>查询我的数据</Button></> : <>
      {plan.status !== "SUCCEEDED" && typeof plan.plan?.explanation === "string" && <p>{plan.plan.explanation}</p>}
      {targetLink && <Link to={targetLink.path} onClick={onNavigate}>{targetLink.label}</Link>}
      {plan.steps.filter((item) => item.status === "SUCCEEDED").map((item) => <ReadResult key={item.step_id} step={item} onNavigate={onNavigate} />)}
      {step?.output?.message && typeof step.output.message === "string" ? <p>{step.output.message}</p> : null}
      {review && <div className="energy-agent-read-result" role="status"><p>复核请求已记录，等待人工审核。</p><p>复核编号：<code>{text(review.output?.request_id) || review.request_id}</code></p></div>}
      <div className="trusted-submit-actions">
        {!review && plan.allowed_actions?.includes("execute") && <Button variant="primary" size="sm" busy={busy} onClick={() => onAction("execute")}>{plan.steps.some((item) => item.mode === "WRITE") ? "提交审批草案" : "执行查询"}</Button>}
        {plan.allowed_actions?.includes("cancel") && <Button variant="secondary" size="sm" disabled={busy} onClick={() => onAction("cancel")}>取消计划</Button>}
        {plan.allowed_actions?.includes("retry") && <Button variant="secondary" size="sm" disabled={busy} onClick={() => onAction("retry")}>重试查询</Button>}
      </div>
    </>}
  </section>;
}
