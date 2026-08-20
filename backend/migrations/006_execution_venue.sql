-- 006: execution venue on risk settings
--
-- Additive column with a default, so every existing account keeps sending
-- automated trades to the broker bridge exactly as it did before.
--
-- EFFECT ON EXISTING DATA: one column added, no row rewritten. An account
-- only reaches the internal demo simulator once someone sets it to
-- JGOLD_DEMO on purpose.

ALTER TABLE risk_settings
    ADD COLUMN IF NOT EXISTS execution_venue VARCHAR(16) NOT NULL
    DEFAULT 'MT5_BRIDGE';

-- Rollback:
--   ALTER TABLE risk_settings DROP COLUMN IF EXISTS execution_venue;
