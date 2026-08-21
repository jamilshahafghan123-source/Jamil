import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { OpportunityFeed, OpportunityRow } from "../lib/types";

/**
 * Opportunity telemetry (section 49).
 *
 * Shows everything the engine detected, including — especially — what it
 * declined. A log of executed trades answers "what did we trade?"; the
 * question worth asking is "what did we see, and why did we not trade
 * it?", and only the declined rows can answer that.
 *
 * The three outcomes are three separate columns throughout. Folding them
 * into one status would make a quiet day unexplainable: "no trades"
 * could equally be the engine finding nothing, risk refusing everything,
 * or execution failing, and those call for different responses.
 */

function decisionTone(row: OpportunityRow): string {
  if (row.execution_result === "FILLED") return "filled";
  // Checked before the generic execution branch: a suppressed repeat
  // never reached execution, and colouring it as a failure would read as
  // something going wrong when nothing did.
  if (row.suppressed_as_duplicate) return "no-trade";
  if (row.execution_result) return "failed";
  if (row.risk_decision === "REJECTED") return "rejected";
  if (row.ai_decision === "NO_TRADE") return "no-trade";
  return "";
}

/** Which stage stopped this opportunity, in plain words. */
function stoppedBy(row: OpportunityRow): string {
  if (row.execution_result === "FILLED") return "Executed";
  if (row.suppressed_as_duplicate) return "Repeat of a setup already traded";
  if (row.execution_result) return `Execution: ${row.execution_result}`;
  if (row.risk_decision === "REJECTED") return "Risk manager";
  if (row.ai_decision === "NO_TRADE") return "AI declined";
  if (row.risk_decision === "APPROVED") return "Approved, awaiting fill";
  return "Detected";
}

export function OpportunityLog({ admin = false }: { admin?: boolean }) {
  const [feed, setFeed] = useState<OpportunityFeed | null>(null);
  const [days, setDays] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setFeed(await (admin ? api.adminOpportunities(days) : api.opportunities(days)));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Telemetry unavailable");
    }
  }, [admin, days]);

  useEffect(() => { void load(); }, [load]);

  if (error) return <p className="jg-ws-error">{error}</p>;
  if (!feed) return <p className="jg-cc-note">Loading…</p>;

  const s = feed.summary;

  return (
    <div className="jg-opp">
      <div className="jg-opp-controls">
        {[1, 7, 30].map((d) => (
          <button key={d} type="button"
                  className={days === d ? "jg-chip active" : "jg-chip"}
                  onClick={() => setDays(d)}>
            {d === 1 ? "Today" : `${d} days`}
          </button>
        ))}
        <div className="jg-spacer" />
        {feed.customers != null && (
          <span className="jg-opp-note">{feed.customers} customer(s)</span>
        )}
      </div>

      {/* The funnel, stage by stage. Reading left to right says where the
          day actually went. */}
      <div className="jg-opp-funnel">
        <Stat label="Detected" value={s.detected} />
        <Stat label="AI declined" value={s.ai_no_trade} />
        <Stat label="AI proposed" value={s.ai_proposed} />
        {/* Its own stage. These never reached the risk manager, so
            folding them into "Risk rejected" would overstate how much it
            refused — and leaving them out entirely turns the funnel into
            a sum that does not add up. */}
        <Stat label="Repeat suppressed" value={s.suppressed_duplicates} />
        <Stat label="Risk rejected" value={s.risk_rejected} />
        <Stat label="Executed" value={s.executed} />
        <Stat
          label="Net P/L"
          value={s.net_pnl == null ? "—" : s.net_pnl.toFixed(2)}
          tone={s.net_pnl == null ? "" : s.net_pnl > 0 ? "up" : s.net_pnl < 0 ? "down" : ""}
        />
      </div>

      <p className="jg-opp-note">
        {s.win_rate != null
          ? `Win rate ${s.win_rate}% across ${s.settled} settled trades.`
          : s.rate_note}
      </p>

      {s.top_rejection_reasons.length > 0 && (
        <section className="jg-opp-reasons">
          <h4 className="jg-symbol-group">Why setups were declined</h4>
          <ul>
            {s.top_rejection_reasons.map((r) => (
              <li key={r.reason}>
                <span className="jg-opp-count">{r.count}×</span> {r.reason}
              </li>
            ))}
          </ul>
        </section>
      )}

      {feed.opportunities.length === 0 ? (
        <p className="jg-cc-note">
          No opportunities detected in this window. A period with no
          qualifying setup correctly produces no trades.
        </p>
      ) : (
        <div className="jg-ws-table-wrap">
          <table className="jg-ws-table jg-opp-table">
            <thead>
              <tr>
                <th>Time</th><th>Symbol</th><th>Session</th><th>Class</th>
                <th>Grade</th><th>Score</th><th>Side</th>
                <th>Conf</th><th>Req</th><th>R:R</th><th>Req</th>
                <th>AI</th><th>Risk</th><th>Execution</th><th>P/L</th>
              </tr>
            </thead>
            <tbody>
              {feed.opportunities.map((row) => (
                <tr key={row.id}
                    className={`jg-opp-row ${decisionTone(row)}`}
                    onClick={() => setExpanded(expanded === row.id ? null : row.id)}
                    title={`${stoppedBy(row)} — click for the score breakdown`}>
                  <td>{row.detected_at
                    ? new Date(row.detected_at).toLocaleTimeString([], { hour12: false })
                    : "—"}</td>
                  <td>{row.symbol}</td>
                  <td>{row.session || "—"}</td>
                  <td>{row.setup_class}</td>
                  <td>{row.grade}</td>
                  <td>{row.score}</td>
                  <td>{row.direction || "—"}</td>
                  <td>{row.confidence}%</td>
                  <td className="jg-opp-required">{row.required_confidence}%</td>
                  <td>{row.expected_rr.toFixed(2)}</td>
                  <td className="jg-opp-required">{row.required_rr.toFixed(2)}</td>
                  <td>{row.ai_decision}</td>
                  <td>{row.risk_decision ?? "—"}</td>
                  <td>{row.execution_result ?? "—"}</td>
                  <td className={row.outcome_pnl == null ? "" :
                                 row.outcome_pnl > 0 ? "up" : "down"}>
                    {row.outcome_pnl == null ? "—" : row.outcome_pnl.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {expanded != null && (() => {
        const row = feed.opportunities.find((o) => o.id === expanded);
        if (!row) return null;
        const factors = Object.entries(row.score_breakdown)
          .sort((a, b) => b[1] - a[1]);
        return (
          <section className="jg-opp-detail">
            <h4 className="jg-symbol-group">
              {row.symbol} {row.direction} · {row.setup_class} · score {row.score}
            </h4>
            <p className="jg-opp-note">{stoppedBy(row)}</p>
            {(row.risk_reason || row.rejection_reason) && (
              <p className="jg-opp-reason">
                {row.risk_reason ?? row.rejection_reason}
              </p>
            )}
            {factors.length > 0 && (
              <ul className="jg-opp-factors">
                {factors.map(([name, contribution]) => (
                  <li key={name}>
                    <span>{name.replace(/_/g, " ")}</span>
                    <span className="jg-opp-factor-value">
                      {contribution.toFixed(1)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })()}

      {feed.note && <p className="jg-opp-note">{feed.note}</p>}
    </div>
  );
}

function Stat({ label, value, tone = "" }: {
  label: string; value: number | string; tone?: string;
}) {
  return (
    <div className="jg-opp-stat">
      <span className="jg-opp-stat-label">{label}</span>
      <strong className={`jg-opp-stat-value ${tone}`}>{value}</strong>
    </div>
  );
}
