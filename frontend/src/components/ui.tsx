import type { ElementType, ReactNode } from "react";
import { AlertCircle, CheckCircle2, LoaderCircle, X } from "lucide-react";

export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
}: {
  title: string;
  description: string;
  eyebrow?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Surface({
  title,
  note,
  actions,
  children,
  className = "",
}: {
  title?: string;
  note?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`surface ${className}`}>
      {(title || actions) && (
        <div className="surface-header">
          <div>
            {title && <h2>{title}</h2>}
            {note && <p>{note}</p>}
          </div>
          {actions && <div className="surface-actions">{actions}</div>}
        </div>
      )}
      <div className="surface-body">{children}</div>
    </section>
  );
}

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

export function Button({
  children,
  icon: Icon,
  variant = "secondary",
  busy = false,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  icon?: ElementType;
  variant?: ButtonVariant;
  busy?: boolean;
}) {
  return (
    <button className={`button button-${variant}`} {...props} disabled={busy || props.disabled}>
      {busy ? <LoaderCircle className="spin" size={16} /> : Icon ? <Icon size={16} /> : null}
      {children}
    </button>
  );
}

const positive = new Set(["ACTIVE", "VALID", "PASSED", "SUCCESS", "CONFIRMED", "AUDITED", "HEALTHY", "RESOLVED", "GENERATED", "PERMIT", "READY"]);
const warning = new Set(["DRAFT", "PENDING", "AUTHORIZED", "COMPUTING", "EVIDENCED", "RUNNING", "MEDIUM", "REVIEW_REQUIRED"]);
const negative = new Set(["FAILED", "DENY", "HIGH", "OPEN", "INVALID", "REVOKED"]);

export function StatusTag({ value, label }: { value?: string | null; label?: string }) {
  const normalized = String(value || "UNKNOWN").toUpperCase();
  const tone = positive.has(normalized) ? "success" : warning.has(normalized) ? "warning" : negative.has(normalized) ? "danger" : "neutral";
  return <span className={`status-tag status-${tone}`}>{label || value || "未知"}</span>;
}

export function Metric({ label, value, meta, tone = "default" }: { label: string; value: ReactNode; meta?: string; tone?: "default" | "green" | "amber" | "red" }) {
  return (
    <div className={`metric metric-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {meta && <small>{meta}</small>}
    </div>
  );
}

export function DataTable({
  columns,
  rows,
  keyField,
  empty = "暂无数据",
}: {
  columns: Array<{ key: string; label: string; render?: (row: any) => ReactNode; className?: string }>;
  rows: any[];
  keyField: string;
  empty?: string;
}) {
  if (!rows.length) return <EmptyState title={empty} />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column.key} className={column.className}>{column.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[keyField]}>
              {columns.map((column) => <td key={column.key} className={column.className}>{column.render ? column.render(row) : row[column.key] ?? "-"}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LoadingState({ label = "正在加载可信数据" }: { label?: string }) {
  return <div className="state-block"><LoaderCircle className="spin" size={24} /><span>{label}</span></div>;
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="state-block state-error">
      <AlertCircle size={24} />
      <span>{message}</span>
      {retry && <Button onClick={retry}>重试</Button>}
    </div>
  );
}

export function EmptyState({ title }: { title: string }) {
  return <div className="empty-state">{title}</div>;
}

export function Modal({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-header">
          <h2>{title}</h2>
          <button className="icon-button" onClick={onClose} title="关闭"><X size={19} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "success" | "warning"; children: ReactNode }) {
  return <div className={`notice notice-${tone}`}>{tone === "success" && <CheckCircle2 size={17} />}{children}</div>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function CodeValue({ children, title }: { children: ReactNode; title?: string }) {
  return <code className="code-value" title={title}>{children}</code>;
}
