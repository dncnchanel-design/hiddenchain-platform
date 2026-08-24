/* eslint-disable react-refresh/only-export-components */
import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Check, ChevronDown, Circle, LoaderCircle, X } from "lucide-react";
import { cn } from "../utils";
import { labelForCode } from "../../../types";

const buttonVariants = cva("energy-button", {
  variants: {
    variant: {
      primary: "energy-button-primary",
      secondary: "energy-button-secondary",
      ghost: "energy-button-ghost",
      danger: "energy-button-danger",
      link: "energy-button-link",
    },
    size: {
      sm: "energy-button-sm",
      md: "energy-button-md",
      lg: "energy-button-lg",
      icon: "energy-button-icon",
    },
  },
  defaultVariants: { variant: "secondary", size: "md" },
});

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  busy?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild = false, busy = false, children, disabled, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";
  return <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} disabled={disabled || busy} aria-busy={busy || undefined} {...props}>
    {busy && <LoaderCircle className="energy-spin" aria-hidden="true" size={14} />}
    {children}
  </Comp>;
});
Button.displayName = "TrustedButton";

export function IconButton({ label, children, className, busy, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; busy?: boolean }) {
  return <Button variant="ghost" size="icon" className={className} aria-label={label} title={label} busy={busy} {...props}>{children}</Button>;
}

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <section className={cn("energy-card", className)} {...props} />;
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("energy-card-header", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("energy-card-title", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("energy-card-description", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("energy-card-content", className)} {...props} />;
}

const badgeVariants = cva("energy-badge", {
  variants: {
    tone: {
      neutral: "energy-badge-neutral",
      success: "energy-badge-success",
      info: "energy-badge-info",
      warning: "energy-badge-warning",
      danger: "energy-badge-danger",
      brand: "energy-badge-brand",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({ className, tone, dot = false, children, ...props }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants> & { dot?: boolean }) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props}>{dot && <i aria-hidden="true" className="energy-badge-dot" />}{children}</span>;
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => <input ref={ref} className={cn("energy-input", className)} {...props} />);
Input.displayName = "TrustedInput";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...props }, ref) => <textarea ref={ref} className={cn("energy-textarea", className)} {...props} />);
Textarea.displayName = "TrustedTextarea";

