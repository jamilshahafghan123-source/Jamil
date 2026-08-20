import type { ChecklistItem, SecurityOverview } from "../lib/types";

/**
 * ADMIN security panel.
 *
 * Everything here is presence and posture: SET or MISSING, READY or NOT
 * READY, PASS or FAIL. No secret value is rendered because the backend
 * sends none — `SecurityOverview` has no field that could carry one.
 *
 * ROTATION RECOMMENDED is a display state, not a backend one. The MT5
 * bridge token was exposed during development, so a token that is merely
 * SET is not good enough for launch, and the panel says so rather than
 * showing a reassuring green tick.
 */

const LABELS: Record<string, string> = {
  JWT_SECRET: "JWT secret",
  MT5_BRIDGE_TOKEN: "MT5 bridge token",
  WINDOWS_AGENT_TOKEN: "Windows agent token",
  ANTHROPIC_API_KEY: "AI provider key",
  DATABASE_URL: "Database",
  BOOTSTRAP_PASSWORD: "Bootstrap password",
};

/** Known to have been exposed in development; SET alone is not sufficient. */
const ROTATION_RECOMMENDED = new Set(["MT5_BRIDGE_TOKEN"]);

function secretState(name: string, value: string): [string, string] {
  if (value !== "SET") return ["MISSING", "bad"];
  if (ROTATION_RECOMMENDED.has(name)) return ["ROTATION RECOMMENDED", "warn"];
  if (name === "DATABASE_URL") return ["CONFIGURED", "ok"];
  return ["SET", "ok"];
}

function itemTone(state: ChecklistItem["state"]): [string, string] {
  if (state === "PASS") return ["PASS", "ok"];
  if (state === "FAIL") return ["FAIL", "bad"];
  // MANUAL is genuinely unverified — amber, never green.
  return ["NOT CONFIRMED", "warn"];
}

export function SecurityPanel({ data }: { data: SecurityOverview | null }) {
  if (!data) {
    return (
      <section className="jg-cc-section">
        <h2>Security</h2>
        <p className="jg-cc-note">Loading security status…</p>
      </section>
    );
  }

  const ready = data.deployment_readiness.status === "READY";
  const rotationNeeded = Object.entries(data.secrets).some(
    ([name, value]) => value === "SET" && ROTATION_RECOMMENDED.has(name),
  );

  return (
    <section className="jg-cc-section">
      <h2>Security</h2>

      {rotationNeeded && (
        <div className="jg-rotate-notice">
          <strong>MT5 bridge credential rotation is recommended before public
          launch.</strong>
          <p className="jg-cc-note">
            The token was exposed during development. Rotation is a manual,
            documented procedure — it is deliberately not available from this
            browser, and the value is never displayed here. See
            docs/SECRET_ROTATION.md in the repository.
          </p>
        </div>
      )}

      <div className="jg-cc-grid">
        <article className="jg-cc-card">
          <div className="jg-cc-card-top">
            <h3>Secret configuration</h3>
          </div>
          <ul className="jg-secret-list">
            {Object.entries(data.secrets).map(([name, value]) => {
              const [label, colour] = secretState(name, value);
              return (
                <li key={name}>
                  <span>{LABELS[name] ?? name}</span>
                  <span className={`jg-pill jg-pill-${colour}`}>{label}</span>
                </li>
              );
            })}
          </ul>
          <p className="jg-cc-note">Values are never shown, only presence.</p>
        </article>

        <article className="jg-cc-card">
          <div className="jg-cc-card-top">
            <h3>Access &amp; accounts</h3>
          </div>
          <dl className="jg-cc-meta">
            <div>
              <dt>Failed logins</dt>
              <dd>{data.recent_failed_logins}</dd>
            </div>
            <div>
              <dt>Admin accounts</dt>
              <dd>{data.admin_accounts}</dd>
            </div>
          </dl>
          <p className="jg-cc-note">MFA: {data.mfa.status.replace(/_/g, " ")}</p>
          <p className="jg-cc-note">
            Password reset backend: AVAILABLE · Email delivery:{" "}
            NOT CONFIGURED
          </p>
          <p className="jg-cc-note">
            Reset tokens can be created, but automated email delivery is not
            configured yet, so an administrator must pass the link on. Tokens
            are never displayed here.
          </p>
        </article>

        <article className="jg-cc-card">
          <div className="jg-cc-card-top">
            <h3>Version</h3>
          </div>
          <dl className="jg-cc-meta">
            <div>
              <dt>Current</dt>
              <dd>{data.version.version}</dd>
            </div>
            <div>
              <dt>Commit</dt>
              <dd>{data.version.commit}</dd>
            </div>
          </dl>
          <dl className="jg-cc-meta">
            <div>
              <dt>Last known good</dt>
              <dd>{data.version.last_known_good}</dd>
            </div>
            <div>
              <dt>Environment</dt>
              <dd>{data.version.environment}</dd>
            </div>
          </dl>
        </article>

        <article className="jg-cc-card">
          <div className="jg-cc-card-top">
            <h3>Deployment readiness</h3>
            <span className={`jg-pill jg-pill-${ready ? "ok" : "bad"}`}>
              {ready ? "READY" : "NOT READY"}
            </span>
          </div>
          {data.deployment_readiness.blocking.length > 0 && (
            <>
              <p className="jg-cc-note">Blocking:</p>
              <ul className="jg-reason-list">
                {data.deployment_readiness.blocking.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </>
          )}
          {data.deployment_readiness.warnings.length > 0 && (
            <>
              <p className="jg-cc-note">Warnings:</p>
              <ul className="jg-reason-list muted">
                {data.deployment_readiness.warnings.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </>
          )}
          {ready && <p className="jg-cc-detail">All checks passed.</p>}
        </article>
      </div>

      {/* ------------------------------------------- launch checklist */}
      <h3 className="jg-cc-sub">Public launch checklist</h3>
      <p className="jg-cc-note">
        {data.launch_checklist.failed} failing ·{" "}
        {data.launch_checklist.manual_outstanding} not confirmed. {data.launch_checklist.note}
      </p>
      <ul className="jg-check-list">
        {data.launch_checklist.items.map((item) => {
          const [label, colour] = itemTone(item.state);
          return (
            <li key={item.key}>
              <span className={`jg-pill jg-pill-${colour}`}>{label}</span>
              <div className="jg-check-body">
                <strong>{item.title}</strong>
                <span className="jg-cc-note">{item.detail}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
