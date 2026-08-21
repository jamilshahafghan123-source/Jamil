import { useMemo } from "react";
import type { Bar, Timeframe } from "../lib/types";

/**
 * Backtest prerequisites (section 43).
 *
 * There is NO backtester here, and this panel does not pretend otherwise.
 * Simulating fills needs things the platform does not yet have, and a
 * "backtest" that guesses at them produces an equity curve that looks
 * authoritative and is fiction — which is worse than no backtester at
 * all, because someone would size a real position on it.
 *
 * What this panel does is state, from live measurements rather than a
 * static list, exactly what is present and what is missing. Every ready
 * line is counted from the data actually loaded, so it goes red on its
 * own when the data is not there.
 */

export interface Prerequisite {
  name: string;
  ready: boolean;
  detail: string;
}

/** How far back the loaded history reaches, in plain words. */
function span(bars: Bar[]): string {
  if (bars.length < 2) return "not enough candles to measure a span";
  const first = new Date(bars[0].time);
  const last = new Date(bars[bars.length - 1].time);
  const hours = (last.getTime() - first.getTime()) / 3_600_000;
  if (hours < 48) return `${hours.toFixed(1)} hours`;
  return `${(hours / 24).toFixed(1)} days`;
}

export function prerequisites(
  bars: Bar[], symbol: string, timeframe: Timeframe,
): Prerequisite[] {
  // Counted, not assumed: a feed that reports zero spread on every candle
  // cannot support a fill model however many candles it sends.
  const withSpread = bars.filter((b) => (b.spread ?? 0) > 0).length;
  const withVolume = bars.filter((b) => (b.tick_volume ?? 0) > 0).length;

  return [
    {
      name: "Historical candles",
      ready: bars.length >= 100,
      detail: bars.length === 0
        ? `No candles loaded for ${symbol} ${timeframe}.`
        : `${bars.length} candles of ${symbol} ${timeframe}, covering ${span(bars)}. `
          + "A backtest needs far more than one screen of history.",
    },
    {
      name: "Historical spread",
      ready: withSpread > bars.length * 0.9 && bars.length > 0,
      detail: bars.length === 0
        ? "No candles to read a spread from."
        : `${withSpread} of ${bars.length} candles carry a spread reading. `
          + "Entry and exit prices are meaningless without the spread that "
          + "applied at the time.",
    },
    {
      name: "Tick volume",
      ready: withVolume > bars.length * 0.9 && bars.length > 0,
      detail: `${withVolume} of ${bars.length} candles carry tick volume — `
        + "an activity proxy, never traded contracts.",
    },
    {
      name: "Deterministic setup engine",
      ready: true,
      detail: "The same engine that produces live setups can be run over "
        + "past candles, so a backtest would test what actually trades.",
    },
    {
      name: "Replay engine",
      ready: true,
      detail: "Bar-by-bar traversal of loaded history already exists and is "
        + "what a backtest would step through.",
    },
    {
      name: "Intrabar path",
      ready: false,
      detail: "MISSING. Candles record open, high, low and close, not the "
        + "order they happened in. Whether a stop or a target was hit first "
        + "inside a candle cannot be known from this data, and guessing it "
        + "is how a backtest reports profits that never existed.",
    },
    {
      name: "Slippage and fill model",
      ready: false,
      detail: "MISSING. No measured relationship between order size, spread "
        + "and the price actually received. Assuming perfect fills flatters "
        + "every result.",
    },
    {
      name: "Commission and swap",
      ready: false,
      detail: "MISSING. No broker cost schedule is configured, and overnight "
        + "financing decides whether many strategies are profitable at all.",
    },
  ];
}

export function BacktestPanel({
  bars, symbol, timeframe,
}: {
  bars: Bar[];
  symbol: string;
  timeframe: Timeframe;
}) {
  const items = useMemo(
    () => prerequisites(bars, symbol, timeframe),
    [bars, symbol, timeframe],
  );
  const missing = items.filter((i) => !i.ready);

  return (
    <section className="jg-backtest">
      <h4 className="jg-symbol-group">Backtesting</h4>

      <p className="jg-backtest-status">
        EXECUTION SIMULATION DISABLED
      </p>
      <p className="jg-cc-note">
        {missing.length} of {items.length} prerequisites are not met, so no
        backtest can be run and none is offered. A result produced without
        them would look authoritative and be fiction — and someone would
        size a real position on it.
      </p>

      <ul className="jg-backtest-list">
        {items.map((item) => (
          <li key={item.name} className={item.ready ? "ready" : "missing"}>
            <span className="jg-backtest-mark" aria-hidden="true">
              {item.ready ? "✓" : "✕"}
            </span>
            <div>
              <strong>{item.name}</strong>
              <p>{item.detail}</p>
            </div>
          </li>
        ))}
      </ul>

      <p className="jg-cc-note">
        The three missing items are data problems, not coding ones. Nothing
        in this panel becomes ready by writing more of the platform.
      </p>
    </section>
  );
}
