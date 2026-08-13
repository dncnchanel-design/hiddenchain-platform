import { useMemo, useState } from "react";
import { Download, Eye, FileCheck2, FilePlus2, RefreshCw, ShieldCheck } from "lucide-react";
import { api, formatDate, post, shortHash } from "../api";
import { useAuth } from "../auth";
import { Button, CodeValue, DataTable, ErrorState, LoadingState, Modal, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import { REPORT_TEMPLATE_LABELS } from "../types";
import type { JsonRecord } from "../types";

export function ReportsPage() {
  const { session } = useAuth();
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [taskId, setTaskId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const canGenerate = ["REGULATOR", "ADMIN"].includes(session!.user.role_code);
  const loader = async () => {
    const [reports, tasks] = await Promise.all([api<JsonRecord[]>("/audit/reports"), api<JsonRecord[]>("/settlement/tasks")]);
    return { reports, tasks };
  };
  const { data, loading, error, reload } = useRemote(loader, []);
  const audited = useMemo(() => data?.tasks.filter((item) => item.status === "AUDITED") || [], [data]);

  async function generate() {
    const id = taskId || audited[0]?.task_id;
    if (!id) return;
    setBusy(true);
    setMessage("");
    try {
      await post("/audit/reports", { task_id: id, template_code: "REGULATORY_AUDIT_V1" });
      setMessage("可信审计报告已生成，报告哈希与证据引用已固化。");
      await reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "生成失败");
    } finally {
      setBusy(false);
    }
  }

  function exportReport(report: JsonRecord) {
    const blob = new Blob([report.report_content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${report.report_title}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (loading) return <LoadingState />;
  if (error || !data) return <ErrorState message={error || "报告加载失败"} retry={reload} />;

  return (
    <>
      <PageHeader eyebrow="可信成果输出" title="可信报告" description="报告 Agent 仅基于审计包和证据引用套用模板，结论由确定性核验规则给出并绑定报告哈希。" actions={<Button icon={RefreshCw} onClick={reload}>刷新</Button>} />
      {canGenerate && <Surface title="生成监管审计报告" note="仅对已完成可信闭环的任务生成">
        <div className="report-generator"><select value={taskId} onChange={(event) => setTaskId(event.target.value)}><option value="">选择已审计任务</option>{audited.map((item) => <option key={item.task_id} value={item.task_id}>{item.capsule_id} · {item.task_name}</option>)}</select><Button icon={FilePlus2} variant="primary" busy={busy} disabled={!taskId && !audited.length} onClick={generate}>生成报告</Button></div>
      </Surface>}
      {message && <Notice tone={message.includes("失败") ? "warning" : "success"}>{message}</Notice>}
      <Surface title="报告归档" note={`${data.reports.length} 份可验证报告`}>
        <DataTable
          keyField="report_id"
          rows={data.reports}
          columns={[
            { key: "report_title", label: "报告名称" },
            { key: "task_id", label: "关联任务", render: (row) => <span className="mono-text">{row.task_id}</span> },
            { key: "template_code", label: "模板", render: (row) => REPORT_TEMPLATE_LABELS[row.template_code] || row.template_code },
            { key: "evidence_refs_json", label: "证据引用", render: (row) => `${row.evidence_refs_json?.length || 0} 项` },
            { key: "report_hash", label: "报告哈希", render: (row) => <CodeValue title={row.report_hash}>{shortHash(row.report_hash)}</CodeValue> },
            { key: "risk_level", label: "风险结论", render: (row) => <StatusTag value={row.risk_level} /> },
            { key: "created_at", label: "生成时间", render: (row) => formatDate(row.created_at) },
            { key: "action", label: "操作", render: (row) => <div className="inline-actions"><button className="icon-button" title="查看报告" onClick={() => setSelected(row)}><Eye size={17} /></button><button className="icon-button" title="导出报告" onClick={() => exportReport(row)}><Download size={17} /></button></div> },
          ]}
        />
      </Surface>
      {selected && <Modal title={selected.report_title} onClose={() => setSelected(null)} footer={<><Button icon={Download} onClick={() => exportReport(selected)}>导出报告</Button><Button onClick={() => setSelected(null)}>关闭</Button></>}>
        <div className="report-proof"><ShieldCheck size={20} /><div><span>ReportHash</span><CodeValue>{selected.report_hash}</CodeValue></div><StatusTag value={selected.risk_level} label={selected.risk_level === "LOW" ? "审计通过" : "需要复核"} /></div>
        <pre className="report-content">{selected.report_content}</pre>
        <div className="citation-list">{(selected.evidence_refs_json || []).map((item: string) => <span key={item}><FileCheck2 size={13} />{shortHash(item, 9)}</span>)}</div>
      </Modal>}
    </>
  );
}
