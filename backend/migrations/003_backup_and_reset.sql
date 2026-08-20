-- 003: backup registry + password reset tokens
--
-- Additive only. See migrations/README.md.
--
-- EFFECT ON EXISTING DATA: none. Two new tables, no existing column touched.
--
-- NOTE ON password_reset_tokens.token_hash: this column stores the SHA-256
-- of a reset token and never the token itself, so a disclosure of this
-- table leaks nothing that can be used to reset an account.

CREATE TABLE IF NOT EXISTS backup_records (
    id                  SERIAL PRIMARY KEY,
    filename            VARCHAR(255) NOT NULL UNIQUE,
    status              VARCHAR(16) NOT NULL DEFAULT 'CREATED',
    size_bytes          INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified_at         TIMESTAMPTZ,
    detail              TEXT NOT NULL DEFAULT '',
    created_by_user_id  INTEGER REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_backup_records_status     ON backup_records (status);
CREATE INDEX IF NOT EXISTS ix_backup_records_created_at ON backup_records (created_at);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users (id),
    token_hash  VARCHAR(64) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_prt_user_id    ON password_reset_tokens (user_id);
CREATE INDEX IF NOT EXISTS ix_prt_expires_at ON password_reset_tokens (expires_at);

-- Rollback:
--   DROP TABLE IF EXISTS password_reset_tokens;
--   DROP TABLE IF EXISTS backup_records;
