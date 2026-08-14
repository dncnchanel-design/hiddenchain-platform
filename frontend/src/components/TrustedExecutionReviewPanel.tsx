import { useState } from "react";
import { CheckCircle2, ChevronDown, Database, FileCheck2, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
import { api, formatDate, post, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Notice, StatusTag, Surface } from "./ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

const regionLabels: Record<string, string> = {
  "EAST-CHINA": "华东",
  "NORTH-CHINA": "华北",
  "CENTRAL-CHINA": "华中",
};

const targetLabels: Record<string, string> = {
  COAL_INVENTORY: "电煤库存",
  POWER_THERMAL_OUTPUT: "火电出力",
  GRID_LOAD: "电网负荷",
  POWER_TRADING: "交易摘要",
  POWER_DISPATCH: "调度边界",
  OIL_GAS_SUPPLY: "油气供应",
};

const policyActionLabels: Record<string, string> = {
  AGGREGATE: "汇总提供",
  ALLOW: "开放提供",
  DELAY: "延迟提供",
  COMPUTE_ONLY: "仅计算",
  PROHIBIT: "禁止提供",
};

function boolValue(value: unknown) {
  return value === true || value === "true" || value === "PASSED";
}

function CheckItem({ label, value }: { label: string; value: unknown }) {
  const passed = boolValue(value);
  return <div className={`review-check-item ${passed ? "passed" : "failed"}`}><span>{passed ? <CheckCircle2 size={16} /> : <XCircle size={16} />}</span><div><strong>{label}</strong><small>{passed ? "已通过" : "需复核"}</small></div></div>;
}

function EvidenceValue({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return <span>-</span>;
  if (typeof value === "object") return <CodeValue>{JSON.stringify(value)}</CodeValue>;
  return <span>{String(value)}</span>;
}

export function TrustedExecutionReviewPanel() {
  const { session } = useAuth();
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const reviews = useRemote<JsonRecord[]>(
    () => api("/trusted-execution/reviews?review_status=PENDING", { cache: "no-store" }),
    [],
  );
  const canConfirm = ["REGULATOR", "ADMIN"].includes(session?.user.role_code || "");

  async function inspect(review: JsonRecord) {
    setBusy(`inspect:${review.review_id}`);
    setMessage("");
    try {
      setSelected(await api<JsonRecord>(`/trusted-execution/reviews/${review.request_id}`, { cache: "no-store" }));
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "复核记录加载失败");
    } finally {
      setBusy("");
    }
  }

  async function confirm() {
    if (!selected) return;
    setBusy(`confirm:${selected.review_id}`);
    setMessage("");
    try {
      await post(`/trusted-execution/reviews/${selected.request_id}/confirm`, {
        opinion: "已核对来源汇总、平衡公式、结果哈希与执行计划，确认计算结果。",
        accept: true,
      });
      setMessage("计算结果已确认，审查 DID 签名和链上复核凭证已生成。");
      setSelected(null);
      await reviews.reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "计算结果确认失败");
    } finally {
      setBusy("");
    }
  }

  if (reviews.loading) return <LoadingState />;
  if (reviews.error || !reviews.data) return <ErrorState message={reviews.error || "计算复核加载失败"} retry={reviews.reload} />;

  return (
    <>
      {message && <Notice tone={message.includes("失败") ? "warning" : "success"}>{message}</Notice>}
      <Surface
        title="计算复核队列"
        note="自动核验通过后仍需授权审计人员确认；这里仅展示安全聚合结果和来源证明。"
        actions={<Button icon={RefreshCw} onClick={reviews.reload}>刷新</Button>}
      >
        <DataTable
          keyField="review_id"
          rows={reviews.data}
          empty="当前没有待人工确认的可信执行结果"
          columns={[
            { key: "request_id", label: "请求", render: (row) => <CodeValue title={row.request_id}>{shortHash(row.request_id, 10)}</CodeValue> },
            { key: "target_data", label: "数据目标", render: (row) => (row.target_data || []).join(" · ") },
            { key: "automatic_status", label: "自动核验", render: (row) => <StatusTag value={row.automatic_status} /> },
            { key: "result_hash", label: "结果哈希", render: (row) => <CodeValue title={row.result_hash}>{shortHash(row.result_hash)}</CodeValue> },
            { key: "created_at", label: "生成时间", render: (row) => formatDate(row.created_at) },
            { key: "action", label: "操作", render: (row) => <Button icon={FileCheck2} busy={busy === `inspect:${row.review_id}`} onClick={() => inspect(row)}>打开复核</Button> },
          ]}
        />
      </Surface>
      {selected && <ReviewInspector selected={selected} canConfirm={canConfirm} busy={busy} onClose={() => setSelected(null)} onConfirm={confirm} />}
    </>
  );
}

