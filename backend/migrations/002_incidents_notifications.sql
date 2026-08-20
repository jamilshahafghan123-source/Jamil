-- 002: incidents + notifications
--
-- Additive only. See migrations/README.md for why plain SQL and when this
-- project would need a real migration tool instead.
--
-- EFFECT ON EXISTING DATA: none. Two new tables, no rows written, no
-- existing column touched.

CREATE TABLE IF NOT EXISTS incidents (
    id              SERIAL PRIMARY KEY,
    service         VARCHAR(32) NOT NULL,
    category        VARCHAR(32) NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'OPEN',
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    recovered_at    TIMESTAMPTZ,
    original_state  VARCHAR(32) NOT NULL DEFAULT '',
    final_state     VARCHAR(32) NOT NULL DEFAULT '',
    attempt_number  INTEGER NOT NULL DEFAULT 0,
    actions         JSON NOT NULL DEFAULT '[]',
    admin_notified  BOOLEAN NOT NULL DEFAULT FALSE,
    detail          TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_incidents_service     ON incidents (service);
CREATE INDEX IF NOT EXISTS ix_incidents_status      ON incidents (status);
CREATE INDEX IF NOT EXISTS ix_incidents_detected_at ON incidents (detected_at);

CREATE TABLE IF NOT EXISTS notifications (
    id                 SERIAL PRIMARY KEY,
    severity           VARCHAR(16) NOT NULL DEFAULT 'INFO',
    event              VARCHAR(64) NOT NULL,
    message            TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at            TIMESTAMPTZ,
    incident_id        INTEGER REFERENCES incidents (id),
    delivered_channels JSON NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS ix_notifications_severity   ON notifications (severity);
CREATE INDEX IF NOT EXISTS ix_notifications_event      ON notifications (event);
CREATE INDEX IF NOT EXISTS ix_notifications_created_at ON notifications (created_at);
CREATE INDEX IF NOT EXISTS ix_notifications_incident   ON notifications (incident_id);

-- Rollback:
--   DROP TABLE IF EXISTS notifications;
--   DROP TABLE IF EXISTS incidents;
