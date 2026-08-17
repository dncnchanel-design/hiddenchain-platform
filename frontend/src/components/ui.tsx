import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ElementType,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Columns3,
  Copy,
  Inbox,
  LoaderCircle,
  X,
} from "lucide-react";
import { useAuth } from "../auth";
import type { RoleCode } from "../types";
import { STATUS_LABELS } from "../types";

const MISSING_VALUE = "—";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div className="page-heading">
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function SectionHeader({ title, description, icon: Icon }: { title: string; description?: string; icon?: ElementType }) {
  return (
    <div className="section-title">
      {Icon && <Icon size={19} aria-hidden="true" />}
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
    </div>
  );
}

export function Surface({
  title,
  meta,
  actions,
  children,
  className = "",
  id,
}: {
  title?: string;
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`surface ${className}`.trim()}>
      {(title || meta || actions) && (
        <div className="surface-header">
          <div className="surface-heading">
            {title && <h2>{title}</h2>}
            {meta && <span className="surface-meta">{meta}</span>}
          </div>
          {actions && <div className="surface-actions">{actions}</div>}
        </div>
      )}
      <div className="surface-body">{children}</div>
    </section>
  );
}

export function FilterBar({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="filter-bar shared-filter-bar">
      <div className="filter-fields">{children}</div>
      {actions && <div className="filter-actions">{actions}</div>}
    </div>
  );
}

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

export function Button({
  children,
  icon: Icon,
  variant = "secondary",
  busy = false,
  onClick,
  ...props
}: Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onClick"> & {
  icon?: ElementType;
  variant?: ButtonVariant;
  busy?: boolean;
  onClick?: (event: MouseEvent<HTMLButtonElement>) => void | Promise<unknown>;
}) {
  const [pending, setPending] = useState(false);
  const isBusy = busy || pending;

  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    const result = onClick?.(event);
    if (!result || typeof (result as PromiseLike<unknown>).then !== "function") return;
    setPending(true);
    void Promise.resolve(result).finally(() => setPending(false)).catch(() => undefined);
  }

  return (
    <button
      className={`button button-${variant}${isBusy ? " is-busy" : ""}`}
      aria-busy={isBusy || undefined}
      {...props}
      onClick={handleClick}
      disabled={isBusy || props.disabled}
    >
      {isBusy ? <LoaderCircle className="spin" size={16} /> : Icon ? <Icon size={16} /> : null}
      {children}
    </button>
  );
}

const positive = new Set(["ACTIVE", "VALID", "PASSED", "SUCCESS", "CONFIRMED", "AUDITED", "HEALTHY", "RESOLVED", "GENERATED", "PERMIT", "READY", "LOW", "RECORDED", "NOT_REQUIRED"]);
const information = new Set(["RUNNING", "PROCESSING", "IN_PROGRESS"]);
const currentSelection = new Set(["CURRENT"]);
const warning = new Set(["DRAFT", "PENDING", "BLOCKED", "MEDIUM", "REVIEW_REQUIRED", "UNCONFIRMED", "PENDING_CONFIRMATION", "PARTIALLY_CONFIRMED", "UNVERIFIED", "NOT_PROVIDED", "NOT_CONFIGURED"]);
const negative = new Set(["FAILED", "EXCEPTION", "DENY", "HIGH", "OPEN", "INVALID", "REVOKED", "REJECTED"]);

export function StatusTag({ value, label }: { value?: string | null; label?: string }) {
  const normalized = String(value || "UNKNOWN").toUpperCase();
  const tone = positive.has(normalized) ? "success"
    : information.has(normalized) ? "info"
      : currentSelection.has(normalized) ? "brand"
        : warning.has(normalized) ? "warning"
          : negative.has(normalized) ? "danger"
            : "neutral";
  return <span className={`status-tag status-${tone}`}>{label || STATUS_LABELS[normalized] || value || "未知"}</span>;
}

