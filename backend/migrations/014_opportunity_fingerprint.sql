-- 014: store what a stable opportunity fingerprint needs.
--
-- The duplicate/cooldown mechanism (Fingerprint, is_duplicate) needs five
-- fields to tell "the same setup again" from "a new setup": symbol,
-- direction, setup class, structure state and entry area. The log stored
-- the first three. Without the last two a fingerprint could not be
-- rebuilt from history, which is why the mechanism was never wired up.
--
-- `suppressed_as_duplicate` is reporting, and section 49 wants it: a
-- quiet hour must be explainable, and "the engine kept finding the same
-- setup it had already traded" is a different answer from "the engine
-- found nothing". It is NOT the cooldown anchor. The anchor is a
-- previous detection that was actually ENTERED (execution_result =
-- 'FILLED'), which is what makes the rule safe in both directions:
--
--   * a suppressed detection is never FILLED, so a setup that persists
--     for an hour cannot keep refreshing its own cooldown; and
--   * a detection the risk engine refused is never FILLED either, so a
--     setup blocked by the position cap at 10:00 is still tradeable the
--     moment the cap clears, instead of being locked out for the rest of
--     its cooldown for a trade that never happened.
--
-- Additive, idempotent, and safe to run with --single-transaction.
-- Existing rows read as NULL structure/entry, which cannot reconstruct a
-- fingerprint and therefore cannot match one — an old row can never
-- suppress a new setup.

ALTER TABLE opportunity_logs
    ADD COLUMN IF NOT EXISTS structure_state VARCHAR(32);

ALTER TABLE opportunity_logs
    ADD COLUMN IF NOT EXISTS entry_price DOUBLE PRECISION;

ALTER TABLE opportunity_logs
    ADD COLUMN IF NOT EXISTS suppressed_as_duplicate BOOLEAN NOT NULL
        DEFAULT FALSE;

-- The cooldown lookup: this user, this symbol, most recent first.
CREATE INDEX IF NOT EXISTS ix_opportunity_logs_fingerprint_lookup
    ON opportunity_logs (user_id, symbol, detected_at DESC);
