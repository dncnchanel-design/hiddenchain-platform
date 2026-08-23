import { Bell, CheckCheck, ExternalLink, RefreshCw, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, formatDate } from "../../../api";
import { useRemote } from "../../../hooks";
import { Badge, Button, IconButton, RemoteState, Sheet } from "./ui-primitives";
import { loadNotifications, markAllNotificationsRead, markNotificationRead, type TrustedNotification } from "../trusted-space-api";
import { notificationPath } from "../trusted-space-ui";

function notificationRouteHint(notification: TrustedNotification) {
  return notificationPath(notification) ? "打开关联记录" : "该通知暂未登记直接详情路由";
}

export function NotificationCenter() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [commandError, setCommandError] = useState("");
  const [page, setPage] = useState(1);
  const remote = useRemote((signal) => loadNotifications({ page, pageSize: 20 }, signal), [page]);
  const payload = remote.data;
  const unreadCount = payload?.unread_count ?? 0;
  const canGoPrevious = page > 1;
  const canGoNext = Boolean(payload && page * payload.page_size < payload.total);

  async function markRead(notification: TrustedNotification) {
    if (notification.read_at || busyId) return;
    setBusyId(notification.notification_id);
    setCommandError("");
    try {
      const updated = await markNotificationRead(notification.notification_id, { retry: 0 });
      remote.setData((current) => current ? {
        ...current,
        items: current.items.map((item) => item.notification_id === notification.notification_id ? { ...item, ...updated, read_at: updated.read_at || new Date().toISOString() } : item),
        unread_count: Math.max(0, current.unread_count - 1),
      } : current);
    } catch (error) {
      setCommandError(error instanceof ApiError ? error.message : "标记通知失败，请重试");
    } finally {
      setBusyId(null);
    }
  }

  async function markAllRead() {
    if (!unreadCount || busyId) return;
    setBusyId("__all__");
    setCommandError("");
    try {
      await markAllNotificationsRead({ retry: 0 });
      remote.setData((current) => current ? {
        ...current,
        items: current.items.map((item) => ({ ...item, read_at: item.read_at || new Date().toISOString() })),
        unread_count: 0,
      } : current);
    } catch (error) {
      setCommandError(error instanceof ApiError ? error.message : "全部标记已读失败，请重试");
    } finally {
      setBusyId(null);
    }
  }

  async function openNotification(notification: TrustedNotification) {
    await markRead(notification);
    const path = notificationPath(notification);
    if (path) {
      setOpen(false);
      navigate(path);
    } else {
      setCommandError("该通知只有记录摘要，当前没有可安全跳转的详情路由。");
    }
  }

  return <>
    <span className="trusted-notification-trigger">
      <IconButton label={unreadCount ? `通知，有 ${unreadCount} 条未读` : "通知"} onClick={() => setOpen(true)}>
        <Bell size={16} />
      </IconButton>
      {unreadCount > 0 && <span className="trusted-notification-count" aria-live="polite">{unreadCount > 99 ? "99+" : unreadCount}</span>}
    </span>
    <Sheet open={open} onOpenChange={setOpen} title="通知中心" className="trusted-utility-sheet trusted-notification-sheet">
      <div className="trusted-utility-sheet-body">
        <div className="trusted-notification-toolbar"><div><strong>当前主体通知</strong><small>{unreadCount ? `${unreadCount} 条未读` : "已全部读完"}</small></div><div><Button variant="secondary" size="sm" disabled={!unreadCount || Boolean(busyId)} busy={busyId === "__all__"} onClick={markAllRead}><CheckCheck size={13} />全部已读</Button><IconButton label="刷新通知" busy={remote.refreshing} onClick={remote.reload}><RefreshCw size={14} /></IconButton></div></div>
        {commandError && <div className="trusted-notification-command-error" role="alert"><X size={14} />{commandError}</div>}
        {remote.loading && !payload && <RemoteState loading />}
        {remote.error && !payload && <RemoteState error={remote.error} onRetry={remote.reload} />}
        {payload && payload.empty_state && <RemoteState empty emptyLabel="当前主体暂无通知" />}
        {payload && !payload.empty_state && <div className="trusted-notification-list">{payload.items.map((notification) => <div className={`trusted-notification-row ${notification.read_at ? "is-read" : "is-unread"}`} key={notification.notification_id}>
          <button type="button" className="trusted-notification-item" onClick={() => openNotification(notification)} aria-busy={busyId === notification.notification_id || undefined} disabled={Boolean(busyId) && busyId !== notification.notification_id}>
            <span className="trusted-notification-dot" aria-hidden="true" />
            <span className="trusted-notification-copy"><strong>{notification.title}</strong><span>{notification.body}</span><small>{formatDate(notification.created_at)} · {notificationRouteHint(notification)}</small></span>
            <ExternalLink size={14} aria-hidden="true" />
          </button>
          {!notification.read_at && <Button variant="link" size="sm" disabled={Boolean(busyId)} busy={busyId === notification.notification_id} onClick={() => markRead(notification)}>标记已读</Button>}
          {notification.read_at && <Badge tone="neutral">已读</Badge>}
        </div>)}</div>}
        {payload && <div className="trusted-step-footer" aria-label="通知分页"><span>第 {payload.page} 页 · 共 {payload.total} 条</span><div><Button variant="secondary" size="sm" disabled={!canGoPrevious || remote.loading} onClick={() => setPage((value) => Math.max(1, value - 1))}>上一页</Button><Button variant="secondary" size="sm" disabled={!canGoNext || remote.loading} onClick={() => setPage((value) => value + 1)}>下一页</Button></div></div>}
      </div>
    </Sheet>
  </>;
}
