export type TradingMode = "MANUAL" | "DEMO" | "REAL";
export type SignalAction = "BUY" | "SELL" | "NO_TRADE";
export type Trend = "UP" | "DOWN" | "RANGE";

export interface AccountInfo {
  login: number;
  server: string;
  currency: string;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  margin_level: number | null;
  leverage: number;
  trade_mode: string; // "demo" | "contest" | "real"
  company: string;
}

export interface Tick {
  symbol: string;
  bid: number;
  ask: number;
  spread_points: number;
  time: string;
}

/** Timeframes the MT5 bridge understands. */
export type Timeframe =
  | "M1" | "M2" | "M3" | "M5" | "M10" | "M15" | "M30" | "M45"
  | "H1" | "H2" | "H3" | "H4" | "D1";

/** One OHLC candle, exactly as GET /api/analysis/bars returns it. */
export interface Bar {
  /** ISO-8601 UTC timestamp of the candle open, e.g. "2026-08-19T03:00:00+00:00". */
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  tick_volume: number;
  spread: number;
}

export interface BarsResponse {
  symbol: string;
  timeframe: Timeframe;
  bars: Bar[];
}

export interface Position {
  ticket: number;
  symbol: string;
  type: "BUY" | "SELL";
  volume: number;
  price_open: number;
  sl: number;
  tp: number;
  price_current: number;
  profit: number;
  swap: number;
  time: string;
  comment: string;
}

export interface Deal {
  ticket: number;
  order: number;
  position_id: number;
  entry: number;
  symbol: string;
  type: string;
  volume: number;
  price: number;
  profit: number;
  commission: number;
  swap: number;
  time: string;
  comment: string;
}

/**
 * The dashboard's own status block, from GET /api/dashboard.
 *
 * A DIFFERENT SHAPE from the derived bot state below, and named
 * differently for that reason. Both were called BotStatus, and because
 * TypeScript merges same-named interfaces the two silently became one
 * type carrying every field of both — so reading `pnl_today` off the
 * derived state, or `state` off this one, type-checked and then came back
 * undefined at runtime.
 */
export interface DashboardBotStatus {
  bot_enabled: boolean;
  emergency_stop: boolean;
  trading_mode: TradingMode;
  real_trading_allowed_by_server: boolean;
  bridge_connected: boolean;
  halted_today: boolean;
  trades_today: number;
  pnl_today: number;
  last_signal_at: string | null;
}

export interface DashboardSnapshot {
  account: AccountInfo | null;
  tick: Tick | null;
  positions: Position[];
  status: DashboardBotStatus;
}

export interface Signal {
  id: number;
  created_at: string;
  symbol: string;
  action: SignalAction;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_reward: number | null;
  confidence: number;
  reason: string;
  risk_approved: boolean | null;
  risk_reasons: string[] | null;
  executed: boolean;
}

export interface LevelZone {
  low: number;
  high: number;
  label: string;
}

export interface TimeframeView {
  timeframe: string;
  trend: Trend;
  structure: string;
  support: number[];
  resistance: number[];
  breakout: string;
  pullback: string;
  liquidity: LevelZone[];
  notes: string;
  // --- added by the upgraded analyst -------------------------------
  role?: string; // MAJOR | INTERMEDIATE | SETUP | REFINEMENT
  structure_text?: string;
  regime?: Regime;
  momentum?: Momentum;
  rsi14?: number;
  adx14?: number;
  atr14?: number;
  ema20?: number;
  ema50?: number;
  ema200?: number;
  macd_hist?: number;
  bos?: boolean;
  choch?: boolean;
  breakout_confirmed?: boolean;
  support_levels?: PriceLevel[];
  resistance_levels?: PriceLevel[];
  volume?: VolumeView;
  /** Structural zones measured on this timeframe specifically. */
  fvg?: AIZoneView[];
  order_blocks?: AIZoneView[];
  swings?: AISwingView[];
}

export type SetupStage = "WATCH" | "ENTRY_TRIGGER" | "CONFIRMED_SETUP";
export type Regime = "TRENDING" | "RANGING" | "EXPANSION" | "CONSOLIDATION" | "UNKNOWN";
export type Momentum = "RISING" | "FALLING" | "NEUTRAL";
export type LevelStrength = "HIGH" | "MEDIUM" | "LOW";

/** A ranked support/resistance level with the evidence behind it. */
export interface PriceLevel {
  price: number;
  strength: LevelStrength;
  touches: number;
  reason: string;
  distance: number;
}

export interface SessionLevel {
  label: string; // PDH | PDL | PWH | PWL
  price: number;
  reason: string;
}

