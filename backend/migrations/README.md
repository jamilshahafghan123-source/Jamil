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
| `003_backup_and_reset.sql` | `backup_records`, `password_reset_tokens` tables | No |
| `004_backup_metadata.sql` | `checksum`, `app_version`, `database_name` columns | Columns added with defaults |
| `005_demo_engine.sql` | `demo_accounts`, `demo_positions`, `demo_trades` tables | No |
| `006_execution_venue.sql` | `execution_venue` column on `risk_settings` | Column added with a default |
| `007_chart_drawings.sql` | `chart_drawings` table | No |
| `008_user_role_enum.sql` | native `userrole` enum type | Column type only; ADMIN/CUSTOMER values preserved |

`008` is the first file that changes an existing column's *type* rather
than adding one. It converts `users.role` from the VARCHAR an older
revision created into the native `userrole` enum that `models.py` now
declares — `create_all` cannot do this, because it never alters a column
that already exists. It refuses to run rather than lose data if any row
holds a value outside `ADMIN`/`CUSTOMER`, and it must be run **without**
`--single-transaction`.

`004` is the first file that ALTERs rather than creates. It is still safe
for `create_all` deployments only because the columns have defaults and
existing rows stay valid without a backfill. The next change that needs a
real backfill is the point to add Alembic — `create_all` cannot do it, and a hand-run SQL
file is not a substitute for a versioned history.
