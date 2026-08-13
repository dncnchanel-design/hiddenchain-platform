import { useMemo, useState } from "react";
import { CheckCircle2, Download, FileSignature, RefreshCw, ShieldCheck } from "lucide-react";
import { api, formatDate, formatMoney, post, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { FIELD_SCOPE_LABELS, RESULT_SCOPE_LABELS } from "../types";
import type { JsonRecord } from "../types";

export function ResultsPage() {
  const { session } = useAuth();
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const loader = async () => {
    const [results, orgs] = await Promise.all([api<JsonRecord[]>("/settlement/results"), api<JsonRecord[]>("/system/organizations")]);
    return { results, orgs };
  };
  const { data, loading, error, reload } = useRemote(loader, []);
  const totals = useMemo(() => {
    const orgRows = data?.results.filter((item) => item.result_scope === "ORG") || [];
    return { rows: orgRows.length, amount: orgRows.reduce((sum, item) => sum + Number(item.result_json?.amount_yuan || 0), 0), confirmed: orgRows.filter((item) => item.confirm_status === "CONFIRMED").length };
  }, [data]);

  async function confirm(row: JsonRecord) {
    setBusy(row.result_id);
    setMessage("");
    try {
      await post(`/results/${row.result_id}/confirm`, { opinion: "同意结算结果" });
      setMessage("本方已对结果哈希完成 DID 签名确认。");
      await reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "确认失败");
    } finally {
      setBusy("");
    }
  }

  function exportReceipt(row: JsonRecord) {
    const blob = new Blob([JSON.stringify({ ...row, exported_raw_data: false }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `settlement-receipt-${row.result_id}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "结算结果加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader eyebrow="结果回执可信" title="结果与回执" description="按主体最小披露返回场景结果，多方仅对同一结果哈希签名，链上不保存业务明文。" actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>} />
      <div className="metrics-grid three">
        <div className="metric"><span>主体结果</span><strong>{totals.rows}</strong><small>不含汇总索引</small></div>
        <div className="metric metric-green"><span>已签名确认</span><strong>{totals.confirmed}</strong><small>DID 签名有效</small></div>
        <div className="metric"><span>结果金额合计</span><strong>{formatMoney(totals.amount)}</strong><small>演示假数据</small></div>
      </div>
      {message && <Notice tone={message.includes("失败") ? "warning" : "success"}>{message}</Notice>}
      <Surface title="结果回执清单" note={`当前可见范围：${FIELD_SCOPE_LABELS[session!.field_scopes.settlement_result] || session!.field_scopes.settlement_result}`}>
        <DataTable
          keyField="result_id"
          rows={data.results}
          columns={[
            { key: "task_id", label: "验证任务", render: (row) => <button className="table-link mono-text" onClick={() => setSelected(row)}>{row.task_id}</button> },
            { key: "org_id", label: "结果主体", render: (row) => row.org_id ? data.orgs.find((item) => item.org_id === row.org_id)?.org_name || row.org_id : "平台汇总结果" },
            { key: "result_scope", label: "披露范围", render: (row) => RESULT_SCOPE_LABELS[row.result_scope] || row.result_scope },
            { key: "energy", label: "结算电量", render: (row) => `${row.result_json?.settlement_energy_mwh ?? "-"} MWh` },
            { key: "amount", label: "结算金额", render: (row) => formatMoney(row.result_json?.amount_yuan ?? row.result_json?.payable_amount_yuan) },
            { key: "result_hash", label: "结果哈希", render: (row) => <CodeValue title={row.result_hash}>{shortHash(row.result_hash)}</CodeValue> },
            { key: "confirm_status", label: "确认状态", render: (row) => <StatusTag value={row.confirm_status} /> },
            { key: "created_at", label: "生成时间", render: (row) => formatDate(row.created_at) },
            { key: "action", label: "操作", render: (row) => row.confirm_status !== "CONFIRMED" && ["GENERATOR", "RETAILER", "EXCHANGE"].includes(session!.user.role_code) ? <Button icon={FileSignature} busy={busy === row.result_id} onClick={() => confirm(row)}>签名确认</Button> : <Button icon={Download} onClick={() => exportReceipt(row)}>导出凭证</Button> },
          ]}
        />
      </Surface>
      {selected && <Surface title="结果凭证摘要" actions={<Button onClick={() => setSelected(null)}>收起</Button>}>
        <div className="result-summary">
          <div><ShieldCheck size={22} /><span>结果哈希</span><CodeValue>{selected.result_hash}</CodeValue></div>
          <div><CheckCircle2 size={22} /><span>多方确认</span><StatusTag value={selected.confirm_status} /></div>
          <div><FileSignature size={22} /><span>披露范围</span><strong>{RESULT_SCOPE_LABELS[selected.result_scope] || selected.result_scope}</strong></div>
        </div>
        <Notice tone="success">该凭证仅包含结果与可验证引用，不含双方计量明细或用户用电记录。</Notice>
      </Surface>}
    </>
  );
}
