import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { BrokerDirectory, BrokerInfo } from "../lib/types";

/**
 * Broker connection centre (sections 40-44).
 *
 * The whole panel is built around one rule: it never claims more than the
 * platform can do. A broker that has no connector says so, cannot be
 * clicked, and carries no rating, star count or "recommended" badge —
 * there is no honest basis for any of those here, and inventing one is
 * how a trading platform starts misleading people about money.
 */

const CATEGORY_LABEL: Record<string, string> = {
  INTERNAL: "J Gold AI",
  MT5: "MetaTrader 5",
  FOREX_CFD: "Forex / CFD",
  MULTI_ASSET: "Multi-asset",
  STOCKS: "Stocks",
  CRYPTO: "Crypto",
  FUTURES: "Futures",
  FUNDED: "Funded / prop",
};

const CATEGORY_ORDER = [
  "INTERNAL", "MT5", "FOREX_CFD", "MULTI_ASSET", "STOCKS", "CRYPTO",
  "FUTURES", "FUNDED",
];

const STATUS_LABEL: Record<string, string> = {
  CONNECTED: "Connected",
  AVAILABLE: "Available",
  COMING_SOON: "Coming soon",
  UNSUPPORTED: "Not supported",
};

const AUTH_LABEL: Record<string, string> = {
  NONE: "No sign-in needed",
  OAUTH: "Broker-hosted sign-in",
  API_TOKEN: "Broker-issued API token",
  BROKER_HOSTED: "Broker-hosted consent",
  BRIDGE_TOKEN: "Host-to-host bridge token",
};

export function BrokerCentre({ open, onClose }: {
  open: boolean;
  onClose: () => void;
}) {
  const [directory, setDirectory] = useState<BrokerDirectory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open || directory) return;
    api.brokers()
      .then(setDirectory)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Broker list unavailable"));
  }, [open, directory]);

  if (!open) return null;

  const q = query.trim().toLowerCase();
  const groups = directory
    ? CATEGORY_ORDER
        .filter((c) => directory.by_category[c]?.length)
        .map((c) => [
          c,
          directory.by_category[c].filter(
            (b) => !q || b.display_name.toLowerCase().includes(q),
          ),
        ] as [string, BrokerInfo[]])
        .filter(([, list]) => list.length > 0)
    : [];

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true"
         aria-label="Broker connection centre" onClick={onClose}>
      <div className="modal jg-broker-modal" onClick={(e) => e.stopPropagation()}>
        <header className="jg-symbol-head">
          <input
            className="jg-symbol-input"
            placeholder="Search brokers"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search brokers"
          />
          <button type="button" className="btn sm" onClick={onClose}>Close</button>
        </header>

        {error && <p className="jg-ws-error">{error}</p>}
        {!directory && !error && <p className="jg-cc-note">Loading…</p>}

        <div className="jg-symbol-body">
          {groups.map(([category, list]) => (
            <section key={category}>
              <h4 className="jg-symbol-group">
                {CATEGORY_LABEL[category] ?? category}
              </h4>
              {list.map((broker) => (
                <article key={broker.key} className="jg-broker-row">
                  <div className="jg-broker-main">
                    <span className="jg-broker-name">{broker.display_name}</span>
                    <span className={`jg-symbol-status ${broker.status.toLowerCase()}`}>
                      {STATUS_LABEL[broker.status] ?? broker.status}
                    </span>
                  </div>
                  <p className="jg-broker-note">{broker.note}</p>
                  <p className="jg-broker-auth">
                    {AUTH_LABEL[broker.auth_method] ?? broker.auth_method}
                    {broker.capabilities.length > 0 &&
                      ` · ${broker.capabilities.join(", ")}`}
                  </p>
                  <button
                    type="button"
                    className="btn sm"
                    disabled={!broker.connectable}
                    title={broker.connectable
                      ? "Connection is configured by an administrator"
                      : "No connector for this broker yet"}
                  >
                    {broker.status === "CONNECTED" ? "Connected" : "Connect"}
                  </button>
                </article>
              ))}
            </section>
          ))}

          {directory && (
            <section>
              <h4 className="jg-symbol-group">Funded / prop accounts</h4>
              <article className="jg-broker-row">
                <div className="jg-broker-main">
                  <span className="jg-broker-name">Funded accounts</span>
                  <span className="jg-symbol-status coming_soon">
                    {STATUS_LABEL[directory.funded_accounts.status]}
                  </span>
                </div>
                <p className="jg-broker-note">
                  {directory.funded_accounts.detail}
                </p>
              </article>
            </section>
          )}
        </div>

        <footer className="jg-symbol-foot">
          {directory?.disclaimer ??
            "Listing a broker is not endorsement or a claim of support."}
        </footer>
      </div>
    </div>
  );
}
