import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { fmt } from "../lib/api";
import type {
  Analysis,
  Deal,
  PriceLevel,
  TradeSetup,
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

/* ------------------------------------------------- AI analyst display */

const BIAS_TONE = { BULLISH: "up", BEARISH: "down", NEUTRAL: "neutral" } as const;
const STRENGTH_TONE = { HIGH: "up", MEDIUM: "gold", LOW: "neutral" } as const;

function Section({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="an-sec">
      <h3 className="an-sec-title">
        <span className="an-sec-n">{n}</span>
        {title}
      </h3>
      <div className="an-sec-body">{children}</div>
    </section>
  );
}

function Row({ k, v, tone }: { k: string; v: ReactNode; tone?: string }) {
  return (
    <div className="an-row">
      <span className="k">{k}</span>
      <span className={`v num ${tone ?? ""}`}>{v}</span>
    </div>
  );
}

function groupTone(bias?: string) {
  return bias === "BULLISH" ? "up" : bias === "BEARISH" ? "down" : "neutral";
}

/** The setup card: what to do, where, and what kills the idea. */
function TradeSetupCard({ setup }: { setup: TradeSetup }) {
  const buy = setup.action === "BUY";
  const sell = setup.action === "SELL";
  const tone = buy ? "up" : sell ? "down" : "neutral";

  if (!buy && !sell) {
    return (
      <div className="setup-card neutral">
        <div className="setup-head">
          <Badge tone="neutral">SIGNAL: NO TRADE</Badge>
          <span className="dim" style={{ fontSize: 11 }}>
            Confidence {setup.confidence}%
          </span>
        </div>
        <p className="setup-reason">{setup.blocking_reason || setup.summary}</p>
        {setup.entry_low != null && setup.stop_loss != null && (
          <>
            <div className="setup-note">
              Not tradeable yet. These are the levels to watch — they become a
              setup only if the condition above is met.
            </div>
            <div className="setup-grid">
              <Row k="Watch zone" v={`${fmt.price(setup.entry_low)} – ${fmt.price(setup.entry_high)}`} />
              <Row k="Would trigger on" v={setup.trigger_text || "—"} />
              <Row k="Stop would sit" v={fmt.price(setup.stop_loss)} tone="down" />
              <Row k="R:R at TP1" v={setup.risk_reward != null ? `1 : ${setup.risk_reward}` : "—"} />
            </div>
          </>
        )}
      </div>
    );
  }

  return (
    <div className={`setup-card ${tone}`}>
      <div className="setup-head">
        <Badge tone={tone as "up" | "down"}>SIGNAL: {setup.action}</Badge>
        <Badge tone={setup.stage === "CONFIRMED_SETUP" ? "up" : setup.stage === "ENTRY_TRIGGER" ? "gold" : "neutral"}>
          {setup.stage.replace("_", " ")}
        </Badge>
        <span className="dim" style={{ fontSize: 11, marginLeft: "auto" }}>
          Confidence {setup.confidence}%
        </span>
      </div>

      <div className="setup-grid">
        <Row k="Entry zone" v={`${fmt.price(setup.entry_low)} – ${fmt.price(setup.entry_high)}`} tone="gold" />
        <Row k="Entry trigger" v={setup.trigger_text || fmt.price(setup.trigger)} />
        <Row k="Stop loss" v={fmt.price(setup.stop_loss)} tone="down" />
        <Row k="TP1" v={fmt.price(setup.take_profit_1)} tone="up" />
        <Row k="TP2" v={fmt.price(setup.take_profit_2)} tone="up" />
        <Row k="TP3" v={fmt.price(setup.take_profit_3)} tone="up" />
        <Row k="Risk / reward" v={setup.risk_reward != null ? `1 : ${setup.risk_reward}` : "—"} />
        <Row k="Next target" v={fmt.price(setup.next_target)} tone="gold" />
      </div>

      <div className="setup-note">
        <strong>Stop:</strong> {setup.stop_loss_reason}
      </div>
      <div className="setup-note warn">
        <strong>Invalidation:</strong> {setup.invalidation}
      </div>
      <div className="setup-note dim">
        A proposal only. The risk engine re-checks size, spread, daily loss and
        mode before anything is sent to the broker.
      </div>
    </div>
  );
}

function LevelList({ levels, tone }: { levels: PriceLevel[]; tone: "up" | "down" }) {
  if (!levels.length) return <div className="dim" style={{ fontSize: 12 }}>None detected.</div>;
  return (
    <ul className="lv-list">
      {levels.map((lv) => (
        <li key={`${tone}-${lv.price}`}>
          <span className={`num lv-price ${tone}`}>{fmt.price(lv.price)}</span>
          <Badge tone={(STRENGTH_TONE[lv.strength] ?? "neutral") as "up" | "gold" | "neutral"}>
            {lv.strength}
          </Badge>
          <span className="lv-reason dim">{lv.reason}</span>
        </li>
      ))}
    </ul>
  );
}

export function AnalysisPanel({ analysis }: { analysis: Analysis | null }) {
  if (!analysis) {
    return <Empty>Run an analysis to see the multi-timeframe breakdown.</Empty>;
  }

  const setup = analysis.setup;
  const market = analysis.market;
  const levels = analysis.levels;
  const vol = analysis.volume;
  const h = analysis.hierarchy;

  // No timeframe survived => the bridge gave us nothing usable. Say so
  // plainly rather than rendering an analysis of nothing.
  if (!analysis.timeframes.length && !setup) {
    return <Empty>Market data unavailable — no analysis can be produced.</Empty>;
  }

  const biasTone = BIAS_TONE[analysis.bias] ?? "neutral";
  const setupTf = analysis.timeframes.find((t) => t.timeframe === "M15")
    ?? analysis.timeframes.find((t) => t.timeframe === "M5")
    ?? analysis.timeframes[0];

  return (
    <div className="analyst">
      {/* ---------------- header ---------------- */}
      <header className="an-head">
        <div className="an-title">XAUUSD AI MARKET ANALYST</div>
        <div className="an-hero">
          <div>
            <div className="an-k">MARKET</div>
            <div className={`an-v ${biasTone}`}>
              {analysis.bias === "NEUTRAL" ? "RANGE" : analysis.bias}
            </div>
          </div>
          <div>
            <div className="an-k">CONFIDENCE</div>
            <div className="an-v num">{setup?.confidence ?? 0}%</div>
          </div>
          <div>
            <div className="an-k">SIGNAL</div>
            <div
              className={`an-v ${
                setup?.action === "BUY" ? "up" : setup?.action === "SELL" ? "down" : ""
              }`}
            >
              {setup ? setup.action.replace("_", " ") : "—"}
            </div>
          </div>
          <div>
            <div className="an-k">CURRENT PRICE</div>
            <div className="an-v num">{fmt.price(market?.price)}</div>
          </div>
          <div>
            <div className="an-k">NEXT TARGET</div>
            <div className="an-v num gold">{fmt.price(setup?.next_target)}</div>
          </div>
        </div>
        {analysis.headline && <p className="an-headline">{analysis.headline}</p>}
        {analysis.model && (
          <span className="faint" style={{ fontSize: 11 }}>
            {analysis.model}
            {analysis.generated_at ? ` · ${fmt.time(analysis.generated_at)}` : ""}
          </span>
        )}
      </header>

      {analysis.warnings.length > 0 && (
        <div className="banner warn" style={{ margin: "0 14px 12px" }}>
          <div>
            <strong>Warnings</strong>
            <ul className="reasons">
              {analysis.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* 1 ---------------- market structure ---------------- */}
      <Section n={1} title="Market structure">
        <p className="an-text">
          {analysis.structure?.description || setupTf?.structure_text || "—"}
        </p>
        <div className="an-chips">
          <Badge tone="neutral">{analysis.structure?.pattern ?? "UNCLEAR"}</Badge>
          {analysis.structure?.bos && <Badge tone="gold">BOS</Badge>}
          {analysis.structure?.choch && <Badge tone="down">CHOCH</Badge>}
          {market && <Badge tone="neutral">{market.regime}</Badge>}
        </div>
      </Section>

      {/* 2 ---------------- multi-timeframe trend ---------------- */}
      <Section n={2} title="Multi-timeframe trend">
        {h && (
          <div className="an-hier">
            <Row k="Major (D1/H4)" v={h.major.bias} tone={groupTone(h.major.bias)} />
            <Row k="Intermediate (H1/M30)" v={h.intermediate.bias} tone={groupTone(h.intermediate.bias)} />
            <Row k="Setup (M15/M5)" v={h.setup.bias} tone={groupTone(h.setup.bias)} />
            <Row k="Refinement (M1)" v={h.refinement.bias} tone={groupTone(h.refinement.bias)} />
          </div>
        )}
        <div className="tf-grid">
          {analysis.timeframes.map((tf) => (
            <div className="tf" key={tf.timeframe}>
              <div className="tf-head">
                <span className="tf-name">{tf.timeframe}</span>
                {tf.role && <span className="faint" style={{ fontSize: 10 }}>{tf.role}</span>}
                <Badge tone={tf.trend === "UP" ? "up" : tf.trend === "DOWN" ? "down" : "neutral"}>
                  {tf.trend}
                </Badge>
              </div>
              <div className="tf-row">
                <span className="k">Structure</span>
                <span className="v">{tf.structure || "—"}</span>
              </div>
              <div className="tf-row">
                <span className="k">RSI / ADX</span>
                <span className="v num">
                  {tf.rsi14 ?? "—"} / {tf.adx14 ?? "—"}
                </span>
              </div>
              <div className="tf-row">
                <span className="k">EMA 20/50/200</span>
                <span className="v num" style={{ fontSize: 11 }}>
                  {fmt.price(tf.ema20)} · {fmt.price(tf.ema50)} · {fmt.price(tf.ema200)}
                </span>
              </div>
              <div className="tf-row">
                <span className="k">Momentum</span>
                <span className="v">{tf.momentum ?? "—"}</span>
              </div>
              {(tf.bos || tf.choch || tf.breakout !== "NONE" || tf.pullback !== "NONE") && (
                <div className="an-chips" style={{ marginTop: 6 }}>
                  {tf.bos && <Badge tone="gold">BOS</Badge>}
                  {tf.choch && <Badge tone="down">CHOCH</Badge>}
                  {tf.breakout !== "NONE" && (
                    <Badge tone={tf.breakout_confirmed ? "up" : "neutral"}>
                      BREAKOUT {tf.breakout}
                      {tf.breakout_confirmed ? " ✓" : " ?"}
                    </Badge>
                  )}
                  {tf.pullback !== "NONE" && <Badge tone="gold">{tf.pullback} PULLBACK</Badge>}
                </div>
              )}
              {tf.notes && <p className="tf-note">{tf.notes}</p>}
            </div>
          ))}
        </div>
      </Section>

      {/* 3 ---------------- support & resistance ---------------- */}
      <Section n={3} title="Support &amp; resistance">
        <div className="an-two">
          <div>
            <div className="an-k">RESISTANCE</div>
            <LevelList levels={levels?.resistance ?? []} tone="down" />
          </div>
          <div>
            <div className="an-k">SUPPORT</div>
            <LevelList levels={levels?.support ?? []} tone="up" />
          </div>
        </div>
        {!!levels?.session?.length && (
          <div className="an-sess">
            {levels.session.map((l) => (
              <span key={l.label} className="an-sess-item">
                <b>{l.label}</b> <span className="num">{fmt.price(l.price)}</span>
              </span>
            ))}
          </div>
        )}
      </Section>

      {/* 4 ---------------- liquidity ---------------- */}
      <Section n={4} title="Liquidity">
        <p className="an-text dim">
          Potential liquidity zones inferred from equal highs/lows and session
          extremes. This is not order-flow data and does not show real orders.
        </p>
        <div className="an-two">
          <div>
            <div className="an-k">POTENTIAL LIQUIDITY ABOVE</div>
            {levels?.liquidity_above?.length ? (
              levels.liquidity_above.map((z, i) => (
                <div className="num an-zone" key={`a${i}`}>
                  {fmt.price(z.low)} – {fmt.price(z.high)}{" "}
                  <span className="dim">{z.label}</span>
                </div>
              ))
            ) : (
              <div className="dim" style={{ fontSize: 12 }}>None detected.</div>
            )}
          </div>
          <div>
            <div className="an-k">POTENTIAL LIQUIDITY BELOW</div>
            {levels?.liquidity_below?.length ? (
              levels.liquidity_below.map((z, i) => (
                <div className="num an-zone" key={`b${i}`}>
                  {fmt.price(z.low)} – {fmt.price(z.high)}{" "}
                  <span className="dim">{z.label}</span>
                </div>
              ))
            ) : (
              <div className="dim" style={{ fontSize: 12 }}>None detected.</div>
            )}
          </div>
        </div>
      </Section>

      {/* 5 ---------------- volume ---------------- */}
      <Section n={5} title="Volume">
        {vol ? (
          <>
            <div className="an-hier">
              <Row k="Current (tick volume)" v={vol.current} />
              <Row k="Recent average" v={vol.average} />
              <Row
                k="Relative"
                v={`${vol.relative}x`}
                tone={vol.relative >= 1.5 ? "up" : vol.relative <= 0.6 ? "down" : ""}
              />
              <Row k="Trend" v={vol.trend} />
            </div>
            <p className="an-text dim">
              MT5 reports <strong>tick volume</strong> for spot gold — the number of
              price changes, not contracts traded. Useful as an activity proxy, but
              it is not exchange or institutional volume.
            </p>
          </>
        ) : (
          <div className="dim" style={{ fontSize: 12 }}>No volume data.</div>
        )}
      </Section>

      {/* 6 ---------------- momentum ---------------- */}
      <Section n={6} title="Momentum">
        <div className="an-hier">
          <Row k="RSI (14)" v={setupTf?.rsi14 ?? "—"} />
          <Row k="MACD histogram" v={setupTf?.macd_hist ?? "—"} tone={(setupTf?.macd_hist ?? 0) >= 0 ? "up" : "down"} />
          <Row k="ADX (14)" v={setupTf?.adx14 ?? "—"} />
          <Row k="ATR (14)" v={setupTf?.atr14 ?? "—"} />
          <Row k="EMA alignment" v={
            setupTf && setupTf.ema20 != null && setupTf.ema50 != null && setupTf.ema200 != null
              ? setupTf.ema20 > setupTf.ema50 && setupTf.ema50 > setupTf.ema200
                ? "20 > 50 > 200 — bullish"
                : setupTf.ema20 < setupTf.ema50 && setupTf.ema50 < setupTf.ema200
                  ? "20 < 50 < 200 — bearish"
                  : "mixed"
              : "—"
          } />
        </div>
        <p className="an-text dim">
          Indicators are evidence, not signals. None of these alone decides the trade.
        </p>
      </Section>

      {/* 7 ---------------- breakout / pullback ---------------- */}
      <Section n={7} title="Breakout / pullback">
        {setupTf && (setupTf.breakout !== "NONE" || setupTf.pullback !== "NONE") ? (
          <div className="an-hier">
            {setupTf.breakout !== "NONE" && (
              <>
                <Row k="Breakout" v={`${setupTf.breakout} ${setupTf.breakout_confirmed ? "— CONFIRMED" : "— unconfirmed"}`}
                     tone={setupTf.breakout_confirmed ? "up" : ""} />
                <Row k="Confirmation" v={
                  setupTf.breakout_confirmed
                    ? "close beyond the level, with volume and momentum agreeing"
                    : "close beyond the level, but volume/momentum have not confirmed"
                } />
              </>
            )}
            {setupTf.pullback !== "NONE" && (
              <Row k="Pullback" v={`${setupTf.pullback} pullback into the fast EMA`} tone="gold" />
            )}
          </div>
        ) : (
          <div className="dim" style={{ fontSize: 12 }}>
            No breakout or pullback detected on {setupTf?.timeframe ?? "the setup timeframe"}.
          </div>
        )}
      </Section>

      {/* 8 ---------------- trade setup ---------------- */}
      <Section n={8} title="Trade setup">
        {setup ? <TradeSetupCard setup={setup} /> : <div className="dim">No setup.</div>}
      </Section>

      {/* 9 ---------------- risk / reward ---------------- */}
      <Section n={9} title="Risk / reward">
        {setup?.targets?.length ? (
          <table className="an-table">
            <thead>
              <tr><th>Target</th><th>Price</th><th>R:R</th><th>Why</th></tr>
            </thead>
            <tbody>
              {setup.targets.map((t, i) => (
                <tr key={t.price}>
                  <td>TP{i + 1}</td>
                  <td className="num up">{fmt.price(t.price)}</td>
                  <td className="num">1 : {t.risk_reward}</td>
                  <td className="dim">{t.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="dim" style={{ fontSize: 12 }}>No targets — no active setup.</div>
        )}
        {setup && Object.keys(setup.confidence_components).length > 0 && (
          <>
            <div className="an-k" style={{ marginTop: 12 }}>
              CONFIDENCE {setup.confidence}/100 — COMPONENTS
            </div>
            <div className="an-conf">
              {Object.entries(setup.confidence_components).map(([name, value]) => (
                <div className="an-conf-row" key={name}>
                  <span className="k">{name.replace(/_/g, " ")}</span>
                  <span className="num">+{value}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </Section>

      {/* 10 ---------------- invalidation ---------------- */}
      <Section n={10} title="Invalidation">
        <p className="an-text">
          {setup?.invalidation || "No active setup, so nothing to invalidate."}
        </p>
      </Section>

      {/* 11 ---------------- next targets ---------------- */}
      <Section n={11} title="Next targets">
        {setup?.next_target != null ? (
          <>
            <Row k="Next target" v={fmt.price(setup.next_target)} tone="gold" />
            <p className="an-text dim">{setup.next_target_reason}</p>
            {setup.take_profit_2 != null && (
              <Row k="Secondary" v={fmt.price(setup.take_profit_2)} />
            )}
          </>
        ) : (
          <div className="dim" style={{ fontSize: 12 }}>No target while there is no setup.</div>
        )}
      </Section>

      {/* 12 ---------------- reasoning ---------------- */}
      <Section n={12} title="Analyst reasoning">
        <p className="an-text">{analysis.summary}</p>
        {!!analysis.reasons?.length && (
          <ul className="reasons">
            {analysis.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

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
