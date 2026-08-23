import { HelpCircle, RefreshCw, Route, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useRemote } from "../../../hooks";
import { Badge, Button, IconButton, RemoteState, Sheet } from "./ui-primitives";
import { loadTrustedHelp, type TrustedHelpPayload } from "../trusted-space-api";
import { ACTION_LABELS, ROLE_LABELS, labelForCode } from "../../../types";
import { getTrustedView, helpViewForTrustedView } from "../types";
import { capabilityLabel } from "../trusted-space-labels";

export function TrustedHelpPanel() {
  const location = useLocation();
  const view = helpViewForTrustedView(getTrustedView(location.pathname));
  const [open, setOpen] = useState(false);
  const remote = useRemote<TrustedHelpPayload | null>(
    (signal) => open ? loadTrustedHelp(view, signal) : Promise.resolve(null),
    [open, view],
  );
  const payload = remote.data;

  return <>
    <IconButton label="页面帮助" onClick={() => setOpen(true)}><HelpCircle size={16} /></IconButton>
    <Sheet open={open} onOpenChange={setOpen} title="页面帮助" className="trusted-utility-sheet">
      <div className="trusted-utility-sheet-body">
        {remote.loading && !payload && <RemoteState loading />}
        {remote.error && !payload && <RemoteState error={remote.error} onRetry={remote.reload} />}
        {payload && <>
          <div className="trusted-utility-heading">
            <div><span className="trusted-utility-kicker">{labelForCode(payload.view, "当前页面")} · {payload.version || "当前版本"}</span><h2>{payload.title}</h2><p>{payload.summary}</p></div>
            <Badge tone={payload.capability_state === "LOCAL_REAL" ? "success" : "warning"} dot>{capabilityLabel(payload.capability_state)}</Badge>
          </div>
          <div className="trusted-help-boundary"><ShieldCheck size={15} /><span>以下内容是后端版本化帮助与能力边界；不会执行动作，也不会加载任意 HTML。</span></div>
          <div className="trusted-help-entries">
            {payload.entries.map((entry) => <section key={entry.id} className="trusted-help-entry">
              <h3>{entry.title}</h3>
              <p>{entry.body}</p>
              {entry.related_paths.length > 0 && <div className="trusted-help-paths"><span><Route size={13} />相关路径</span>{entry.related_paths.map((path) => <code key={path}>{path}</code>)}</div>}
              {entry.allowed_actions.length > 0 && <div className="trusted-help-actions"><span>可用动作</span>{entry.allowed_actions.map((action) => <Badge tone="neutral" key={action}>{ACTION_LABELS[action] || labelForCode(action, "已登记动作")}</Badge>)}</div>}
            </section>)}
          </div>
          <div className="trusted-utility-footer"><span>角色：{ROLE_LABELS[payload.role_code as keyof typeof ROLE_LABELS] || labelForCode(payload.role_code, "未登记角色")}</span><Button variant="secondary" size="sm" busy={remote.refreshing} onClick={remote.reload}><RefreshCw size={13} />刷新帮助</Button></div>
        </>}
      </div>
    </Sheet>
  </>;
}
