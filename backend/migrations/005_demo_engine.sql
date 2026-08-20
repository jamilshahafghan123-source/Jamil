-- 005: J Gold AI internal demo trading
--
-- Additive only. Three new tables; no existing column touched.
--
-- NOTE: these hold VIRTUAL money. Nothing in demo_accounts is broker funds
-- or subscription money, and no balance here is withdrawable — it exists
-- only as a row.

CREATE TABLE IF NOT EXISTS demo_accounts (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER NOT NULL UNIQUE REFERENCES users (id),
    starting_balance  DOUBLE PRECISION NOT NULL DEFAULT 100000,
    balance           DOUBLE PRECISION NOT NULL DEFAULT 100000,
    currency          VARCHAR(8) NOT NULL DEFAULT 'USD',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reset_at          TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS demo_positions (
    id                SERIAL PRIMARY KEY,
    account_id        INTEGER NOT NULL REFERENCES demo_accounts (id),
    symbol            VARCHAR(24) NOT NULL,
    side              VARCHAR(8) NOT NULL,
    volume            DOUBLE PRECISION NOT NULL,
    entry_price       DOUBLE PRECISION NOT NULL,
    stop_loss         DOUBLE PRECISION,
    take_profit       DOUBLE PRECISION,
    source            VARCHAR(16) NOT NULL DEFAULT 'MANUAL',
    signal_confidence INTEGER,
    signal_rr         DOUBLE PRECISION,
    opened_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_demo_positions_account ON demo_positions (account_id);
CREATE INDEX IF NOT EXISTS ix_demo_positions_symbol  ON demo_positions (symbol);

CREATE TABLE IF NOT EXISTS demo_trades (
    id                SERIAL PRIMARY KEY,
    account_id        INTEGER NOT NULL REFERENCES demo_accounts (id),
    symbol            VARCHAR(24) NOT NULL,
    side              VARCHAR(8) NOT NULL,
    volume            DOUBLE PRECISION NOT NULL,
    entry_price       DOUBLE PRECISION NOT NULL,
    exit_price        DOUBLE PRECISION NOT NULL,
    realized_pnl      DOUBLE PRECISION NOT NULL DEFAULT 0,
    source            VARCHAR(16) NOT NULL DEFAULT 'MANUAL',
    close_reason      VARCHAR(32) NOT NULL DEFAULT 'MANUAL_CLOSE',
    signal_confidence INTEGER,
    signal_rr         DOUBLE PRECISION,
    opened_at         TIMESTAMPTZ NOT NULL,
    closed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_demo_trades_account   ON demo_trades (account_id);
CREATE INDEX IF NOT EXISTS ix_demo_trades_closed_at ON demo_trades (closed_at);

-- Rollback:
--   DROP TABLE IF EXISTS demo_trades;
--   DROP TABLE IF EXISTS demo_positions;
--   DROP TABLE IF EXISTS demo_accounts;
