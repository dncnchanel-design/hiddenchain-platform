import { Download, FileSpreadsheet, RefreshCw, ShieldCheck, UploadCloud } from "lucide-react";
import { useState } from "react";
import { api, postForm } from "../api";
import { useAuth } from "../auth";
import { Button, DataTable, DateTimeText, Field, IdText, Metric, MetricStrip, Notice, PageHeader, StatusTag, Surface } from "../components/ui";
import { useRemote } from "../hooks";
import type { JsonRecord } from "../types";

type ExcelSheetSummary = {
  name: string;
  row_count: number;
  allowed_asset_types: string[];
};

type ExcelValidationError = {
  sheet: string;
  row: number;
  field: string;
  message: string;
};

type ExcelValidation = {
  valid: boolean;
  file_name: string;
  file_digest: string | null;
  role_code: string;
  owner_org_id: string;
  sheet_count: number;
  row_count: number;
  imported_count: number;
  idempotent_replay: boolean;
  sheets: ExcelSheetSummary[];
  errors: ExcelValidationError[];
};

const MAX_FILE_BYTES = 8 * 1024 * 1024;
const assetNames: Record<string, string> = {
  GENERATION_DATA: "发电计量",
  RENEWABLE_FORECAST: "新能源预测",
  RETAIL_DATA: "售电履约",
  USER_LOAD_CURVE: "用户负荷曲线",
  VPP_RESOURCE: "虚拟电厂资源",
  GRID_CONSTRAINT: "调度安全边界",
};
const roleRules: Record<string, string> = {
  GENERATOR: "发电企业可上传发电计量、新能源预测。",
  RETAILER: "售电企业可上传售电履约、用户负荷、虚拟电厂资源。",
  EXCHANGE: "交易中心可上传调度安全边界，并查看其他数据资产。",
  REGULATOR: "监管角色仅可查看导入记录，不能执行上传。",
  ADMIN: "管理员可通过 Excel 受控批量导入全部模板类型，数据归属当前管理员组织。",
};

