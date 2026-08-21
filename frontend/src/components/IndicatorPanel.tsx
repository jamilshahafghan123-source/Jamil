import { useMemo, useState } from "react";
import {
  DEFAULT_PERIOD,
  INDICATOR_GROUP,
  INDICATOR_LABEL,
  accumulationDistribution,
  adx,
  atr,
  cmf,
  bollinger,
  cci,
  donchian,
  ema,
  hma,
  ichimoku,
  keltner,
  maRibbon,
  mfi,
  obv,
  parabolicSAR,
  roc,
  isOverlay,
  latest,
  macd,
  rsi,
  rsiSeries,
  sma,
  standardDeviation,
  stochastic,
  stochasticRSI,
  supertrend,
  tickVolume,
  tickVolumeAverage,
  vwap,
  vwma,
  williamsR,
  wma,
  type Series,
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
  SMA: "#6aa9ff", EMA: "#d9a441", WMA: "#79c0ff", HMA: "#f0a35e",
  VWMA: "#4ec9b0", BOLLINGER: "#b071e0", VWAP: "#4ec9b0",
  DONCHIAN: "#8ab4f8", KELTNER: "#c2708f", SUPERTREND: "#3fb950",
  RSI: "#f0a35e", MACD: "#8ab4f8", STOCHASTIC: "#b071e0", CCI: "#79c0ff",
  ROC: "#4ec9b0", WILLIAMS_R: "#c2708f", ADX: "#d9a441",
  ATR: "#9aa3b0", STDDEV: "#8b93a1",
  VOLUME: "#646d7c", OBV: "#5aa9a3", MFI: "#f4a15a",
  PSAR: "#e0a3d0", ICHIMOKU: "#7fb3d5", MA_RIBBON: "#6aa9ff",
  STOCH_RSI: "#b071e0", CMF: "#5aa9a3", AD_LINE: "#8ab4f8",
};

/** Everything the engine can compute, in library order. */
const AVAILABLE: IndicatorKind[] = [
  "SMA", "EMA", "WMA", "HMA", "VWMA", "BOLLINGER", "DONCHIAN", "KELTNER",
  "SUPERTREND", "PSAR", "ICHIMOKU", "MA_RIBBON",
  "RSI", "MACD", "STOCHASTIC", "STOCH_RSI", "CCI", "ROC", "WILLIAMS_R", "ADX",
  "ATR", "STDDEV",
  "VOLUME", "OBV", "MFI", "CMF", "AD_LINE", "VWAP",
];

/**
 * Indicator templates (section 23).
 *
 * A preset REPLACES the current set rather than adding to it, so picking
 * one gives the chart the preset describes instead of the preset plus
 * whatever happened to be there already.
 */
