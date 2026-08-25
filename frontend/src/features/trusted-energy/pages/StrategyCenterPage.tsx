import { useState } from "react";
import { useRemote } from "../../../hooks";
import { createIdempotencyKey } from "../../../api";
import { PrototypeCardTitle, PrototypePageFrame } from "../components/PrototypePageFrame";
import { RemoteState } from "../components/ui-primitives";
import { addPrototypePolicyRule, deletePrototypePolicyRule, loadPrototypePolicy, type PrototypePolicyResource } from "../trusted-space-api";
import { useTrustedSpaceContext } from "../trusted-space-context";

const ACTION_NAMES: Record<string, string> = { allow: "直接提供", deny: "禁止提供", aggregate: "汇总提供", delay: "延迟提供", compute_only: "仅计算不出域" };
const ACTIONS = ["allow", "deny", "aggregate", "delay", "compute_only"];

type FormState = { role: string; purpose: string; action: string };

function initialForm(): FormState { return { role: "", purpose: "", action: "aggregate" }; }

function actionClass(action: string) { return `prototype-action-badge is-${action}`; }

function PolicyBlock({ resource, form, onFormChange, onAdd, onDelete, canManage, allowDirect, busy }: { resource: PrototypePolicyResource; form: FormState; onFormChange: (next: FormState) => void; onAdd: () => void; onDelete: (role: string) => void; canManage: boolean; allowDirect: boolean; busy: boolean }) {
  return <section className="prototype-policy-block">
    <div className="prototype-policy-heading"><div><b>{resource.name}</b> <code>{resource.id}</code>{resource.dynamic && <span className="prototype-dynamic-tag">动态接入</span>}<span className={`prototype-level-tag is-${resource.level.slice(0, 2)}`}>{resource.level}</span></div><span>默认动作：<strong className="prototype-policy-default">{ACTION_NAMES[resource.default_action] || resource.default_action}</strong></span></div>
    <div className="prototype-policy-explainer"><div><span>何时命中</span><strong>申请角色 + 使用目的 + 数据字段</strong></div><div><span>命中后动作</span><strong>{resource.rules.length ? resource.rules.map((rule) => ACTION_NAMES[rule.action] || rule.action).filter((value, index, values) => values.indexOf(value) === index).join(" / ") : ACTION_NAMES[resource.default_action] || "按默认策略"}</strong></div><div><span>平台输出</span><strong>{resource.default_action === "compute_only" ? "只返回聚合计算结果" : resource.default_action === "deny" ? "不执行、不返回结果" : "按授权范围受控返回"}</strong></div></div>
    <div className="prototype-table-scroll"><table className="prototype-table"><thead><tr><th>角色</th><th>用途限定</th><th>裁决</th><th>字段白名单</th><th>附加约束</th>{resource.dynamic && <th>操作</th>}</tr></thead><tbody>{resource.rules.map((rule) => <tr key={`${rule.role}-${rule.rule_id || rule.action}`}><td>{rule.role}</td><td>{rule.purposes.length ? rule.purposes.join("/") : "不限"}</td><td><span className={actionClass(rule.action)}>{ACTION_NAMES[rule.action] || rule.action}</span></td><td className="prototype-compact-cell">{rule.fields.join(", ") || "—"}</td><td className="prototype-compact-cell">{[rule.min_granularity ? `最低粒度:${rule.min_granularity}` : "", rule.delay_hours ? `延迟:${rule.delay_hours}h` : ""].filter(Boolean).join("；") || "—"}</td>{resource.dynamic && <td><button type="button" className="prototype-danger-button" disabled={busy} onClick={() => onDelete(rule.role)}>删除</button></td>}</tr>)}</tbody></table></div>
    {resource.dynamic && canManage && <div className="prototype-rule-form"><b>添加规则：</b><label><span>角色</span><input value={form.role} onChange={(event) => onFormChange({ ...form, role: event.target.value })} placeholder="如 省发改委-分析师" /></label><label><span>用途（可空）</span><input value={form.purpose} onChange={(event) => onFormChange({ ...form, purpose: event.target.value })} placeholder="如 保供监测" /></label><label><span>裁决</span><select value={form.action} onChange={(event) => onFormChange({ ...form, action: event.target.value })}>{ACTIONS.filter((action) => allowDirect || action !== "allow").map((action) => <option key={action} value={action}>{ACTION_NAMES[action]}</option>)}</select></label><button type="button" className="prototype-primary-button" disabled={busy || !form.role.trim()} onClick={onAdd}>添加</button></div>}
  </section>;
}

