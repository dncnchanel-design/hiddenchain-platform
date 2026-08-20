import { useMemo, useRef, useState } from "react";
import { ArrowLeft, Eye, FileSignature, RefreshCw } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api, formatMoney, formatNumber, post, prepareIdempotencyKey, type IdempotencyKeyRecord } from "../api";
import { useAuth } from "../auth";
import { AmountText, Button, ConfirmDialog, DataTable, DateTimeText, DetailDrawer, ErrorState, IdText, LoadingState, Metric, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { RESULT_SCOPE_LABELS, type JsonRecord, type ResultConfirmationCommand } from "../types";

const amountDirectionLabels: Record<string, string> = {
  RECEIVABLE: "应收",
  PAYABLE: "应付",
};

export function ResultsPage() {
  const { session } = useAuth();
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get("task_id") || "";
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<JsonRecord | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const taskEtagsRef = useRef(new Map<string, string>());
  const confirmationKeysRef = useRef(new Map<string, IdempotencyKeyRecord>());
  const loader = async (signal?: AbortSignal) => {
    const request = { signal, timeoutMs: 12000, cache: "no-store" as RequestCache };
    const [results, orgs, task] = await Promise.all([
      api<JsonRecord[]>(taskId ? `/settlement/results?task_id=${encodeURIComponent(taskId)}` : "/settlement/results", request),
      api<JsonRecord[]>("/system/organizations", request),
      taskId
        ? api<JsonRecord>(`/settlement/tasks/${taskId}`, {
          ...request,
          onResponseMetadata: (metadata) => {
            if (metadata.etag) taskEtagsRef.current.set(taskId, metadata.etag);
          },
        })
        : Promise.resolve(null),
    ]);
    return { results, orgs, task };
  };
  const { data, loading, refreshing, error, reload } = useRemote(loader, [taskId]);
  const totals = useMemo(() => {
    const orgRows = data?.results.filter((item) => item.result_scope === "ORG") || [];
    const summaryRows = data?.results.filter((item) => item.result_scope === "SUMMARY") || [];
    const amountRows = summaryRows.length ? summaryRows : orgRows;
    return {
      rows: orgRows.length,
      amount: amountRows.reduce((sum, item) => sum + Number(item.result_json?.amount_yuan ?? item.result_json?.payable_amount_yuan ?? 0), 0),
      amountLabel: summaryRows.length ? "任务结算金额" : "本主体结果金额",
      confirmed: orgRows.filter((item) => item.confirm_status === "CONFIRMED").length,
    };
  }, [data]);

  async function confirm(row: JsonRecord) {
    setBusy(row.result_id);
    setMessage("");
    try {
      const rowTaskId = String(row.task_id || taskId);
      let etag = taskEtagsRef.current.get(rowTaskId);
      if (!etag) {
        await api<JsonRecord>(`/settlement/tasks/${rowTaskId}`, {
          cache: "no-store",
          timeoutMs: 12_000,
          onResponseMetadata: (metadata) => {
            if (metadata.etag) taskEtagsRef.current.set(rowTaskId, metadata.etag);
          },
        });
        etag = taskEtagsRef.current.get(rowTaskId);
      }
      const payload: ResultConfirmationCommand = {
        decision: "APPROVE",
        opinion: "同意结算结果",
      };
      const fingerprint = JSON.stringify({ resultId: row.result_id, resultHash: row.result_hash, payload, etag });
      const requestKey = prepareIdempotencyKey(confirmationKeysRef.current.get(row.result_id), `result-confirm:${row.result_id}`, fingerprint);
      confirmationKeysRef.current.set(row.result_id, requestKey);
      await post(`/results/${row.result_id}/confirm`, payload, {
        idempotencyKey: requestKey.key,
        ifMatch: etag,
        onResponseMetadata: (metadata) => {
          if (metadata.etag) taskEtagsRef.current.set(rowTaskId, metadata.etag);
        },
      });
      setMessage("结果回执已签名确认。");
      await reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "确认失败");
    } finally {
      setBusy("");
    }
  }

  if (loading) return <LoadingState label="正在加载结果回执" variant="page" />;
  if (error || !data) return <ErrorState message={error || "结果回执加载失败"} retry={reload} />;

  const canConfirm = ["GENERATOR", "RETAILER"].includes(session!.user.role_code);
  return (
    <>
      <PageHeader title="结算结果" actions={<>{taskId && <Link className="button button-secondary" to={`/settlements/${taskId}`}><ArrowLeft size={16} />返回结算任务</Link>}<Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新</Button></>} />
      {taskId && <div className="association-context"><span>关联结算任务</span><Link to={`/settlements/${taskId}`}>{taskId}</Link></div>}
      <div className="metrics-grid three">
        <Metric label="主体结果" value={totals.rows} />
        <Metric label="已确认" value={totals.confirmed} tone="green" />
        <Metric label={totals.amountLabel} value={formatMoney(totals.amount)} />
      </div>
      {message && <Notice tone={message.includes("失败") ? "warning" : "success"}>{message}</Notice>}
      <Surface title="结果与回执" meta={`${data.results.length} 项`}>
        <DataTable
          keyField="result_id" rows={data.results} label="结果与回执列表"
          columns={[
            { key: "task_id", label: "结算任务", minWidth: 155, render: (row) => <Link className="table-link" to={`/settlements/${row.task_id}`}><IdText value={row.task_id} copyable={false} /></Link> },
            { key: "org_id", label: "结果主体", minWidth: 150, render: (row) => row.org_id ? data.orgs.find((item) => item.org_id === row.org_id)?.org_name || <IdText value={row.org_id} /> : "平台汇总结果" },
            { key: "result_scope", label: "结果类型", render: (row) => RESULT_SCOPE_LABELS[row.result_scope] || row.result_scope || "—" },
            { key: "energy", label: "场景电量", align: "right", render: (row) => row.result_json?.settlement_energy_mwh === undefined ? "—" : `${formatNumber(row.result_json.settlement_energy_mwh, 2)} MWh` },
            { key: "amount", label: "场景金额", align: "right", minWidth: 130, render: (row) => <AmountText value={row.result_json?.amount_yuan ?? row.result_json?.payable_amount_yuan} /> },
            { key: "amount_direction", label: "收付方向", render: (row) => row.result_scope === "SUMMARY" ? "任务汇总" : amountDirectionLabels[row.result_json?.amount_direction] || "未标注" },
            { key: "result_hash", label: "结果摘要", minWidth: 155, render: (row) => <IdText value={row.result_hash} /> },
            { key: "confirm_status", label: "确认状态", render: (row) => <StatusTag value={row.confirm_status} /> },
            { key: "created_at", label: "生成时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
            { key: "action", label: "操作", sortable: false, hideable: false, sticky: "right", minWidth: 96, render: (row) => <div className="inline-actions">{row.confirm_status === "UNCONFIRMED" && row.org_id === session!.user.org_id && canConfirm && <Button icon={FileSignature} busy={busy === row.result_id} onClick={() => setConfirmTarget(row)}>签名确认</Button>}<Button icon={Eye} onClick={() => setSelected(row)}>详情</Button></div> },
          ]}
        />
      </Surface>

      {selected && <DetailDrawer title="结果回执详情" onClose={() => setSelected(null)} footer={<Button onClick={() => setSelected(null)}>关闭</Button>}>
        <div className="detail-grid">
          <div><span>结果编号</span><IdText value={selected.result_id} /></div>
          <div><span>关联任务</span><Link className="text-link" to={`/settlements/${selected.task_id}`}><IdText value={selected.task_id} /></Link></div>
          <div><span>结果类型</span><strong>{RESULT_SCOPE_LABELS[selected.result_scope] || selected.result_scope || "—"}</strong></div>
          <div><span>结果主体</span><strong>{selected.org_id ? data.orgs.find((item) => item.org_id === selected.org_id)?.org_name || "当前主体" : "平台汇总结果"}</strong></div>
          <div><span>收付方向</span><strong>{selected.result_scope === "SUMMARY" ? "任务汇总" : amountDirectionLabels[selected.result_json?.amount_direction] || "未标注"}</strong></div>
          <div><span>确认状态</span><StatusTag value={selected.confirm_status} /></div>
          <div><span>结果摘要</span><IdText value={selected.result_hash} /></div>
          <div><span>生成时间</span><DateTimeText value={selected.created_at} /></div>
        </div>
        <div className="detail-section"><h3>结果数据</h3><div className="parameter-grid">{Object.entries(selected.result_json || {}).map(([key, value]) => <div key={key}><span>{key}</span><strong>{typeof value === "object" ? JSON.stringify(value) : String(value)}</strong></div>)}</div></div>
      </DetailDrawer>}

      <ConfirmDialog
        open={Boolean(confirmTarget)} title="确认结果回执" objectName={confirmTarget?.result_id || "—"}
        currentState={confirmTarget?.confirm_status} consequence="确认后将使用当前主体身份对结果摘要签名，并把确认意见写入审计记录。"
        confirmLabel="签名确认" busy={Boolean(confirmTarget && busy === confirmTarget.result_id)} onCancel={() => setConfirmTarget(null)}
        onConfirm={async () => { if (!confirmTarget) return; await confirm(confirmTarget); setConfirmTarget(null); }}
      />
    </>
  );
}