/** Tick volume — a count of price changes, never traded contracts. */
export interface VolumeView {
  type: "TICK_VOLUME";
  current: number;
  average: number;
  relative: number;
  trend: "EXPANDING" | "CONTRACTING" | "STEADY" | "UNKNOWN";
  state: "HIGH" | "NORMAL" | "LOW" | "UNKNOWN";
}

export interface StructureView {
  pattern: string;
  bos: boolean;
  choch: boolean;
  description: string;
}

export interface TargetView {
  price: number;
  reason: string;
  risk_reward: number;
}

/** The deterministic setup. Every number here is computed, not model output. */
export interface TradeSetup {
  action: SignalAction;
  stage: SetupStage;
  confidence: number;
  confidence_components: Record<string, number>;
  entry_low: number | null;
  entry_high: number | null;
  trigger: number | null;
  trigger_text: string;
  stop_loss: number | null;
  stop_loss_reason: string;
  take_profit_1: number | null;
  take_profit_2: number | null;
  take_profit_3: number | null;
  targets: TargetView[];
  risk_reward: number | null;
  invalidation: string;
  next_target: number | null;
  next_target_reason: string;
  summary: string;
  reasons: string[];
  warnings: string[];
  blocking_reason: string | null;
}

export interface GroupBias {
  bias: "BULLISH" | "BEARISH" | "RANGE" | "UNKNOWN";
  timeframes: string[];
  agree: boolean;
}

export interface Hierarchy {
  major: GroupBias;
  intermediate: GroupBias;
  setup: GroupBias;
  refinement: GroupBias;
  higher_aligned: boolean;
}

export interface Analysis {
  symbol?: string;
  generated_at?: string;
  model?: string;
  bias: "BULLISH" | "BEARISH" | "NEUTRAL";
  headline?: string;
  summary: string;
  timeframes: TimeframeView[];
  entry_zones: LevelZone[];
  warnings: string[];
  // --- added by the upgraded analyst -------------------------------
  market?: {
    price: number;
    bid: number;
    ask: number;
    spread_points: number;
    trend: string;
    regime: Regime;
    momentum: Momentum;
    volatility: number;
    confluence_score: number;
  };
  hierarchy?: Hierarchy;
  structure?: StructureView;
  levels?: {
    support: PriceLevel[];
    resistance: PriceLevel[];
    session: SessionLevel[];
    liquidity_above: LevelZone[];
    liquidity_below: LevelZone[];
  };
  volume?: VolumeView;
  setup?: TradeSetup;
  reasons?: string[];
  /**
   * Structural zones the deterministic engine measured on the setup
   * timeframe. Optional because an older cached analysis will not carry
   * them, and empty because the engine genuinely found nothing — never
   * because the chart should invent something to fill the space.
   */
  zones?: {
    fvg: AIZoneView[];
    order_blocks: AIZoneView[];
    liquidity: AIZoneView[];
  };
  swings?: AISwingView[];
}

/** One measured structural zone: an imbalance, an order block, a pool. */
export interface AIZoneView {
  kind: "fvg" | "order_block" | "liquidity";
  side?: "bullish" | "bearish" | "demand" | "supply";
  low: number;
  high: number;
  /** Bar the zone starts at. Absent on liquidity bands. */
  from_time?: string;
  label: string;
}

export interface AISwingView {
  side: "high" | "low";
  price: number;
  time: string;
}

export interface RiskSettings {
  max_risk_per_trade_pct: number;
  max_daily_loss_pct: number;
  max_trades_per_day: number;
  max_open_positions: number;
  max_lot_size: number;
  min_confidence: number;
  min_rr: number;
  max_spread_points: number;
  trading_mode: TradingMode;
  bot_enabled: boolean;
  bot_paused: boolean;
  emergency_stop: boolean;
  halted_until_date: string | null;
}

export interface OrderLog {
  id: number;
  created_at: string;
  mode: TradingMode;
  symbol: string;
  action: SignalAction;
  volume: number;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  status: "REQUESTED" | "FILLED" | "REJECTED" | "ERROR";
  broker_ticket: number | null;
  broker_retcode: number | null;
  broker_comment: string | null;
}

export interface ExecutionResult {
  executed: boolean;
  reasons: string[];
  order_log_id: number | null;
  ticket: number | null;
  volume: number;
}

export interface LiveMessage {
  type: string;
  tick?: Tick;
  positions?: Position[];
  account?: AccountInfo;
  bridge_connected: boolean;
  bot_enabled?: boolean;
  emergency_stop?: boolean;
  trading_mode?: TradingMode;
  error?: string;
}

