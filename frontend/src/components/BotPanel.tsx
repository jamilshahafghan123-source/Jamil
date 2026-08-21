import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { money } from "../lib/format";
import type {
  BotStatus, DemoAccountResponse, DemoPerformance, DemoPosition, RiskSettings,
} from "../lib/types";

/**
 * Bot control panel (sections 16-20).
 *
 * The status shown is derived by the backend from things it can observe —
 * settings, safe mode, maintenance, venue health, open positions — so it
 * never reports RUNNING because a switch is on. A bot whose broker is
 * unreachable is disconnected, whatever its own setting says.
 *
 * Every figure here is the real demo account. There is no sample money in
 * this panel and no placeholder performance: a day with no trades shows
 * zeros, and a figure the platform does not have shows an em dash.
 */

const STATE_TONE: Record<string, string> = {
  OFF: "off",
  READY: "ready",
  STARTING: "active",
  RUNNING: "active",
  WAITING_FOR_SETUP: "active",
  POSITION_OPEN: "active",
  PAUSED: "warn",
  STALLED: "danger",
  BLOCKED_BY_RISK: "warn",
  SAFE_MODE: "warn",
  MAINTENANCE_MODE: "warn",
  EMERGENCY_STOP: "danger",
  BROKER_DISCONNECTED: "danger",
  MARKET_DATA_ERROR: "danger",
  CONNECTION_ERROR: "danger",
};

/**
 * Every state the bot can report, and what each one means.
 *
 * Written out because a status word on its own is a decoration. Someone
 * looking at "BLOCKED BY RISK" needs to know whether that is a fault to
 * fix or the system working correctly, and the panel is where they are
 * already looking.
 */
const STATE_MEANING: [string, string][] = [
  ["OFF", "Switched off. Nothing is analysed and nothing is opened."],
  ["READY", "On, but trading mode is manual — you place the trades."],
  ["STARTING", "The loop is up but has not finished its first scan yet."],
  ["RUNNING", "Never reported on its own — see WAITING FOR SETUP."],
  ["WAITING FOR SETUP", "Analysing. No setup currently qualifies."],
  ["POSITION OPEN", "Managing one or more open positions."],
  ["PAUSED", "Holding. Open positions still managed, nothing new opened."],
  ["NOT ANALYSING", "The analysis loop is not running. Nothing is scanning "
    + "the market — this is a fault, not a quiet period."],
  ["BLOCKED BY RISK", "The risk manager refused the current setup."],
  ["SAFE MODE", "Platform safe mode is blocking new positions."],
  ["MAINTENANCE MODE", "A maintenance window is blocking new positions."],
  ["EMERGENCY STOP", "Halted until the emergency stop is cleared."],
  ["BROKER DISCONNECTED", "The trading venue is unreachable."],
  ["MARKET DATA ERROR", "No prices, so no setup can be assessed."],
  ["CONNECTION ERROR", "The engine cannot reach a service it needs."],
];

/** Lot presets. Every one is a real multiple of the 0.01 minimum step. */
const LOT_PRESETS = [0.01, 0.05, 0.10, 0.25, 0.50, 1.00];
const LOT_MIN = 0.01;
const LOT_MAX = 10.0;
const LOT_STEP = 0.01;

function clampLot(value: number): number {
  const stepped = Math.round(value / LOT_STEP) * LOT_STEP;
  return Number(Math.min(LOT_MAX, Math.max(LOT_MIN, stepped)).toFixed(2));
}

function tone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value === 0) return "";
  return value > 0 ? "up" : "down";
}

