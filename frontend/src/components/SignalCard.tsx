import { useState } from "react";
import { fmt } from "../lib/api";
import type { ExecutionResult, Signal, TradingMode } from "../lib/types";
import { Badge, Banner, Confidence, Spinner } from "./Primitives";

export function SignalCard({
  signal,
  mode,
  onExecute,
  busy,
  lastResult,
}: {
  signal: Signal | null;
  mode: TradingMode;
  onExecute: (signalId: number, volume?: number) => void;
  busy: boolean;
  lastResult: ExecutionResult | null;
}) {
  const [volume, setVolume] = useState("");

  if (!signal) {
    return (
      <div className="signal flat">
        <div className="signal-head">
          <span className="signal-action">NO SIGNAL YET</span>
        </div>
        <div className="reason">
          Run an analysis to generate a signal, or enable the bot to have one
          produced on every cycle.
        </div>
      </div>
    );
  }

  const kind =
    signal.action === "BUY" ? "buy" : signal.action === "SELL" ? "sell" : "flat";
  const actionable = signal.action !== "NO_TRADE";

  return (
    <div className={`signal ${kind}`}>
      <div className="signal-head">
        <span className="signal-action">{signal.action.replace("_", " ")}</span>
        <Confidence value={signal.confidence} />
        <div style={{ flex: 1 }} />
        {signal.executed && <Badge tone="up">Executed</Badge>}
        {signal.risk_approved === false && <Badge tone="down">Risk blocked</Badge>}
        <span className="faint num" style={{ fontSize: 12 }}>
          {fmt.time(signal.created_at)}
        </span>
      </div>

      {actionable && (
        <div className="levels">
          <div className="level">
            <div className="k">Entry</div>
            <div className="v num">{fmt.price(signal.entry)}</div>
          </div>
          <div className="level sl">
            <div className="k">Stop loss</div>
            <div className="v num">{fmt.price(signal.stop_loss)}</div>
          </div>
          <div className="level tp">
            <div className="k">Take profit</div>
            <div className="v num">{fmt.price(signal.take_profit)}</div>
          </div>
          <div className="level">
            <div className="k">R : R</div>
            <div className="v num">
              {signal.risk_reward ? `1 : ${signal.risk_reward}` : "—"}
            </div>
          </div>
        </div>
      )}

      <div className="reason">{signal.reason || "No rationale supplied."}</div>

      {signal.risk_reasons && signal.risk_reasons.length > 0 && (
        <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)" }}>
          <Banner tone={signal.risk_approved ? "ok" : "warn"}>
            <div>
              <strong>Risk engine</strong>
              <ul className="reasons">
                {signal.risk_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          </Banner>
        </div>
      )}

      {lastResult && (
        <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)" }}>
          <Banner tone={lastResult.executed ? "ok" : "err"}>
            <div>
              <strong>
                {lastResult.executed
                  ? `Order filled — ticket ${lastResult.ticket}, ${lastResult.volume} lots`
                  : "Not executed"}
              </strong>
              <ul className="reasons">
                {lastResult.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          </Banner>
        </div>
      )}

      {actionable && !signal.executed && (
        <div className="row" style={{ padding: "12px 14px" }}>
          <input
            className="num"
            style={{
              width: 92,
              font: "inherit",
              fontFamily: "var(--mono)",
              background: "var(--bg-inset)",
              border: "1px solid var(--line-strong)",
              borderRadius: 5,
              color: "var(--text)",
              padding: "6px 9px",
            }}
            placeholder="auto"
            inputMode="decimal"
            value={volume}
            onChange={(e) => setVolume(e.target.value)}
            aria-label="Lot size (leave blank for risk-based sizing)"
          />
          <button
            className={`btn ${signal.action === "BUY" ? "buy" : "sell"}`}
            disabled={busy}
            onClick={() =>
              onExecute(signal.id, volume.trim() ? Number(volume) : undefined)
            }
          >
            {busy ? <Spinner /> : null} Place {signal.action} order
          </button>
          <span className="faint" style={{ fontSize: 12 }}>
            {mode === "MANUAL"
              ? "Manual mode — you decide."
              : `${mode} mode — the bot may also act on this.`}{" "}
            Blank lot size = sized from your risk %.
          </span>
        </div>
      )}
    </div>
  );
}
