-- 012: pause the bot without switching it off.
--
-- PAUSED is a hold: the bot stays enabled and keeps managing what is
-- already open, but opens nothing new. It is deliberately not the
-- emergency stop, which is an incident control, and not bot_enabled,
-- which would make resuming a re-arm.
--
-- Idempotent, additive, and defaulted, so an account that has never
-- paused reads exactly as it did before this column existed. Safe to run
-- with --single-transaction.

ALTER TABLE risk_settings
    ADD COLUMN IF NOT EXISTS bot_paused BOOLEAN NOT NULL DEFAULT FALSE;