export function Select({ label, value, onChange, options, className, disabled = false }: { label?: string; value?: string; onChange?: React.ChangeEventHandler<HTMLSelectElement>; options: Array<{ value: string; label: string }>; className?: string; disabled?: boolean }) {
  return <label className={cn("energy-select-wrap", className)}>{label && <span className="energy-field-label">{label}</span>}<span className="energy-select-shell"><select className="energy-select" value={value} onChange={onChange} disabled={disabled}>{options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><ChevronDown size={14} aria-hidden="true" /></span></label>;
}

export function FieldLabel({ children, htmlFor, hint }: { children: React.ReactNode; htmlFor?: string; hint?: string }) {
  return <div className="energy-field-label-row"><label className="energy-field-label" htmlFor={htmlFor}>{children}</label>{hint && <span className="energy-field-hint">{hint}</span>}</div>;
}

export function Divider({ className }: { className?: string }) {
  return <div className={cn("energy-divider", className)} role="separator" />;
}

export const Table = ({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) => <table className={cn("energy-table", className)} {...props} />;
export const TableHeader = ({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) => <thead className={className} {...props} />;
export const TableBody = ({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) => <tbody className={className} {...props} />;
export const TableRow = ({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) => <tr className={className} {...props} />;
export const TableHead = ({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) => <th className={className} {...props} />;
export const TableCell = ({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) => <td className={className} {...props} />;

export function Progress({ value, label, className }: { value: number; label?: string; className?: string }) {
  return <div className={cn("energy-progress-wrap", className)}>{label && <span className="energy-progress-label">{label}</span>}<div className="energy-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}><span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div></div>;
}

export const Tabs = TabsPrimitive.Root;
export const TabsList = React.forwardRef<React.ElementRef<typeof TabsPrimitive.List>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>>(({ className, ...props }, ref) => <TabsPrimitive.List ref={ref} className={cn("energy-tabs-list", className)} {...props} />);
TabsList.displayName = TabsPrimitive.List.displayName;
export const TabsTrigger = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Trigger>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>>(({ className, ...props }, ref) => <TabsPrimitive.Trigger ref={ref} className={cn("energy-tabs-trigger", className)} {...props} />);
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;
export const TabsContent = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Content>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>>(({ className, ...props }, ref) => <TabsPrimitive.Content ref={ref} className={cn("energy-tabs-content", className)} {...props} />);
TabsContent.displayName = TabsPrimitive.Content.displayName;

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export const DialogPortal = DialogPrimitive.Portal;
export const DialogOverlay = React.forwardRef<React.ElementRef<typeof DialogPrimitive.Overlay>, React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>>(({ className, ...props }, ref) => <DialogPrimitive.Overlay ref={ref} className={cn("energy-dialog-overlay", className)} {...props} />);
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;
export const DialogContent = React.forwardRef<React.ElementRef<typeof DialogPrimitive.Content>, React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>>(({ className, children, ...props }, ref) => <DialogPortal><DialogOverlay /><DialogPrimitive.Content ref={ref} className={cn("energy-dialog-content", className)} {...props}>{children}<DialogPrimitive.Close className="energy-dialog-close" aria-label="关闭"><X size={16} /></DialogPrimitive.Close></DialogPrimitive.Content></DialogPortal>);
DialogContent.displayName = DialogPrimitive.Content.displayName;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;

export function Sheet({ open, onOpenChange, title, side = "right", children, className }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; side?: "right" | "left"; children: React.ReactNode; className?: string }) {
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className={cn("energy-sheet", side === "left" ? "energy-sheet-left" : "energy-sheet-right", className)}><DialogTitle className="energy-sheet-title">{title}</DialogTitle>{children}</DialogContent></Dialog>;
}

export function Steps({ steps, current }: { steps: string[]; current: number }) {
  return <ol className="energy-steps" aria-label="流程进度">{steps.map((step, index) => { const state = index < current ? "done" : index === current ? "current" : "pending"; return <li className={`energy-step energy-step-${state}`} key={step}><span className="energy-step-marker">{state === "done" ? <Check size={13} /> : index + 1}</span><span>{step}</span>{index < steps.length - 1 && <i className="energy-step-line" aria-hidden="true" />}</li>; })}</ol>;
}

export function Timeline({ events }: { events: Array<{ id: string; label: string; detail: string; time: string; state: "done" | "current" | "pending" }> }) {
  return <ol className="energy-timeline">{events.map((event) => <li key={event.id} className={`energy-timeline-item energy-timeline-${event.state}`}><span className="energy-timeline-marker">{event.state === "done" ? <Check size={12} /> : event.state === "current" ? <LoaderCircle className="energy-spin" size={12} /> : <Circle size={8} />}</span><div className="energy-timeline-copy"><strong>{event.label}</strong><span>{event.detail}</span></div><time>{event.time}</time></li>)}</ol>;
}

export function SurfaceHeader({ title, action }: { title: string; description?: string; action?: React.ReactNode }) {
  return <div className="energy-surface-header"><div><h2>{title}</h2></div>{action && <div className="energy-surface-header-action">{action}</div>}</div>;
}

export function MetricBand({ items }: { items: Array<{ label: string; value: string; detail?: string; tone?: "brand" | "success" | "warning" | "info" }> }) {
  return <div className="energy-metric-band">{items.map((item) => <div className={`energy-metric-cell energy-metric-${item.tone ?? "brand"}`} key={item.label}><span>{item.label}</span><strong>{item.value}</strong>{item.detail && <small>{item.detail}</small>}</div>)}</div>;
}

export function StatusBadge({ value }: { value: string }) {
  const label = labelForCode(value, "未登记");
  const tone = /已完成|已验证|通过|成功|有效|已连接|已授权|可申请|已启用/.test(label) ? "success" : /计算中|进行中|运行中|已签署|执行中/.test(label) ? "info" : /复核|待开始|适配器|演示|待执行|未提供|未配置/.test(label) ? "warning" : /受限|阻断|失败|拒绝|无效/.test(label) ? "danger" : "neutral";
  return <Badge tone={tone} dot>{label}</Badge>;
}

export function RemoteState({ loading, error, onRetry, empty = false, emptyLabel = "暂无数据" }: { loading?: boolean; error?: string; onRetry?: () => void; empty?: boolean; emptyLabel?: string }) {
  if (loading) return <div className="trusted-empty-state" role="status"><LoaderCircle className="energy-spin" size={20} /><span>正在加载真实数据…</span></div>;
  if (error) return <div className="trusted-empty-state" role="alert"><X size={20} /><strong>数据加载失败</strong><span>{error}</span>{onRetry && <Button variant="secondary" onClick={onRetry}>重试</Button>}</div>;
  if (empty) return <div className="trusted-empty-state" role="status"><Circle size={20} /><strong>{emptyLabel}</strong></div>;
  return null;
}
