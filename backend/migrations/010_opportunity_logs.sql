-- 010: opportunity telemetry
--
-- New table only. No existing table is altered and no row is touched.
--
-- The three outcome columns are separate on purpose (sections 40, 49):
-- ai_decision, risk_decision and execution_result answer different
-- questions. A single "status" column would make a quiet trading day
-- impossible to explain, because "no trades" could equally mean the
-- engine found nothing, the risk manager refused everything, or execution
-- kept failing — and those call for completely different responses.
--
-- Idempotent: safe to run repeatedly.

CREATE TABLE IF NOT EXISTS opportunity_logs (
    id                   SERIAL PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES users(id),
    detected_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol               VARCHAR(24) NOT NULL,
    session              VARCHAR(16) NOT NULL DEFAULT '',
    setup_class          VARCHAR(16) NOT NULL DEFAULT 'STANDARD',
    grade                VARCHAR(16) NOT NULL DEFAULT 'POOR',
    score                INTEGER     NOT NULL DEFAULT 0,
    direction            VARCHAR(8)  NOT NULL DEFAULT '',
    confidence           INTEGER     NOT NULL DEFAULT 0,
    expected_rr          DOUBLE PRECISION NOT NULL DEFAULT 0,
    required_confidence  INTEGER     NOT NULL DEFAULT 0,
    required_rr          DOUBLE PRECISION NOT NULL DEFAULT 0,
    ai_decision          VARCHAR(16) NOT NULL DEFAULT 'NO_TRADE',
    risk_decision        VARCHAR(16),
    risk_reason          TEXT,
    execution_result     VARCHAR(16),
    rejection_reason     TEXT,
    outcome_pnl          DOUBLE PRECISION,
    score_breakdown      JSON        NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS ix_opportunity_logs_user_id
    ON opportunity_logs (user_id);
CREATE INDEX IF NOT EXISTS ix_opportunity_logs_detected_at
    ON opportunity_logs (detected_at);
CREATE INDEX IF NOT EXISTS ix_opportunity_logs_symbol
    ON opportunity_logs (symbol);

-- Rollback:
--   DROP TABLE IF EXISTS opportunity_logs;
