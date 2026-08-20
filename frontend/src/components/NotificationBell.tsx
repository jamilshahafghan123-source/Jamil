import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { AdminNotification, NotificationFeed, Severity } from "../lib/types";

/**
 * Owner notification centre.
 *
 * Reads the notification table the recovery system writes to. Delivery is
 * in-app only: the backend reports EMAIL / PUSH / SMS as NOT_CONFIGURED and
 * this panel says so rather than implying an email went out. A row's
 * `delivered_channels` stays empty until something real delivers it.
 */

const SEVERITIES: (Severity | "ALL")[] = ["ALL", "CRITICAL", "HIGH", "WARNING", "INFO"];

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString();
}

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [feed, setFeed] = useState<NotificationFeed | null>(null);
  const [severity, setSeverity] = useState<Severity | "ALL">("ALL");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setFeed(await api.adminNotifications(severity === "ALL" ? undefined : severity));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load notifications");
    }
  }, [severity]);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(t);
  }, [load]);

  async function markRead(n: AdminNotification) {
    if (n.read) return;
    await api.adminMarkNotificationRead(n.id);
    await load();
  }

  async function markAll() {
    await api.adminMarkAllNotificationsRead();
    await load();
  }

  const unread = feed?.unread ?? 0;

  return (
    <div className="jg-bell-wrap">
      <button
        type="button"
        className="jg-bell"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}
        aria-expanded={open}
      >
        <span aria-hidden="true">🔔</span>
        {unread > 0 && <span className="jg-bell-count">{unread}</span>}
      </button>

      {open && (
        <div className="jg-bell-panel" role="dialog" aria-label="Notifications">
          <header className="jg-bell-head">
            <strong>Notifications</strong>
            <button type="button" className="btn sm" onClick={markAll}>
              Mark all read
            </button>
          </header>

          <div className="jg-bell-filters">
            {SEVERITIES.map((s) => (
              <button
                key={s}
                type="button"
                className={severity === s ? "jg-chip active" : "jg-chip"}
                onClick={() => setSeverity(s)}
              >
                {s}
              </button>
            ))}
          </div>

          {error && <p className="jg-bell-empty">{error}</p>}

          <ul className="jg-bell-list">
            {(feed?.notifications ?? []).map((n) => (
              <li
                key={n.id}
                className={n.read ? "jg-note-row" : "jg-note-row unread"}
              >
                <div className="jg-note-top">
                  <span className={`jg-sev jg-sev-${n.severity}`}>{n.severity}</span>
                  <span className="jg-note-time">{when(n.created_at)}</span>
                </div>
                <p className="jg-note-msg">{n.message}</p>
                <div className="jg-note-foot">
                  {n.incident_id != null && (
                    <span className="jg-note-link">Incident #{n.incident_id}</span>
                  )}
                  {!n.read && (
                    <button
                      type="button"
                      className="btn sm"
                      onClick={() => void markRead(n)}
                    >
                      Mark read
                    </button>
                  )}
                </div>
              </li>
            ))}
            {feed && feed.notifications.length === 0 && (
              <li className="jg-bell-empty">Nothing to report.</li>
            )}
          </ul>

          <footer className="jg-bell-foot">
            Delivery:{" "}
            {Object.entries(feed?.channels ?? {})
              .map(([k, v]) => `${k} ${v === "ACTIVE" ? "on" : "not configured"}`)
              .join(" · ")}
          </footer>
        </div>
      )}
    </div>
  );
}