function ReviewInspector({ selected, canConfirm, busy, onClose, onConfirm }: { selected: JsonRecord; canConfirm: boolean; busy: string; onClose: () => void; onConfirm: () => Promise<void>; }) {
  const checks = (selected.checks?.checks || {}) as JsonRecord;
  const result = (selected.result || {}) as JsonRecord;
  const snapshots = Array.isArray(selected.source_snapshot) ? selected.source_snapshot as JsonRecord[] : [];
  const series = Array.isArray(result.series) ? result.series as JsonRecord[] : [];
  const policyHits = Array.isArray(selected.policy_hits) ? selected.policy_hits as JsonRecord[] : [];
  const sourceReconciliation = checks.source_aggregate_reconciliation === true && checks.source_result_mapping === true;
  const hashRecorded = typeof selected.result_hash === "string" && selected.result_hash.length > 0;
  const hashCheck = typeof checks.result_hash === "boolean" ? checks.result_hash : hashRecorded;
  return (
    <Surface
      title="计算准确性复核"
      note={`请求 ${selected.request_id} · 自动状态 ${selected.automatic_status}`}
      actions={<Button onClick={onClose}>收起</Button>}
    >
      <div className="review-summary-bar">
        <div><span>结果哈希</span><CodeValue title={selected.result_hash}>{shortHash(selected.result_hash, 18)}</CodeValue></div>
        <div><span>自动核验</span><StatusTag value={selected.automatic_status} /></div>
        <div><span>人工确认</span><StatusTag value={selected.verification_status} /></div>
        {selected.reviewer_did && <div><span>确认主体</span><CodeValue>{shortHash(selected.reviewer_did, 18)}</CodeValue></div>}
      </div>
      <div className="review-check-grid">
        <CheckItem label="平衡公式" value={checks.balance_formula} />
        <CheckItem label="来源汇总与映射" value={sourceReconciliation} />
        <CheckItem label="结果哈希凭证" value={hashCheck} />
        <CheckItem label="原始数据边界" value={checks.raw_data_boundary} />
      </div>
      {policyHits.length > 0 && <PolicyHitStrip hits={policyHits} />}
      {series.length > 0 && <ReviewTrend series={series} />}
      <div className="review-evidence-grid">
        <div className="review-evidence-card"><div className="review-evidence-heading"><Database size={17} /><strong>来源快照</strong><span>{snapshots.length} 个节点</span></div><div className="review-evidence-list">{snapshots.slice(0, 6).map((item, index) => <div key={`${item.node || item.provider || "source"}-${index}`}><span>{item.node || item.provider || item.target_data_type || "数据节点"}</span><strong>{item.target_data_type || item.data_type || "安全聚合"}</strong><small>{item.raw_data_exposed === false ? "原始数据未出域" : "需复核"} · {item.group_by ? `按 ${Array.isArray(item.group_by) ? item.group_by.join("、") : item.group_by} 汇总` : "受控计算"}</small></div>)}</div></div>
        <div className="review-evidence-card"><div className="review-evidence-heading"><ShieldCheck size={17} /><strong>安全交付</strong><span>{series.length} 条结果</span></div><div className="review-evidence-list">{series.slice(0, 6).map((item, index) => <div key={`series-${index}`}><span>{item.period || item.date || `结果 ${index + 1}`}</span><strong><EvidenceValue value={item.balance_status || item.trend || item.thermal_output_mwh || item.value} /></strong><small>{item.raw_data_exposed === false || result.raw_data_returned === false ? "仅返回聚合/趋势" : "受控结果"}</small></div>)}</div></div>
      </div>
      <details className="review-raw-details"><summary>查看安全摘要 <ChevronDown size={15} /></summary><pre className="json-view">{JSON.stringify({ checks: selected.checks, target_data: selected.target_data, source_snapshot: snapshots, series }, null, 2)}</pre></details>
      {selected.verification_status === "PENDING" && canConfirm && <div className="review-confirm-bar"><div><strong>确认计算结果</strong><span>确认后将写入审查 DID 签名，并生成 REVIEW_CONFIRMED 链上事件。</span></div><Button icon={CheckCircle2} variant="primary" busy={busy === `confirm:${selected.review_id}`} onClick={onConfirm}>确认并留痕</Button></div>}
      {selected.verification_status === "PENDING" && !canConfirm && <Notice tone="warning">当前角色可以查看复核材料，但只有监管方或系统管理员可以确认计算结果。</Notice>}
    </Surface>
  );
}

