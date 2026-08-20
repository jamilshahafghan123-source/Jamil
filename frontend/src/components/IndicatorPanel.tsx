import { useMemo, useState } from "react";
import {
  DEFAULT_PERIOD,
  atr,
  bollinger,
  ema,
  isOverlay,
  latest,
  macd,
  rsi,
  sma,
  tickVolume,
  tickVolumeAverage,
  vwap,
  type IndicatorConfig,
  type IndicatorKind,
} from "../lib/indicators";
import type { OverlaySeries } from "./TradingChart";
import type { Bar } from "../lib/types";

/**
 * Indicator controls and readouts.
 *
 * OVERLAYS vs READOUTS. Moving averages, Bollinger bands and VWAP share the
 * price axis, so they draw on the chart. RSI, MACD and ATR do not — their
 * ranges have nothing to do with price, and forcing them onto the same axis
 * either flattens the candles or hides the indicator. lightweight-charts 4
 * has no separate pane, so rather than fake one they are shown as live
 * readouts with their interpretation. That is a real limitation, stated
 * rather than papered over.
 *
 * Every calculation is memoised on `bars` and the configuration, so a poll
 * returning an unchanged array recomputes nothing.
 */

const PALETTE: Record<IndicatorKind, string> = {
  SMA: "#6aa9ff",
  EMA: "#d9a441",
  BOLLINGER: "#b071e0",
  VWAP: "#4ec9b0",
  RSI: "#f0a35e",
  MACD: "#8ab4f8",
  ATR: "#9aa3b0",
  VOLUME: "#646d7c",
};

const AVAILABLE: IndicatorKind[] = [
  "SMA", "EMA", "BOLLINGER", "VWAP", "RSI", "MACD", "ATR", "VOLUME",
];

let nextId = 1;

export function useIndicators(bars: Bar[]) {
  const [configs, setConfigs] = useState<IndicatorConfig[]>([
    { id: "ema-50", kind: "EMA", period: 50, enabled: true, colour: PALETTE.EMA },
  ]);

  const overlays: OverlaySeries[] = useMemo(() => {
    const out: OverlaySeries[] = [];
    for (const config of configs) {
      if (!config.enabled || !isOverlay(config.kind)) continue;
      if (config.kind === "SMA") {
        out.push({ id: config.id, label: `SMA ${config.period}`,
                   colour: config.colour, values: sma(bars, config.period) });
      } else if (config.kind === "EMA") {
        out.push({ id: config.id, label: `EMA ${config.period}`,
                   colour: config.colour, values: ema(bars, config.period) });
      } else if (config.kind === "VWAP") {
        out.push({ id: config.id, label: "VWAP (window)",
                   colour: config.colour, values: vwap(bars) });
      } else if (config.kind === "BOLLINGER") {
        const bands = bollinger(bars, config.period);
        out.push({ id: `${config.id}-u`, label: "BB upper", colour: config.colour,
                   values: bands.upper, dashed: true });
        out.push({ id: `${config.id}-m`, label: "BB mid", colour: config.colour,
                   values: bands.middle });
        out.push({ id: `${config.id}-l`, label: "BB lower", colour: config.colour,
                   values: bands.lower, dashed: true });
      }
    }
    return out;
  }, [configs, bars]);

  const readouts = useMemo(() => {
    const out: { id: string; label: string; value: string; note: string }[] = [];
    for (const config of configs) {
      if (!config.enabled || isOverlay(config.kind)) continue;
      if (config.kind === "RSI") {
        const value = latest(rsi(bars, config.period));
        out.push({
          id: config.id,
          label: `RSI ${config.period}`,
          value: value != null ? value.toFixed(1) : "—",
          note:
            value == null ? "warming up"
              : value >= 70 ? "overbought"
              : value <= 30 ? "oversold"
              : "neutral",
        });
      } else if (config.kind === "MACD") {
        const result = macd(bars);
        const hist = latest(result.histogram);
        out.push({
          id: config.id,
          label: "MACD hist",
          value: hist != null ? hist.toFixed(2) : "—",
          note: hist == null ? "warming up" : hist > 0 ? "above signal" : "below signal",
        });
      } else if (config.kind === "VOLUME") {
        const value = latest(tickVolume(bars));
        const average = latest(tickVolumeAverage(bars, config.period));
        // The ratio is the readable part; a bare tick count says little.
        const ratio = value != null && average ? value / average : null;
        out.push({
          id: config.id,
          label: `Tick volume (${config.period})`,
          value: value != null ? Math.round(value).toLocaleString() : "—",
          note:
            ratio == null ? "warming up"
              : ratio >= 1.5 ? `${ratio.toFixed(1)}x average — active`
              : ratio <= 0.5 ? `${ratio.toFixed(1)}x average — quiet`
              : `${ratio.toFixed(1)}x average`,
        });
      } else if (config.kind === "ATR") {
        const value = latest(atr(bars, config.period));
        out.push({
          id: config.id,
          label: `ATR ${config.period}`,
          value: value != null ? value.toFixed(2) : "—",
          note: "average true range",
        });
      }
    }
    return out;
  }, [configs, bars]);

  return { configs, setConfigs, overlays, readouts };
}

