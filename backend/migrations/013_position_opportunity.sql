-- 013: link a demo position to the opportunity it came from.
--
-- Setup class, grade, score and session are already recorded on
-- opportunity_logs. Storing a link rather than copying those columns onto
-- the position keeps one account of the trade: copies drift, and a
-- position claiming a setup class the opportunity record disagrees with
-- would be worse than showing nothing.
--
-- Nullable on purpose. A position the customer opened by hand has no
-- opportunity behind it, and inventing one would be a fabrication.
--
-- Idempotent and additive. Existing rows read as NULL, which is correct
-- for every position opened before this column existed. Safe to run with
-- --single-transaction.

ALTER TABLE demo_positions
    ADD COLUMN IF NOT EXISTS opportunity_id INTEGER REFERENCES opportunity_logs(id);

CREATE INDEX IF NOT EXISTS ix_demo_positions_opportunity_id
    ON demo_positions (opportunity_id);