export const TEMPLATES: { id: string; name: string; kinds: IndicatorKind[] }[] = [
  { id: "scalping", name: "Scalping", kinds: ["EMA", "SMA", "RSI", "ATR"] },
  { id: "trend", name: "Trend", kinds: ["EMA", "SMA", "MACD", "ADX"] },
  { id: "volatility", name: "Volatility", kinds: ["BOLLINGER", "KELTNER", "ATR", "STDDEV"] },
  { id: "volume", name: "Volume", kinds: ["VWAP", "VOLUME", "OBV", "MFI"] },
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
      } else if (config.kind === "WMA") {
        out.push({ id: config.id, label: `WMA ${config.period}`,
                   colour: config.colour, values: wma(bars, config.period) });
      } else if (config.kind === "HMA") {
        out.push({ id: config.id, label: `HMA ${config.period}`,
                   colour: config.colour, values: hma(bars, config.period) });
      } else if (config.kind === "VWMA") {
        out.push({ id: config.id, label: `VWMA ${config.period}`,
                   colour: config.colour, values: vwma(bars, config.period) });
      } else if (config.kind === "DONCHIAN") {
        const channel = donchian(bars, config.period);
        out.push({ id: `${config.id}-u`, label: "Donchian upper",
                   colour: config.colour, values: channel.upper });
        out.push({ id: `${config.id}-l`, label: "Donchian lower",
                   colour: config.colour, values: channel.lower });
      } else if (config.kind === "KELTNER") {
        const channel = keltner(bars, config.period);
        out.push({ id: `${config.id}-u`, label: "Keltner upper",
                   colour: config.colour, values: channel.upper, dashed: true });
        out.push({ id: `${config.id}-l`, label: "Keltner lower",
                   colour: config.colour, values: channel.lower, dashed: true });
      } else if (config.kind === "SUPERTREND") {
        out.push({ id: config.id, label: `Supertrend ${config.period}`,
                   colour: config.colour,
                   values: supertrend(bars, config.period).line });
      } else if (config.kind === "PSAR") {
        out.push({ id: config.id, label: "Parabolic SAR",
                   colour: config.colour, values: parabolicSAR(bars).sar });
      } else if (config.kind === "MA_RIBBON") {
        // One series per band, so the fan opens and closes visibly.
        for (const band of maRibbon(bars)) {
          out.push({ id: `${config.id}-${band.period}`,
                     label: `EMA ${band.period}`, colour: config.colour,
                     values: band.values });
        }
      } else if (config.kind === "ICHIMOKU") {
        const cloud = ichimoku(bars, 9, config.period);
        out.push({ id: `${config.id}-conv`, label: "Tenkan",
                   colour: config.colour, values: cloud.conversion });
        out.push({ id: `${config.id}-base`, label: "Kijun",
                   colour: config.colour, values: cloud.base, dashed: true });
        out.push({ id: `${config.id}-a`, label: "Senkou A",
                   colour: config.colour, values: cloud.spanA, dashed: true });
        out.push({ id: `${config.id}-b`, label: "Senkou B",
                   colour: config.colour, values: cloud.spanB, dashed: true });
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
      } else if (config.kind === "STOCHASTIC") {
        const result = stochastic(bars, config.period);
        const k = latest(result.k);
        out.push({
          id: config.id, label: `Stochastic ${config.period}`,
          value: k != null ? k.toFixed(1) : "—",
          note: k == null ? "warming up"
            : k >= 80 ? "overbought" : k <= 20 ? "oversold" : "neutral",
        });
      } else if (config.kind === "CCI") {
        const value = latest(cci(bars, config.period));
        out.push({
          id: config.id, label: `CCI ${config.period}`,
          value: value != null ? value.toFixed(1) : "—",
          note: value == null ? "warming up"
            : value >= 100 ? "above +100" : value <= -100 ? "below -100" : "in range",
        });
      } else if (config.kind === "ROC") {
        const value = latest(roc(bars, config.period));
        out.push({
          id: config.id, label: `ROC ${config.period}`,
          value: value != null ? `${value.toFixed(2)}%` : "—",
          note: value == null ? "warming up" : value > 0 ? "rising" : "falling",
        });
      } else if (config.kind === "WILLIAMS_R") {
        const value = latest(williamsR(bars, config.period));
        out.push({
          id: config.id, label: `Williams %R ${config.period}`,
          value: value != null ? value.toFixed(1) : "—",
          note: value == null ? "warming up"
            : value >= -20 ? "overbought" : value <= -80 ? "oversold" : "neutral",
        });
      } else if (config.kind === "ADX") {
        const result = adx(bars, config.period);
        const strength = latest(result.adx);
        const plus = latest(result.plusDI);
        const minus = latest(result.minusDI);
        // ADX measures strength only; +DI/-DI carry the direction, so the
        // note reports both rather than letting a number imply a side.
        out.push({
          id: config.id, label: `ADX ${config.period}`,
          value: strength != null ? strength.toFixed(1) : "—",
          note: strength == null ? "warming up"
            : `${strength >= 25 ? "trending" : "ranging"}` +
              (plus != null && minus != null
                ? ` · ${plus > minus ? "+DI" : "-DI"} leads` : ""),
        });
      } else if (config.kind === "STDDEV") {
        const value = latest(standardDeviation(bars, config.period));
        out.push({
          id: config.id, label: `Std dev ${config.period}`,
          value: value != null ? value.toFixed(2) : "—",
          note: "close dispersion",
        });
      } else if (config.kind === "OBV") {
        const value = latest(obv(bars));
        out.push({
          id: config.id, label: "On-balance volume",
          value: value != null ? Math.round(value).toLocaleString() : "—",
          note: "cumulative tick volume",
        });
      } else if (config.kind === "MFI") {
        const value = latest(mfi(bars, config.period));
        out.push({
          id: config.id, label: `MFI ${config.period}`,
          value: value != null ? value.toFixed(1) : "—",
          note: value == null ? "warming up"
            : value >= 80 ? "overbought" : value <= 20 ? "oversold" : "neutral",
        });
      } else if (config.kind === "STOCH_RSI") {
        const value = latest(stochasticRSI(bars, config.period).k);
        out.push({
          id: config.id, label: `Stoch RSI ${config.period}`,
          value: value != null ? value.toFixed(1) : "—",
          note: value == null ? "warming up"
            : value >= 80 ? "overbought" : value <= 20 ? "oversold" : "neutral",
        });
      } else if (config.kind === "CMF") {
        const value = latest(cmf(bars, config.period));
        out.push({
          id: config.id, label: `CMF ${config.period}`,
          value: value != null ? value.toFixed(3) : "—",
          note: value == null ? "warming up"
            : value > 0 ? "accumulation" : value < 0 ? "distribution" : "flat",
        });
      } else if (config.kind === "AD_LINE") {
        const value = latest(accumulationDistribution(bars));
        out.push({
          id: config.id, label: "Accum / Dist",
          value: value != null ? Math.round(value).toLocaleString() : "—",
          note: "cumulative flow",
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

  /**
   * Lower panes (section 28).
   *
   * Only the indicators whose scale genuinely does not belong on the
   * price axis get one — an RSI on a gold price scale is a flat line at
   * the bottom of the chart, which is why it needs its own.
   */
  const panes = useMemo(() => {
    const out: {
      id: string; kind: IndicatorKind; title: string;
      series: { id: string; label: string; colour: string;
                values: Series; histogram?: boolean; dashed?: boolean }[];
      guides: { value: number; colour?: string }[];
    }[] = [];

    for (const config of configs) {
      if (!config.enabled) continue;
      const c = config.colour;
      if (config.kind === "RSI") {
        out.push({
          id: config.id, kind: config.kind, title: `RSI ${config.period}`,
          series: [{ id: config.id, label: `RSI ${config.period}`, colour: c,
                     values: rsiSeries(bars, config.period) }],
          guides: [{ value: 70 }, { value: 30 }, { value: 50 }],
        });
      } else if (config.kind === "MACD") {
        const result = macd(bars);
        out.push({
          id: config.id, kind: config.kind, title: "MACD",
          series: [
            { id: `${config.id}-h`, label: "histogram", colour: c,
              values: result.histogram, histogram: true },
            { id: `${config.id}-m`, label: "MACD", colour: "#6aa9ff",
              values: result.macd },
            { id: `${config.id}-s`, label: "signal", colour: "#d9a441",
              values: result.signal, dashed: true },
          ],
          guides: [{ value: 0 }],
        });
      } else if (config.kind === "STOCHASTIC") {
        const result = stochastic(bars, config.period);
        out.push({
          id: config.id, kind: config.kind, title: `Stochastic ${config.period}`,
          series: [
            { id: `${config.id}-k`, label: "%K", colour: c, values: result.k },
            { id: `${config.id}-d`, label: "%D", colour: "#d9a441",
              values: result.d, dashed: true },
          ],
          guides: [{ value: 80 }, { value: 20 }],
        });
      } else if (config.kind === "STOCH_RSI") {
        const result = stochasticRSI(bars, config.period);
        out.push({
          id: config.id, kind: config.kind, title: `Stoch RSI ${config.period}`,
          series: [
            { id: `${config.id}-k`, label: "%K", colour: c, values: result.k },
            { id: `${config.id}-d`, label: "%D", colour: "#d9a441",
              values: result.d, dashed: true },
          ],
          guides: [{ value: 80 }, { value: 20 }],
        });
      } else if (config.kind === "ADX") {
        const result = adx(bars, config.period);
        out.push({
          id: config.id, kind: config.kind, title: `ADX ${config.period}`,
          series: [
            { id: `${config.id}-a`, label: "ADX", colour: c, values: result.adx },
            { id: `${config.id}-p`, label: "+DI", colour: "#3fb950",
              values: result.plusDI },
            { id: `${config.id}-m`, label: "-DI", colour: "#f4564a",
              values: result.minusDI },
          ],
          guides: [{ value: 25 }],
        });
      } else if (config.kind === "VOLUME") {
        out.push({
          id: config.id, kind: config.kind, title: "Tick volume",
          series: [
            { id: `${config.id}-v`, label: "tick volume", colour: c,
              values: tickVolume(bars), histogram: true },
            { id: `${config.id}-a`, label: `average ${config.period}`,
              colour: "#d9a441",
              values: tickVolumeAverage(bars, config.period) },
          ],
          guides: [],
        });
      }
    }
    return out;
  }, [configs, bars]);

  return { configs, setConfigs, overlays, readouts, panes };
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
  const [query, setQuery] = useState("");

  /** Library grouped by family, filtered by the search box (section 17). */
  const visibleGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const grouped = new Map<string, IndicatorKind[]>();
    for (const kind of AVAILABLE) {
      const label = INDICATOR_LABEL[kind];
      if (q && !`${kind} ${label}`.toLowerCase().includes(q)) continue;
      const group = INDICATOR_GROUP[kind];
      grouped.set(group, [...(grouped.get(group) ?? []), kind]);
    }
    return [...grouped.entries()];
  }, [query]);

  function applyTemplate(kinds: IndicatorKind[]) {
    setConfigs(
      kinds.map((kind) => ({
        id: `${kind.toLowerCase()}-${nextId++}`,
        kind,
        period: DEFAULT_PERIOD[kind],
        enabled: true,
        colour: PALETTE[kind],
      })),
    );
  }

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
          {/* Templates replace the set, so a preset gives exactly what it
              names rather than the preset plus whatever was already on. */}
          <div className="jg-ind-templates">
            <span className="jg-ind-heading">Templates</span>
            {TEMPLATES.map((template) => (
              <button
                key={template.id}
                type="button"
                className="jg-chip"
                title={template.kinds.join(", ")}
                onClick={() => applyTemplate(template.kinds)}
              >
                {template.name}
              </button>
            ))}
          </div>

          <input
            className="jg-ind-search"
            placeholder="Search indicators"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search indicators"
          />

          <div className="jg-ind-add">
            {visibleGroups.length === 0 && (
              <p className="jg-cc-note">No indicator matches “{query}”.</p>
            )}
            {visibleGroups.map(([group, kinds]) => (
              <div key={group} className="jg-ind-group">
                <span className="jg-ind-heading">{group}</span>
                {kinds.map((kind) => (
                  <button key={kind} type="button" className="jg-chip"
                          title={kind}
                          onClick={() => add(kind)}>
                    + {INDICATOR_LABEL[kind]}
                  </button>
                ))}
              </div>
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
