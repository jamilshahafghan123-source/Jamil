import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { AlertKindInfo, CustomerAlert } from "../lib/types";

/**
 * Alerts (section 62).
 *
 * There is no channel selector, because there is no channel to select:
 * email, SMS and push are not connected, and the panel says so rather
 * than offering a switch that would do nothing. An alert a customer
 * believed would reach their phone and did not would be worse than no
 * alert at all.
 *
 * The form only offers a level or a session where the chosen kind
 * actually needs one, so an alert that could never fire cannot be
 * assembled here — the backend refuses it too.
 */
export function AlertsPanel({ symbol }: { symbol: string }) {
  const [kinds, setKinds] = useState<AlertKindInfo[]>([]);
  const [deliveryNote, setDeliveryNote] = useState("");
  const [alerts, setAlerts] = useState<CustomerAlert[]>([]);
  const [kind, setKind] = useState("PRICE_ABOVE");
  const [threshold, setThreshold] = useState("");
  const [session, setSession] = useState("LONDON");
  const [note, setNote] = useState("");
  const [repeatable, setRepeatable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setAlerts((await api.alerts()).alerts);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Alerts unavailable");
    }
  }, []);

  useEffect(() => {
    api.alertKinds()
      .then((r) => { setKinds(r.kinds); setDeliveryNote(r.delivery_note); })
      .catch(() => setKinds([]));
    void refresh();
  }, [refresh]);

  const selected = kinds.find((k) => k.kind === kind);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await api.createAlert({
        kind,
        symbol,
        threshold: selected?.needs_threshold ? Number(threshold) : null,
        session: selected?.needs_session ? session : null,
        note,
        repeatable,
      });
      setThreshold("");
      setNote("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create alert");
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  const incomplete =
    (selected?.needs_threshold && threshold.trim() === "") ||
    (selected?.needs_session && !session);

  return (
    <div className="jg-alerts">
      {error && <p className="jg-ws-error">{error}</p>}

      <section className="jg-alert-form">
        <label>
          Alert me when
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {kinds.map((k) => (
              <option key={k.kind} value={k.kind}>{k.label}</option>
            ))}
          </select>
        </label>

        {selected?.needs_threshold && (
          <label>
            Level
            <input type="number" step="any" value={threshold}
                   placeholder="3000.00"
                   onChange={(e) => setThreshold(e.target.value)} />
          </label>
        )}

        {selected?.needs_session && (
          <label>
            Session
            <select value={session} onChange={(e) => setSession(e.target.value)}>
              {["SYDNEY", "TOKYO", "LONDON", "NEW_YORK"].map((s) => (
                <option key={s} value={s}>{s.replace("_", " ")}</option>
              ))}
            </select>
          </label>
        )}

        <label>
          Note
          <input value={note} maxLength={200} placeholder="optional"
                 onChange={(e) => setNote(e.target.value)} />
        </label>

        <label className="jg-alert-repeat">
          <input type="checkbox" checked={repeatable}
                 onChange={(e) => setRepeatable(e.target.checked)} />
          Repeat — otherwise it fires once and disarms
        </label>

        <button type="button" className="btn primary" disabled={busy || incomplete}
                onClick={() => void create()}>
          Add alert for {symbol}
        </button>
      </section>

      <section className="jg-alert-list">
        {alerts.length === 0 && (
          <p className="jg-cc-note">No alerts yet.</p>
        )}
        {alerts.map((alert) => (
          <article key={alert.id}
                   className={alert.acknowledged ? "jg-alert-row"
                                                 : "jg-alert-row fired"}>
            <div className="jg-alert-main">
              <span className="jg-alert-label">
                {alert.label}
                {alert.threshold != null && ` ${alert.threshold}`}
                {alert.session && ` · ${alert.session.replace("_", " ")}`}
              </span>
              <span className="jg-alert-symbol">{alert.symbol}</span>
            </div>
            {alert.note && <p className="jg-alert-note">{alert.note}</p>}
            {alert.last_message && (
              <p className="jg-alert-fired">
                {alert.last_message}
                {alert.triggered_at &&
                  ` · ${new Date(alert.triggered_at).toLocaleString([], { hour12: false })}`}
              </p>
            )}
            <div className="jg-alert-actions">
              <button type="button" className="btn sm" disabled={busy}
                      onClick={() => void act(() =>
                        api.setAlertEnabled(alert.id, !alert.enabled))}>
                {alert.enabled ? "Disable" : "Enable"}
              </button>
              {!alert.acknowledged && (
                <button type="button" className="btn sm" disabled={busy}
                        onClick={() => void act(() => api.acknowledgeAlert(alert.id))}>
                  Dismiss
                </button>
              )}
              <button type="button" className="btn sm danger" disabled={busy}
                      onClick={() => void act(() => api.deleteAlert(alert.id))}>
                Delete
              </button>
              {alert.repeatable && <span className="jg-alert-flag">repeats</span>}
            </div>
          </article>
        ))}
      </section>

      {deliveryNote && <p className="jg-opp-note">{deliveryNote}</p>}
    </div>
  );
}