export function RiskLevelTag({ value }: { value?: string | null }) {
  return <StatusTag value={value} />;
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

export function MetricStrip({ children, columns = 4 }: { children: ReactNode; columns?: 2 | 3 | 4 | 5 }) {
  return <div className={`metrics-grid metric-strip columns-${columns}`}>{children}</div>;
}

export type DataColumn<Row = any> = {
  key: string;
  label: string;
  render?: (row: Row) => ReactNode;
  sortValue?: (row: Row) => unknown;
  className?: string;
  align?: "left" | "center" | "right";
  width?: number | string;
  minWidth?: number | string;
  sortable?: boolean;
  hideable?: boolean;
  sticky?: boolean | "left" | "right";
};

function compareValues(left: unknown, right: unknown): number {
  if (left === right) return 0;
  if (left === null || left === undefined || left === "") return 1;
  if (right === null || right === undefined || right === "") return -1;
  if (typeof left === "number" && typeof right === "number") return left - right;
  return String(left).localeCompare(String(right), "zh-CN", { numeric: true, sensitivity: "base" });
}

function isPrimitive(value: unknown): boolean {
  return value === null || value === undefined || ["string", "number", "boolean"].includes(typeof value);
}

export function DataTable<Row extends Record<string, any>>({
  columns,
  rows,
  keyField,
  empty = "暂无数据",
  label = "数据列表",
  pageSize: initialPageSize = 20,
  pageSizeOptions = [20, 50, 100],
  stickyFirstColumn = true,
  loading = false,
  error = "",
  onRetry,
}: {
  columns: DataColumn<Row>[];
  rows: Row[];
  keyField: string;
  empty?: string;
  label?: string;
  pageSize?: number;
  pageSizeOptions?: number[];
  stickyFirstColumn?: boolean;
  loading?: boolean;
  error?: string;
  onRetry?: () => void | Promise<unknown>;
}) {
  const rowSignature = `${rows.length}:${String(rows[0]?.[keyField] ?? "")}:${String(rows[rows.length - 1]?.[keyField] ?? "")}`;
  const columnSignature = columns.map((column) => column.key).join("|");
  const [pageState, setPageState] = useState({ value: 1, signature: rowSignature });
  const [pageSize, setPageSize] = useState(initialPageSize);
  const [sort, setSort] = useState<{ key: string; direction: "asc" | "desc" } | null>(null);
  const [visibility, setVisibility] = useState(() => ({ signature: columnSignature, keys: new Set(columns.map((column) => column.key)) }));
  const visibleKeys = visibility.signature === columnSignature ? visibility.keys : new Set(columns.map((column) => column.key));

  const visibleColumns = columns.filter((column) => visibleKeys.has(column.key));
  const sortableKeys = useMemo(() => new Set(columns.filter((column) => {
    if (column.sortable === false) return false;
    if (column.sortValue || column.sortable === true) return true;
    return rows.some((row) => isPrimitive(row[column.key]) && row[column.key] !== undefined);
  }).map((column) => column.key)), [columns, rows]);

  const sortedRows = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((item) => item.key === sort.key);
    if (!column) return rows;
    return [...rows].sort((left, right) => {
      const leftValue = column.sortValue ? column.sortValue(left) : left[column.key];
      const rightValue = column.sortValue ? column.sortValue(right) : right[column.key];
      const result = compareValues(leftValue, rightValue);
      return sort.direction === "asc" ? result : -result;
    });
  }, [columns, rows, sort]);

  const totalPages = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const requestedPage = pageState.signature === rowSignature ? pageState.value : 1;
  const safePage = Math.min(requestedPage, totalPages);
  const startIndex = (safePage - 1) * pageSize;
  const pageRows = sortedRows.slice(startIndex, startIndex + pageSize);

  function changeSort(column: DataColumn<Row>) {
    if (!sortableKeys.has(column.key)) return;
    setSort((current) => current?.key === column.key
      ? current.direction === "asc" ? { key: column.key, direction: "desc" } : null
      : { key: column.key, direction: "asc" });
  }

  function toggleColumn(key: string) {
    setVisibility(() => {
      const next = new Set(visibleKeys);
      if (next.has(key) && next.size > 1) next.delete(key);
      else next.add(key);
      return { signature: columnSignature, keys: next };
    });
  }

  function changePageSize(value: number) {
    setPageSize(value);
    setPageState({ value: 1, signature: rowSignature });
  }

  function changePage(value: number) {
    setPageState({ value, signature: rowSignature });
  }

  if (loading) return <LoadingState label="正在加载列表" variant="table" />;
  if (error) return <ErrorState message={error} retry={onRetry} />;
  if (!rows.length) return <EmptyState title={empty} />;

  return (
    <div className="data-table">
      <div className="table-toolbar">
        <span>共 {rows.length} 条</span>
        {columns.filter((column) => column.hideable !== false).length > 1 && (
          <details className="column-picker">
            <summary><Columns3 size={15} />列设置</summary>
            <div>
              {columns.map((column) => (
                <label key={column.key}>
                  <input
                    type="checkbox"
                    checked={visibleKeys.has(column.key)}
                    disabled={column.hideable === false || (visibleKeys.has(column.key) && visibleKeys.size === 1)}
                    onChange={() => toggleColumn(column.key)}
                  />
                  <span>{column.label}</span>
                </label>
              ))}
            </div>
          </details>
        )}
      </div>
      <div className="table-wrap" role="region" aria-label={label} tabIndex={0}>
        <table>
          <thead>
            <tr>
              {visibleColumns.map((column, index) => {
                const sortable = sortableKeys.has(column.key);
                const activeSort = sort?.key === column.key ? sort.direction : undefined;
                const stickySide = column.sticky === "right" ? "right"
                  : column.sticky === true || column.sticky === "left" || (column.sticky === undefined && stickyFirstColumn && index === 0) ? "left"
                    : null;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={activeSort === "asc" ? "ascending" : activeSort === "desc" ? "descending" : sortable ? "none" : undefined}
                    className={`${column.className || ""}${stickySide ? ` table-sticky-column table-sticky-${stickySide}` : ""}${column.align ? ` align-${column.align}` : ""}`.trim()}
                    style={{ width: column.width, minWidth: column.minWidth }}
                  >
                    {sortable ? (
                      <button type="button" onClick={() => changeSort(column)}>
                        <span>{column.label}</span>
                        <span className="sort-indicator" aria-hidden="true">{activeSort === "asc" ? "↑" : activeSort === "desc" ? "↓" : "↕"}</span>
                      </button>
                    ) : column.label}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, rowIndex) => (
              <tr key={String(row[keyField] ?? `${keyField}-${startIndex + rowIndex}`)}>
                {visibleColumns.map((column, index) => {
                  const stickySide = column.sticky === "right" ? "right"
                    : column.sticky === true || column.sticky === "left" || (column.sticky === undefined && stickyFirstColumn && index === 0) ? "left"
                      : null;
                  return (
                    <td
                      key={column.key}
                      className={`${column.className || ""}${stickySide ? ` table-sticky-column table-sticky-${stickySide}` : ""}${column.align ? ` align-${column.align}` : ""}`.trim()}
                      style={{ width: column.width, minWidth: column.minWidth }}
                    >
                      {column.render ? column.render(row) : row[column.key] ?? MISSING_VALUE}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-pagination" aria-label="分页">
        <span>显示 {startIndex + 1}-{Math.min(startIndex + pageSize, rows.length)} / {rows.length}</span>
        <label>每页
          <select value={pageSize} onChange={(event) => changePageSize(Number(event.target.value))}>
            {pageSizeOptions.map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
        <div>
          <button type="button" disabled={safePage <= 1} onClick={() => changePage(Math.max(1, safePage - 1))} aria-label="上一页"><ChevronLeft size={15} /></button>
          <span>第 {safePage} / {totalPages} 页</span>
          <button type="button" disabled={safePage >= totalPages} onClick={() => changePage(Math.min(totalPages, safePage + 1))} aria-label="下一页"><ChevronRight size={15} /></button>
        </div>
      </div>
    </div>
  );
}

export function LoadingState({ label = "正在加载", variant = "inline" }: { label?: string; variant?: "inline" | "page" | "table" }) {
  if (variant === "table") {
    return (
      <div className="table-skeleton" role="status" aria-live="polite">
        <span className="sr-only">{label}</span>
        <div className="skeleton-toolbar" />
        {Array.from({ length: 6 }, (_, index) => <div className="skeleton-row" key={index}><i /><i /><i /><i /></div>)}
      </div>
    );
  }
  if (variant === "page") {
    return (
      <div className="page-skeleton" role="status" aria-live="polite">
        <span className="sr-only">{label}</span>
        <div className="skeleton-title" />
        <div className="skeleton-panel" />
        <div className="skeleton-panel short" />
      </div>
    );
  }
  return <div className="state-block" role="status" aria-live="polite"><LoaderCircle className="spin" size={22} /><span>{label}</span></div>;
}

export function ErrorState({ message, retry, traceId }: { message: string; retry?: () => void | Promise<unknown>; traceId?: string }) {
  return (
    <div className="state-block state-error" role="alert">
      <AlertCircle size={24} />
      <div><strong>加载失败</strong><span>{message}</span>{traceId && <small>Trace ID：{traceId}</small>}</div>
      {retry && <Button onClick={retry}>重试</Button>}
    </div>
  );
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return <div className="empty-state"><Inbox size={24} /><strong>{title}</strong>{description && <span>{description}</span>}</div>;
}

function useDialogFocus(ref: RefObject<HTMLElement | null>, onClose: () => void, closeDisabled = false) {
  const onCloseRef = useRef(onClose);
  const closeDisabledRef = useRef(closeDisabled);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    closeDisabledRef.current = closeDisabled;
  }, [closeDisabled]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    const selector = "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])";
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(selector)).filter((element) => element.offsetParent !== null);

    document.body.style.overflow = "hidden";
    window.setTimeout(() => focusable()[0]?.focus(), 0);

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!closeDisabledRef.current) onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusable();
      if (!elements.length) return;
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, [ref]);
}

export function Modal({
  title,
  onClose,
  children,
  footer,
  className = "",
  closeDisabled = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  closeDisabled?: boolean;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogFocus(dialogRef, onClose, closeDisabled);

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => !closeDisabled && event.target === event.currentTarget && onClose()}>
      <div ref={dialogRef} className={`modal ${className}`.trim()} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-busy={closeDisabled || undefined}>
        <div className="modal-header">
          <h2 id={titleId}>{title}</h2>
          <button className="icon-button" type="button" onClick={onClose} disabled={closeDisabled} aria-label={closeDisabled ? "操作处理中，暂时无法关闭" : "关闭"}><X size={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

export function DetailDrawer({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const titleId = useId();
  const drawerRef = useRef<HTMLElement>(null);
  useDialogFocus(drawerRef, onClose);
  return (
    <div className="detail-drawer-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside ref={drawerRef} className="detail-drawer" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header><h2 id={titleId}>{title}</h2><button className="icon-button" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button></header>
        <div className="detail-drawer-body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </aside>
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  objectName,
  currentState,
  consequence,
  confirmLabel = "确认",
  danger = false,
  busy = false,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  objectName: string;
  currentState?: string;
  consequence: string;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void | Promise<unknown>;
}) {
  if (!open) return null;
  return (
    <Modal
      title={title}
      onClose={onCancel}
      className="confirm-dialog"
      closeDisabled={busy}
      footer={<><Button disabled={busy} onClick={onCancel}>取消</Button><Button variant={danger ? "danger" : "primary"} busy={busy} onClick={onConfirm}>{confirmLabel}</Button></>}
    >
      <div className={`confirm-summary${danger ? " is-danger" : ""}`}>
        {danger ? <AlertTriangle size={20} /> : <CheckCircle2 size={20} />}
        <div><span>操作对象</span><strong>{objectName}</strong></div>
      </div>
      {currentState && <div className="confirm-state"><span>当前状态</span><strong>{currentState}</strong></div>}
      <p className="confirm-consequence">{consequence}</p>
    </Modal>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "success" | "warning"; children: ReactNode }) {
  return <div className={`notice notice-${tone}`} role={tone === "warning" ? "alert" : "status"}>{tone === "success" && <CheckCircle2 size={17} />}{children}</div>;
}

export function Field({ label, children, hint, error }: { label: string; children: ReactNode; hint?: string; error?: string }) {
  return (
    <label className={`field${error ? " field-error" : ""}`}>
      <span>{label}</span>
      {children}
      {hint && !error && <small>{hint}</small>}
      {error && <small role="alert">{error}</small>}
    </label>
  );
}

export function CodeValue({ children, title }: { children: ReactNode; title?: string }) {
  return <code className="code-value" title={title}>{children ?? MISSING_VALUE}</code>;
}

export function IdText({ value, length = 10, copyable = true }: { value?: string | null; length?: number; copyable?: boolean }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span>{MISSING_VALUE}</span>;
  const display = value.length <= length * 2 ? value : `${value.slice(0, length)}…${value.slice(-6)}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(value!);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  return (
    <span className="id-text">
      <CodeValue title={value}>{display}</CodeValue>
      {copyable && <button className="copy-button" type="button" onClick={copy} aria-label="复制完整编号" title={copied ? "已复制" : "复制完整编号"}><Copy size={13} /></button>}
    </span>
  );
}

export function AmountText({ value, currency = "CNY" }: { value?: number | string | null; currency?: string }) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return <span>{MISSING_VALUE}</span>;
  return <span className="amount-text">{new Intl.NumberFormat("zh-CN", { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value))}</span>;
}

export function DateTimeText({ value }: { value?: string | null }) {
  if (!value) return <span>{MISSING_VALUE}</span>;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return <span>{value}</span>;
  const pad = (part: number) => String(part).padStart(2, "0");
  return <time dateTime={value}>{date.getFullYear()}-{pad(date.getMonth() + 1)}-{pad(date.getDate())} {pad(date.getHours())}:{pad(date.getMinutes())}:{pad(date.getSeconds())}</time>;
}

export function PermissionGuard({
  roles,
  menuCode,
  fallback = null,
  children,
}: {
  roles?: readonly RoleCode[];
  menuCode?: string;
  fallback?: ReactNode;
  children: ReactNode;
}) {
  const { session } = useAuth();
  if (!session) return <>{fallback}</>;
  const roleAllowed = !roles || roles.includes(session.user.role_code);
  const menuAllowed = !menuCode || session.menus.some((item) => item.code === menuCode);
  return roleAllowed && menuAllowed ? <>{children}</> : <>{fallback}</>;
}

export function AuditTimeline({ events }: { events: Array<{ id: string; title: string; time: ReactNode; status?: string; meta?: ReactNode }> }) {
  if (!events.length) return <EmptyState title="暂无审计事件" />;
  return (
    <ol className="shared-audit-timeline">
      {events.map((event) => (
        <li key={event.id}>
          <span className="timeline-marker" aria-hidden="true" />
          <div><div className="timeline-time">{event.time}</div><strong>{event.title}</strong>{event.meta && <small>{event.meta}</small>}</div>
          {event.status && <StatusTag value={event.status} />}
        </li>
      ))}
    </ol>
  );
}
