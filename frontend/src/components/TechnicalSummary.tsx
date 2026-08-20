import { useMemo } from "react";
import {
  adx, cci, ema, latest, macd, roc, rsi, sma, stochastic, williamsR, wma,
} from "../lib/indicators";
import type { Bar } from "../lib/types";

/**
 * Technical summary (section 32).
 *
 * Every rating here is computed from this project's own indicator engine
 * over the bars already on screen. Each contributing indicator casts one
 * vote — buy, sell or neutral — and the rating is the balance of those
 * votes. Nothing is weighted by opinion, and the individual values are
 * shown underneath so the summary can always be checked against what
 * produced it.
 *
 * This is a description of current indicator readings. It is not advice
 * and not a forecast, which is why the wording stays on what the
 * indicators say rather than on what price will do.
 */

export type Rating =
  | "STRONG_SELL" | "SELL" | "NEUTRAL" | "BUY" | "STRONG_BUY";

export const RATING_LABEL: Record<Rating, string> = {
  STRONG_SELL: "Strong sell",
  SELL: "Sell",
  NEUTRAL: "Neutral",
  BUY: "Buy",
  STRONG_BUY: "Strong buy",
};

type Vote = 1 | 0 | -1;

interface Reading {
  label: string;
  value: string;
  vote: Vote;
}

/** Balance of votes to a rating. Thresholds are proportions, not counts,
 *  so adding an indicator later does not silently shift every rating. */
function rate(votes: Vote[]): Rating {
  if (votes.length === 0) return "NEUTRAL";
  const score = votes.reduce<number>((a, b) => a + b, 0) / votes.length;
  if (score >= 0.5) return "STRONG_BUY";
  if (score >= 0.15) return "BUY";
  if (score <= -0.5) return "STRONG_SELL";
  if (score <= -0.15) return "SELL";
  return "NEUTRAL";
}

function oscillatorReadings(bars: Bar[]): Reading[] {
  const out: Reading[] = [];

  const r = latest(rsi(bars, 14));
  if (r != null) {
    out.push({ label: "RSI (14)", value: r.toFixed(1),
      vote: r >= 70 ? -1 : r <= 30 ? 1 : 0 });
  }

  const stoch = latest(stochastic(bars, 14).k);
  if (stoch != null) {
    out.push({ label: "Stochastic %K (14)", value: stoch.toFixed(1),
      vote: stoch >= 80 ? -1 : stoch <= 20 ? 1 : 0 });
  }

  const c = latest(cci(bars, 20));
  if (c != null) {
    out.push({ label: "CCI (20)", value: c.toFixed(1),
      vote: c >= 100 ? -1 : c <= -100 ? 1 : 0 });
  }

  const w = latest(williamsR(bars, 14));
  if (w != null) {
    out.push({ label: "Williams %R (14)", value: w.toFixed(1),
      vote: w >= -20 ? -1 : w <= -80 ? 1 : 0 });
  }

  const hist = latest(macd(bars).histogram);
  if (hist != null) {
    out.push({ label: "MACD histogram", value: hist.toFixed(2),
      vote: hist > 0 ? 1 : hist < 0 ? -1 : 0 });
  }

  const rate12 = latest(roc(bars, 12));
  if (rate12 != null) {
    out.push({ label: "Rate of change (12)", value: `${rate12.toFixed(2)}%`,
      vote: rate12 > 0 ? 1 : rate12 < 0 ? -1 : 0 });
  }

  // ADX contributes strength, never direction: a strong trend is only a
  // buy if the directional components agree it is an uptrend.
  const dmi = adx(bars, 14);
  const strength = latest(dmi.adx);
  const plus = latest(dmi.plusDI);
  const minus = latest(dmi.minusDI);
  if (strength != null && plus != null && minus != null) {
    out.push({
      label: "ADX (14)",
      value: strength.toFixed(1),
      vote: strength < 25 ? 0 : plus > minus ? 1 : -1,
    });
  }

  return out;
}

function movingAverageReadings(bars: Bar[]): Reading[] {
  const close = bars.length ? bars[bars.length - 1].close : null;
  if (close == null) return [];
  const out: Reading[] = [];
  const add = (label: string, value: number | null) => {
    if (value == null) return;
    out.push({ label, value: value.toFixed(2),
      vote: close > value ? 1 : close < value ? -1 : 0 });
  };
  for (const period of [10, 20, 50, 100, 200]) {
    add(`SMA ${period}`, latest(sma(bars, period)));
    add(`EMA ${period}`, latest(ema(bars, period)));
  }
  add("WMA 20", latest(wma(bars, 20)));
  return out;
}

export function useTechnicalSummary(bars: Bar[]) {
  return useMemo(() => {
    const oscillators = oscillatorReadings(bars);
    const movingAverages = movingAverageReadings(bars);
    const all = [...oscillators, ...movingAverages];
    return {
      oscillators,
      movingAverages,
      oscillatorRating: rate(oscillators.map((r) => r.vote)),
      movingAverageRating: rate(movingAverages.map((r) => r.vote)),
      summaryRating: rate(all.map((r) => r.vote)),
      // Enough history for the slowest contributor is what separates
      // "neutral" from "not enough data to say".
      ready: all.length > 0,
    };
  }, [bars]);
}

function Gauge({ label, rating }: { label: string; rating: Rating }) {
  return (
    <div className={`jg-tech-gauge ${rating.toLowerCase()}`}>
      <span className="jg-tech-gauge-label">{label}</span>
      <strong className="jg-tech-gauge-value">{RATING_LABEL[rating]}</strong>
    </div>
  );
}

export function TechnicalSummary({
  bars,
  timeframe,
}: {
  bars: Bar[];
  timeframe: string;
}) {
  const summary = useTechnicalSummary(bars);

  if (!summary.ready) {
    return (
      <div className="jg-tech">
        <p className="jg-cc-note">
          Not enough {timeframe} history loaded to rate the indicators yet.
        </p>
      </div>
    );
  }

  return (
    <div className="jg-tech">
      <div className="jg-tech-gauges">
        <Gauge label="Oscillators" rating={summary.oscillatorRating} />
        <Gauge label="Summary" rating={summary.summaryRating} />
        <Gauge label="Moving averages" rating={summary.movingAverageRating} />
      </div>

      <Readings title="Oscillators" rows={summary.oscillators} />
      <Readings title="Moving averages" rows={summary.movingAverages} />

      <p className="jg-tech-note">
        Each indicator casts one vote from its current reading on {timeframe}.
        This describes what the indicators say now — it is not a forecast and
        not advice.
      </p>
    </div>
  );
}

function Readings({ title, rows }: { title: string; rows: Reading[] }) {
  if (rows.length === 0) return null;
  return (
    <section className="jg-tech-section">
      <h4 className="jg-tech-heading">{title}</h4>
      <table className="jg-tech-table">
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td>{row.label}</td>
              <td className="jg-tech-value">{row.value}</td>
              <td className={`jg-tech-vote v${row.vote}`}>
                {row.vote === 1 ? "Buy" : row.vote === -1 ? "Sell" : "Neutral"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