function PolicyHitStrip({ hits }: { hits: JsonRecord[] }) {
  return (
    <div className="review-policy-panel">
      <div className="review-policy-heading"><div><strong>策略命中</strong><span>最终裁决来自确定性规则，不由解释服务决定</span></div><span>{hits.length} 个数据目标</span></div>
      <div className="review-policy-grid">
        {hits.map((hit, index) => {
          const action = String(hit.action || "PROHIBIT");
          const grouping = Array.isArray(hit.group_by) ? hit.group_by.join("、") : String(hit.group_by || "");
          return <article className="review-policy-item" key={`${hit.target_data_type || "target"}-${index}`}><div><strong>{targetLabels[String(hit.target_data_type)] || hit.target_data_type}</strong><StatusTag value={hit.decision} label={hit.decision === "PERMIT" ? "已授权" : "已拦截"} /></div><span>{policyActionLabels[action] || action}</span><small>{grouping ? `按 ${grouping} 汇总` : `规则 ${shortHash(hit.rule_id, 10)}`}</small></article>;
        })}
      </div>
    </div>
  );
}

function ReviewTrend({ series }: { series: JsonRecord[] }) {
  const rows = series.slice(0, 8).map((item) => ({
    period: String(item.period || item.date || "结果"),
    region: regionLabels[String(item.region || "")] || String(item.region || ""),
    thermal: Number(item.thermal_output_mwh || 0),
    load: Number(item.grid_load_mwh || 0),
    status: String(item.balance_status || "-")
  }));
  const maxValue = Math.max(1, ...rows.flatMap((row) => [row.thermal, row.load]));
  return (
    <div className="review-trend-panel">
      <div className="review-trend-heading"><div><strong>聚合趋势视图</strong><span>只展示安全交付结果，不还原主体明细</span></div><div className="review-trend-legend"><i className="trend-thermal" />火电出力<i className="trend-load" />电网负荷</div></div>
      <div className="review-trend-rows">
        {rows.map((row, index) => <div className="review-trend-row" key={`${row.period}-${row.region}-${index}`}><span>{row.region ? `${row.period} · ${row.region}` : row.period}</span><div className="review-trend-bars"><div><i className="trend-thermal" style={{ width: `${Math.max(2, row.thermal / maxValue * 100)}%` }} /></div><div><i className="trend-load" style={{ width: `${Math.max(2, row.load / maxValue * 100)}%` }} /></div></div><strong className={row.status === "GAP" ? "trend-gap" : "trend-surplus"}>{row.status}</strong></div>)}
      </div>
    </div>
  );
}
