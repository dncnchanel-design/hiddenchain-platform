import { useState } from "react";
import { CheckCircle2, FileCheck2, RefreshCw, ShieldCheck } from "lucide-react";
import { api, formatDate, post, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Notice, StatusTag, Surface } from "./ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

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
      setMessage(reason instanceof Error ? reason.message : "核对记录加载失败");
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
        opinion: "已核对节点安全汇总、计算公式和结果哈希，确认",
        accept: true,
      });
      setMessage("已完成计算核对，审核 DID 签名和链上复核凭证已生成。");
      setSelected(null);
      await reviews.reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "计算结果确认失败");
    } finally {
      setBusy("");
    }
  }

  if (reviews.loading) return <LoadingState />;
  if (reviews.error || !reviews.data) return <ErrorState message={reviews.error || "可信执行复核加载失败"} retry={reviews.reload} />;

  return (
    <>
      {message && <Notice tone={message.includes("失败") ? "warning" : "success"}>{message}</Notice>}
      <Surface
        title="可信执行结果核对"
        note="自动核对通过后仍需审计人员确认；这里展示的是安全聚合快照，不是能源主体原始明细。"
        actions={<Button icon={RefreshCw} onClick={reviews.reload}>刷新</Button>}
      >
        <DataTable
          keyField="review_id"
          rows={reviews.data}
          empty="暂无待人工确认的可信执行结果"
          columns={[
            { key: "request_id", label: "请求", render: (row) => <CodeValue title={row.request_id}>{shortHash(row.request_id, 10)}</CodeValue> },
            { key: "target_data", label: "数据目标", render: (row) => (row.target_data || []).join(" · ") },
            { key: "automatic_status", label: "自动核对", render: (row) => <StatusTag value={row.automatic_status} /> },
            { key: "result_hash", label: "结果哈希", render: (row) => <CodeValue title={row.result_hash}>{shortHash(row.result_hash)}</CodeValue> },
            { key: "created_at", label: "生成时间", render: (row) => formatDate(row.created_at) },
            { key: "action", label: "操作", render: (row) => <Button icon={FileCheck2} busy={busy === `inspect:${row.review_id}`} onClick={() => inspect(row)}>核对</Button> },
          ]}
        />
      </Surface>
      {selected && (
        <Surface
          title="计算准确性复核"
          note={`请求 ${selected.request_id} · 自动状态 ${selected.automatic_status}`}
          actions={<Button onClick={() => setSelected(null)}>收起</Button>}
        >
          <div className="result-summary">
            <div><ShieldCheck size={22} /><span>结果哈希</span><CodeValue>{selected.result_hash}</CodeValue></div>
            <div><CheckCircle2 size={22} /><span>自动检查</span><StatusTag value={selected.automatic_status} /></div>
            <div><FileCheck2 size={22} /><span>人工确认</span><StatusTag value={selected.verification_status} /></div>
          </div>
          <pre className="json-view">{JSON.stringify({ checks: selected.checks, target_data: selected.target_data, source_snapshot: selected.source_snapshot, result: selected.result }, null, 2)}</pre>
          {selected.verification_status === "PENDING" && canConfirm && <Button icon={CheckCircle2} variant="primary" busy={busy === `confirm:${selected.review_id}`} onClick={confirm}>确认计算结果</Button>}
          {selected.verification_status === "PENDING" && !canConfirm && <Notice tone="warning">当前角色可查看核对材料，但只有监管人员或管理员可以确认。</Notice>}
        </Surface>
      )}
    </>
  );
}
