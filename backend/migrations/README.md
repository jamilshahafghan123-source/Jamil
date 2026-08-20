# Migrations

This project has no migration tool. `app/db.py` calls
`Base.metadata.create_all` on startup, which creates missing tables and
never alters existing ones — enough for additive changes, which is all
that has been needed so far.

Files here are plain SQL for deployments where the database is migrated
out of band and the application runs without DDL rights. Each is
idempotent and states its effect on existing data.

| File | Adds | Alters existing data |
|---|---|---|
| `001_subscriptions.sql` | `subscriptions` table | No |
| `002_incidents_notifications.sql` | `incidents`, `notifications` tables | No |

If a change ever needs to *alter* or backfill an existing table, that is
the point to add Alembic — `create_all` cannot do it, and a hand-run SQL
file is not a substitute for a versioned history.
