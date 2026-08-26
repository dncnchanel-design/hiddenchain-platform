import { useState } from "react";
import { ArrowLeft, CheckCircle2, Eye, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api, formatNumber, post } from "../api";
import { useAuth } from "../auth";
import { Button, ConfirmDialog, DataTable, DateTimeText, DetailDrawer, Field, IdText, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

const policyLabels: Record<string, string> = {
  "policy:settlement-purpose": "限定结算用途",
  "policy:no-raw-data-export": "禁止原文导出",
};

function ruleScope(rule: JsonRecord) {
  const labels = (rule.policy_refs_json || []).map((item: string) => policyLabels[item] || item).filter(Boolean);
  return labels.length ? labels.join("、") : "—";
}

export function RulesPage() {
  const { session } = useAuth();
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get("task_id") || "";
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [activateTarget, setActivateTarget] = useState<JsonRecord | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const { data, loading, refreshing, error, reload } = useRemote<JsonRecord[]>(
    (signal) => api("/rules", { signal, timeoutMs: 12000, cache: "no-store" }), [],
  );
  const taskContext = useRemote<JsonRecord | null>((signal) => taskId ? api(`/settlement/tasks/${taskId}`, { signal, cache: "no-store" }) : Promise.resolve(null), [taskId]);
  const canEdit = session!.user.role_code === "EXCHANGE";
  const visibleRules = taskId && taskContext.data ? (data || []).filter((item) => item.rule_id === taskContext.data?.rule_id) : (data || []);

  async function activate(ruleId: string) {
    setBusy(ruleId);
    setMessage("");
    try {
      await post(`/rules/${ruleId}/activate`, {});
      setMessage("规则已生效并记录审批签名。");
      await reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "启用失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <PageHeader title="结算规则" actions={<>{taskId && <Link className="button button-secondary" to={`/settlements/${taskId}`}><ArrowLeft size={16} />返回结算任务</Link>}<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button>{canEdit && <Button icon={Plus} variant="primary" disabled={loading} onClick={() => setShowForm(true)}>新建规则</Button>}</>} />
      {taskContext.data && <div className="association-context"><span>任务使用规则</span><Link to={`/settlements/${taskId}`}>{taskContext.data.task_name}</Link><IdText value={taskContext.data.capsule_id || taskId} /></div>}
      {message && <Notice tone={message.includes("失败") ? "warning" : "success"}>{message}</Notice>}
      <Surface title="规则列表" meta={data ? `${visibleRules.length} 项` : "正在读取"}>
        <DataTable
          keyField="rule_id" rows={visibleRules} label="结算规则列表" loading={loading}
          error={error || (!loading && !data ? "规则加载失败" : "")} onRetry={reload}
          columns={[
            { key: "rule_name", label: "规则名称", minWidth: 190, render: (row) => <button className="table-link" type="button" onClick={() => setSelected(row)}>{row.rule_name || "—"}</button> },
            { key: "scope", label: "适用范围", minWidth: 220, render: (row) => ruleScope(row) },
            { key: "rule_version", label: "版本", minWidth: 120 },
            { key: "created_at", label: "创建时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "action", label: "操作", sortable: false, hideable: false, sticky: "right", render: (row) => <div className="inline-actions">{row.status === "DRAFT" && canEdit && <Button icon={CheckCircle2} busy={busy === row.rule_id} onClick={() => setActivateTarget(row)}>启用</Button>}<Button icon={Eye} onClick={() => setSelected(row)}>详情</Button></div> },
          ]}
        />
      </Surface>

      {selected && <RuleDetail rule={selected} onClose={() => setSelected(null)} />}
      {showForm && <RuleForm onClose={() => setShowForm(false)} onCreated={async () => { setShowForm(false); setMessage("规则草稿已创建。"); await reload(); }} />}
      <ConfirmDialog
        open={Boolean(activateTarget)} title="启用规则版本" objectName={`${activateTarget?.rule_name || "—"}（${activateTarget?.rule_version || "—"}）`}
        currentState={activateTarget?.status} consequence="启用后，该规则版本将可被新的结算任务引用，并记录当前审批人的签名。"
        confirmLabel="确认启用" busy={Boolean(activateTarget && busy === activateTarget.rule_id)} onCancel={() => setActivateTarget(null)}
        onConfirm={async () => { if (!activateTarget) return; await activate(activateTarget.rule_id); setActivateTarget(null); }}
      />
    </>
  );
}

function RuleDetail({ rule, onClose }: { rule: JsonRecord; onClose: () => void }) {
  const parameters = rule.parameters_json || {};
  return (
    <DetailDrawer title="授权规则详情" onClose={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
      <div className="detail-grid">
        <div><span>规则名称</span><strong>{rule.rule_name || "—"}</strong></div>
        <div><span>规则版本</span><strong>{rule.rule_version || "—"}</strong></div>
        <div><span>适用范围</span><strong>{ruleScope(rule)}</strong></div>
        <div><span>状态</span><StatusTag value={rule.status} /></div>
        <div><span>规则摘要</span><IdText value={rule.rule_hash} /></div>
        <div><span>审批签名</span><strong>{rule.approver_signatures_json?.length ?? 0} 个</strong></div>
      </div>
      {rule.description && <div className="detail-section"><h3>规则说明</h3><p>{rule.description}</p></div>}
      <div className="detail-section"><h3>计算参数</h3><div className="parameter-grid">
        <div><span>合同电价</span><strong>{formatNumber(parameters.contract_price)} 元/MWh</strong></div>
        <div><span>偏差阈值</span><strong>{formatNumber(parameters.deviation_threshold_mwh)} MWh</strong></div>
        <div><span>偏差惩罚率</span><strong>{formatNumber(parameters.deviation_penalty_rate)}</strong></div>
        <div><span>服务费率</span><strong>{formatNumber(parameters.service_fee_rate)}</strong></div>
        <div><span>小数位</span><strong>{parameters.rounding ?? "—"}</strong></div>
      </div></div>
      <div className="detail-section"><h3>规则依据</h3><ul className="plain-list">{(rule.source_refs_json || []).map((item: string) => <li key={item}>{item}</li>)}</ul>{!rule.source_refs_json?.length && <span className="muted-text">—</span>}</div>
      <details className="secondary-details"><summary>查看确定性公式</summary><pre className="code-block">{rule.formula_dsl || "—"}</pre></details>
    </DetailDrawer>
  );
}

function RuleForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const [form, setForm] = useState({ name: "", description: "", price: "", threshold: "", penalty: "", fee: "", sources: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sourceRefs = form.sources.split(/[\n,，]+/).map((item) => item.trim()).filter(Boolean);
  const formReady = form.name.trim().length >= 2 && sourceRefs.length > 0
    && Number.isFinite(Number(form.price)) && Number(form.price) > 0
    && Number.isFinite(Number(form.threshold)) && Number(form.threshold) >= 0
    && Number.isFinite(Number(form.penalty)) && Number(form.penalty) >= 0
    && Number.isFinite(Number(form.fee)) && Number(form.fee) >= 0;
  const set = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await post("/rules", {
        rule_name: form.name.trim(), description: form.description.trim(), contract_price: Number(form.price),
        deviation_threshold_mwh: Number(form.threshold), deviation_penalty_rate: Number(form.penalty),
        service_fee_rate: Number(form.fee), rounding: 2, source_refs: sourceRefs,
      });
      await onCreated();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="新建授权规则" onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button icon={ShieldCheck} variant="primary" busy={busy} disabled={!formReady} onClick={submit}>创建草稿</Button></>}>
      <div className="form-grid two">
        <Field label="规则名称"><input value={form.name} onChange={(event) => set("name", event.target.value)} /></Field>
        <Field label="合同电价（元/MWh）"><input type="number" min="0" value={form.price} onChange={(event) => set("price", event.target.value)} /></Field>
        <Field label="偏差阈值（MWh）"><input type="number" min="0" value={form.threshold} onChange={(event) => set("threshold", event.target.value)} /></Field>
        <Field label="偏差惩罚率"><input type="number" min="0" value={form.penalty} onChange={(event) => set("penalty", event.target.value)} /></Field>
        <Field label="服务费率"><input type="number" min="0" value={form.fee} onChange={(event) => set("fee", event.target.value)} /></Field>
        <div className="form-span"><Field label="规则说明"><textarea value={form.description} onChange={(event) => set("description", event.target.value)} /></Field></div>
        <div className="form-span"><Field label="规则依据" hint="每行填写一项依据"><textarea value={form.sources} onChange={(event) => set("sources", event.target.value)} /></Field></div>
      </div>
      {error && <Notice tone="warning">{error}</Notice>}
    </Modal>
  );
}
