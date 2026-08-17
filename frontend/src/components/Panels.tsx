import { useEffect, useState } from "react";
import { fmt } from "../lib/api";
import type {
  Analysis,
  Deal,
  OrderLog,
  Position,
  RiskSettings,
  TradingMode,
} from "../lib/types";
import { Badge, Empty } from "./Primitives";

/* ------------------------------------------------------------ price box */

export function PriceBox({
  bid,
  ask,
  spread,
  time,
}: {
  bid?: number;
  ask?: number;
  spread?: number;
  time?: string;
}) {
  const [dir, setDir] = useState<{ bid: string; ask: string }>({ bid: "", ask: "" });
  const [prev, setPrev] = useState<{ bid?: number; ask?: number }>({});

  useEffect(() => {
    if (bid == null || ask == null) return;
    setDir({
      bid: prev.bid == null || bid === prev.bid ? "" : bid > prev.bid ? "tick-up" : "tick-down",
      ask: prev.ask == null || ask === prev.ask ? "" : ask > prev.ask ? "tick-up" : "tick-down",
    });
    setPrev({ bid, ask });
    const t = setTimeout(() => setDir({ bid: "", ask: "" }), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bid, ask]);

  return (
    <div className="price">
      <div className="price-leg">
        <div className="label">Bid</div>
        <div className={`value num ${dir.bid}`}>{fmt.price(bid)}</div>
      </div>
      <div className="price-leg">
        <div className="label">Ask</div>
        <div className={`value num ${dir.ask}`}>{fmt.price(ask)}</div>
      </div>
      <div className="price-leg">
        <div className="label">Spread</div>
        <div className="value num dim" style={{ fontSize: 20 }}>
          {spread == null ? "—" : `${spread.toFixed(0)}p`}
        </div>
      </div>
      <div style={{ flex: 1 }} />
      <span className="faint num" style={{ fontSize: 12 }}>
        {fmt.time(time)}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------- positions */

export function PositionsTable({
  positions,
  onClose,
  busyTicket,
}: {
  positions: Position[];
  onClose: (ticket: number) => void;
  busyTicket: number | null;
}) {
  if (positions.length === 0) return <Empty>No open positions.</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Ticket</th>
            <th>Side</th>
            <th className="right">Lots</th>
            <th className="right">Open</th>
            <th className="right">Current</th>
            <th className="right">SL</th>
            <th className="right">TP</th>
            <th className="right">P/L</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.ticket}>
              <td className="num faint">{p.ticket}</td>
              <td>
                <Badge tone={p.type === "BUY" ? "up" : "down"}>{p.type}</Badge>
              </td>
              <td className="right num">{p.volume.toFixed(2)}</td>
              <td className="right num">{fmt.price(p.price_open)}</td>
              <td className="right num">{fmt.price(p.price_current)}</td>
              <td className="right num faint">{p.sl ? fmt.price(p.sl) : "—"}</td>
              <td className="right num faint">{p.tp ? fmt.price(p.tp) : "—"}</td>
              <td className={`right num ${p.profit >= 0 ? "up" : "down"}`}>
                {fmt.signed(p.profit)}
              </td>
              <td className="right">
                <button
                  className="btn sm"
                  disabled={busyTicket === p.ticket}
                  onClick={() => onClose(p.ticket)}
                >
                  Close
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* -------------------------------------------------------------- analysis */

export function AnalysisPanel({ analysis }: { analysis: Analysis | null }) {
  if (!analysis) return <Empty>Run an analysis to see the multi-timeframe breakdown.</Empty>;

  const biasTone =
    analysis.bias === "BULLISH" ? "up" : analysis.bias === "BEARISH" ? "down" : "neutral";

  return (
    <>
      <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)" }}>
        <div className="row" style={{ marginBottom: 8 }}>
          <Badge tone={biasTone as "up" | "down" | "neutral"}>{analysis.bias}</Badge>
          {analysis.model && <span className="faint" style={{ fontSize: 11 }}>{analysis.model}</span>}
        </div>
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, color: "var(--text-dim)" }}>
          {analysis.summary}
        </p>
      </div>

      {analysis.warnings.length > 0 && (
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--line)" }}>
          <div className="banner warn">
            <div>
              <strong>Warnings</strong>
              <ul className="reasons">
                {analysis.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      <div className="tf-grid">
        {analysis.timeframes.map((tf) => (
          <div className="tf" key={tf.timeframe}>
            <div className="tf-head">
              <span className="tf-name">{tf.timeframe}</span>
              <Badge
                tone={tf.trend === "UP" ? "up" : tf.trend === "DOWN" ? "down" : "neutral"}
              >
                {tf.trend}
              </Badge>
            </div>
            <div className="tf-row">
              <span className="k">Structure</span>
              <span className="v">{tf.structure || "—"}</span>
            </div>
            <div className="tf-row">
              <span className="k">Resistance</span>
              <span className="v">
                {tf.resistance.length ? tf.resistance.map((r) => r.toFixed(2)).join(" · ") : "—"}
              </span>
            </div>
            <div className="tf-row">
              <span className="k">Support</span>
              <span className="v">
                {tf.support.length ? tf.support.map((s) => s.toFixed(2)).join(" · ") : "—"}
              </span>
            </div>
            <div className="tf-row">
              <span className="k">Breakout</span>
              <span className="v">{tf.breakout}</span>
            </div>
            <div className="tf-row">
              <span className="k">Pullback</span>
              <span className="v">{tf.pullback}</span>
            </div>
            <div className="tf-row">
              <span className="k">Liquidity</span>
              <span className="v">
                {tf.liquidity.length
                  ? tf.liquidity
                      .map((l) => `${l.low.toFixed(2)}–${l.high.toFixed(2)}`)
                      .join(" · ")
                  : "—"}
              </span>
            </div>
            {tf.notes && (
              <p style={{ margin: "8px 0 0", fontSize: 11.5, color: "var(--text-faint)", lineHeight: 1.5 }}>
                {tf.notes}
              </p>
            )}
          </div>
        ))}
      </div>

      {analysis.entry_zones.length > 0 && (
        <div style={{ padding: "12px 14px", borderTop: "1px solid var(--line)" }}>
          <div className="stat-label" style={{ marginBottom: 6 }}>Possible entry zones</div>
          <div className="row">
            {analysis.entry_zones.map((z, i) => (
              <Badge key={i} tone="gold">
                {z.low.toFixed(2)} – {z.high.toFixed(2)}
                {z.label ? ` · ${z.label}` : ""}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------ risk panel */

const FIELDS: {
  key: keyof RiskSettings;
  label: string;
  hint: string;
  step: string;
}[] = [
  { key: "max_risk_per_trade_pct", label: "Max risk / trade", hint: "% of balance", step: "0.05" },
  { key: "max_daily_loss_pct", label: "Max daily loss", hint: "% — halts trading", step: "0.1" },
  { key: "max_trades_per_day", label: "Max trades / day", hint: "count", step: "1" },
  { key: "max_open_positions", label: "Max open positions", hint: "count", step: "1" },
  { key: "max_lot_size", label: "Max lot size", hint: "hard cap", step: "0.01" },
  { key: "min_confidence", label: "Min confidence", hint: "0–100", step: "1" },
  { key: "min_rr", label: "Min risk/reward", hint: "e.g. 1.5", step: "0.1" },
  { key: "max_spread_points", label: "Max spread", hint: "points", step: "1" },
];

export function RiskPanel({
  settings,
  onSave,
  saving,
}: {
  settings: RiskSettings;
  onSave: (patch: Partial<RiskSettings>) => void;
  saving: boolean;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});

  useEffect(() => {
    const next: Record<string, string> = {};
    for (const f of FIELDS) next[f.key] = String(settings[f.key]);
    setDraft(next);
  }, [settings]);

  const dirty = FIELDS.some((f) => draft[f.key] !== String(settings[f.key]));

  return (
    <>
      <div className="field-grid">
        {FIELDS.map((f) => (
          <div className="field" key={f.key}>
            <label htmlFor={f.key}>{f.label}</label>
            <input
              id={f.key}
              type="number"
              step={f.step}
              value={draft[f.key] ?? ""}
              onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
            />
            <span className="hint">{f.hint}</span>
          </div>
        ))}
      </div>
      <div className="row">
        <button
          className="btn primary"
          disabled={!dirty || saving}
          onClick={() => {
            const patch: Record<string, number> = {};
            for (const f of FIELDS) patch[f.key] = Number(draft[f.key]);
            onSave(patch as Partial<RiskSettings>);
          }}
        >
          {saving ? "Saving…" : "Save risk settings"}
        </button>
        {dirty && <span className="faint" style={{ fontSize: 12 }}>Unsaved changes</span>}
      </div>
    </>
  );
}

/* ----------------------------------------------------------- mode switch */

export function ModeSwitch({
  mode,
  serverAllowsReal,
  onChange,
  disabled,
}: {
  mode: TradingMode;
  serverAllowsReal: boolean;
  onChange: (m: TradingMode) => void;
  disabled: boolean;
}) {
  const modes: TradingMode[] = ["MANUAL", "DEMO", "REAL"];
  return (
    <div className="modes" role="group" aria-label="Trading mode">
      {modes.map((m) => (
        <button
          key={m}
          className={m === "REAL" ? "real" : undefined}
          aria-pressed={mode === m}
          disabled={disabled || (m === "REAL" && !serverAllowsReal)}
          title={
            m === "REAL" && !serverAllowsReal
              ? "Real trading is disabled on the server (ALLOW_REAL_TRADING=false)"
              : `Switch to ${m} mode`
          }
          onClick={() => onChange(m)}
        >
          {m}
        </button>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------- history */

export function OrderHistory({ orders }: { orders: OrderLog[] }) {
  if (orders.length === 0) return <Empty>No orders submitted yet.</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Mode</th>
            <th>Side</th>
            <th className="right">Lots</th>
            <th className="right">Entry</th>
            <th>Status</th>
            <th>Broker</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td className="num faint">{fmt.datetime(o.created_at)}</td>
              <td><Badge>{o.mode}</Badge></td>
              <td>
                <Badge tone={o.action === "BUY" ? "up" : o.action === "SELL" ? "down" : "neutral"}>
                  {o.action}
                </Badge>
              </td>
              <td className="right num">{o.volume.toFixed(2)}</td>
              <td className="right num">{fmt.price(o.entry)}</td>
              <td>
                <Badge
                  tone={
                    o.status === "FILLED" ? "up" : o.status === "REQUESTED" ? "warn" : "down"
                  }
                >
                  {o.status}
                </Badge>
              </td>
              <td className="faint" style={{ fontSize: 12 }}>
                {o.broker_ticket ? `#${o.broker_ticket} ` : ""}
                {o.broker_comment ?? ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DealHistory({ deals }: { deals: Deal[] }) {
  if (deals.length === 0) return <Empty>No closed deals in this window.</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Symbol</th>
            <th>Side</th>
            <th className="right">Lots</th>
            <th className="right">Price</th>
            <th className="right">Profit</th>
          </tr>
        </thead>
        <tbody>
          {deals.map((d) => (
            <tr key={d.ticket}>
              <td className="num faint">{fmt.datetime(d.time)}</td>
              <td>{d.symbol}</td>
              <td>
                <Badge tone={d.type === "BUY" ? "up" : "down"}>{d.type}</Badge>
              </td>
              <td className="right num">{d.volume.toFixed(2)}</td>
              <td className="right num">{fmt.price(d.price)}</td>
              <td className={`right num ${d.profit >= 0 ? "up" : "down"}`}>
                {fmt.signed(d.profit)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
