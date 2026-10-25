import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { ACTION_LABELS, ASSET_TYPE_LABELS, labelForCode } from "../../../types";
import type { AssistantPlan, AssistantPlanStep } from "../trusted-space-api";
import { isKnownTrustedPath } from "../types";
import { Badge, Button } from "./ui-primitives";

const TARGET_LINKS: Record<string, { path: string; label: string }> = {
  CHECK_ASSET_INTEGRITY: { path: "/trusted-space/catalog", label: "选择数据资产" },
  QUERY_AUTHORIZATION_STATUS: { path: "/trusted-space/authorizations", label: "选择授权申请" },
  CHECK_TTC_STATUS: { path: "/trusted-space/mpc", label: "选择计算任务" },
  VERIFY_EVIDENCE_SUMMARY: { path: "/trusted-space/ttc", label: "选择结算任务" },
  EXPLAIN_AUDIT: { path: "/trusted-space/ttc", label: "选择结算任务" },
};

const LIST_VIEWS: Record<string, { label: string; empty: string; path: string; link: string }> = {
  LIST_DATA_ASSETS: { label: "本方数据", empty: "当前账号尚未登记本方数据。", path: "/trusted-space/catalog", link: "打开数据目录" },
  LIST_VISIBLE_DATA_ASSETS: { label: "可见数据", empty: "当前账号暂无可见数据。", path: "/trusted-space/catalog", link: "打开数据目录" },
  LIST_AUTHORIZED_DATA_ASSETS: { label: "可用数据", empty: "当前账号暂无可用数据，可在数据目录查看并申请授权。", path: "/trusted-space/catalog", link: "打开数据目录" },
  LIST_AUTHORIZATIONS: { label: "授权申请", empty: "当前账号暂无符合条件的授权申请。", path: "/trusted-space/authorizations", link: "打开数据授权" },
  LIST_TASKS: { label: "任务", empty: "当前账号暂无符合条件的任务。", path: "/trusted-space/mpc", link: "打开隐私计算" },
  LIST_AUDIT_REPORTS: { label: "审计报告", empty: "当前账号暂无符合条件的审计报告。", path: "/trusted-space/audit?view=reports", link: "打开审计报告" },
  LIST_NOTIFICATIONS: { label: "通知", empty: "当前账号暂无符合条件的通知。", path: "/trusted-space/workbench", link: "打开运行总览" },
};

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function internalPath(value: unknown): string | undefined {
  const path = text(value);
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\") || Array.from(path).some((character) => character.charCodeAt(0) <= 32)) return undefined;
  try {
    const url = new URL(path, "https://assistant.local");
    return url.origin === "https://assistant.local" && isKnownTrustedPath(url.pathname) ? `${url.pathname}${url.search}${url.hash}` : undefined;
  } catch {
    return undefined;
  }
}

function statusLabel(value: unknown): string {
  return ({ READ: "已读", UNREAD: "未读", CONFIG_REQUIRED: "待配置", CONFIGURED: "已配置", DISABLED: "已停用", EMPTY: "暂无登记", DEMO: "公开演示环境", DEVELOPMENT: "开发环境", TEST: "测试环境", PRODUCTION: "生产环境" } as Record<string, string>)[text(value)] || labelForCode(value, "未登记");
}

function SystemOverview({ output }: { output: Record<string, unknown> }) {
  const overview = record(output.overview), system = record(output.system), agents = record(output.agents);
  const health = record(overview.service_health), agentHealth = record(agents.service_health), counts = record(overview.counts);
  const services: Array<[string, unknown]> = [
    ["API 服务", health.api], ["数据库", health.database], ["运行环境", health.environment],
    ["身份登记服务", record(system.technical_status).identity_registry], ["节点登记服务", record(system.technical_status).node_registry],
    ["原始数据访问", record(system.technical_status).raw_payload_access],
    ["助手 API 服务", agentHealth.api], ["解释服务", agentHealth.explanation_service],
    ["服务提供方", agentHealth.provider], ["配置模型", agentHealth.model], ["服务凭证", agentHealth.credential_configured],
  ];
  const metrics: Array<[string, unknown]> = [
    ["组织总数", counts.organizations_total ?? record(system.organization_counts).total], ["活跃组织数", counts.organizations_active ?? record(system.organization_counts).active],
    ["账号总数", counts.users_total ?? record(system.user_counts).total], ["活跃账号数", counts.users_active ?? record(system.user_counts).active],
    ["身份总数", counts.identities_total ?? record(system.identity_counts).total], ["有效身份数", counts.identities_valid ?? record(system.identity_counts).valid],
    ["组织身份数", record(system.identity_counts).organizations], ["个人身份数", record(system.identity_counts).users], ["助手身份数", record(system.identity_counts).agents],
    ["节点总数", counts.nodes_total ?? record(system.node_counts).total], ["活跃节点数", counts.nodes_active ?? record(system.node_counts).active], ["节点健康已确认数", record(system.node_counts).health_confirmed],
  ];
  return <div className="energy-agent-read-result" role="status">
    <dl>{services.filter(([, value]) => typeof value === "boolean" || Boolean(text(value))).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{typeof value === "boolean" ? value ? "已配置" : "未配置" : statusLabel(value)}</dd></div>)}</dl>
    <dl>{metrics.filter(([, value]) => typeof value === "number" && Number.isFinite(value)).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{Number(value).toLocaleString("zh-CN")}</dd></div>)}</dl>
  </div>;
}

