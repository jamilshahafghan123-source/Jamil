-- 007: customer chart drawings
--
-- Additive only. One new table; no existing column touched.
--
-- These rows are a CUSTOMER'S OWN annotations. AI overlays are derived from
-- analysis, are never persisted, and never touch this table — so clearing
-- AI overlays cannot delete a customer's work.

CREATE TABLE IF NOT EXISTS chart_drawings (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users (id),
    symbol     VARCHAR(24) NOT NULL,
    timeframe  VARCHAR(8) NOT NULL,
    kind       VARCHAR(24) NOT NULL,
    payload    JSON NOT NULL DEFAULT '{}',
    locked     BOOLEAN NOT NULL DEFAULT FALSE,
    hidden     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_chart_drawings_user   ON chart_drawings (user_id);
CREATE INDEX IF NOT EXISTS ix_chart_drawings_symbol ON chart_drawings (symbol);
CREATE INDEX IF NOT EXISTS ix_chart_drawings_tf     ON chart_drawings (timeframe);

-- Rollback:
--   DROP TABLE IF EXISTS chart_drawings;
