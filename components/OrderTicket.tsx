"use client";

import { useEffect, useState } from "react";

import { ApiClientError, apiFetch } from "@/lib/client";
import type {
  OrderOutcome,
  OrderSide,
  OrderType,
  RiskState,
  SymbolSummary,
  Tick,
} from "@/lib/types";
import { Panel, Spinner, humanizeCode } from "./ui";

type Outcome =
  | { kind: "executed"; result: OrderOutcome }
  | { kind: "validated"; result: OrderOutcome; blocked: boolean; message: string }
  | { kind: "error"; title: string; message: string; retcode?: number; retcodeText?: string };

/** Digs a MT5 retcode out of whichever error envelope it arrived in. */
function findRetcode(details: unknown): { retcode?: number; retcodeText?: string } {
  if (!details || typeof details !== "object") return {};
  const record = details as Record<string, unknown>;
  if (typeof record.retcode === "number") {
    return {
      retcode: record.retcode,
      retcodeText:
        typeof record.retcode_description === "string" ? record.retcode_description : undefined,
    };
  }
  return findRetcode(record.details);
}

export default function OrderTicket({
  symbol,
  symbolInfo,
  tick,
  risk,
  liveExecutionEnabled,
  bridgeReady,
  onOrderPlaced,
}: {
  symbol: string;
  symbolInfo: SymbolSummary | null;
  tick: Tick | null;
  risk: RiskState | null;
  liveExecutionEnabled: boolean;
  bridgeReady: boolean;
  onOrderPlaced: () => void;
}) {
  const [side, setSide] = useState<OrderSide>("buy");
  const [type, setType] = useState<OrderType>("market");
  const [volume, setVolume] = useState("0.10");
  const [priceInput, setPriceInput] = useState("");
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [validateOnly, setValidateOnly] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const digits = symbolInfo?.digits ?? 5;

  // Mirror the bridge's policy locally so the form cannot submit an order the
  // bridge is certain to refuse. The bridge stays the authority either way.
  const limits = risk?.enabled ? risk.limits : null;
  const symbolBlocked = Boolean(
    limits?.allowed_symbols.length && !limits.allowed_symbols.includes(symbol),
  );
  const positionsFull = Boolean(risk?.enabled && risk.positions_remaining <= 0);
  const dailyLimitHit = Boolean(risk?.enabled && risk.daily_loss_limit_hit);
  const maxLot = limits ? Math.min(limits.max_lot, symbolInfo?.volume_max ?? Infinity) : symbolInfo?.volume_max;

  const blockedReason = symbolBlocked
    ? `The risk policy only allows ${limits?.allowed_symbols.join(", ")}.`
    : dailyLimitHit
      ? "The daily loss limit has been reached — no new orders today."
      : positionsFull
        ? `The position limit (${limits?.max_positions}) is already used.`
        : null;

  // Seed the pending-order price from the live quote when switching away from market.
  useEffect(() => {
    if (type === "market") {
      setPriceInput("");
      return;
    }
    setPriceInput((current) => {
      if (current) return current;
      const reference = side === "buy" ? tick?.ask : tick?.bid;
      return reference ? reference.toFixed(digits) : "";
    });
  }, [type, side, tick, digits]);

  useEffect(() => {
    setOutcome(null);
  }, [symbol]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setOutcome(null);

    const body: Record<string, unknown> = {
      symbol,
      side,
      type,
      volume: Number(volume),
    };
    if (type !== "market") body.price = Number(priceInput);
    if (sl.trim()) body.sl = Number(sl);
    if (tp.trim()) body.tp = Number(tp);
    if (validateOnly) body.dry_run = true;

    try {
      const result = await apiFetch<OrderOutcome>("/api/mt5/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      setOutcome(
        result.executed
          ? { kind: "executed", result }
          : {
              kind: "validated",
              result,
              blocked: false,
              message: "Validation only — this order was checked by MT5, not sent.",
            },
      );
      if (result.executed) onOrderPlaced();
    } catch (caught) {
      const error = caught as ApiClientError;

      if (error.code === "live_execution_disabled") {
        const result = error.details as OrderOutcome | null;
        setOutcome(
          result && typeof result === "object" && "retcode" in result
            ? { kind: "validated", result, blocked: true, message: error.message }
            : { kind: "error", title: "Live execution disabled", message: error.message },
        );
      } else {
        const { retcode, retcodeText } = findRetcode(error.details);
        setOutcome({
          kind: "error",
          title: error.offline ? "MT5 Bridge Offline" : humanizeCode(error.code),
          message: error.message,
          retcode,
          retcodeText,
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  const disabled = submitting || !bridgeReady;
  const cannotSubmit = disabled || Boolean(blockedReason);
  const submitLabel = validateOnly
    ? "Validate order"
    : `${side === "buy" ? "Buy" : "Sell"} ${volume || "0"} ${symbol}`;

  return (
    <Panel title="New order">
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="order-side">Side</label>
          <div className="seg" id="order-side" role="group">
            <button
              type="button"
              className={side === "buy" ? "active" : ""}
              onClick={() => setSide("buy")}
              disabled={disabled}
            >
              BUY {tick ? tick.ask.toFixed(digits) : ""}
            </button>
            <button
              type="button"
              className={side === "sell" ? "active" : ""}
              onClick={() => setSide("sell")}
              disabled={disabled}
            >
              SELL {tick ? tick.bid.toFixed(digits) : ""}
            </button>
          </div>
        </div>

        <div className="field">
          <label htmlFor="order-type">Order type</label>
          <select
            id="order-type"
            value={type}
            onChange={(event) => setType(event.target.value as OrderType)}
            disabled={disabled}
          >
            <option value="market">Market</option>
            <option value="limit">Limit</option>
            <option value="stop">Stop</option>
          </select>
        </div>

        <div className="field">
          <label htmlFor="order-volume">Volume (lots)</label>
          <input
            id="order-volume"
            type="number"
            inputMode="decimal"
            min={symbolInfo?.volume_min ?? 0.01}
            max={maxLot ?? undefined}
            step={symbolInfo?.volume_step ?? 0.01}
            value={volume}
            onChange={(event) => setVolume(event.target.value)}
            disabled={disabled}
            required
          />
          {symbolInfo ? (
            <span className="hint">
              min {symbolInfo.volume_min} · step {symbolInfo.volume_step} · max{" "}
              {maxLot}
              {limits && limits.max_lot < symbolInfo.volume_max ? " (risk policy)" : ""}
            </span>
          ) : null}
        </div>

        {type !== "market" ? (
          <div className="field">
            <label htmlFor="order-price">{type === "limit" ? "Limit price" : "Stop price"}</label>
            <input
              id="order-price"
              type="number"
              inputMode="decimal"
              step={symbolInfo ? symbolInfo.point : 0.00001}
              value={priceInput}
              onChange={(event) => setPriceInput(event.target.value)}
              disabled={disabled}
              required
            />
          </div>
        ) : null}

        <div className="field-row">
          <div className="field">
            <label htmlFor="order-sl">
              Stop loss{limits?.require_sl ? " *" : ""}
            </label>
            <input
              id="order-sl"
              type="number"
              inputMode="decimal"
              step={symbolInfo ? symbolInfo.point : 0.00001}
              value={sl}
              onChange={(event) => setSl(event.target.value)}
              placeholder={limits?.require_sl ? "required" : "none"}
              disabled={disabled}
              required={limits?.require_sl}
            />
          </div>
          <div className="field">
            <label htmlFor="order-tp">
              Take profit{limits?.require_tp ? " *" : ""}
            </label>
            <input
              id="order-tp"
              type="number"
              inputMode="decimal"
              step={symbolInfo ? symbolInfo.point : 0.00001}
              value={tp}
              onChange={(event) => setTp(event.target.value)}
              placeholder={limits?.require_tp ? "required" : "none"}
              disabled={disabled}
              required={limits?.require_tp}
            />
          </div>
        </div>

        {limits ? (
          <p className="hint" style={{ margin: "0 0 10px", color: "var(--muted)" }}>
            Risk policy: max {limits.risk_per_trade_pct}% of balance per trade
            {sl ? "" : " — set a stop loss to size it"}.
          </p>
        ) : null}

        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            margin: "4px 0 12px",
            fontSize: 12,
            color: "var(--muted)",
          }}
        >
          <input
            type="checkbox"
            checked={validateOnly}
            onChange={(event) => setValidateOnly(event.target.checked)}
            disabled={disabled}
          />
          Validate against MT5 without sending
        </label>

        <button
          type="submit"
          className={`btn ${validateOnly ? "primary" : side}`}
          style={{ width: "100%", padding: "11px 12px" }}
          disabled={cannotSubmit}
          title={blockedReason ?? undefined}
        >
          {submitting ? <Spinner /> : null} {submitting ? "Sending…" : submitLabel}
        </button>

        {blockedReason ? (
          <div className="notice warn" style={{ marginTop: 10 }}>
            <span>{blockedReason}</span>
          </div>
        ) : null}

        {!liveExecutionEnabled ? (
          <p className="hint" style={{ marginTop: 10, color: "var(--muted)" }}>
            Live execution is disabled on the server. Orders are checked against MT5 and the
            real result is shown, but nothing reaches the market.
          </p>
        ) : null}
      </form>

      {outcome ? <OutcomeNotice outcome={outcome} /> : null}
    </Panel>
  );
}

function OutcomeNotice({ outcome }: { outcome: Outcome }) {
  if (outcome.kind === "executed") {
    const { result } = outcome;
    return (
      <div className={result.success ? "notice ok" : "notice error"} style={{ marginTop: 12 }} role="status">
        <div>
          <strong>
            {result.success ? "Order executed on MT5" : "MT5 rejected the order"} · retcode{" "}
            {result.retcode}
          </strong>
          <span>{result.retcode_description}</span>
          <div className="result-detail">
            {result.order ? <span>order #{result.order}</span> : null}
            {result.deal ? <span>deal #{result.deal}</span> : null}
            {result.volume ? <span>volume {result.volume}</span> : null}
            {result.price ? <span>price {result.price}</span> : null}
            {result.risk?.risk_money != null ? (
              <span>
                risk: {result.risk.risk_money} ({result.risk.risk_pct}% of balance)
              </span>
            ) : null}
            {result.comment ? <span>comment: {result.comment}</span> : null}
          </div>
        </div>
      </div>
    );
  }

  if (outcome.kind === "validated") {
    const { result } = outcome;
    return (
      <div className="notice warn" style={{ marginTop: 12 }} role="status">
        <div>
          <strong>
            Not sent to the market{outcome.blocked ? " — live execution disabled" : ""}
          </strong>
          <span>{outcome.message}</span>
          <div className="result-detail">
            <span>
              MT5 check: retcode {result.retcode} — {result.retcode_description}
            </span>
            {result.comment ? <span>comment: {result.comment}</span> : null}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="notice error" style={{ marginTop: 12 }} role="alert">
      <div>
        <strong>{outcome.title}</strong>
        <span>{outcome.message}</span>
        {outcome.retcode ? (
          <div className="result-detail">
            <span>
              MT5 retcode {outcome.retcode}
              {outcome.retcodeText ? ` — ${outcome.retcodeText}` : ""}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
