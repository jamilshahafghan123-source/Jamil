-- 001: subscriptions
--
-- The application bootstraps its schema with SQLAlchemy's create_all (see
-- app/db.py), which creates missing tables and never alters existing ones,
-- so a deployment that runs startup needs nothing from this file. It exists
-- for deployments where the database is migrated out of band and the app
-- runs without DDL rights.
--
-- Idempotent: safe to run more than once.
--
-- EFFECT ON EXISTING DATA: none is modified. No rows are created, so every
-- existing CUSTOMER has no entitlement and loses access to paid platform
-- endpoints the moment the new dependencies ship. That is the intended fix
-- rather than a regression: the frontend already blocked those customers,
-- and the backend was not. ADMIN accounts are unaffected; they bypass
-- entitlement entirely.

CREATE TABLE IF NOT EXISTS subscriptions (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL UNIQUE REFERENCES users (id),
    status              VARCHAR(16) NOT NULL DEFAULT 'NONE',
    plan                VARCHAR(32),
    current_period_end  TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id ON subscriptions (user_id);
CREATE INDEX IF NOT EXISTS ix_subscriptions_status  ON subscriptions (status);

-- Rollback:
--   DROP TABLE IF EXISTS subscriptions;
