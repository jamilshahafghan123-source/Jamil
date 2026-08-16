"use client";

import { money, number, timeAgo } from "@/lib/format";
import type { Account } from "@/lib/types";
import type { PollState } from "@/hooks/usePolling";
import { ErrorNotice, Panel, RefreshIndicator, SkeletonRows } from "./ui";

/** Real MT5 account state: balance, equity, margin, free margin and status. */
export default function AccountPanel({
  state,
  online,
}: {
  state: PollState<Account>;
  online: boolean;
}) {
  const { data: account, error, loading, refreshing, lastUpdated, refresh } = state;

  return (
    <Panel
      title="Account"
      tight={Boolean(account)}
      actions={
        <RefreshIndicator
          refreshing={refreshing}
          label={online ? `updated ${timeAgo(lastUpdated)}` : "unavailable"}
        />
      }
    >
      {!online && !account ? (
        <div className="empty">
          Account data is unavailable while the MT5 bridge is offline.
        </div>
      ) : null}

      {online && loading && !account ? (
        <div style={{ padding: 14 }}>
          <SkeletonRows rows={4} />
        </div>
      ) : null}

      {error && !account ? (
        <div style={{ padding: 14 }}>
          <ErrorNotice error={error} onRetry={refresh} />
        </div>
      ) : null}

      {account ? (
        <>
          {error ? (
            <div style={{ padding: 12 }}>
              <div className="notice warn">
                <span>
                  Showing the last known account state — the latest refresh failed:{" "}
                  {error.message}
                </span>
              </div>
            </div>
          ) : null}

          <div className="metrics">
            <div className="metric">
              <div className="label">Balance</div>
              <div className="value">{money(account.balance, account.currency)}</div>
            </div>
            <div className="metric">
              <div className="label">Equity</div>
              <div className="value">{money(account.equity, account.currency)}</div>
            </div>
            <div className="metric">
              <div className="label">Margin</div>
              <div className="value small">{money(account.margin, account.currency)}</div>
            </div>
            <div className="metric">
              <div className="label">Free margin</div>
              <div className="value small">{money(account.margin_free, account.currency)}</div>
            </div>
            <div className="metric">
              <div className="label">Margin level</div>
              <div className="value small">
                {account.margin_level ? `${number(account.margin_level)}%` : "—"}
              </div>
            </div>
            <div className="metric">
              <div className="label">Leverage</div>
              <div className="value small">1:{account.leverage}</div>
            </div>
          </div>

          <div
            style={{
              display: "flex",
              gap: 8,
              flexWrap: "wrap",
              alignItems: "center",
              padding: "12px 14px",
              borderTop: "1px solid var(--border)",
            }}
          >
            <span className={account.is_demo ? "badge online" : "badge warn"}>
              <span className="dot" />
              {(account.trade_mode_name ?? "unknown").toUpperCase()} ACCOUNT
            </span>
            <span className="badge muted">#{account.login}</span>
            {account.server ? <span className="badge muted">{account.server}</span> : null}
            {account.trade_allowed === false ? (
              <span className="badge offline">
                <span className="dot" />
                Trading disabled by broker
              </span>
            ) : null}
          </div>
        </>
      ) : null}
    </Panel>
  );
}