/* ---------------------------------------------------------------- admin
 * Shapes for the ADMIN control centre. Note what is absent: no token, no
 * URL, no DSN. The backend never sends them, and these types make that
 * visible — a field appearing here would be a review flag.
 */

export type ComponentStatus =
  | "UP"
  | "DEGRADED"
  | "DOWN"
  | "UNKNOWN"
  | "NOT_CONFIGURED";

export interface ComponentHealth {
  component: string;
  status: ComponentStatus;
  detail: string;
  checked_at: string | null;
}

export interface ControlCentre {
  generated_at: string;
  system_health: {
    overall: ComponentStatus;
    components: ComponentHealth[];
    fault_count: number;
  };
  safe_mode: {
    active: boolean;
    reasons: string[];
    banner: string | null;
    customer_messages: string[];
  };
  customers: {
    total: number;
    admins: number;
    customers: number;
    active: number;
  };
  trading: {
    bots_enabled: number;
    accounts_emergency_stopped: number;
    real_trading_allowed_by_server: boolean;
  };
  incidents: {
    open: number;
    recovering: number;
    needs_admin: number;
    recovered: number;
    failed_recoveries: number;
  };
  support: {
    open: number;
    ai_handling: number;
    needs_admin: number;
    resolved: number;
    urgent: number;
  };
  /** Why the bot is waiting, in numbers the operator can check. */
  bot: {
    signal: {
      action: string;
      confidence: number;
      required_confidence: number | null;
      rr: number | null;
      required_rr: number | null;
      reason: string;
      risk_approved: boolean | null;
      risk_reasons: string[];
      executed: boolean;
      created_at: string | null;
    } | null;
    last_execution_error: {
      status: string;
      action: string;
      symbol: string;
      created_at: string | null;
    } | null;
  };
  recovery: Record<
    string,
    {
      state: string;
      last_incident: {
        id: number;
        status: string;
        category: string;
        detected_at: string | null;
        recovered_at: string | null;
        final_state: string;
      } | null;
    }
  >;
}

