-- Read-only schema check. Run this against a database to see which
-- migrations have actually been applied to it.
--
--     psql "$DATABASE_URL" -f migrations/verify_schema.sql
--
-- It SELECTs and nothing else: no ALTER, no INSERT, no DELETE. Safe to
-- run against production, and safe to run repeatedly.
--
-- Every row reports PRESENT or MISSING. A MISSING row names the file to
-- run; the files are additive and idempotent, so running one that has
-- already been applied is a no-op rather than an error.

\pset border 2

SELECT
    expected.migration,
    expected.change,
    CASE WHEN found.ok THEN 'PRESENT' ELSE 'MISSING' END AS status
FROM (
    VALUES
        ('006_execution_venue.sql',  'risk_settings.execution_venue'),
        ('007_chart_drawings.sql',   'chart_drawings table'),
        ('008_user_role_enum.sql',   'users.role is the userrole enum'),
        ('009_strategies.sql',       'strategies table'),
        ('010_opportunity_logs.sql', 'opportunity_logs table'),
        ('011_alerts.sql',           'alerts table'),
        ('012_bot_pause.sql',        'risk_settings.bot_paused'),
        ('013_position_opportunity.sql',
                                     'demo_positions.opportunity_id'),
        ('014_opportunity_fingerprint.sql',
                                     'opportunity_logs fingerprint columns')
) AS expected(migration, change)
JOIN LATERAL (
    SELECT CASE expected.migration
        WHEN '006_execution_venue.sql' THEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'risk_settings'
              AND column_name = 'execution_venue')
        WHEN '007_chart_drawings.sql' THEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'chart_drawings')
        WHEN '008_user_role_enum.sql' THEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'role'
              AND udt_name = 'userrole')
        WHEN '009_strategies.sql' THEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'strategies')
        WHEN '010_opportunity_logs.sql' THEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'opportunity_logs')
        WHEN '011_alerts.sql' THEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'alerts')
        WHEN '012_bot_pause.sql' THEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'risk_settings'
              AND column_name = 'bot_paused')
        WHEN '013_position_opportunity.sql' THEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'demo_positions'
              AND column_name = 'opportunity_id')
        -- All three, not any one: a half-applied 014 cannot rebuild a
        -- fingerprint and must not read as PRESENT.
        WHEN '014_opportunity_fingerprint.sql' THEN (
            SELECT COUNT(*) = 3 FROM information_schema.columns
            WHERE table_name = 'opportunity_logs'
              AND column_name IN ('structure_state', 'entry_price',
                                  'suppressed_as_duplicate'))
        ELSE FALSE
    END AS ok
) AS found ON TRUE
ORDER BY expected.migration;

-- The detail behind the two most recent, so a PRESENT row can be trusted
-- rather than taken on faith.
SELECT 'risk_settings.bot_paused' AS column,
       data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'risk_settings' AND column_name = 'bot_paused';

SELECT 'demo_positions.opportunity_id' AS column,
       data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'demo_positions' AND column_name = 'opportunity_id';

SELECT indexname AS "index on demo_positions.opportunity_id"
FROM pg_indexes
WHERE tablename = 'demo_positions'
  AND indexname = 'ix_demo_positions_opportunity_id';

SELECT column_name AS "opportunity_logs fingerprint column",
       data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'opportunity_logs'
  AND column_name IN ('structure_state', 'entry_price',
                      'suppressed_as_duplicate')
ORDER BY column_name;

SELECT indexname AS "index for the cooldown lookup"
FROM pg_indexes
WHERE tablename = 'opportunity_logs'
  AND indexname = 'ix_opportunity_logs_fingerprint_lookup';