function formatFileSize(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function buildForm(file: File) {
  const form = new FormData();
  form.append("file", file, file.name);
  return form;
}

export function ExcelUploadPage() {
  const { session } = useAuth();
  const role = session!.user.role_code;
  const canUpload = ["GENERATOR", "RETAILER", "EXCHANGE", "ADMIN"].includes(role);
  const [file, setFile] = useState<File | null>(null);
  const [validation, setValidation] = useState<ExcelValidation | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [fileError, setFileError] = useState("");
  const { data: uploads, loading, refreshing, error, reload } = useRemote<JsonRecord[]>(
    (signal) => api("/data/uploads", { signal, timeoutMs: 12000, cache: "no-store" }),
    [],
  );

  function chooseFile(next: File | null) {
    setNotice("");
    setValidation(null);
    setFileError("");
    if (!next) {
      setFile(null);
      return;
    }
    if (!next.name.toLowerCase().endsWith(".xlsx")) {
      setFile(null);
      setFileError("只支持 .xlsx 格式的 Excel 文件。");
      return;
    }
    if (next.size > MAX_FILE_BYTES) {
      setFile(null);
      setFileError("Excel 文件不能超过 8 MB。");
      return;
    }
    setFile(next);
  }

  async function validateAndImport() {
    if (!file || !canUpload) return;
    setBusy(true);
    setNotice("");
    setValidation(null);
    try {
      const checked = await postForm<ExcelValidation>("/data/uploads/excel/validate", buildForm(file));
      setValidation(checked);
      if (!checked.valid) {
        setNotice(`校验未通过，共发现 ${checked.errors.length} 个问题；未写入数据。`);
        return;
      }
      const imported = await postForm<ExcelValidation>("/data/uploads/excel/import", buildForm(file));
      setValidation(imported);
      setNotice(imported.idempotent_replay
        ? "该 Excel 批次已经导入过，系统返回了幂等结果，未产生重复数据。"
        : `Excel 批量导入完成，共写入 ${imported.imported_count} 条数据资产。`);
      await reload();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "Excel 批量导入失败。");
    } finally {
      setBusy(false);
    }
  }

  const validationErrors = (validation?.errors || []).map((item, index) => ({ ...item, key: `${item.sheet}-${item.row}-${item.field}-${index}` }));
  const recentUploads = (uploads || []).slice(0, 100);

  return (
    <>
      <PageHeader
        title="Excel 批量上传"
        description="按统一工作簿导入数据资产；系统会先校验全部工作表，全部通过后才一次性提交。"
        actions={<><a className="button button-secondary" href="/sample-data/hiddenchain-excel-batch-data.xlsx" download><Download size={16} />下载示例数据</a><Button icon={RefreshCw} busy={refreshing} onClick={reload}>刷新记录</Button></>}
      />

      {notice && <Notice tone={notice.includes("失败") || notice.includes("未通过") ? "warning" : "success"}>{notice}</Notice>}
      {!canUpload && <Notice tone="info">{roleRules[role] || "当前角色仅可查看导入记录。"}</Notice>}

      <MetricStrip columns={4}>
        <Metric label="工作表" value={validation?.sheet_count || 0} meta="标准模板共 10 组" />
        <Metric label="数据行" value={validation?.row_count || 0} meta="单次最多 5,000 行" />
        <Metric label="校验错误" value={validation?.errors.length || 0} tone={validation?.errors.length ? "red" : "green"} />
        <Metric label="当前状态" value={<StatusTag value={validation?.valid ? "PASSED" : file ? "PENDING" : "NOT_PROVIDED"} />} />
      </MetricStrip>

      <Surface title="选择 Excel 工作簿" meta="支持 .xlsx，最大 8 MB">
        <div className="upload-file-panel">
          <div className="upload-file-control">
            <FileSpreadsheet size={25} aria-hidden="true" />
            <Field label="Excel 文件" hint="标准工作簿应包含 10 个数据组工作表，每组建议 100 条记录。" error={fileError}>
              <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => chooseFile(event.target.files?.[0] || null)} disabled={!canUpload || busy} />
            </Field>
            {file && <div className="upload-file-meta"><strong>{file.name}</strong><span>{formatFileSize(file.size)}</span></div>}
          </div>
          <div className="upload-file-actions">
            <div className="upload-scope"><ShieldCheck size={17} /><span>{roleRules[role] || "当前角色按后端权限执行校验。"}</span></div>
            <Button icon={UploadCloud} variant="primary" busy={busy} disabled={!file || !canUpload} onClick={validateAndImport}>校验并导入</Button>
          </div>
        </div>
      </Surface>

      <Surface title="工作表校验结果" meta={validation ? `${validation.sheet_count} 张工作表 / ${validation.row_count} 行` : "等待选择文件"}>
        {validation?.sheets?.length ? (
          <DataTable
            keyField="name"
            rows={validation.sheets}
            label="工作表校验结果"
            columns={[
              { key: "name", label: "工作表", minWidth: 150 },
              { key: "row_count", label: "数据行", align: "right" },
              { key: "allowed_asset_types", label: "允许资产类型", minWidth: 250, render: (row) => row.allowed_asset_types.map((type) => assetNames[type] || type).join("、") },
              { key: "status", label: "状态", render: () => <StatusTag value={validation.valid ? "PASSED" : "FAILED"} /> },
            ]}
          />
        ) : <div className="empty-state"><FileSpreadsheet size={23} /><strong>尚未校验工作簿</strong><span>选择文件后点击“校验并导入”，系统会列出所有工作表和错误行。</span></div>}
      </Surface>

      {validationErrors.length > 0 && <Surface title="校验错误" meta={`${validationErrors.length} 条，最多展示 500 条`}>
        <DataTable
          keyField="key"
          rows={validationErrors}
          label="Excel 校验错误"
          columns={[
            { key: "sheet", label: "工作表", minWidth: 130 },
            { key: "row", label: "行号", align: "right" },
            { key: "field", label: "字段", minWidth: 150 },
            { key: "message", label: "错误原因", minWidth: 320 },
          ]}
        />
      </Surface>}

      <Surface title="最近数据资产" meta={loading ? "正在读取" : `${recentUploads.length} 条`}>
        <DataTable
          keyField="upload_id"
          rows={recentUploads}
          loading={loading}
          error={error || (!loading && !uploads ? "数据加载失败" : "")}
          onRetry={reload}
          label="最近数据资产"
          columns={[
            { key: "label", label: "数据资产", minWidth: 210 },
            { key: "asset_type", label: "资产类型", minWidth: 150, render: (row) => assetNames[row.asset_type] || row.asset_type || "—" },
            { key: "owner_org_name", label: "数据提供方", minWidth: 160 },
            { key: "trade_batch_no", label: "批次编号", minWidth: 150, render: (row) => <IdText value={row.trade_batch_no} length={8} /> },
            { key: "summary_json", label: "功能覆盖", minWidth: 220, render: (row) => row.summary_json?.excel_import?.function_scope || "—" },
            { key: "validation_status", label: "校验状态", render: (row) => <StatusTag value={row.validation_status} /> },
            { key: "created_at", label: "登记时间", minWidth: 165, render: (row) => <DateTimeText value={row.created_at} /> },
          ]}
        />
      </Surface>
    </>
  );
}
