"use client";

import { useState } from "react";

import { ApiClientError, apiFetch } from "@/lib/client";
import { number, timeAgo } from "@/lib/format";
import type { BotStatus } from "@/lib/types";
import type { PollState } from "@/hooks/usePolling";
import { ErrorNotice, Panel, RefreshIndicator, SkeletonRows, Spinner, humanizeCode } from "./ui";

const EVENT_TONE: Record<string, string> = {
  trade: "up",
  would_trade: "",
  no_trade: "muted",
  rejected: "down",
  capped: "muted",
  error: "down",
  started: "",
  stopped: "muted",
  waiting: "muted",
};

/** Start/stop the autonomous loop and watch what it decides. */
export default function BotPanel({
  state,
  online,
  onChanged,
}: {
  state: PollState<BotStatus>;
  online: boolean;
  onChanged: () => void;
}) {
  const { data: bot, error, loading, refreshing, lastUpdated, refresh } = state;
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function send(action: "start" | "stop") {
    setBusy(true);
    setActionError(null);
    try {
      await apiFetch<BotStatus>("/api/mt5/bot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      refresh();
      onChanged();
    } catch (caught) {
      const err = caught as ApiClientError;
      setActionError(`${humanizeCode(err.code)}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  if (!online && !bot) {
    return (
      <Panel title="Bot">
        <div className="empty">The bot is unavailable while the MT5 bridge is offline.</div>
      </Panel>
    );
  }

  if (loading && !bot) {
    return (
      <Panel title="Bot">
        <SkeletonRows rows={3} />
      </Panel>
    );
  }

  if (error && !bot) {
    return (
      <Panel title="Bot">
        <ErrorNotice error={error} onRetry={refresh} />
      </Panel>
    );
  }

  if (!bot) return null;

  return (
    <Panel
      title="Bot"
      actions={<RefreshIndicator refreshing={refreshing} label={timeAgo(lastUpdated)} />}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
        <span className={bot.running ? "badge online" : "badge muted"}>
          <span className="dot" />
          {bot.running ? "Running" : "Stopped"}
        </span>
        {bot.running ? (
          <span className={bot.dry_run ? "badge muted" : "badge warn"}>
            {bot.dry_run ? "dry run" : "LIVE"}
          </span>
        ) : null}
      </div>

      {!bot.enabled ? (
        <div className="notice warn" style={{ marginBottom: 12 }}>
          <span>
            The bot is disabled on the bridge (<code>BOT_ENABLED</code> is not true), so it
            cannot be started from here.
          </span>
        </div>
      ) : null}

      {bot.enabled && bot.dry_run ? (
        <div className="notice" style={{ marginBottom: 12 }}>
          <span>
            Dry run: the loop records the trades it would take and sends nothing. Set{" "}
            <code>BOT_DRY_RUN=false</code> on the bridge to let it trade.
          </span>
        </div>
      ) : null}

      <dl className="risk-grid">
        <dt>Watching</dt>
        <dd>{bot.symbol ? `${bot.symbol} ${bot.timeframe}` : "—"}</dd>
        <dt>Cadence</dt>
        <dd>
          {bot.mode === "bar" ? "per closed bar" : `every ${number(bot.poll_seconds, 0)}s`}
        </dd>
        <dt>Trades today</dt>
        <dd>
          {bot.trades_today} / {bot.max_trades_per_day}
        </dd>
        <dt>Last look</dt>
        <dd>{bot.last_evaluated_at ? timeAgo(Date.parse(bot.last_evaluated_at)) : "—"}</dd>
      </dl>

      {bot.last_decision ? (
        <p className="pipeline-note" style={{ marginTop: 10 }}>
          Last decision: <strong>{bot.last_decision.decision.replace("_", " ")}</strong> at{" "}
          {number(bot.last_decision.confidence, 0)}% — {bot.last_decision.reason}
        </p>
      ) : null}

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button
          type="button"
          className="btn buy"
          style={{ flex: 1 }}
          disabled={busy || bot.running || !bot.enabled}
          onClick={() => send("start")}
        >
          {busy && !bot.running ? <Spinner /> : null} Start
        </button>
        <button
          type="button"
          className="btn sell"
          style={{ flex: 1 }}
          disabled={busy || !bot.running}
          onClick={() => send("stop")}
        >
          Stop
        </button>
      </div>

      {actionError ? (
        <div className="notice error" style={{ marginTop: 10 }} role="alert">
          <span>{actionError}</span>
        </div>
      ) : null}

      {bot.events.length ? (
        <>
          <div className="risk-meter-head" style={{ marginTop: 14 }}>
            <span className="muted">Recent activity</span>
          </div>
          <ul className="bot-log">
            {bot.events.slice(0, 6).map((event, index) => (
              <li key={`${event.at}-${index}`}>
                <span className={`bot-log-kind ${EVENT_TONE[event.kind] ?? ""}`}>
                  {event.kind.replace("_", " ")}
                </span>
                <span className="bot-log-message">{event.message}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <p className="hint" style={{ marginTop: 10, color: "var(--muted)" }}>
        Stopping leaves open positions exactly as they are — it stops the bot opening more,
        it does not close anything.
      </p>
    </Panel>
  );
}
