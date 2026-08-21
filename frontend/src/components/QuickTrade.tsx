import { useMemo } from "react";
import type { InstrumentInfo } from "../lib/types";

/**
 * Compact quick-trade control, anchored to the chart's top-left.
 *
 * Deliberately small and dismissible: a large order panel floating over
 * the middle of the chart hides the thing the customer is reading in
 * order to decide. SELL and BUY carry the live bid and ask, so the price
 * being acted on is the price on screen.
 *
 * Volume bounds come from the instrument's own metadata rather than a
 * universal constant, and the Central Risk Manager still rules on
 * everything afterwards — a lot this control accepts is not a lot the
 * platform has agreed to trade.
 */
export function QuickTrade({
  instrument, bid, ask, volume, onVolume, side, onSide,
  stopLoss, takeProfit, onStopLoss, onTakeProfit, onPlace,
  disabled, disabledReason, onHide,
}: {
  instrument: InstrumentInfo | null;
  bid: number | null;
  ask: number | null;
  volume: string;
  onVolume: (v: string) => void;
  side: "BUY" | "SELL";
  onSide: (s: "BUY" | "SELL") => void;
  stopLoss: string;
  takeProfit: string;
  onStopLoss: (v: string) => void;
  onTakeProfit: (v: string) => void;
  onPlace: () => void;
  disabled: boolean;
  disabledReason?: string | null;
  onHide: () => void;
}) {
  const step = instrument?.volume_step ?? 0.01;
  const min = instrument?.min_volume ?? 0.01;
  const max = instrument?.max_volume ?? 100;
  const digits = instrument?.digits ?? 2;

  const parsed = Number.parseFloat(volume);
  const invalid = useMemo(() => {
    if (!Number.isFinite(parsed)) return "Enter a volume";
    if (parsed < min) return `Minimum ${min}`;
    if (parsed > max) return `Maximum ${max}`;
    // Off-step volumes are rejected by the broker, so they are caught here
    // rather than after a round trip.
    const steps = Math.round((parsed - min) / step);
    if (Math.abs(min + steps * step - parsed) > 1e-9) {
      return `Must be a multiple of ${step}`;
    }
    return null;
  }, [parsed, min, max, step]);

  const nudge = (direction: 1 | -1) => {
    const base = Number.isFinite(parsed) ? parsed : min;
    const next = Math.min(max, Math.max(min, base + direction * step));
    // Round to the step's own precision so 0.1 + 0.01 is not 0.11000000001.
    const decimals = (String(step).split(".")[1] ?? "").length;
    onVolume(next.toFixed(decimals));
  };

  const spread = bid != null && ask != null ? ask - bid : null;

  return (
    <div className="jg-quick">
      <div className="jg-quick-prices">
        <button
          type="button"
          className={side === "SELL" ? "jg-quick-side sell active" : "jg-quick-side sell"}
          onClick={() => onSide("SELL")}
        >
          <span className="jg-quick-price">
            {bid != null ? bid.toFixed(digits) : "—"}
          </span>
          <span className="jg-quick-tag">SELL</span>
        </button>

        <span className="jg-quick-spread" title="Spread">
          {spread != null ? (spread * Math.pow(10, digits)).toFixed(1) : "—"}
        </span>

        <button
          type="button"
          className={side === "BUY" ? "jg-quick-side buy active" : "jg-quick-side buy"}
          onClick={() => onSide("BUY")}
        >
          <span className="jg-quick-price">
            {ask != null ? ask.toFixed(digits) : "—"}
          </span>
          <span className="jg-quick-tag">BUY</span>
        </button>

        <button type="button" className="jg-quick-hide" onClick={onHide}
                title="Hide quick trade" aria-label="Hide quick trade">×</button>
      </div>

      <div className="jg-quick-row">
        <label className="jg-quick-field">
          <span>LOT SIZE</span>
          <div className="jg-quick-volume">
            <button type="button" onClick={() => nudge(-1)}
                    aria-label="Decrease volume">−</button>
            <input
              value={volume}
              inputMode="decimal"
              aria-label="Volume"
              onChange={(e) => onVolume(e.target.value)}
            />
            <button type="button" onClick={() => nudge(1)}
                    aria-label="Increase volume">+</button>
          </div>
        </label>
      </div>

      <div className="jg-quick-row">
        <label className="jg-quick-field">
          <span>SL</span>
          <input value={stopLoss} inputMode="decimal" placeholder="none"
                 aria-label="Stop loss"
                 onChange={(e) => onStopLoss(e.target.value)} />
        </label>
        <label className="jg-quick-field">
          <span>TP</span>
          <input value={takeProfit} inputMode="decimal" placeholder="none"
                 aria-label="Take profit"
                 onChange={(e) => onTakeProfit(e.target.value)} />
        </label>
      </div>

      {invalid && <p className="jg-quick-invalid">{invalid}</p>}
      {!invalid && disabledReason && (
        <p className="jg-quick-invalid">{disabledReason}</p>
      )}

      <button
        type="button"
        className={side === "BUY" ? "jg-quick-place buy" : "jg-quick-place sell"}
        disabled={disabled || invalid != null}
        onClick={onPlace}
      >
        {side} {Number.isFinite(parsed) ? parsed : ""} {instrument?.symbol ?? ""}
      </button>
      <p className="jg-quick-note">
        Virtual money · risk manager decides
      </p>
    </div>
  );
}