export function StrategyCenterPage() {
  const remote = useRemote(loadPrototypePolicy, []);
  const context = useTrustedSpaceContext();
  const [forms, setForms] = useState<Record<string, FormState>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const role = context.context?.actor.role_code;
  const canManage = role === "REGULATOR" || Boolean(context.context?.actor.permissions?.includes("MANAGE_RULES"));
  const allowDirect = role !== "REGULATOR";
  const resources = remote.data?.matrix || [];

  function formFor(resourceId: string) { return forms[resourceId] || initialForm(); }

  async function addRule(resource: PrototypePolicyResource) {
    const form = formFor(resource.id);
    setBusy(true); setError("");
    try {
      await addPrototypePolicyRule({ resource_id: resource.id, role: form.role.trim(), purpose: form.purpose.trim(), action: form.action }, { idempotencyKey: createIdempotencyKey("prototype-policy-add") });
      setForms((current) => ({ ...current, [resource.id]: initialForm() }));
      await remote.reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "规则添加失败"); } finally { setBusy(false); }
  }

  async function deleteRule(resource: PrototypePolicyResource, role: string) {
    if (!window.confirm(`确定删除角色「${role}」的规则吗？`)) return;
    setBusy(true); setError("");
    try { await deletePrototypePolicyRule(resource.id, role, { idempotencyKey: createIdempotencyKey("prototype-policy-delete") }); await remote.reload(); } catch (reason) { setError(reason instanceof Error ? reason.message : "规则删除失败"); } finally { setBusy(false); }
  }

  return <PrototypePageFrame className="prototype-policy-page">
    <RemoteState loading={remote.loading} error={remote.error} onRetry={() => void remote.reload()} />
    <section className="prototype-card prototype-policy-intro"><PrototypeCardTitle>策略管理中心（敏感边界可配置 · 声明式策略）</PrototypeCardTitle><p className="prototype-policy-intro-copy">所有访问动作由确定性策略引擎裁决：首个规则命中生效，未命中按默认拒绝（失败关闭）。动态接入资源可在下方追加规则。</p></section>
    {error && <div className="prototype-error" role="alert">{error}</div>}
    {remote.data && <div className="prototype-policy-list">{resources.map((resource) => <PolicyBlock key={resource.id} resource={resource} form={formFor(resource.id)} onFormChange={(next) => setForms((current) => ({ ...current, [resource.id]: next }))} onAdd={() => void addRule(resource)} onDelete={(role) => void deleteRule(resource, role)} canManage={canManage} allowDirect={allowDirect} busy={busy} />)}</div>}
    <section className="prototype-card prototype-applications"><PrototypeCardTitle>授权申请记录</PrototypeCardTitle>{remote.data?.applications.length ? <div className="prototype-table-scroll"><table className="prototype-table"><thead><tr><th>申请时间</th><th>申请资产</th><th>申请方</th><th>用途</th><th>状态</th></tr></thead><tbody>{remote.data.applications.map((item) => <tr key={`${item.ts}-${item.applicant_did}`}><td>{item.ts}</td><td><b>{item.resource_name}</b><br /><code>{item.resource_id}</code></td><td>{item.applicant_role}<br /><code>{item.applicant_did}</code></td><td>{item.purpose}</td><td><span className={`prototype-status-tag is-${item.status}`}>{item.status === "pending" ? "待审批" : item.status === "approved" ? "已通过" : "已拒绝"}</span></td></tr>)}</tbody></table></div> : <div className="prototype-empty">暂无授权申请记录</div>}</section>
  </PrototypePageFrame>;
}
