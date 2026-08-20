import { useState } from "react";
import { api } from "../lib/api";
import type { Analysis, RiskSettings, Signal } from "../lib/types";

/**
 * J Gold AI analysis panel — the explainable-AI surface.
 *
 * The panel's job is to make a *waiting* bot legible as waiting rather than
 * broken. Every gate is shown with the live value beside the configured
 * minimum, so "NO TRADE, confidence 42% against a required 80%" is an
 * answer a customer can check, where "NO TRADE" alone is a mystery.
 *
 * AI ASSIST NEVER EXECUTES. "Use AI setup" fills the order ticket and
 * nothing else — the customer still presses the button and still confirms.
 * This component has no execution call of its own; `onUseSetup` hands
 * values to the ticket, which is the only thing that can place an order.
 */

export interface AISetup {
  side: "BUY" | "SELL";
  entry: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  confidence: number;
  rr: number | null;
}

function Gate({
  label,
  value,
  required,
  unmet,
}: {
  label: string;
  value: string;
  required: string;
  unmet: boolean;
}) {
  return (
    <div className={unmet ? "jg-ai-gate unmet" : "jg-ai-gate"}>
      <span className="jg-ai-gate-label">{label}</span>
      <span className="jg-ai-gate-value">{value}</span>
      <span className="jg-ai-gate-req">required {required}</span>
    </div>
  );
}

export function AIPanel({
  risk,
  onUseSetup,
  onAnalysis,
}: {
  risk: RiskSettings | null;
  onUseSetup: (setup: AISetup) => void;
  onAnalysis?: (analysis: Analysis | null) => void;
}) {
  const [signal, setSignal] = useState<Signal | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.runAnalysis();
      setSignal(res.signal);
      setAnalysis(res.analysis);
      onAnalysis?.(res.analysis);
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? err.message
          : "Analysis is unavailable right now.",
      );
    } finally {
      setBusy(false);
    }
  }

  const minConfidence = risk?.min_confidence ?? 70;
  const minRr = risk?.min_rr ?? 1.5;
  const tradable = signal ? signal.action === "BUY" || signal.action === "SELL" : false;
  const confidenceUnmet = signal ? signal.confidence < minConfidence : false;
  const rrUnmet = signal
    ? signal.risk_reward == null || signal.risk_reward < minRr
    : false;

  // Whether the setup is complete enough to fill a ticket. A partial setup
  // is not offered: half an idea is worse than none in an order form.
  const usable =
    signal != null &&
    tradable &&
    signal.entry != null &&
    signal.stop_loss != null;

  return (
    <section className="jg-ai">
      <header className="jg-ai-head">
        <h3>J Gold AI analysis</h3>
        <button type="button" className="btn sm" disabled={busy} onClick={() => void run()}>
          {busy ? "Analysing…" : "Run analysis"}
        </button>
      </header>

      {error && <p className="jg-ws-error">{error}</p>}

      {!signal && !error && (
        <p className="jg-ai-idle">
          Run an analysis to see the current read, the gates it must clear,
          and why it would or would not trade.
        </p>
      )}

      {signal && (
        <>
          <div className={`jg-ai-verdict ${tradable ? "trade" : "wait"}`}>
            <span className="jg-ai-action">{signal.action.replace("_", " ")}</span>
            <span className="jg-ai-symbol">{signal.symbol}</span>
          </div>

          <Gate
            label="Confidence"
            value={`${signal.confidence}%`}
            required={`${minConfidence}%`}
            unmet={confidenceUnmet}
          />
          <Gate
            label="Risk / reward"
            value={signal.risk_reward != null ? signal.risk_reward.toFixed(2) : "—"}
            required={minRr.toFixed(2)}
            unmet={rrUnmet}
          />

          {analysis?.market && (
            <dl className="jg-ai-context">
              <div><dt>Trend</dt><dd>{analysis.market.trend}</dd></div>
              <div><dt>Regime</dt><dd>{String(analysis.market.regime)}</dd></div>
              <div><dt>Momentum</dt><dd>{String(analysis.market.momentum)}</dd></div>
            </dl>
          )}

          {analysis?.hierarchy && (
            <div className="jg-ai-tfs">
              {(["major", "intermediate", "setup", "refinement"] as const).map((k) => {
                const group = analysis.hierarchy![k];
                const bias = String(
                  (group as unknown as { bias?: string }).bias ?? group,
                );
                return (
                  <div key={k} className="jg-ai-tf">
                    <span>{k}</span>
                    <strong className={`jg-bias-${bias.toLowerCase()}`}>{bias}</strong>
                  </div>
                );
              })}
            </div>
          )}

          {signal.risk_approved === false && signal.risk_reasons?.length ? (
            <div className="jg-ai-blocked">
              <strong>Risk engine blocked this setup</strong>
              <ul>
                {signal.risk_reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <p className="jg-ai-reason">
            {signal.reason ||
              (tradable
                ? "A setup is present."
                : "No setup meets the configured requirements yet.")}
          </p>

          <div className="jg-ai-decision">
            {tradable && !confidenceUnmet && !rrUnmet
              ? "Decision: setup meets your configured minimums."
              : "Decision: wait for a better entry."}
          </div>

          {/* AI ASSIST: fills the ticket. It cannot place an order. */}
          <button
            type="button"
            className="jg-btn primary"
            style={{ width: "100%", marginTop: 12 }}
            disabled={!usable}
            onClick={() =>
              usable &&
              onUseSetup({
                side: signal.action as "BUY" | "SELL",
                entry: signal.entry,
                stopLoss: signal.stop_loss,
                takeProfit: signal.take_profit,
                confidence: signal.confidence,
                rr: signal.risk_reward,
              })
            }
          >
            {usable ? "Use AI setup" : "No usable setup to fill"}
          </button>
          <p className="jg-ai-note">
            Fills the order ticket only. You still place and confirm the trade.
          </p>
        </>
      )}
    </section>
  );
}
