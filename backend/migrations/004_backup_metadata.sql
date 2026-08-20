-- 004: backup metadata (checksum, app version, database name)
--
-- Additive columns with defaults, so existing rows remain valid: a backup
-- taken before this migration simply has an empty checksum and an unknown
-- version, which verify_against() treats as "no expected checksum" rather
-- than as a mismatch.
--
-- EFFECT ON EXISTING DATA: columns added, no row rewritten by hand.

ALTER TABLE backup_records ADD COLUMN IF NOT EXISTS checksum      VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE backup_records ADD COLUMN IF NOT EXISTS app_version   VARCHAR(64) NOT NULL DEFAULT 'unknown';
ALTER TABLE backup_records ADD COLUMN IF NOT EXISTS database_name VARCHAR(64) NOT NULL DEFAULT '';

-- Rollback:
--   ALTER TABLE backup_records DROP COLUMN IF EXISTS database_name;
--   ALTER TABLE backup_records DROP COLUMN IF EXISTS app_version;
--   ALTER TABLE backup_records DROP COLUMN IF EXISTS checksum;
