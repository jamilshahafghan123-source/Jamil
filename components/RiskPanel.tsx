"use client";

import { money, number, timeAgo } from "@/lib/format";
import type { RiskState } from "@/lib/types";
import type { PollState } from "@/hooks/usePolling";
import { ErrorNotice, Panel, RefreshIndicator, SkeletonRows } from "./ui";

/** Today's risk budget and the standing limits, straight from the bridge. */
export default function RiskPanel({
  state,
  online,
}: {
  state: PollState<RiskState>;
  online: boolean;
}) {
  const { data: risk, error, loading, refreshing, lastUpdated, refresh } = state;

  if (!online && !risk) {
    return (
      <Panel title="Risk">
        <div className="empty">Risk state is unavailable while the MT5 bridge is offline.</div>
      </Panel>
    );
  }

  if (loading && !risk) {
    return (
      <Panel title="Risk">
        <SkeletonRows rows={3} />
      </Panel>
    );
  }

  if (error && !risk) {
    return (
      <Panel title="Risk">
        <ErrorNotice error={error} onRetry={refresh} />
      </Panel>
    );
  }

  if (!risk) return null;

  if (!risk.enabled) {
    return (
      <Panel title="Risk">
        <div className="notice warn">
          <span>
            The risk policy is switched off on the bridge (<code>RISK_ENABLED=false</code>).
            Only the demo-account guard and the lot ceiling apply.
          </span>
        </div>
      </Panel>
    );
  }

  const { limits } = risk;
  const usedPct =
    limits.max_daily_loss_pct > 0
      ? Math.min(100, (risk.daily_loss_pct / limits.max_daily_loss_pct) * 100)
      : 0;
  const barColor =
    usedPct >= 100 ? "var(--down)" : usedPct >= 60 ? "var(--warn)" : "var(--up)";

  return (
    <Panel
      title="Risk"
      actions={<RefreshIndicator refreshing={refreshing} label={`updated ${timeAgo(lastUpdated)}`} />}
    >
      {risk.daily_loss_limit_hit ? (
        <div className="notice error" style={{ marginBottom: 12 }} role="alert">
          <div>
            <strong>Daily loss limit reached</strong>
            <span>
              {number(risk.daily_loss_pct, 2)}% of the day&apos;s opening balance against a{" "}
              {limits.max_daily_loss_pct}% cap. The bridge is refusing new orders until the
              next trading day.
            </span>
          </div>
        </div>
      ) : null}

      <div className="risk-meter">
        <div className="risk-meter-head">
          <span className="muted">Daily loss</span>
          <span className="mono">
            {money(risk.daily_loss, risk.currency)} / {money(risk.daily_loss_budget, risk.currency)}
          </span>
        </div>
        <div className="risk-bar" role="img" aria-label={`${number(usedPct, 0)}% of the daily loss budget used`}>
          <span style={{ width: `${usedPct}%`, background: barColor }} />
        </div>
        <div className="risk-meter-head" style={{ marginTop: 4 }}>
          <span className="muted" style={{ fontSize: 11 }}>
            {number(risk.daily_loss_pct, 2)}% of {limits.max_daily_loss_pct}%
          </span>
          <span className="muted" style={{ fontSize: 11 }}>
            {money(risk.daily_loss_remaining, risk.currency)} left
          </span>
        </div>
      </div>

      <dl className="risk-grid">
        <Row label="Realised today" value={money(risk.daily.realized, risk.currency)} signed={risk.daily.realized} />
        <Row label="Floating" value={money(risk.daily.floating, risk.currency)} signed={risk.daily.floating} />
        <Row
          label="Positions"
          value={`${risk.open_positions} / ${limits.max_positions}`}
        />
        <Row label="Risk per trade" value={`${limits.risk_per_trade_pct}% of balance`} />
        <Row label="Max lot" value={number(limits.max_lot, 2)} />
        <Row
          label="Stops"
          value={`SL ${limits.require_sl ? "required" : "optional"} · TP ${
            limits.require_tp ? "required" : "optional"
          }`}
        />
        <Row
          label="Symbols"
          value={limits.allowed_symbols.length ? limits.allowed_symbols.join(", ") : "any"}
        />
      </dl>
    </Panel>
  );
}

function Row({
  label,
  value,
  signed,
}: {
  label: string;
  value: string;
  signed?: number;
}) {
  const tone = signed == null || signed === 0 ? "" : signed > 0 ? "up" : "down";
  return (
    <>
      <dt>{label}</dt>
      <dd className={tone}>{value}</dd>
    </>
  );
}
