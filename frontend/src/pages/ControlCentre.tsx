import { useCallback, useEffect, useState } from "react";
import { OpportunityLog } from "../components/OpportunityLog";
import { api } from "../lib/api";
import { Brand } from "../components/Brand";
import { NotificationBell } from "../components/NotificationBell";
import { BackupPanel } from "../components/BackupPanel";
import { SecurityPanel } from "../components/SecurityPanel";
import type {
  AdminIncident,
  SecurityOverview,
  AdminTicket,
  ComponentStatus,
  ControlCentre as ControlCentreData,
  RecoveryStatus,
} from "../lib/types";

/**
 * ADMIN-only control centre.
 *
 * Every endpoint behind this page is gated by require_admin server-side and
 * 404s for a customer, so this page is a convenience, not the boundary.
 *
 * Two rules the layout enforces:
 *
 * 1. NOT CONFIGURED is not a fault. A payment provider nobody has connected
 *    reads as a neutral state, not as an outage — colouring it red would
 *    train the operator to ignore red.
 * 2. Mutating actions confirm first. The buttons here restart real services
 *    on a real machine, and the recovery backend accepts only allow-listed
 *    operations, so there is deliberately no place to type a command.
 */

const LABELS: Record<string, string> = {
  backend: "Backend",
  database: "Database",
  mt5: "MT5",
  mt5_bridge: "MT5 Bridge",
  market_data: "Market Data",
  ai_workers: "AI Workers",
  payment_service: "Payment Service",
  notification_service: "Notification Service",
  BRIDGE: "MT5 Bridge",
  BACKEND: "Backend",
  FRONTEND: "Frontend",
  DATABASE: "Database",
  DOCKER: "Docker",
  MT5: "MT5",
  MARKET_DATA: "Market Data",
};

/** Backend vocabulary → the words section 1 asks to display. */
function displayStatus(status: ComponentStatus | string): string {
  switch (status) {
    case "UP":
      return "HEALTHY";
    case "DOWN":
      return "OFFLINE";
    case "UNKNOWN":
      return "UNKNOWN";
    case "NOT_CONFIGURED":
      return "NOT CONFIGURED";
    case "NEEDS_ADMIN":
      return "NEEDS ADMIN";
    default:
      return String(status).replace(/_/g, " ");
  }
}

function tone(status: string): string {
  if (status === "UP" || status === "HEALTHY" || status === "CONNECTED") return "ok";
  if (status === "RECOVERED") return "ok";
  if (status === "DOWN" || status === "OFFLINE" || status === "FAILED") return "bad";
  if (status === "NEEDS_ADMIN") return "bad";
  if (status === "DEGRADED" || status === "RECOVERING" || status === "MONITORING")
    return "warn";
  // UNKNOWN and NOT_CONFIGURED are deliberately neutral, never alarming.
  return "muted";
}

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

const INCIDENT_FILTERS = ["ALL", "OPEN", "RECOVERING", "NEEDS_ADMIN", "RECOVERED"];

type Pending = { operation: string; label: string } | null;

