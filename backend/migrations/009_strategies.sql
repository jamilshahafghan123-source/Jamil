-- 009: customer strategies
--
-- New table only. No existing table is altered and no row is touched, so
-- this is safe to apply to a live database at any time.
--
-- The `rule` column holds a validated condition tree as JSON. It is DATA,
-- never code: the application re-parses it through services.strategy on
-- every read, so a row edited directly here still cannot introduce
-- anything outside the closed vocabulary the parser accepts.
--
-- action_mode has no REAL_AUTO value on purpose. Real broker automation
-- is disabled platform-wide, and a value the column cannot hold is a
-- value no row can carry.
--
-- Idempotent: safe to run repeatedly.

CREATE TABLE IF NOT EXISTS strategies (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    name         VARCHAR(80) NOT NULL,
    symbol       VARCHAR(24) NOT NULL,
    timeframe    VARCHAR(8)  NOT NULL DEFAULT 'M15',
    direction    VARCHAR(8)  NOT NULL,
    action_mode  VARCHAR(16) NOT NULL DEFAULT 'ALERT_ONLY',
    rule         JSON        NOT NULL DEFAULT '{}',
    notes        TEXT        NOT NULL DEFAULT '',
    enabled      BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every query filters by owner, so the index matches how the table is read.
CREATE INDEX IF NOT EXISTS ix_strategies_user_id ON strategies (user_id);
CREATE INDEX IF NOT EXISTS ix_strategies_symbol  ON strategies (symbol);

-- Rollback:
--   DROP TABLE IF EXISTS strategies;
