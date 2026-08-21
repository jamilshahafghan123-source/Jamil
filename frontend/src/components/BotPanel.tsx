import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { money } from "../lib/format";
import type {
  BotStatus, DemoAccountResponse, DemoPosition, RiskSettings,
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
 * this panel and no placeholder performance.
 */

const STATE_TONE: Record<string, string> = {
  OFF: "off",
  READY: "ready",
  STARTING: "active",
  RUNNING: "active",
  WAITING_FOR_SETUP: "active",
  POSITION_OPEN: "active",
  PAUSED: "warn",
  BLOCKED_BY_RISK: "warn",
  SAFE_MODE: "warn",
  MAINTENANCE_MODE: "warn",
  EMERGENCY_STOP: "danger",
  BROKER_DISCONNECTED: "danger",
  MARKET_DATA_ERROR: "danger",
  CONNECTION_ERROR: "danger",
};

export function BotPanel({
  account, positions, risk, onRiskChange,
}: {
  account: DemoAccountResponse | null;
  positions: DemoPosition[];
  risk: RiskSettings | null;
  onRiskChange: (next: RiskSettings) => void;
}) {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.botStatus());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bot status unavailable");
    }
  }, []);

  useEffect(() => {
    void refresh();
    // The bot's state changes without the customer doing anything, so it
    // is polled — on its own modest beat, not the market's.
    const timer = window.setInterval(() => void refresh(), 20_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

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

  // AI_AUTO is the only automated source today. Strategy-sourced trades
  // will join it when the strategy engine executes, and filtering on a
  // source that does not exist yet would be inventing a category.
  const botPositions = positions.filter((p) => p.source === "AI_AUTO");
  const tone = status ? STATE_TONE[status.state] ?? "off" : "off";
  const state = account?.account ?? null;
  const currency = state?.currency ?? "USD";

  return (
    <div className="jg-bot">
      {error && <p className="jg-ws-error">{error}</p>}

      <div className={`jg-bot-state ${tone}`}>
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
            <dd className={(state?.floating_pnl ?? 0) > 0 ? "up"
                          : (state?.floating_pnl ?? 0) < 0 ? "down" : ""}>
              {money(state?.floating_pnl, currency)}
            </dd>
          </div>
          <div>
            <dt>Realised P/L</dt>
            <dd className={(state?.realized_pnl ?? 0) > 0 ? "up"
                          : (state?.realized_pnl ?? 0) < 0 ? "down" : ""}>
              {money(state?.realized_pnl, currency)}
            </dd>
          </div>
          <div><dt>Open positions</dt><dd>{positions.length}</dd></div>
        </dl>
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
          <ul className="jg-bot-positions">
            {botPositions.map((position) => (
              <li key={position.id}>
                <span>{position.symbol} {position.side} {position.volume}</span>
                <span className={(position.floating_pnl ?? 0) >= 0 ? "up" : "down"}>
                  {money(position.floating_pnl, currency)}
                </span>
              </li>
            ))}
          </ul>
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
