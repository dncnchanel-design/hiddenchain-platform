import { useState } from "react";
import { CheckCircle2, FileCode2, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import { api, formatDate, post, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, CodeValue, DataTable, ErrorState, Field, LoadingState, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

export function RulesPage() {
  const { session } = useAuth();
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const { data, loading, error, reload } = useRemote<JsonRecord[]>(() => api("/rules"), []);
  const canEdit = session!.user.role_code === "EXCHANGE";

  async function activate(ruleId: string) {
    setBusy(ruleId);
    setMessage("");
    try {
      await post(`/rules/${ruleId}/activate`, {});
      setMessage("规则已签名启用。");
      await reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "启用失败");
    } finally {
      setBusy("");
    }
  }

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "规则加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader title="使用规则" actions={<><Button icon={RefreshCw} onClick={reload}>刷新</Button>{canEdit && <Button icon={Plus} variant="primary" onClick={() => setShowForm(true)}>新建规则</Button>}</>} />
      {message && <Notice tone={message.includes("失败") ? "warning" : "success"}>{message}</Notice>}
      <Surface title="规则列表">
        <DataTable
          keyField="rule_id"
          rows={data}
          columns={[
            { key: "rule_version", label: "版本", render: (row) => <button className="table-link" onClick={() => setSelected(row)}>{row.rule_version}</button> },
            { key: "rule_name", label: "规则名称" },
            { key: "contract_price", label: "基准价", render: (row) => `${row.parameters_json?.contract_price ?? "-"} 元/MWh` },
            { key: "rule_hash", label: "规则编号", render: (row) => <CodeValue title={row.rule_hash}>{shortHash(row.rule_hash)}</CodeValue> },
            { key: "source_refs_json", label: "依据", render: (row) => `${row.source_refs_json?.length || 0} 条` },
            { key: "created_at", label: "创建时间", render: (row) => formatDate(row.created_at) },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "action", label: "操作", render: (row) => row.status === "DRAFT" && canEdit ? <Button icon={CheckCircle2} busy={busy === row.rule_id} onClick={() => activate(row.rule_id)}>确认启用</Button> : <Button icon={FileCode2} onClick={() => setSelected(row)}>查看规则</Button> },
          ]}
        />
      </Surface>
      {selected && <RuleDetail rule={selected} onClose={() => setSelected(null)} />}
      {showForm && <RuleForm onClose={() => setShowForm(false)} onCreated={async () => { setShowForm(false); await reload(); }} />}
    </>
  );
}

function RuleDetail({ rule, onClose }: { rule: JsonRecord; onClose: () => void }) {
  return (
    <Modal title={`${rule.rule_version} 规则`} onClose={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
      <div className="detail-grid">
        <div><span>规则编号</span><CodeValue>{rule.rule_hash}</CodeValue></div>
        <div><span>策略引用</span><strong>{(rule.policy_refs_json || []).map((item: string) => item === "policy:settlement-purpose" ? "限定验证用途" : item === "policy:no-raw-data-export" ? "禁止导出原文" : item).join(" · ")}</strong></div>
        <div><span>批准签名</span><strong>{rule.approver_signatures_json?.length || 0} 个</strong></div>
        <div><span>状态</span><StatusTag value={rule.status} /></div>
      </div>
      <div className="code-block"><div>确定性计算规则</div><code>{rule.formula_dsl}</code></div>
      <div className="parameter-grid">
        {Object.entries(rule.parameters_json || {}).map(([key, value]) => <div key={key}><span>{key}</span><strong>{String(value)}</strong></div>)}
      </div>
    </Modal>
  );
}

function RuleForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const [form, setForm] = useState({ name: "山东能源场景验证规则", price: "425", threshold: "100", penalty: "150", fee: "3.2" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const formReady = form.name.trim().length >= 2
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
        rule_name: form.name,
        contract_price: Number(form.price),
        deviation_threshold_mwh: Number(form.threshold),
        deviation_penalty_rate: Number(form.penalty),
        service_fee_rate: Number(form.fee),
        rounding: 2,
        source_refs: ["月度结算条款", "数据使用规则"],
      });
      await onCreated();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="新建使用规则" onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button icon={ShieldCheck} variant="primary" busy={busy} disabled={!formReady} onClick={submit}>创建规则</Button></>}>
      <div className="form-grid two">
        <Field label="规则名称"><input value={form.name} onChange={(event) => set("name", event.target.value)} /></Field>
        <Field label="合同电价（元/MWh）"><input type="number" value={form.price} onChange={(event) => set("price", event.target.value)} /></Field>
        <Field label="偏差阈值（MWh）"><input type="number" value={form.threshold} onChange={(event) => set("threshold", event.target.value)} /></Field>
        <Field label="偏差惩罚率"><input type="number" value={form.penalty} onChange={(event) => set("penalty", event.target.value)} /></Field>
        <Field label="服务费率"><input type="number" value={form.fee} onChange={(event) => set("fee", event.target.value)} /></Field>
      </div>
      {error && <Notice tone="warning">{error}</Notice>}
    </Modal>
  );
}
