# Updating a local J Gold AI install (Windows)

For an installation that already runs. A **first-time** setup is in the main
[`README.md`](../README.md) — start there instead, then come back here for
every later update.

Run these from the repository folder in PowerShell.

> This document never contains secrets. Your `.env` stays on your machine and
> is not in the repository. Nothing here deletes a database or a volume.

---

## 1. Get the new code

```powershell
git fetch origin
git checkout claude/jamil-trading-dashboard-w7fe6d
git pull origin claude/jamil-trading-dashboard-w7fe6d
```

If `git checkout` complains about local changes, decide what to do with them
first (`git stash` keeps them, `git checkout -- <file>` discards that file).
Do not force anything you have not looked at.

## 2. Check whether `.env` needs a new key

```powershell
git diff HEAD~1 --stat -- .env.example
```

If `.env.example` gained a key that your `.env` does not have, add it by hand.
Copy the **name** across and supply your own value — never copy a value out of
an example file into a running install.

## 3. Apply database migrations

`app/db.py` calls `create_all` on startup, which **creates missing tables but
never alters existing ones**. Anything that changes a column you already have
must be applied from `backend/migrations/` by hand.

Check what is in there and what your database already has:

```powershell
Get-ChildItem backend\migrations\*.sql | Select-Object Name
```

Each file states, at the top, what it changes and whether it touches existing
rows. They are all idempotent — running one twice is safe.

With the stack up, apply a file through the database container:

```powershell
Get-Content backend\migrations\008_user_role_enum.sql | `
  docker compose exec -T db psql -U mt5ai -d mt5ai
```

Substitute your own user and database name if you changed them in `.env`.

**Do not add `--single-transaction`.** `008` may add an enum label, and
PostgreSQL refuses to use a label in the same transaction that created it.

### Migrations most likely to be missing on an older install

| File | Fixes |
|---|---|
| `006_execution_venue.sql` | `column risk_settings.execution_venue does not exist` |
| `007_chart_drawings.sql` | `relation "chart_drawings" does not exist` |
| `008_user_role_enum.sql` | errors casting `users.role`, after the column was created as VARCHAR by an older revision |

`008` refuses to run and changes nothing if any row's `role` is not `ADMIN`
or `CUSTOMER`; it prints the offending value so you can look at it. That is
deliberate — it will not quietly drop a row to make itself succeed.

## 4. Rebuild and start

```powershell
docker compose up -d --build
```

## 5. Confirm the update took

```powershell
docker compose ps
docker compose logs --tail=40 backend
```

The backend logs its startup checklist. Confirm it reports real trading as
disabled:

```powershell
docker compose logs backend | Select-String "ALLOW_REAL_TRADING"
```

`ALLOW_REAL_TRADING` is `false` by default and there is a second, independent
latch on the bridge host. Turning either on is a deliberate decision, made in
your own `.env`, never by an update.

Then open **http://localhost:8081** and sign in.

---

## If something fails

**A table or column "does not exist"** — a migration has not been applied.
Match the name in the error against the table above and apply that file.

**The frontend loads but every request fails** — the backend container is not
up. `docker compose logs backend` will say why; a bad `.env` value is the
usual cause.

**"MT5 offline"** — expected until the bridge VM is running. The internal
J Gold AI demo account, the chart, drawings and indicators all work without
it, because the demo engine never talks to a broker.

**Do not** drop the database or delete the `db` volume to get past an error.
That destroys your accounts, trade history and drawings, and no migration in
this repository requires it.