export function ControlCentre({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<ControlCentreData | null>(null);
  const [recovery, setRecovery] = useState<RecoveryStatus | null>(null);
  const [incidents, setIncidents] = useState<AdminIncident[]>([]);
  const [filter, setFilter] = useState("ALL");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [stopPending, setStopPending] = useState(false);
  const [tickets, setTickets] = useState<AdminTicket[]>([]);
  const [security, setSecurity] = useState<SecurityOverview | null>(null);
  const [showTickets, setShowTickets] = useState(false);

  const load = useCallback(async () => {
    try {
      const [cc, rec, sec] = await Promise.all([
        api.adminControlCentre(),
        api.adminRecovery(),
        api.adminSecurity(),
      ]);
      setData(cc);
      setRecovery(rec);
      setSecurity(sec);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load status");
    }
  }, []);

  const loadIncidents = useCallback(async () => {
    try {
      setIncidents(await api.adminIncidents(filter));
    } catch {
      /* the panel simply stays empty; the banner above already reports */
    }
  }, [filter]);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(t);
  }, [load]);

  useEffect(() => {
    void loadIncidents();
  }, [loadIncidents]);

  const loadTickets = useCallback(async () => {
    try {
      setTickets(await api.adminTickets());
    } catch {
      /* the summary counts above already report; the list stays empty */
    }
  }, []);

  useEffect(() => {
    if (showTickets) void loadTickets();
  }, [showTickets, loadTickets]);

  async function runOperation(operation: string) {
    setBusy(true);
    setResult(null);
    try {
      const res = await api.adminRunRecovery(operation);
      setResult(
        `${res.operation}: ${res.ok ? "succeeded" : "failed"}${
          res.detail ? ` — ${res.detail}` : ""
        }`,
      );
      await load();
      await loadIncidents();
    } catch (err) {
      setResult(err instanceof Error ? err.message : "Operation failed");
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  async function emergencyStopAll() {
    setBusy(true);
    try {
      const res = await api.adminEmergencyStopAll();
      setResult(res.detail);
      await load();
    } catch (err) {
      setResult(err instanceof Error ? err.message : "Emergency stop failed");
    } finally {
      setBusy(false);
      setStopPending(false);
    }
  }

  // Section 8: link to the incident the restore already created, found in
  // the incidents the backend already returns. Nothing is stored twice.
  const restoreIncident =
    incidents.find((i) => i.category === "RESTORE_FAILED") ?? null;

  const permitted = recovery?.permitted_operations ?? [];
  const mutating = permitted.filter(
    (op) => op.startsWith("RESTART_") || op.startsWith("START_"),
  );

  return (
    <div className="jg-cc">
      <header className="jg-cc-top">
        <Brand size={26} />
        <span className="jg-cc-tag">Control Centre</span>
        <div className="jg-spacer" />
        <NotificationBell />
        <button type="button" className="btn" onClick={onBack}>
          Back to dashboard
        </button>
      </header>

      {error && <p className="jg-cc-error">{error}</p>}
      {result && (
        <p className="jg-cc-result" role="status">
          {result}
        </p>
      )}

      {/* Always shown, active or not: an operator should be able to read
          the maintenance state off the page rather than infer it from the
          absence of a banner. The state comes from the backend on every
          poll, so the UI cannot claim a window ended before it has. */}
      <section className="jg-cc-section">
        <h2>Opportunity telemetry</h2>
        <p className="jg-cc-note">
          Every setup the engine detected across the platform, including the
          ones it declined and the ones the risk manager refused. The three
          outcomes are separate columns on purpose: a quiet day has a
          different cause depending on which stage stopped it.
        </p>
        <OpportunityLog admin />
      </section>

      <section className="jg-cc-section">
        <div
          className={security?.maintenance.active ? "jg-maint active" : "jg-maint"}
        >
          <div className="jg-maint-head">
            <strong>MAINTENANCE MODE</strong>
            <span
              className={`jg-pill jg-pill-${
                security?.maintenance.active ? "warn" : "ok"
              }`}
            >
              {security?.maintenance.active ? "ACTIVE" : "INACTIVE"}
            </span>
          </div>
          {security?.maintenance.active ? (
            <>
              <ul>
                <li>New automated trades are blocked.</li>
                <li>New opening orders are blocked.</li>
                <li>
                  Closing a position remains allowed — positions are{" "}
                  <em>not</em> closed automatically.
                </li>
                <li>Admin diagnostics and support remain available.</li>
              </ul>
              <p className="jg-cc-note">
                {security.maintenance.reason || "No reason recorded"}
                {security.maintenance.since
                  ? ` · started ${when(security.maintenance.since)}`
                  : ""}
                {security.maintenance.detail
                  ? ` · ${security.maintenance.detail}`
                  : ""}
              </p>
              {restoreIncident && (
                <button
                  type="button"
                  className="btn sm"
                  onClick={() => {
                    setFilter("NEEDS_ADMIN");
                    document
                      .querySelector(".jg-cc-incidents")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                >
                  Open related incident #{restoreIncident.id}
                </button>
              )}
            </>
          ) : (
            <p className="jg-cc-note">
              Normal operation. Automated trading and order placement are not
              blocked by maintenance.
            </p>
          )}
        </div>
      </section>

      {/* --------------------------------------------------- safe mode */}
      <section className="jg-cc-section">
        <div
          className={
            data?.safe_mode.active ? "jg-safebar active" : "jg-safebar"
          }
        >
          <div className="jg-safebar-head">
            <span className="jg-safebar-state">
              {data?.safe_mode.active ? "SAFE MODE ACTIVE" : "SAFE MODE INACTIVE"}
            </span>
            <span className="jg-safebar-auto">
              AI Auto {data?.safe_mode.active ? "paused" : "permitted"}
            </span>
          </div>
          {data?.safe_mode.active ? (
            <>
              <ul className="jg-safebar-reasons">
                {data.safe_mode.customer_messages.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
              <p className="jg-cc-note">
                Affected:{" "}
                {data.safe_mode.reasons
                  .map((r) => r.replace(/_/g, " ").toLowerCase())
                  .join(", ")}{" "}
                · detected {when(data.generated_at)}
              </p>
            </>
          ) : (
            <p className="jg-cc-note">
              No blocking condition detected. Automated trading may proceed.
            </p>
          )}
          <p className="jg-safebar-rule">
            Safe Mode blocks <strong>new</strong> automated trades. It never
            closes an existing position.
          </p>
        </div>
      </section>

      {/* --------------------------------------------- bot / trading state */}
      <section className="jg-cc-section">
        <h2>Bot &amp; trading</h2>
        <div className="jg-cc-grid">
          <article className="jg-cc-card">
            <div className="jg-cc-card-top">
              <h3>Bot</h3>
              <span
                className={`jg-pill jg-pill-${
                  (data?.trading.bots_enabled ?? 0) > 0 ? "ok" : "muted"
                }`}
              >
                {(data?.trading.bots_enabled ?? 0) > 0 ? "RUNNING" : "STOPPED"}
              </span>
            </div>
            <p className="jg-cc-detail">
              {data?.trading.bots_enabled ?? 0} bot(s) enabled ·{" "}
              {data?.trading.accounts_emergency_stopped ?? 0} account(s)
              emergency-stopped
            </p>
            <p className="jg-cc-note">
              Real trading{" "}
              {data?.trading.real_trading_allowed_by_server
                ? "allowed by server"
                : "disabled"}
            </p>
          </article>

          <article className="jg-cc-card jg-cc-signal">
            <div className="jg-cc-card-top">
              <h3>Latest signal</h3>
              <span
                className={`jg-pill jg-pill-${
                  data?.bot.signal?.action === "NO_TRADE" ? "muted" : "ok"
                }`}
              >
                {data?.bot.signal?.action?.replace(/_/g, " ") ?? "NONE"}
              </span>
            </div>
            {data?.bot.signal ? (
              <>
                {/* Each gate beside its minimum, so a waiting bot reads as
                    waiting rather than broken. */}
                <Gate
                  label="Confidence"
                  value={`${data.bot.signal.confidence}%`}
                  required={
                    data.bot.signal.required_confidence != null
                      ? `${data.bot.signal.required_confidence}%`
                      : null
                  }
                  unmet={
                    data.bot.signal.required_confidence != null &&
                    data.bot.signal.confidence < data.bot.signal.required_confidence
                  }
                />
                <Gate
                  label="Risk / reward"
                  value={data.bot.signal.rr != null ? String(data.bot.signal.rr) : "—"}
                  required={
                    data.bot.signal.required_rr != null
                      ? String(data.bot.signal.required_rr)
                      : null
                  }
                  unmet={
                    data.bot.signal.rr != null &&
                    data.bot.signal.required_rr != null &&
                    data.bot.signal.rr < data.bot.signal.required_rr
                  }
                />
                {data.bot.signal.risk_reasons.length > 0 && (
                  <p className="jg-cc-note">
                    Risk engine: {data.bot.signal.risk_reasons.join("; ")}
                  </p>
                )}
                <p className="jg-cc-note">{when(data.bot.signal.created_at)}</p>
              </>
            ) : (
              <p className="jg-cc-detail">No analysis has been produced yet.</p>
            )}
          </article>

          <article className="jg-cc-card">
            <div className="jg-cc-card-top">
              <h3>Last execution error</h3>
              <span
                className={`jg-pill jg-pill-${
                  data?.bot.last_execution_error ? "warn" : "muted"
                }`}
              >
                {data?.bot.last_execution_error ? "PRESENT" : "NONE"}
              </span>
            </div>
            {data?.bot.last_execution_error ? (
              <p className="jg-cc-detail">
                {data.bot.last_execution_error.status} on{" "}
                {data.bot.last_execution_error.action}{" "}
                {data.bot.last_execution_error.symbol} ·{" "}
                {when(data.bot.last_execution_error.created_at)}
              </p>
            ) : (
              <p className="jg-cc-detail">No failed orders recorded.</p>
            )}
          </article>

          <article className="jg-cc-card">
            <div className="jg-cc-card-top">
              <h3>Support</h3>
              <span
                className={`jg-pill jg-pill-${
                  (data?.support.needs_admin ?? 0) > 0 ? "warn" : "ok"
                }`}
              >
                {data?.support.needs_admin ?? 0} NEEDS ADMIN
              </span>
            </div>
            <p className="jg-cc-detail">
              {data?.support.open ?? 0} open · {data?.support.urgent ?? 0} urgent
              · {data?.support.resolved ?? 0} resolved
            </p>
            <button
              type="button"
              className="btn sm"
              style={{ marginTop: 10 }}
              onClick={() => setShowTickets((v) => !v)}
            >
              {showTickets ? "Hide tickets" : "View tickets"}
            </button>
          </article>
        </div>

        {showTickets && (
          <ul className="jg-cc-incidents" style={{ marginTop: 12 }}>
            {tickets.length === 0 && <li className="jg-cc-note">No tickets.</li>}
            {tickets.map((t) => (
              <li key={t.id}>
                <details>
                  <summary>
                    <span className={`jg-pill jg-pill-${tone(t.status)}`}>
                      {displayStatus(t.status)}
                    </span>
                    <span className="jg-inc-service">{t.subject}</span>
                    <span className="jg-inc-cat">{t.category}</span>
                    <span className="jg-inc-time">{when(t.created_at)}</span>
                  </summary>
                  <div className="jg-inc-body">
                    <p>{t.ai_summary || "No summary."}</p>
                    {t.status !== "RESOLVED" && (
                      <button
                        type="button"
                        className="btn sm"
                        onClick={async () => {
                          await api.adminResolveTicket(t.id);
                          await loadTickets();
                          await load();
                        }}
                      >
                        Mark resolved
                      </button>
                    )}
                  </div>
                </details>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ------------------------------------------------ system health */}
      <section className="jg-cc-section">
        <h2>System health</h2>
        <div className="jg-cc-grid">
          <StatusCard
            name="Windows Agent"
            status={recovery?.agent.configured ? "CONNECTED" : "NOT_CONFIGURED"}
            detail={
              recovery?.agent.configured
                ? "Recovery agent configured."
                : "No recovery agent configured."
            }
          />
          {(data?.system_health.components ?? []).map((c) => (
            <StatusCard
              key={c.component}
              name={LABELS[c.component] ?? c.component}
              status={c.status}
              detail={c.detail}
              checkedAt={c.checked_at}
            />
          ))}
          <StatusCard
            name="AI Bot"
            status={(data?.trading.bots_enabled ?? 0) > 0 ? "UP" : "UNKNOWN"}
            detail={`${data?.trading.bots_enabled ?? 0} bot(s) enabled · ${
              data?.trading.accounts_emergency_stopped ?? 0
            } account(s) stopped`}
          />
          <StatusCard
            name="Safe Mode"
            status={data?.safe_mode.active ? "DEGRADED" : "UP"}
            detail={
              data?.safe_mode.active
                ? // The backend already writes these for a human to read;
                  // showing the raw enum would make the operator decode it.
                  data.safe_mode.customer_messages.join(" ") ||
                  data.safe_mode.reasons.join(", ").replace(/_/g, " ")
                : "Automated trading permitted."
            }
          />
        </div>
      </section>

      {/* --------------------------------------------- recovery services */}
      <section className="jg-cc-section">
        <h2>Recovery</h2>
        <div className="jg-cc-grid">
          {Object.entries(recovery?.services ?? {}).map(([name, svc]) => (
            <article key={name} className="jg-cc-card">
              <div className="jg-cc-card-top">
                <h3>{LABELS[name] ?? name}</h3>
                <span className={`jg-pill jg-pill-${tone(svc.state)}`}>
                  {displayStatus(svc.state)}
                </span>
              </div>
              <p className="jg-cc-detail">{svc.policy}</p>
              <dl className="jg-cc-meta">
                <div>
                  <dt>Attempts</dt>
                  <dd>{svc.attempts_in_window}</dd>
                </div>
                <div>
                  <dt>Auto repair</dt>
                  <dd>{svc.has_automatic_repair ? "yes" : "no"}</dd>
                </div>
              </dl>
              {data?.recovery?.[name]?.last_incident ? (
                <p className="jg-cc-note">
                  Last incident #{data.recovery[name].last_incident!.id} ·{" "}
                  {displayStatus(data.recovery[name].last_incident!.status)} ·{" "}
                  {when(data.recovery[name].last_incident!.detected_at)}
                  {data.recovery[name].last_incident!.recovered_at
                    ? ` · recovered ${when(
                        data.recovery[name].last_incident!.recovered_at,
                      )}`
                    : ""}
                </p>
              ) : (
                <p className="jg-cc-note">No incidents recorded.</p>
              )}
            </article>
          ))}
        </div>

        <h3 className="jg-cc-sub">Actions</h3>
        <p className="jg-cc-note">
          Only operations the recovery backend accepts are shown. There is no
          free-form command entry.
        </p>
        <div className="jg-cc-actions">
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => void runOperation("VERIFY_HEALTH")}
          >
            Check now
          </button>
          {mutating.map((op) => (
            <button
              key={op}
              type="button"
              className="btn"
              disabled={busy}
              onClick={() =>
                setPending({ operation: op, label: op.replace(/_/g, " ") })
              }
            >
              {op.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------ emergency stop */}
      <section className="jg-cc-section">
        <h2>Emergency control</h2>
        <div className="jg-cc-danger">
          <div>
            <strong>Emergency stop all automated trading</strong>
            <p>
              Halts automation on every account and disables all bots. Open
              positions are <em>not</em> closed and stay manageable.
            </p>
            <p className="jg-cc-note">
              Currently stopped: {data?.trading.accounts_emergency_stopped ?? 0}{" "}
              account(s).
            </p>
          </div>
          <button
            type="button"
            className="btn danger"
            disabled={busy}
            onClick={() => setStopPending(true)}
          >
            Emergency stop all
          </button>
        </div>
      </section>

      <BackupPanel
        restoreEnabled={security?.restore_enabled_on_host ?? false}
        onChanged={() => void load()}
      />

      <SecurityPanel data={security} />

      {/* ----------------------------------------------------- incidents */}
      <section className="jg-cc-section">
        <h2>Incidents</h2>
        <div className="jg-cc-filters">
          {INCIDENT_FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              className={filter === f ? "jg-chip active" : "jg-chip"}
              onClick={() => setFilter(f)}
            >
              {f.replace(/_/g, " ")}
            </button>
          ))}
        </div>
        {incidents.length === 0 ? (
          <p className="jg-cc-note">No incidents recorded.</p>
        ) : (
          <ul className="jg-cc-incidents">
            {incidents.map((i) => (
              <li key={i.id}>
                <details>
                  <summary>
                    <span className={`jg-pill jg-pill-${tone(i.status)}`}>
                      {displayStatus(i.status)}
                    </span>
                    <span className="jg-inc-service">
                      {LABELS[i.service] ?? i.service}
                    </span>
                    <span className="jg-inc-cat">{i.category}</span>
                    <span className="jg-inc-time">{when(i.detected_at)}</span>
                  </summary>
                  <div className="jg-inc-body">
                    <p>{i.detail || "No further detail."}</p>
                    <p className="jg-cc-note">
                      Attempt {i.attempt_number} · final state{" "}
                      {i.final_state || "—"} · recovered {when(i.recovered_at)}
                    </p>
                    {i.actions.length > 0 && (
                      <ul className="jg-inc-actions">
                        {i.actions.map((a, idx) => (
                          <li key={`${a.operation}-${idx}`}>
                            <code>{a.operation}</code> {a.ok ? "ok" : "failed"}
                            {a.detail ? ` — ${a.detail}` : ""}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </details>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* --------------------------------------------------- confirmations */}
      {pending && (
        <ConfirmDialog
          title={pending.label}
          body={`This will run ${pending.label} on the host machine. It is recorded in the incident log.`}
          confirmLabel="Run it"
          onCancel={() => setPending(null)}
          onConfirm={() => void runOperation(pending.operation)}
          busy={busy}
        />
      )}
      {stopPending && (
        <ConfirmDialog
          title="Emergency stop all automated trading"
          body="Automation stops on every account and all bots are disabled. Open positions are NOT closed."
          confirmLabel="Stop all automation"
          danger
          onCancel={() => setStopPending(false)}
          onConfirm={() => void emergencyStopAll()}
          busy={busy}
        />
      )}
    </div>
  );
}

function Gate({
  label,
  value,
  required,
  unmet,
}: {
  label: string;
  value: string;
  required: string | null;
  unmet: boolean;
}) {
  return (
    <div className={unmet ? "jg-metric unmet" : "jg-metric"}>
      <span className="jg-metric-label">{label}</span>
      <span className="jg-metric-value">{value}</span>
      {required != null && <span className="jg-metric-req">req {required}</span>}
    </div>
  );
}

function StatusCard({
  name,
  status,
  detail,
  checkedAt,
}: {
  name: string;
  status: string;
  detail: string;
  checkedAt?: string | null;
}) {
  return (
    <article className="jg-cc-card">
      <div className="jg-cc-card-top">
        <h3>{name}</h3>
        <span className={`jg-pill jg-pill-${tone(status)}`}>
          {displayStatus(status)}
        </span>
      </div>
      <p className="jg-cc-detail">{detail || "—"}</p>
      {checkedAt !== undefined && (
        <p className="jg-cc-note">Last checked {when(checkedAt)}</p>
      )}
    </article>
  );
}

function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onCancel,
  onConfirm,
  busy,
  danger,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
  busy: boolean;
  danger?: boolean;
}) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="jg-confirm">
        <h3>{title}</h3>
        <p>{body}</p>
        <div className="jg-confirm-actions">
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className={danger ? "btn danger" : "btn primary"}
            onClick={onConfirm}
            disabled={busy}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