export interface AdminTicket {
  id: number;
  category: string;
  subject: string;
  description: string;
  ai_summary: string;
  safe_diagnostics: Record<string, unknown>;
  priority: string;
  status: string;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface RecoveryService {
  state: string;
  attempts_in_window: number;
  has_automatic_repair: boolean;
  policy: string;
}

export interface AdminIncident {
  id: number;
  service: string;
  category: string;
  status: string;
  detected_at: string | null;
  recovered_at: string | null;
  attempt_number: number;
  actions: { operation: string; ok: boolean; detail: string }[];
  final_state: string;
  detail: string;
}

export interface RecoveryStatus {
  agent: { configured: boolean; status: string };
  services: Record<string, RecoveryService>;
  /** The complete allow-list, straight from the backend enum. */
  permitted_operations: string[];
  incidents: AdminIncident[];
  notifications: unknown[];
}

export type Severity = "INFO" | "WARNING" | "HIGH" | "CRITICAL";

export interface AdminNotification {
  id: number;
  severity: Severity;
  event: string;
  message: string;
  created_at: string | null;
  read: boolean;
  incident_id: number | null;
  delivered_channels: string[];
}

export interface NotificationFeed {
  unread: number;
  /** IN_APP is the only real channel today; the rest report NOT_CONFIGURED. */
  channels: Record<string, string>;
  notifications: AdminNotification[];
}

/* ------------------------------------------------------- admin security
 * Note what these types cannot carry: there is no field for a secret
 * value anywhere. The backend sends SET / MISSING and nothing else, and
 * a value-shaped field appearing here would be a review flag.
 */

export interface AdminBackup {
  id: number;
  filename: string;
  status: "CREATED" | "FAILED" | "VERIFIED" | "RESTORE_TESTED";
  size_bytes: number;
  created_at: string;
  verified_at: string | null;
  detail: string;
  app_version: string;
  has_checksum: boolean;
  database_name: string;
}

export interface ChecklistItem {
  key: string;
  title: string;
  state: "PASS" | "FAIL" | "MANUAL";
  detail: string;
}

export interface SecurityOverview {
  /** Presence only — SET or MISSING, never a value. */
  secrets: Record<string, "SET" | "MISSING">;
  version: {
    version: string;
    commit: string;
    last_known_good: string;
    environment: string;
  };
  deployment_readiness: {
    status: "READY" | "NOT_READY";
    blocking: string[];
    warnings: string[];
  };
  recent_failed_logins: number;
  admin_accounts: number;
  restore_enabled_on_host: boolean;
  maintenance: {
    active: boolean;
    reason: string;
    since: string | null;
    detail: string;
  };
  mfa: { provider: string; status: string; detail: string };
  latest_backup: AdminBackup | null;
  launch_checklist: {
    ready: boolean;
    failed: number;
    manual_outstanding: number;
    items: ChecklistItem[];
    note: string;
  };
}

/* ------------------------------------------------- J Gold AI demo account
 * VIRTUAL money. Not broker funds, not subscription money. The backend
 * states that in the payload itself so no surface can forget to say it.
 */

export interface DemoAccountState {
  balance: number;
  equity: number;
  floating_pnl: number;
  realized_pnl: number;
  free_margin: number;
  open_positions: number;
  currency: string;
  account_type: "J_GOLD_AI_DEMO";
  virtual_money: boolean;
  withdrawable: boolean;
}

export type TradeSource = "MANUAL" | "AI_ASSIST" | "AI_AUTO";

export interface DemoPosition {
  id: number;
  symbol: string;
  side: "BUY" | "SELL";
  volume: number;
  entry_price: number;
  /** The price this position would close at: the other side of the spread. */
  current_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  source: TradeSource;
  signal_confidence: number | null;
  signal_rr: number | null;
  opened_at: string | null;
  floating_pnl: number | null;
  /**
   * The opportunity this position came from, and its figures.
   *
   * All null for a position the customer opened by hand: there was no
   * opportunity behind it, so there is no setup class to report. The
   * table shows an em dash rather than a plausible-looking guess.
   */
  opportunity_id: number | null;
  setup_class: string | null;
  grade: string | null;
  opportunity_score: number | null;
  session: string | null;
  /** Null until a strategy can execute. No strategy opens positions yet. */
  strategy: string | null;
}

export interface DemoAccountResponse {
  account: DemoAccountState;
  starting_balance: number;
  positions: DemoPosition[];
  market_price: { bid: number; ask: number } | null;
  can_open: boolean;
  blocked_reason: string | null;
}

export interface DemoTrade {
  id: number;
  symbol: string;
  side: "BUY" | "SELL";
  volume: number;
  entry_price: number;
  exit_price: number;
  realized_pnl: number;
  source: TradeSource;
  close_reason: string;
  signal_confidence: number | null;
  signal_rr: number | null;
  opened_at: string | null;
  closed_at: string | null;
  account_type: string;
}

export interface InstrumentInfo {
  symbol: string;
  display_name: string;
  asset_class: string;
  status: "ENABLED" | "DATA_ONLY" | "COMING_SOON" | "UNSUPPORTED" | "DISABLED";
  tradable: boolean;
  /** Whether a real feed exists. Nothing else may ever show a price. */
  priceable: boolean;
  always_open: boolean;
  base_currency: string;
  aliases: string[];
  digits: number;
  contract_size: number;
  tick_size: number;
  tick_value: number;
  min_volume: number;
  max_volume: number;
  volume_step: number;
  quote_currency: string;
}


/**
 * A persisted customer drawing. `payload` carries price/time geometry that
 * the backend stores without interpreting — a new tool is a frontend
 * change, not a migration.
 */
export interface ApiDrawing {
  id: number;
  symbol: string;
  timeframe: string;
  kind: string;
  payload: { points?: { time: string; price: number }[]; text?: string };
  locked: boolean;
  hidden: boolean;
  created_at: string;
  updated_at: string;
}

/** J Gold AI Session Map (section 8). Measured from bars, never assumed. */
export interface SessionRange {
  session: "SYDNEY" | "TOKYO" | "LONDON" | "NEW_YORK";
  display_name: string;
  colour: string;
  date: string;
  start: string;
  end: string;
  /** False while the session is still running. */
  complete: boolean;
  high: number;
  low: number;
  open: number | null;
}

/** PDH/PDL, PWH/PWL and previous month extremes (section 10). */
export interface PreviousLevel {
  period: "DAY" | "WEEK" | "MONTH";
  start: string;
  end: string;
  high: number;
  high_label: string;
  low: number;
  low_label: string;
}

export interface SessionDefinition {
  session: string;
  display_name: string;
  timezone: string;
  colour: string;
  opens_local: string;
  closes_local: string;
}

export interface SessionMap {
  symbol: string;
  timeframe: string;
  sessions: SessionRange[];
  previous_levels: PreviousLevel[];
  active: { session: string; display_name: string; colour: string }[];
  definitions: SessionDefinition[];
}

/** Broker connection centre (sections 40-44). Never carries a credential. */
export interface BrokerInfo {
  key: string;
  display_name: string;
  category: string;
  status: "CONNECTED" | "AVAILABLE" | "COMING_SOON" | "UNSUPPORTED";
  auth_method: string;
  connectable: boolean;
  capabilities: string[];
  note: string;
}

export interface BrokerDirectory {
  by_category: Record<string, BrokerInfo[]>;
  connectable: string[];
  funded_accounts: { supported: boolean; status: string; detail: string };
  disclaimer: string;
}

/** Strategy builder (sections 32-37). Rules are DATA, never code. */
export interface StrategyVocabulary {
  fields: { field: string; boolean: boolean; zone: boolean; labels: string[] }[];
  operators: string[];
  logic: string[];
  action_modes: string[];
  timeframes: string[];
  limits: { max_conditions: number; max_depth: number; max_strategies: number };
  note: string;
}

export interface StrategyCondition {
  field: string;
  operator: string;
  value: string | number | null;
  value_is_field?: boolean;
  period: number | null;
  timeframe: string;
}

export interface StrategyGroup {
  logic: string;
  children: (StrategyGroup | StrategyCondition)[];
}

export type StrategyRule = StrategyGroup | StrategyCondition;

export interface SavedStrategy {
  id: number;
  name: string;
  symbol: string;
  timeframe: string;
  direction: "BUY" | "SELL";
  action_mode: string;
  rule: StrategyRule | Record<string, never>;
  description: string[];
  /** False when a stored rule no longer parses; it is not rendered as runnable. */
  valid: boolean;
  notes: string;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/** Opportunity telemetry (section 49). Three outcomes, kept apart. */
export interface OpportunityRow {
  id: number;
  detected_at: string | null;
  symbol: string;
  session: string;
  setup_class: string;
  grade: string;
  score: number;
  direction: string;
  confidence: number;
  expected_rr: number;
  required_confidence: number;
  required_rr: number;
  ai_decision: string;
  risk_decision: string | null;
  risk_reason: string | null;
  execution_result: string | null;
  rejection_reason: string | null;
  outcome_pnl: number | null;
  score_breakdown: Record<string, number>;
}

export interface OpportunitySummary {
  detected: number;
  ai_proposed: number;
  ai_no_trade: number;
  risk_rejected: number;
  executed: number;
  settled: number;
  wins: number;
  losses: number;
  by_setup_class: Record<string, number>;
  by_session: Record<string, number>;
  by_grade: Record<string, number>;
  top_rejection_reasons: { reason: string; count: number }[];
  /** Null until enough trades have settled for a rate to mean anything. */
  win_rate: number | null;
  net_pnl: number | null;
  rate_note?: string;
}

export interface OpportunityFeed {
  days: number;
  summary: OpportunitySummary;
  opportunities: OpportunityRow[];
  note?: string;
  customers?: number;
}

/** Alerts (section 62). In-app delivery only — no channel to choose. */
export interface AlertKindInfo {
  kind: string;
  label: string;
  needs_threshold: boolean;
  needs_session: boolean;
}

export interface AlertKinds {
  kinds: AlertKindInfo[];
  delivery: string;
  delivery_note: string;
}

export interface CustomerAlert {
  id: number;
  kind: string;
  label: string;
  symbol: string;
  threshold: number | null;
  session: string | null;
  note: string;
  enabled: boolean;
  repeatable: boolean;
  triggered_at: string | null;
  trigger_count: number;
  last_message: string;
  acknowledged: boolean;
  created_at: string | null;
}

export interface AlertFeed {
  alerts: CustomerAlert[];
  unacknowledged: number;
}

/** Bot state, derived from real observations (section 17). */
export interface BotStatus {
  state: string;
  label: string;
  detail: string;
  blocked: boolean;
  active: boolean;
  bot_enabled: boolean;
  /** A hold, not a stop: enabled, managing what is open, opening nothing. */
  bot_paused: boolean;
  trading_mode: TradingMode;
  venue: string;
  open_positions: number;
}

/**
 * Today's trading, counted from trades that actually closed.
 *
 * The day boundary comes back with the figures because "today" on a
 * 24-hour market is not self-evident, and a P/L whose window the reader
 * has to guess at is not a P/L.
 */
export interface DemoPerformance {
  day_start: string;
  day_basis: string;
  today: {
    net_pnl: number;
    trades: number;
    wins: number;
    losses: number;
    breakeven: number;
    /** Null until there is something to take a rate of. */
    win_rate: number | null;
  };
  open_positions: number;
  currency: string;
}