function needsAttention(step: AssistantPlanStep): boolean {
  const output = step.output || {};
  const integrity = record(output.integrity);
  return ["version_present", "passport_present", "quality_present"].some((key) => integrity[key] === false)
    || ["FAIL", "FAILED", "REJECT", "REJECTED", "BLOCKED"].includes(text(record(output.quality).decision))
    || (Array.isArray(output.items) && output.items.some((item) => record(record(item).verify).matched === false));
}

function ReadResult({ step, busy, onNavigate, onSuggest, onOpenElectricity }: { step: AssistantPlanStep; busy: boolean; onNavigate: () => void; onSuggest: (content: string) => void; onOpenElectricity?: (question: string) => void }) {
  const output = step.output || {};
  const list = LIST_VIEWS[step.action_code];
  if (list) {
    const items = Array.isArray(output.items) ? output.items.map(record) : [];
    return <div className="energy-agent-read-result" role="status">
      <p>{output.total || items.length ? `当前账号${step.action_code === "LIST_DATA_ASSETS" ? "登记了" : "有"} ${text(output.total ?? items.length)} 项${list.label}。` : list.empty}</p>
      {items.length > 0 && <ul className="energy-agent-data-list">{items.map((item, index) => {
        const href = internalPath(item.href || (item.asset_id ? `/trusted-space/assets/${encodeURIComponent(text(item.asset_id))}` : ""));
        const label = text(item.label) || text(item.asset_name) || "未命名对象";
        return <li key={`${text(item.entity_id || item.asset_id)}:${text(item.version_id)}:${index}`}>
          {href ? <Link to={href} onClick={onNavigate}>{label}</Link> : <strong>{label}</strong>}
          {item.status ? <span>{statusLabel(item.status)}</span> : null}
          {(item.asset_type || typeof item.record_count === "number") ? <span>{ASSET_TYPE_LABELS[text(item.asset_type)] || "数据资源"}{typeof item.version_no === "number" ? ` · 第 ${item.version_no} 版` : ""}{typeof item.record_count === "number" ? ` · ${item.record_count.toLocaleString("zh-CN")} 条记录` : ""}</span> : null}
          {item.period_start && item.period_end ? <span>{text(item.period_start)} 至 {text(item.period_end)}</span> : null}
          {typeof item.remaining_uses === "number" ? <span>剩余 {item.remaining_uses} 次</span> : null}
        </li>;
      })}</ul>}
      {output.has_more === true && <p>当前显示前 {items.length} 项，可{list.link}继续查看。</p>}
      <Link to={list.path} onClick={onNavigate}>{list.link}</Link>
    </div>;
  }
  if (step.action_code === "SYSTEM_OVERVIEW") return <SystemOverview output={output} />;
  if (step.action_code === "ASSISTANT_HELP") {
    const actions = Array.isArray(output.help_actions) ? output.help_actions.map(record).filter((item) => text(item.label) && text(item.prompt)) : [];
    return <div className="energy-agent-read-result" role="status"><p>选择一项，或直接告诉我你想做什么。</p><div className="trusted-submit-actions">{actions.map((item, index) => <Button key={`${text(item.prompt)}:${index}`} size="sm" disabled={busy} onClick={() => onSuggest(text(item.prompt))}>{text(item.label)}</Button>)}</div></div>;
  }
  if (step.action_code === "NAVIGATE_QUERY" || step.action_code === "NAVIGATE_ELECTRICITY") {
    const navigation = record(output.navigation);
    if (navigation.path === "#electricity") return <div className="energy-agent-read-result" role="status">{onOpenElectricity ? <Button size="sm" disabled={busy} onClick={() => onOpenElectricity(text(navigation.question))}>打开电力交易计算</Button> : <p>当前助手没有可用的电力计算入口。</p>}</div>;
    let path = internalPath(navigation.path);
    if (!path) return <div className="energy-agent-read-result" role="status"><p>暂时无法打开该入口，请使用页面导航。</p></div>;
    const url = new URL(path, "https://assistant.local");
    const query = url.pathname === "/trusted-space/query";
    if (query) {
      const question = text(navigation.question) || url.searchParams.get("question") || "";
      path = `${url.pathname}${question ? `?${new URLSearchParams({ question })}` : ""}`;
    }
    return <div className="energy-agent-read-result" role="status"><Link to={path} onClick={onNavigate}>{query ? "打开智能数据查询" : "打开相关页面"}</Link></div>;
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

export function AssistantPlanView({ plan, busy, onAction, onNavigate, onSuggest, onOpenElectricity }: {
  plan: AssistantPlan; busy: boolean;
  onAction: (action: "execute" | "cancel" | "retry") => void;
  onNavigate: () => void; onSuggest: (content: string) => void;
  onOpenElectricity?: (question: string) => void;
}) {
  const resultRef = useRef<HTMLElement>(null);
  useEffect(() => {
    resultRef.current?.scrollIntoView({ block: "nearest" });
  }, [plan.plan_id, plan.state_version]);
  const unknown = plan.intent_code === "UNKNOWN_INTENT";
  const step = plan.steps[0];
  const needsTarget = plan.status === "NEEDS_INPUT" || step?.mode === "NEEDS_INPUT" || step?.error_code === "ASSISTANT_TARGET_REQUIRED" || step?.error_code === "ASSISTANT_TARGET_TYPE_MISMATCH";
  const candidates = needsTarget && Array.isArray(plan.plan?.candidates) ? plan.plan.candidates.map((value, index) => ({ item: record(value), position: index + 1 })).filter(({ item }) => text(item.entity_id) && text(item.entity_type) && text(item.label)) : [];
  const targetLink = needsTarget ? TARGET_LINKS[plan.intent_code] : null;
  const attention = plan.steps.some(needsAttention);
  const review = plan.status === "PENDING_REVIEW" ? plan.steps.find((item) => item.output?.review_requested === true) : undefined;
  const status = unknown ? "换个说法试试" : needsTarget ? "待选择" : review ? "待人工复核" : attention ? "存在待处理项" : labelForCode(plan.status, "待处理");
  return <section ref={resultRef} className="energy-agent-plan" aria-label="助手查询结果">
    <div className="energy-agent-section-heading"><h3>{unknown ? "你想查询什么？" : ACTION_LABELS[plan.intent_code] || "处理结果"}</h3><Badge tone={plan.status === "SUCCEEDED" && !attention ? "success" : unknown || needsTarget ? "info" : "warning"}>{status}</Badge></div>
    {unknown ? <><p>可以查看助手支持的功能，再选择要处理的内容。</p><Button size="sm" disabled={busy} onClick={() => onSuggest("你能做什么")}>你能做什么</Button></> : <>
      {plan.status !== "SUCCEEDED" && typeof plan.plan?.explanation === "string" && <p>{plan.plan.explanation}</p>}
      {candidates.length > 0 && <ul className="energy-agent-data-list" aria-label="可选业务对象">{candidates.map(({ item, position }) => <li key={`${text(item.entity_type)}:${text(item.entity_id)}`}><Button size="sm" disabled={busy} aria-label={`选择第${position}个：${text(item.label)}`} onClick={() => onSuggest(position === 1 ? "第一个" : `第${position}个`)}>{position}. {text(item.label)}</Button>{item.status ? <span>{statusLabel(item.status)}</span> : null}</li>)}</ul>}
      {targetLink && <Link to={targetLink.path} onClick={onNavigate}>{targetLink.label}</Link>}
      {plan.steps.filter((item) => item.status === "SUCCEEDED").map((item) => <ReadResult key={item.step_id} step={item} busy={busy} onNavigate={onNavigate} onSuggest={onSuggest} onOpenElectricity={onOpenElectricity} />)}
      {step?.output?.message && typeof step.output.message === "string" ? <p>{step.output.message}</p> : null}
      {review && <div className="energy-agent-read-result" role="status"><p>复核请求已记录，等待人工审核。</p><p>复核编号：<code>{text(review.output?.request_id) || review.request_id}</code></p></div>}
      <div className="trusted-submit-actions">
        {!review && !needsTarget && plan.allowed_actions?.includes("execute") && <Button variant="primary" size="sm" busy={busy} onClick={() => onAction("execute")}>{plan.steps.some((item) => item.mode === "WRITE") ? "提交审批草案" : "执行查询"}</Button>}
        {plan.allowed_actions?.includes("cancel") && <Button variant="secondary" size="sm" disabled={busy} onClick={() => onAction("cancel")}>取消计划</Button>}
        {plan.allowed_actions?.includes("retry") && <Button variant="secondary" size="sm" disabled={busy} onClick={() => onAction("retry")}>重试查询</Button>}
      </div>
    </>}
  </section>;
}
