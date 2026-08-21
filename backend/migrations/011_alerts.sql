-- 011: customer alerts
--
-- New table only. No existing table is altered and no row is touched.
--
-- There is no delivery-channel column. Alerts are in-app only, because no
-- email, SMS or push provider is connected — and a schema that could
-- record "send by SMS" would invite code that pretends to.
--
-- Idempotent: safe to run repeatedly.

CREATE TABLE IF NOT EXISTS alerts (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    kind          VARCHAR(32) NOT NULL,
    symbol        VARCHAR(24) NOT NULL,
    threshold     DOUBLE PRECISION,
    session       VARCHAR(16),
    note          VARCHAR(200) NOT NULL DEFAULT '',
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    repeatable    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    triggered_at  TIMESTAMPTZ,
    trigger_count INTEGER NOT NULL DEFAULT 0,
    last_message  TEXT NOT NULL DEFAULT '',
    acknowledged  BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS ix_alerts_user_id ON alerts (user_id);
CREATE INDEX IF NOT EXISTS ix_alerts_symbol  ON alerts (symbol);

-- Rollback:
--   DROP TABLE IF EXISTS alerts;