export function IndicatorPanel({
  configs,
  setConfigs,
  readouts,
}: {
  configs: IndicatorConfig[];
  setConfigs: React.Dispatch<React.SetStateAction<IndicatorConfig[]>>;
  readouts: { id: string; label: string; value: string; note: string }[];
}) {
  const [open, setOpen] = useState(false);

  function add(kind: IndicatorKind) {
    setConfigs((current) => [
      ...current,
      {
        id: `${kind.toLowerCase()}-${nextId++}`,
        kind,
        period: DEFAULT_PERIOD[kind],
        enabled: true,
        colour: PALETTE[kind],
      },
    ]);
  }

  return (
    <div className="jg-ind">
      <button
        type="button"
        className={open ? "btn sm active" : "btn sm"}
        onClick={() => setOpen((v) => !v)}
      >
        Indicators ({configs.filter((c) => c.enabled).length})
      </button>

      {open && (
        <div className="jg-ind-panel">
          <div className="jg-ind-add">
            {AVAILABLE.map((kind) => (
              <button key={kind} type="button" className="jg-chip"
                      onClick={() => add(kind)}>
                + {kind}
              </button>
            ))}
          </div>

          <ul className="jg-ind-list">
            {configs.length === 0 && (
              <li className="jg-cc-note">No indicators added.</li>
            )}
            {configs.map((config) => (
              <li key={config.id}>
                <span className="jg-ind-dot" style={{ background: config.colour }} />
                <span className="jg-ind-name">{config.kind}</span>
                {DEFAULT_PERIOD[config.kind] > 0 && (
                  <input
                    type="number"
                    min={2}
                    max={400}
                    value={config.period}
                    aria-label={`${config.kind} period`}
                    onChange={(e) =>
                      setConfigs((current) =>
                        current.map((c) =>
                          c.id === config.id
                            ? {
                                ...c,
                                // Clamp here: a period of 0 or 5000 is a
                                // typo, and either would produce a blank
                                // series that looks like a bug.
                                period: Math.min(
                                  400,
                                  Math.max(2, Number(e.target.value) || 2),
                                ),
                              }
                            : c,
                        ),
                      )
                    }
                  />
                )}
                <button
                  type="button"
                  className="jg-ind-toggle"
                  onClick={() =>
                    setConfigs((current) =>
                      current.map((c) =>
                        c.id === config.id ? { ...c, enabled: !c.enabled } : c,
                      ),
                    )
                  }
                >
                  {config.enabled ? "hide" : "show"}
                </button>
                <button
                  type="button"
                  className="jg-ind-remove"
                  aria-label={`Remove ${config.kind}`}
                  onClick={() =>
                    setConfigs((current) =>
                      current.filter((c) => c.id !== config.id),
                    )
                  }
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
          <p className="jg-cc-note">
            RSI, MACD and ATR read out below the chart rather than drawing on
            it — their ranges are not price, and the chart library has no
            separate pane.
          </p>
        </div>
      )}

      {readouts.length > 0 && (
        <div className="jg-ind-readouts">
          {readouts.map((r) => (
            <div key={r.id} className="jg-ind-readout">
              <span className="jg-ind-readout-label">{r.label}</span>
              <span className="jg-ind-readout-value">{r.value}</span>
              <span className="jg-ind-readout-note">{r.note}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
