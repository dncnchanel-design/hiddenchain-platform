import { useState } from "react";
import { CheckCircle2, FileCode2, Gavel, Plus, RefreshCw, ShieldCheck } from "lucide-react";
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
      setMessage("规则已通过人工闸门并由交易中心 DID 签名启用。");
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
      <PageHeader eyebrow="用途与规则控制" title="用途与规则控制" description="调用用途经 RAG 检索引用、DSL 固化、哈希签名和人工闸门后，才能进入确定性隐私计算或场景验证。" actions={<><Button icon={RefreshCw} onClick={reload}>刷新</Button>{canEdit && <Button icon={Plus} variant="primary" onClick={() => setShowForm(true)}>新建规则包</Button>}</>} />
      <div className="boundary-strip">
        <Gavel size={18} /><div><strong>Agent 不生成最终规则</strong><span>规则 Agent 仅检索、解析和校验；启用动作必须由交易中心人员签署。</span></div><StatusTag value="ACTIVE" label="人工闸门" />
      </div>
      {message && <Notice tone={message.includes("失败") ? "warning" : "success"}>{message}</Notice>}
      <Surface title="用途控制 RulePackage" note="每个调用或验证任务只能绑定已启用且哈希固定的规则版本">
        <DataTable
          keyField="rule_id"
          rows={data}
          columns={[
            { key: "rule_version", label: "版本", render: (row) => <button className="table-link" onClick={() => setSelected(row)}>{row.rule_version}</button> },
            { key: "rule_name", label: "规则名称" },
            { key: "contract_price", label: "基准价", render: (row) => `${row.parameters_json?.contract_price ?? "-"} 元/MWh` },
            { key: "rule_hash", label: "RuleHash", render: (row) => <CodeValue title={row.rule_hash}>{shortHash(row.rule_hash)}</CodeValue> },
            { key: "source_refs_json", label: "依据", render: (row) => `${row.source_refs_json?.length || 0} 条引用` },
            { key: "created_at", label: "创建时间", render: (row) => formatDate(row.created_at) },
            { key: "status", label: "状态", render: (row) => <StatusTag value={row.status} /> },
            { key: "action", label: "操作", render: (row) => row.status === "DRAFT" && canEdit ? <Button icon={CheckCircle2} busy={busy === row.rule_id} onClick={() => activate(row.rule_id)}>签名启用</Button> : <Button icon={FileCode2} onClick={() => setSelected(row)}>查看 DSL</Button> },
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
    <Modal title={`${rule.rule_version} 规则包`} onClose={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
      <div className="detail-grid">
        <div><span>RuleHash</span><CodeValue>{rule.rule_hash}</CodeValue></div>
        <div><span>策略引用</span><strong>{(rule.policy_refs_json || []).join(" · ")}</strong></div>
        <div><span>批准签名</span><strong>{rule.approver_signatures_json?.length || 0} 个</strong></div>
        <div><span>状态</span><StatusTag value={rule.status} /></div>
      </div>
      <div className="code-block"><div>DETERMINISTIC SETTLEMENT DSL</div><code>{rule.formula_dsl}</code></div>
      <div className="parameter-grid">
        {Object.entries(rule.parameters_json || {}).map(([key, value]) => <div key={key}><span>{key}</span><strong>{String(value)}</strong></div>)}
      </div>
      <Notice>RAG 仅提供依据检索与引用；最终执行内容以此 RuleHash 对应的 DSL 和参数为准。</Notice>
    </Modal>
  );
}

function RuleForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const [form, setForm] = useState({ name: "山东电力交易月度结算规则", price: "425", threshold: "100", penalty: "150", fee: "3.2" });
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
        description: "用于能源场景验证的确定性规则与用途控制包",
        contract_price: Number(form.price),
        deviation_threshold_mwh: Number(form.threshold),
        deviation_penalty_rate: Number(form.penalty),
        service_fee_rate: Number(form.fee),
        rounding: 2,
        source_refs: ["比赛项目书-多方安全协同条款", "演示规则库-月度结算条款-02"],
      });
      await onCreated();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="新建用途控制规则包" onClose={onClose} footer={<><Button onClick={onClose}>取消</Button><Button icon={ShieldCheck} variant="primary" busy={busy} disabled={!formReady} onClick={submit}>生成待审 RulePackage</Button></>}>
      <div className="form-grid two">
        <Field label="规则名称"><input value={form.name} onChange={(event) => set("name", event.target.value)} /></Field>
        <Field label="合同电价（元/MWh）"><input type="number" value={form.price} onChange={(event) => set("price", event.target.value)} /></Field>
        <Field label="偏差阈值（MWh）"><input type="number" value={form.threshold} onChange={(event) => set("threshold", event.target.value)} /></Field>
        <Field label="偏差惩罚率"><input type="number" value={form.penalty} onChange={(event) => set("penalty", event.target.value)} /></Field>
        <Field label="服务费率"><input type="number" value={form.fee} onChange={(event) => set("fee", event.target.value)} /></Field>
      </div>
      <Notice>创建后保持 DRAFT，需交易中心人员核对来源与参数并执行 DID 签名启用。</Notice>
      {error && <Notice tone="warning">{error}</Notice>}
    </Modal>
  );
}
