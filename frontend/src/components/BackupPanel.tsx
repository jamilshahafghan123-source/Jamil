import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { AdminBackup } from "../lib/types";

/**
 * ADMIN backup panel.
 *
 * Restore is deliberately awkward. It names a backup by *registry id* —
 * there is no path field and no filename field anywhere in this component,
 * because the backend accepts neither and a UI that offered one would be
 * lying about what it can do. The confirmation spells out that it is a
 * maintenance operation before the button is live.
 *
 * When the host has restore disabled the control reads RESTORE DISABLED
 * rather than rendering a button that would fail: a control that cannot
 * work should say so, not wait to disappoint.
 *
 * The result is only reported after the backend answers, and the backend
 * only reports success when its own post-restore health check passed.
 */

function size(bytes: number): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function when(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

function tone(status: string): string {
  if (status === "VERIFIED" || status === "RESTORE_TESTED") return "ok";
  if (status === "FAILED") return "bad";
  if (status === "CREATED") return "warn";
  return "muted";
}

export function BackupPanel({
  restoreEnabled,
  onChanged,
}: {
  restoreEnabled: boolean;
  onChanged?: () => void;
}) {
  const [backups, setBackups] = useState<AdminBackup[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState<AdminBackup | null>(null);

  const load = useCallback(async () => {
    try {
      setBackups(await api.adminBackups());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load backups");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function create() {
    setBusy(true);
    setResult(null);
    try {
      const made = await api.adminCreateBackup();
      setResult(
        made.status === "FAILED"
          ? `Backup failed: ${made.detail}`
          : `Backup #${made.id} created (${size(made.size_bytes)}).`,
      );
      await load();
      onChanged?.();
    } catch (err) {
      setResult(err instanceof Error ? err.message : "Backup failed");
    } finally {
      setBusy(false);
    }
  }

  async function verify(backup: AdminBackup) {
    setBusy(true);
    setResult(null);
    try {
      const checked = await api.adminVerifyBackup(backup.id);
      setResult(`Backup #${checked.id}: ${checked.detail}`);
      await load();
      onChanged?.();
    } catch (err) {
      setResult(err instanceof Error ? err.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  }

  async function restore(backup: AdminBackup) {
    setBusy(true);
    setResult(null);
    try {
      // Reported only once the backend has answered, and it answers ok
      // only when its own post-restore health check passed.
      const res = await api.adminRestoreBackup(backup.id);
      setResult(
        res.ok
          ? `Restore from backup #${backup.id} completed and verified.`
          : `Restore did not complete: ${res.detail}${
              res.maintenance_active
                ? " The platform remains in maintenance."
                : ""
            }`,
      );
      await load();
      onChanged?.();
    } catch (err) {
      setResult(err instanceof Error ? err.message : "Restore failed");
    } finally {
      setBusy(false);
      setRestoreTarget(null);
    }
  }

  const latest = backups[0] ?? null;

  return (
    <section className="jg-cc-section">
      <h2>Backups</h2>

      {error && <p className="jg-cc-error">{error}</p>}
      {result && (
        <p className="jg-cc-result" role="status">
          {result}
        </p>
      )}

      <div className="jg-cc-grid">
        <article className="jg-cc-card">
          <div className="jg-cc-card-top">
            <h3>Latest backup</h3>
            <span className={`jg-pill jg-pill-${tone(latest?.status ?? "")}`}>
              {latest ? latest.status.replace(/_/g, " ") : "NONE"}
            </span>
          </div>
          {latest ? (
            <>
              <p className="jg-cc-detail">Backup #{latest.id}</p>
              <dl className="jg-cc-meta">
                <div>
                  <dt>Created</dt>
                  <dd>{when(latest.created_at)}</dd>
                </div>
                <div>
                  <dt>Size</dt>
                  <dd>{size(latest.size_bytes)}</dd>
                </div>
              </dl>
              <dl className="jg-cc-meta">
                <div>
                  <dt>Verified</dt>
                  <dd>{when(latest.verified_at)}</dd>
                </div>
                <div>
                  <dt>Version</dt>
                  <dd>{latest.app_version}</dd>
                </div>
              </dl>
              <p className="jg-cc-note">
                Database {latest.database_name || "unknown"} · checksum{" "}
                {latest.has_checksum ? "recorded" : "not recorded"}
              </p>
            </>
          ) : (
            <p className="jg-cc-detail">No backup has been taken yet.</p>
          )}
        </article>

        <article className="jg-cc-card">
          <div className="jg-cc-card-top">
            <h3>Actions</h3>
          </div>
          <div className="jg-cc-actions">
            <button type="button" className="btn" disabled={busy} onClick={create}>
              Create backup
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy || !latest}
              onClick={() => latest && verify(latest)}
            >
              Verify latest
            </button>
          </div>
          <p className="jg-cc-note">
            Restore is a maintenance operation and is started from the history
            below.
          </p>
        </article>
      </div>

      <button
        type="button"
        className="btn sm"
        style={{ marginTop: 12 }}
        onClick={() => setShowHistory((v) => !v)}
      >
        {showHistory ? "Hide history" : `History (${backups.length})`}
      </button>

      {showHistory && (
        <ul className="jg-cc-incidents" style={{ marginTop: 10 }}>
          {backups.length === 0 && (
            <li className="jg-cc-note">No backups registered.</li>
          )}
          {backups.map((b) => (
            <li key={b.id}>
              <details>
                <summary>
                  <span className={`jg-pill jg-pill-${tone(b.status)}`}>
                    {b.status.replace(/_/g, " ")}
                  </span>
                  <span className="jg-inc-service">Backup #{b.id}</span>
                  <span className="jg-inc-cat">{size(b.size_bytes)}</span>
                  <span className="jg-inc-time">{when(b.created_at)}</span>
                </summary>
                <div className="jg-inc-body">
                  <p>{b.detail || "No detail recorded."}</p>
                  <p className="jg-cc-note">
                    Version {b.app_version} · database{" "}
                    {b.database_name || "unknown"} · checksum{" "}
                    {b.has_checksum ? "recorded" : "none"} · verified{" "}
                    {when(b.verified_at)}
                  </p>
                  <div className="jg-cc-actions">
                    <button
                      type="button"
                      className="btn sm"
                      disabled={busy}
                      onClick={() => verify(b)}
                    >
                      Verify
                    </button>
                    {restoreEnabled ? (
                      <button
                        type="button"
                        className="btn sm danger"
                        disabled={busy}
                        onClick={() => setRestoreTarget(b)}
                      >
                        Restore…
                      </button>
                    ) : (
                      <span className="jg-pill jg-pill-muted">
                        RESTORE DISABLED
                      </span>
                    )}
                  </div>
                </div>
              </details>
            </li>
          ))}
        </ul>
      )}

      {restoreTarget && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="jg-confirm">
            <h3>Restore from backup #{restoreTarget.id}?</h3>
            <p>
              This is a <strong>maintenance operation</strong>. The platform
              enters maintenance mode: new automated trading and new orders are
              blocked. Open positions are <em>not</em> closed and can still be
              closed manually.
            </p>
            <p>
              The database is overwritten with the contents of this backup,
              taken {when(restoreTarget.created_at)} from version{" "}
              {restoreTarget.app_version}.
            </p>
            <div className="jg-confirm-actions">
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => setRestoreTarget(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn danger"
                disabled={busy}
                onClick={() => void restore(restoreTarget)}
              >
                {busy ? "Restoring…" : "Restore this backup"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
