import type { Analysis, Bar } from "../lib/types";

/**
 * Data Window (section 49 of the reference spec).
 *
 * Reads the bar under the crosshair, or the most recent bar when the
 * pointer is off the chart — a panel that emptied every time the mouse
 * left would be unusable.
 *
 * Everything shown is measured from the bar or computed from the loaded
 * series. Where a value genuinely is not available — exchange volume on a
 * feed that only reports tick counts — it says so rather than printing a
 * number that means something else.
 */
export function DataWindow({
  bars, hoverIndex, timeframe, symbol, readouts, analysis,
}: {
  bars: Bar[];
  hoverIndex: number | null;
  timeframe: string;
  symbol: string;
  /**
   * Indicator values AT the hovered candle, computed by the indicator
   * hook. Reading them at the hovered bar is the whole point of the
   * panel: a value taken from the end of the series while the pointer is
   * two hundred candles back answers a question nobody asked.
   */
  readouts: { id: string; label: string; value: string; note: string }[];
  analysis: Analysis | null;
}) {
  if (bars.length === 0) {
    return (
      <p className="jg-cc-note">
        No {timeframe} candles loaded, so there is nothing to read.
      </p>
    );
  }

  const index = hoverIndex != null && hoverIndex < bars.length
    ? hoverIndex : bars.length - 1;
  const bar = bars[index];
  const previous = index > 0 ? bars[index - 1] : null;

  const change = previous ? bar.close - previous.close : null;
  const changePct = previous && previous.close !== 0
    ? (change! / previous.close) * 100 : null;
  const range = bar.high - bar.low;
  const body = Math.abs(bar.close - bar.open);
  const upperWick = bar.high - Math.max(bar.open, bar.close);
  const lowerWick = Math.min(bar.open, bar.close) - bar.low;

  const rows: [string, string, string?][] = [
    ["Time", new Date(bar.time).toLocaleString([], { hour12: false }), ""],
    ["Open", bar.open.toFixed(2)],
    ["High", bar.high.toFixed(2)],
    ["Low", bar.low.toFixed(2)],
    ["Close", bar.close.toFixed(2)],
    ["Change", change == null ? "—"
      : `${change >= 0 ? "+" : ""}${change.toFixed(2)}`,
      change == null ? "" : change >= 0 ? "up" : "down"],
    ["Change %", changePct == null ? "—"
      : `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`,
      changePct == null ? "" : changePct >= 0 ? "up" : "down"],
    ["Range", range.toFixed(2)],
    ["Body", body.toFixed(2)],
    ["Upper wick", upperWick.toFixed(2)],
    ["Lower wick", lowerWick.toFixed(2)],
    // MT5 reports tick volume — a count of price changes, not contracts —
    // so it is labelled as such and never as turnover.
    ["Tick volume", bar.tick_volume != null
      ? Math.round(bar.tick_volume).toLocaleString() : "—"],
  ];

  return (
    <div className="jg-data">
      <p className="jg-data-scope">
        {symbol} · {timeframe} ·{" "}
        {hoverIndex == null ? "latest candle" : `candle ${index + 1} of ${bars.length}`}
      </p>

      {/* Two columns: twelve stacked rows pushed the indicator and AI
          sections below the fold of a side panel, so the panel had all
          the facts and showed a third of them at a time. */}
      <dl className="jg-data-grid">
        {rows.map(([label, value, tone]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd className={tone ? `jg-data-value ${tone}` : "jg-data-value"}>
              {value}
            </dd>
          </div>
        ))}
      </dl>

      <p className="jg-data-note">
        Exchange volume is not available on this feed — the figure above
        counts price changes in the candle, which is what MT5 reports.
      </p>

      {readouts.length > 0 && (
        <>
          <h4 className="jg-symbol-group">Indicators</h4>
          <table className="jg-data-table">
            <tbody>
              {readouts.map((readout) => (
                <tr key={readout.id}>
                  <td>
                    {readout.label}
                    <span className="jg-data-sub">{readout.note}</span>
                  </td>
                  <td className="jg-data-value">{readout.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="jg-data-note">
            Read at the candle above. An indicator still warming up at that
            point shows an em dash rather than a later value carried back.
          </p>
        </>
      )}

      <h4 className="jg-symbol-group">AI context</h4>
      {analysis ? (
        <table className="jg-data-table">
          <tbody>
            <tr><td>Signal</td>
                <td className="jg-data-value">
                  {analysis.setup?.action ?? "—"}
                </td></tr>
            <tr><td>Bias</td>
                <td className="jg-data-value">{analysis.bias}</td></tr>
            <tr><td>Confidence</td>
                <td className="jg-data-value">
                  {analysis.setup?.confidence != null
                    ? `${analysis.setup.confidence}%` : "—"}
                </td></tr>
            <tr><td>Support levels</td>
                <td className="jg-data-value">
                  {analysis.levels?.support?.length ?? 0}
                </td></tr>
            <tr><td>Resistance levels</td>
                <td className="jg-data-value">
                  {analysis.levels?.resistance?.length ?? 0}
                </td></tr>
          </tbody>
        </table>
      ) : (
        <p className="jg-cc-note">
          No analysis run yet. Use Run analysis in the AI panel — nothing is
          shown here until the engine has actually looked.
        </p>
      )}
    </div>
  );
}