export function BotPanel({
  account, positions, risk, onRiskChange,
}: {
  account: DemoAccountResponse | null;
  positions: DemoPosition[];
  risk: RiskSettings | null;
  onRiskChange: (next: RiskSettings) => void;
}) {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [performance, setPerformance] = useState<DemoPerformance | null>(null);
  const [performanceError, setPerformanceError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showStates, setShowStates] = useState(false);
  const [lot, setLot] = useState<string>("");
  const [lotSaved, setLotSaved] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.botStatus());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bot status unavailable");
    }
    try {
      setPerformance(await api.demoPerformance());
      setPerformanceError(null);
    } catch (err) {
      // Reported separately from the bot's own state. Losing today's
      // figures is not the same as losing the bot, and showing zeros
      // instead of saying so would be inventing a quiet day.
      setPerformance(null);
      setPerformanceError(
        err instanceof Error ? err.message : "Performance unavailable",
      );
    }
  }, []);

  useEffect(() => {
    void refresh();
    // The bot's state changes without the customer doing anything, so it
    // is polled — on its own modest beat, not the market's.
    const timer = window.setInterval(() => void refresh(), 20_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  // The field follows the saved setting until the customer edits it.
  useEffect(() => {
    if (risk) setLot(risk.max_lot_size.toFixed(2));
  }, [risk?.max_lot_size]);

  async function act(fn: () => Promise<RiskSettings>) {
    setBusy(true);
    setError(null);
    try {
      onRiskChange(await fn());
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the bot");
    } finally {
      setBusy(false);
    }
  }

  const parsedLot = Number.parseFloat(lot);
  const lotInvalid = useMemo(() => {
    if (!Number.isFinite(parsedLot)) return "Enter a lot size";
    if (parsedLot < LOT_MIN) return `Minimum ${LOT_MIN.toFixed(2)}`;
    if (parsedLot > LOT_MAX) return `Maximum ${LOT_MAX.toFixed(2)}`;
    if (Math.abs(Math.round(parsedLot / LOT_STEP) * LOT_STEP - parsedLot) > 1e-9)
      return `Must be a multiple of ${LOT_STEP.toFixed(2)}`;
    return null;
  }, [parsedLot]);

  const lotDirty =
    risk != null && !lotInvalid && parsedLot !== risk.max_lot_size;

  async function saveLot(value: number) {
    setLotSaved(false);
    await act(async () => {
      const next = await api.saveRisk({ ...risk!, max_lot_size: value });
      setLotSaved(true);
      return next;
    });
  }

  // AI_AUTO is the only automated source today. Strategy-sourced trades
  // will join it when the strategy engine executes, and filtering on a
  // source that does not exist yet would be inventing a category.
  const botPositions = positions.filter((p) => p.source === "AI_AUTO");
  const stateTone = status ? STATE_TONE[status.state] ?? "off" : "off";
  const state = account?.account ?? null;
  const currency = state?.currency ?? "USD";
  const today = performance?.today ?? null;
  const paused = status?.bot_paused ?? false;

  return (
    <div className="jg-bot">
      {error && <p className="jg-ws-error">{error}</p>}

      <div className={`jg-bot-state ${stateTone}`}>
        <span className="jg-bot-dot" aria-hidden="true" />
        <div>
          <strong>{status?.label ?? "Checking…"}</strong>
          <p>{status?.detail ?? ""}</p>
        </div>
      </div>

      <div className="jg-bot-controls">
        <button
          type="button"
          className={status?.bot_enabled ? "btn sm danger" : "btn primary"}
          disabled={busy || !status}
          onClick={() => void act(() => api.setBotEnabled(!status!.bot_enabled))}
        >
          {status?.bot_enabled ? "Stop bot" : "Start bot"}
        </button>

        {/* A pause is a hold, not a stop, so it is a separate control.
            Offering only "stop" would make "wait a moment" and "tear it
            down" the same button. It is only meaningful while the bot is
            on — a paused-off bot is just off. */}
        <button
          type="button"
          className={paused ? "btn sm active" : "btn sm"}
          disabled={busy || !status || !status.bot_enabled}
          aria-pressed={paused}
          title={
            !status?.bot_enabled
              ? "The bot is off — there is nothing to pause"
              : paused
              ? "Resume opening new positions"
              : "Hold: keep managing open positions, open nothing new"
          }
          onClick={() => void act(() => api.setBotPaused(!paused))}
        >
          {paused ? "Resume" : "Pause"}
        </button>

        <label className="jg-bot-mode">
          Auto trade
          <select
            value={status?.trading_mode ?? "MANUAL"}
            disabled={busy || !status}
            onChange={(e) => void act(() => api.setTradingMode(e.target.value))}
          >
            <option value="MANUAL">Off — I place trades myself</option>
            <option value="DEMO">On — J Gold AI demo only</option>
          </select>
        </label>
      </div>

      {/* Lot size the bot may use. The risk manager still sizes each
          individual trade from the account and the stop distance — this is
          the ceiling it may not exceed, not an instruction to trade it. */}
      <section className="jg-bot-lot">
        <div className="jg-bot-lot-head">
          <span>Maximum lot size</span>
          {lotSaved && !lotDirty && (
            <span className="jg-bot-lot-saved" role="status">Saved</span>
          )}
        </div>
        <div className="jg-bot-lot-row">
          <button type="button" aria-label="Decrease lot size"
                  disabled={busy || !risk}
                  onClick={() => setLot(clampLot((Number.isFinite(parsedLot)
                    ? parsedLot : LOT_MIN) - LOT_STEP).toFixed(2))}>−</button>
          <input
            value={lot}
            inputMode="decimal"
            aria-label="Maximum lot size"
            disabled={!risk}
            onChange={(e) => { setLot(e.target.value); setLotSaved(false); }}
          />
          <button type="button" aria-label="Increase lot size"
                  disabled={busy || !risk}
                  onClick={() => setLot(clampLot((Number.isFinite(parsedLot)
                    ? parsedLot : LOT_MIN) + LOT_STEP).toFixed(2))}>+</button>
        </div>
        <div className="jg-bot-lot-presets" role="group" aria-label="Lot presets">
          {LOT_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className={parsedLot === preset ? "jg-chip active" : "jg-chip"}
              disabled={busy || !risk}
              onClick={() => { setLot(preset.toFixed(2)); setLotSaved(false); }}
            >
              {preset.toFixed(2)}
            </button>
          ))}
        </div>
        {lotInvalid && <p className="jg-quick-invalid">{lotInvalid}</p>}
        <button
          type="button"
          className="btn sm"
          disabled={busy || !lotDirty}
          onClick={() => void saveLot(parsedLot)}
        >
          {lotDirty ? `Save ${parsedLot.toFixed(2)}` : "Saved"}
        </button>
        <p className="jg-bot-note">
          A ceiling, not an instruction. The risk manager sizes each trade
          from the account and the stop distance and may use less — it never
          uses more.
        </p>
      </section>

      {/* Real trading is disabled platform-wide, and the panel says so
          rather than offering a mode that would be refused. */}
      <p className="jg-bot-note">
        Live broker automation is disabled on this platform. The bot trades
        the internal J Gold AI demo account only.
      </p>

      <section className="jg-bot-stats">
        <h4 className="jg-symbol-group">Account</h4>
        <dl>
          <div><dt>Balance</dt><dd>{money(state?.balance, currency)}</dd></div>
          <div><dt>Equity</dt><dd>{money(state?.equity, currency)}</dd></div>
          <div><dt>Free margin</dt><dd>{money(state?.free_margin, currency)}</dd></div>
          <div>
            <dt>Floating P/L</dt>
            <dd className={tone(state?.floating_pnl)}>
              {money(state?.floating_pnl, currency)}
            </dd>
          </div>
          <div>
            <dt>Realised P/L</dt>
            <dd className={tone(state?.realized_pnl)}>
              {money(state?.realized_pnl, currency)}
            </dd>
          </div>
          <div><dt>Open positions</dt><dd>{positions.length}</dd></div>
        </dl>
      </section>

      <section className="jg-bot-stats">
        <h4 className="jg-symbol-group">
          Today
          {performance && (
            <span className="jg-bot-daybasis">
              {" "}since {new Date(performance.day_start).toISOString().slice(0, 10)}
              {" "}{performance.day_basis}
            </span>
          )}
        </h4>
        {performanceError ? (
          <p className="jg-cc-note">
            DATA UNAVAILABLE — {performanceError}. Nothing is shown rather
            than a zero that would read as a quiet day.
          </p>
        ) : (
          <dl>
            <div>
              <dt>Net P/L</dt>
              <dd className={tone(today?.net_pnl)}>
                {money(today?.net_pnl, currency)}
              </dd>
            </div>
            <div><dt>Trades</dt><dd>{today?.trades ?? "—"}</dd></div>
            <div>
              <dt>Wins</dt>
              <dd className={today && today.wins > 0 ? "up" : ""}>
                {today?.wins ?? "—"}
              </dd>
            </div>
            <div>
              <dt>Losses</dt>
              <dd className={today && today.losses > 0 ? "down" : ""}>
                {today?.losses ?? "—"}
              </dd>
            </div>
            {today != null && today.breakeven > 0 && (
              <div><dt>Break-even</dt><dd>{today.breakeven}</dd></div>
            )}
            <div>
              <dt>Win rate</dt>
              {/* Null until there is something to take a rate of. A win
                  rate off no trades is not 0%, it is unknown. */}
              <dd>{today?.win_rate != null ? `${today.win_rate}%` : "—"}</dd>
            </div>
          </dl>
        )}
      </section>

      <section className="jg-bot-stats">
        <h4 className="jg-symbol-group">
          Bot positions ({botPositions.length})
        </h4>
        {botPositions.length === 0 ? (
          <p className="jg-cc-note">
            The bot has no open positions. A period with no qualifying setup
            correctly produces no trades.
          </p>
        ) : (
          <ul className="jg-bot-positions detail">
            {botPositions.map((position) => (
              <li key={position.id}>
                <div className="jg-bot-pos-head">
                  <span className={position.side === "BUY" ? "buy" : "sell"}>
                    {position.side}
                  </span>
                  <strong>{position.symbol}</strong>
                  <span>{position.volume.toFixed(2)} lots</span>
                  <span className="jg-spacer" />
                  <span className={tone(position.floating_pnl)}>
                    {money(position.floating_pnl, currency)}
                  </span>
                </div>
                <dl className="jg-bot-pos-grid">
                  <div><dt>Entry</dt><dd>{position.entry_price.toFixed(2)}</dd></div>
                  <div>
                    <dt>Current</dt>
                    <dd>{position.current_price != null
                      ? position.current_price.toFixed(2) : "—"}</dd>
                  </div>
                  <div>
                    <dt>SL</dt>
                    <dd>{position.stop_loss != null
                      ? position.stop_loss.toFixed(2) : "none"}</dd>
                  </div>
                  <div>
                    <dt>TP</dt>
                    <dd>{position.take_profit != null
                      ? position.take_profit.toFixed(2) : "none"}</dd>
                  </div>
                  <div>
                    <dt>Opened</dt>
                    <dd>{position.opened_at
                      ? new Date(position.opened_at).toLocaleString(undefined, {
                          month: "short", day: "numeric",
                          hour: "2-digit", minute: "2-digit",
                        })
                      : "—"}</dd>
                  </div>
                  <div><dt>Source</dt><dd>{position.source.replace("_", " ")}</dd></div>
                  {/* Everything below comes from the linked opportunity
                      record. A hand-placed trade has none, so these read
                      as an em dash rather than a plausible-looking class
                      the platform never assigned. */}
                  <div>
                    <dt>Setup</dt>
                    <dd>{position.setup_class
                      ? position.setup_class.replace("_", " ") : "—"}</dd>
                  </div>
                  <div>
                    <dt>Confidence</dt>
                    <dd>{position.signal_confidence != null
                      ? `${position.signal_confidence}%` : "—"}</dd>
                  </div>
                  <div>
                    <dt>Score</dt>
                    <dd>{position.opportunity_score != null
                      ? `${position.opportunity_score}${position.grade
                          ? ` · ${position.grade.toLowerCase()}` : ""}`
                      : "—"}</dd>
                  </div>
                  <div>
                    <dt>R:R</dt>
                    <dd>{position.signal_rr != null
                      ? position.signal_rr.toFixed(2) : "—"}</dd>
                  </div>
                  <div>
                    <dt>Session</dt>
                    <dd>{position.session
                      ? position.session.replace(/_/g, " ") : "—"}</dd>
                  </div>
                  <div>
                    <dt>Strategy</dt>
                    <dd>{position.strategy ?? "none"}</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ul>
        )}
        {botPositions.some((p) => p.opportunity_id == null) && (
          <p className="jg-cc-note">
            An em dash means the platform did not record that figure for
            this position — not that it was zero. Positions opened before
            opportunity telemetry, or by hand, have no setup behind them.
          </p>
        )}
      </section>

      <section className="jg-bot-stats">
        <button
          type="button"
          className="jg-bot-states-toggle"
          aria-expanded={showStates}
          onClick={() => setShowStates((v) => !v)}
        >
          {showStates ? "Hide" : "What the states mean"}
        </button>
        {showStates && (
          <dl className="jg-bot-states">
            {STATE_MEANING.map(([name, meaning]) => (
              <div key={name}
                   className={status?.label?.toUpperCase() === name
                     ? "current" : undefined}>
                <dt>{name}</dt>
                <dd>{meaning}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      {risk && (
        <p className="jg-bot-note">
          Risk manager: max {risk.max_open_positions} open positions,
          {" "}{risk.max_risk_per_trade_pct}% risk per trade. Every bot order
          passes through it, and it has the final say.
        </p>
      )}
    </div>
  );
}
