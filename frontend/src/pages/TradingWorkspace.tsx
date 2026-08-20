import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { Brand } from "../components/Brand";
import { SupportChat } from "../components/SupportChat";
import { TradingChart, type TradeMarker } from "../components/TradingChart";
import type {
  Bar,
  DemoAccountResponse,
  DemoTrade,
  InstrumentInfo,
  Timeframe,
} from "../lib/types";

/**
 * J Gold AI customer trading workspace.
 *
 * ACCOUNT MODE. This page trades the J Gold AI internal demo account —
 * virtual money that never reaches MT5. That is not a label on a screen:
 * every order here calls /api/demo/*, and the demo engine behind it imports
 * no broker client at all. The MT5 demo account is a different thing, and
 * the copy says "J Gold AI Demo" everywhere rather than just "demo" so the
 * two cannot be confused.
 *
 * The chart is the page. Controls are compact, the panels are secondary,
 * and none of the homepage's decorative treatment comes in here.
 */

const TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

/** Bars per timeframe. Enough for context without over-fetching. */
const BAR_COUNT = 300;

function money(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined) return "—";
  const sign = value < 0 ? "-" : "";
  return `${sign}${currency} ${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "";
  return value > 0 ? "up" : "down";
}

export function TradingWorkspace({ onLogout }: { onLogout: () => void }) {
  const [symbol, setSymbol] = useState("XAUUSD");
  const [timeframe, setTimeframe] = useState<Timeframe>("M15");
  const [bars, setBars] = useState<Bar[]>([]);
  const [barsError, setBarsError] = useState<string | null>(null);
  const [loadingBars, setLoadingBars] = useState(true);

  const [instruments, setInstruments] = useState<
    Record<string, InstrumentInfo[]>
  >({});
  const [account, setAccount] = useState<DemoAccountResponse | null>(null);
  const [trades, setTrades] = useState<DemoTrade[]>([]);
  const [tab, setTab] = useState<"positions" | "history">("positions");

  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [volume, setVolume] = useState("0.10");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [ticketError, setTicketError] = useState<string | null>(null);
  const [pendingOrder, setPendingOrder] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // One in-flight bars request at a time; a timeframe click mid-flight must
  // not let a stale response land after the new one.
  const barsRequest = useRef<AbortController | null>(null);

  const loadBars = useCallback(async () => {
    barsRequest.current?.abort();
    const controller = new AbortController();
    barsRequest.current = controller;
    setLoadingBars(true);
    try {
      const res = await api.bars(timeframe, BAR_COUNT, symbol, controller.signal);
      setBars(res.bars);
      setBarsError(null);
    } catch (err) {
      if (controller.signal.aborted) return;
      // A safe explanation beats "Failed to fetch".
      setBarsError(
        err instanceof Error && err.message
          ? err.message
          : "Market data is unavailable right now.",
      );
    } finally {
      if (!controller.signal.aborted) setLoadingBars(false);
    }
  }, [symbol, timeframe]);

  const loadAccount = useCallback(async () => {
    try {
      setAccount(await api.demoAccount());
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Demo account unavailable");
    }
  }, []);

  const loadTrades = useCallback(async () => {
    try {
      setTrades(await api.demoTrades());
    } catch {
      /* history simply stays as it was */
    }
  }, []);

  useEffect(() => {
    void loadBars();
  }, [loadBars]);

  useEffect(() => {
    void loadAccount();
    void loadTrades();
    void api.demoInstruments().then((r) => setInstruments(r.by_asset_class));
  }, [loadAccount, loadTrades]);

  // One poll for account state. Bars refresh on the same beat rather than
  // running a second timer against the same backend.
  useEffect(() => {
    const t = window.setInterval(() => {
      void loadAccount();
      void loadBars();
    }, 15_000);
    return () => window.clearInterval(t);
  }, [loadAccount, loadBars]);

  const price = account?.market_price ?? null;
  const spread = price ? price.ask - price.bid : null;

  const parsedVolume = Number.parseFloat(volume);
  const parsedSl = stopLoss.trim() ? Number.parseFloat(stopLoss) : null;
  const parsedTp = takeProfit.trim() ? Number.parseFloat(takeProfit) : null;

  const instrument = useMemo(() => {
    for (const group of Object.values(instruments)) {
      const found = group.find((i) => i.symbol === symbol);
      if (found) return found;
    }
    return null;
  }, [instruments, symbol]);

  /** Risk and RR from the instrument's own tick maths, not a gold constant. */
  const estimate = useMemo(() => {
    if (!price || !instrument || !Number.isFinite(parsedVolume)) return null;
    const entry = side === "BUY" ? price.ask : price.bid;
    const perUnit = (instrument.tick_value / instrument.tick_size) * parsedVolume;
    const risk =
      parsedSl != null ? Math.abs(entry - parsedSl) * perUnit : null;
    const reward =
      parsedTp != null ? Math.abs(parsedTp - entry) * perUnit : null;
    const rr = risk && reward && risk > 0 ? reward / risk : null;
    return { entry, risk, reward, rr };
  }, [price, instrument, parsedVolume, parsedSl, parsedTp, side]);

  const markers: TradeMarker[] = useMemo(() => {
    const open = (account?.positions ?? []).map((p) => ({
      time: p.opened_at ?? new Date().toISOString(),
      side: p.side,
      source: p.source,
      text: `${p.source === "MANUAL" ? "" : "AI "}${p.side} ${p.volume}`,
    }));
    const closed = trades.slice(0, 30).map((t) => ({
      time: t.closed_at ?? new Date().toISOString(),
      side: t.side,
      source: t.source,
      exit: true,
      text: `exit ${t.realized_pnl >= 0 ? "+" : ""}${t.realized_pnl}`,
    }));
    return [...open, ...closed];
  }, [account, trades]);

  async function submitOrder() {
    setPendingOrder(true);
    setTicketError(null);
    try {
      await api.demoOpen({
        symbol,
        side,
        volume: parsedVolume,
        stop_loss: parsedSl,
        take_profit: parsedTp,
        source: "MANUAL",
      });
      setNotice(`${side} ${parsedVolume} ${symbol} opened on virtual money.`);
      await loadAccount();
    } catch (err) {
      setTicketError(err instanceof Error ? err.message : "Order rejected");
    } finally {
      setPendingOrder(false);
      setConfirming(false);
    }
  }

  async function closePosition(id: number) {
    try {
      const res = await api.demoClose(id);
      setNotice(`Closed. Realised ${money(res.realized_pnl)}.`);
      await loadAccount();
      await loadTrades();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not close position");
    }
  }

  async function resetDemo() {
    try {
      const res = await api.demoReset();
      setNotice(res.detail);
      await loadAccount();
      await loadTrades();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setResetting(false);
    }
  }

  const acct = account?.account ?? null;
  const canOpen = account?.can_open ?? false;

  return (
    <div className="jg-ws">
      {/* ------------------------------------------------------- toolbar */}
      <header className="jg-ws-top">
        <Brand size={22} />
        <span className="jg-ws-mode">J GOLD AI DEMO</span>

        <select
          className="jg-ws-select"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          aria-label="Symbol"
        >
          {Object.entries(instruments).map(([group, list]) => (
            <optgroup key={group} label={group}>
              {list.map((i) => (
                <option key={i.symbol} value={i.symbol} disabled={!i.tradable}>
                  {i.symbol}
                  {i.tradable ? "" : " — coming soon"}
                </option>
              ))}
            </optgroup>
          ))}
        </select>

        <div className="jg-tf">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              className={tf === timeframe ? "jg-tf-btn active" : "jg-tf-btn"}
              onClick={() => setTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </div>

        <div className="jg-spacer" />
        <button type="button" className="btn sm" onClick={() => setResetting(true)}>
          Reset demo
        </button>
        <button type="button" className="btn sm" onClick={onLogout}>
          Sign out
        </button>
      </header>

      {/* ------------------------------------------------------- metrics */}
      <div className="jg-ws-metrics">
        <Metric label="Balance" value={money(acct?.balance, acct?.currency)} />
        <Metric label="Equity" value={money(acct?.equity, acct?.currency)} />
        <Metric label="Free margin" value={money(acct?.free_margin, acct?.currency)} />
        <Metric
          label="Floating P/L"
          value={money(acct?.floating_pnl, acct?.currency)}
          tone={pnlClass(acct?.floating_pnl)}
        />
        <Metric
          label="Realised P/L"
          value={money(acct?.realized_pnl, acct?.currency)}
          tone={pnlClass(acct?.realized_pnl)}
        />
        <Metric
          label="Market"
          value={price ? `${price.bid.toFixed(2)} / ${price.ask.toFixed(2)}` : "—"}
          sub={spread != null ? `spread ${spread.toFixed(2)}` : undefined}
        />
      </div>

      {notice && (
        <p className="jg-ws-notice" role="status">
          {notice}
        </p>
      )}
      {account?.blocked_reason && (
        <p className="jg-ws-blocked">{account.blocked_reason}</p>
      )}

      {/* --------------------------------------------------- chart + ticket */}
      <div className="jg-ws-main">
        <section className="jg-ws-chart">
          {barsError ? (
            <div className="jg-ws-chart-empty">{barsError}</div>
          ) : loadingBars && bars.length === 0 ? (
            <div className="jg-ws-chart-empty">Loading {symbol} {timeframe}…</div>
          ) : bars.length === 0 ? (
            <div className="jg-ws-chart-empty">
              No candles returned for {timeframe}.
            </div>
          ) : (
            <TradingChart bars={bars} markers={markers} height={460} />
          )}
        </section>

        <aside className="jg-ws-ticket">
          <h3>Order ticket</h3>
          <p className="jg-ws-virtual">VIRTUAL MONEY — J Gold AI demo</p>

          <div className="jg-side-toggle">
            <button
              type="button"
              className={side === "BUY" ? "jg-side buy active" : "jg-side buy"}
              onClick={() => setSide("BUY")}
            >
              BUY
            </button>
            <button
              type="button"
              className={side === "SELL" ? "jg-side sell active" : "jg-side sell"}
              onClick={() => setSide("SELL")}
            >
              SELL
            </button>
          </div>

          <label className="jg-ws-field">
            <span>Volume</span>
            <input
              type="number"
              step={instrument?.volume_step ?? 0.01}
              min={instrument?.min_volume ?? 0.01}
              max={instrument?.max_volume ?? 100}
              value={volume}
              onChange={(e) => setVolume(e.target.value)}
            />
          </label>
          <label className="jg-ws-field">
            <span>Stop loss</span>
            <input
              type="number"
              step="0.01"
              value={stopLoss}
              onChange={(e) => setStopLoss(e.target.value)}
              placeholder="optional"
            />
          </label>
          <label className="jg-ws-field">
            <span>Take profit</span>
            <input
              type="number"
              step="0.01"
              value={takeProfit}
              onChange={(e) => setTakeProfit(e.target.value)}
              placeholder="optional"
            />
          </label>

          <dl className="jg-ws-estimate">
            <div>
              <dt>Entry</dt>
              <dd>{estimate ? estimate.entry.toFixed(2) : "—"}</dd>
            </div>
            <div>
              <dt>Risk</dt>
              <dd>{estimate?.risk != null ? money(estimate.risk) : "—"}</dd>
            </div>
            <div>
              <dt>R:R</dt>
              <dd>{estimate?.rr != null ? estimate.rr.toFixed(2) : "—"}</dd>
            </div>
          </dl>

          {ticketError && <p className="jg-ws-error">{ticketError}</p>}

          <button
            type="button"
            className="jg-btn primary"
            style={{ width: "100%" }}
            disabled={!canOpen || pendingOrder || !Number.isFinite(parsedVolume)}
            onClick={() => setConfirming(true)}
          >
            {canOpen ? `Place ${side} order` : "Trading unavailable"}
          </button>
        </aside>
      </div>

      {/* ---------------------------------------------- positions / history */}
      <section className="jg-ws-bottom">
        <div className="jg-ws-tabs">
          <button
            type="button"
            className={tab === "positions" ? "jg-chip active" : "jg-chip"}
            onClick={() => setTab("positions")}
          >
            Open positions ({account?.positions.length ?? 0})
          </button>
          <button
            type="button"
            className={tab === "history" ? "jg-chip active" : "jg-chip"}
            onClick={() => setTab("history")}
          >
            Trade history ({trades.length})
          </button>
        </div>

        <div className="jg-ws-table-wrap">
          {tab === "positions" ? (
            <table className="jg-ws-table">
              <thead>
                <tr>
                  <th>Symbol</th><th>Side</th><th>Source</th><th>Volume</th>
                  <th>Entry</th><th>SL</th><th>TP</th><th>Floating</th><th />
                </tr>
              </thead>
              <tbody>
                {(account?.positions ?? []).length === 0 && (
                  <tr><td colSpan={9} className="jg-ws-empty">No open positions.</td></tr>
                )}
                {(account?.positions ?? []).map((p) => (
                  <tr key={p.id}>
                    <td>{p.symbol}</td>
                    <td className={p.side === "BUY" ? "up" : "down"}>{p.side}</td>
                    <td className="jg-src">{p.source.replace("_", " ")}</td>
                    <td>{p.volume}</td>
                    <td>{p.entry_price.toFixed(2)}</td>
                    <td>{p.stop_loss?.toFixed(2) ?? "—"}</td>
                    <td>{p.take_profit?.toFixed(2) ?? "—"}</td>
                    <td className={pnlClass(p.floating_pnl)}>
                      {money(p.floating_pnl)}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn sm"
                        onClick={() => void closePosition(p.id)}
                      >
                        Close
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="jg-ws-table">
              <thead>
                <tr>
                  <th>Closed</th><th>Symbol</th><th>Side</th><th>Source</th>
                  <th>Volume</th><th>Entry</th><th>Exit</th><th>Realised</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 && (
                  <tr><td colSpan={9} className="jg-ws-empty">No closed trades yet.</td></tr>
                )}
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td>{t.closed_at ? new Date(t.closed_at).toLocaleString() : "—"}</td>
                    <td>{t.symbol}</td>
                    <td className={t.side === "BUY" ? "up" : "down"}>{t.side}</td>
                    <td className="jg-src">{t.source.replace("_", " ")}</td>
                    <td>{t.volume}</td>
                    <td>{t.entry_price.toFixed(2)}</td>
                    <td>{t.exit_price.toFixed(2)}</td>
                    <td className={pnlClass(t.realized_pnl)}>
                      {money(t.realized_pnl)}
                    </td>
                    <td className="jg-src">{t.close_reason.replace(/_/g, " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {/* ------------------------------------------------- confirmations */}
      {confirming && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="jg-confirm">
            <h3>Confirm order</h3>
            <dl className="jg-ws-confirm-list">
              <div><dt>Account</dt><dd>J Gold AI Demo — VIRTUAL MONEY</dd></div>
              <div><dt>Symbol</dt><dd>{symbol}</dd></div>
              <div><dt>Side</dt><dd>{side}</dd></div>
              <div><dt>Volume</dt><dd>{volume}</dd></div>
              <div><dt>Entry</dt><dd>{estimate ? estimate.entry.toFixed(2) : "—"}</dd></div>
              <div><dt>Stop loss</dt><dd>{parsedSl?.toFixed(2) ?? "none"}</dd></div>
              <div><dt>Take profit</dt><dd>{parsedTp?.toFixed(2) ?? "none"}</dd></div>
              <div><dt>Risk</dt><dd>{estimate?.risk != null ? money(estimate.risk) : "—"}</dd></div>
              <div><dt>R:R</dt><dd>{estimate?.rr != null ? estimate.rr.toFixed(2) : "—"}</dd></div>
            </dl>
            <div className="jg-confirm-actions">
              <button type="button" className="btn" onClick={() => setConfirming(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="jg-btn primary"
                disabled={pendingOrder}
                onClick={() => void submitOrder()}
              >
                {pendingOrder ? "Placing…" : `Place ${side}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {resetting && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="jg-confirm">
            <h3>Reset the demo account?</h3>
            <p>
              Virtual balance returns to its starting value and all virtual
              positions and history are cleared. Your subscription, profile and
              any broker account are <strong>not</strong> affected.
            </p>
            <div className="jg-confirm-actions">
              <button type="button" className="btn" onClick={() => setResetting(false)}>
                Cancel
              </button>
              <button type="button" className="btn danger" onClick={() => void resetDemo()}>
                Reset demo
              </button>
            </div>
          </div>
        </div>
      )}

      <SupportChat />
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div className="jg-ws-metric">
      <span className="jg-ws-metric-label">{label}</span>
      <span className={`jg-ws-metric-value ${tone ?? ""}`}>{value}</span>
      {sub && <span className="jg-ws-metric-sub">{sub}</span>}
    </div>
  );
}
