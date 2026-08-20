-- 008: users.role as a native enum type
--
-- WHY THIS EXISTS
-- ---------------
-- models.py declares `role: Mapped[UserRole] = mapped_column(Enum(UserRole))`,
-- which SQLAlchemy maps to a native PostgreSQL enum type named `userrole`.
-- A database created by an older revision of this project has `role` as a
-- plain VARCHAR. create_all() never alters an existing column, so that
-- installation keeps the VARCHAR and every later query that casts to the enum
-- fails. This migration closes that gap without touching anyone's data.
--
-- EFFECT ON EXISTING DATA: no row is deleted and no value is rewritten. The
-- column's storage type changes; 'ADMIN' stays 'ADMIN' and 'CUSTOMER' stays
-- 'CUSTOMER'. If any row holds a value outside those two, the migration
-- ABORTS with an explanatory message and changes nothing, so an unexpected
-- value can be inspected by hand rather than silently discarded.
--
-- Idempotent: safe to run repeatedly. On a database that already has the
-- enum column, every branch below is skipped.
--
-- RUN THIS FILE WITHOUT --single-transaction. PostgreSQL refuses to use an
-- enum label in the same transaction that added it, and step 2 may add one.
-- Plain `psql -f` gives each statement its own transaction, which is what
-- this file expects; the DO blocks are individually atomic either way.

-- 1. Create the enum type if this database has never had it.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'userrole') THEN
        CREATE TYPE userrole AS ENUM ('ADMIN', 'CUSTOMER');
    END IF;
END
$$;

-- 2. Make sure both labels exist even if the type was created earlier with
--    only one of them. ADD VALUE IF NOT EXISTS is a no-op when present.
ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'ADMIN';
ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'CUSTOMER';

-- 3. Convert the column only when it is still a character type.
DO $$
DECLARE
    current_type text;
    stray_count  bigint;
    stray_sample text;
BEGIN
    SELECT data_type INTO current_type
    FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'role';

    IF current_type IS NULL THEN
        RAISE NOTICE '008: users.role not found; nothing to convert.';
        RETURN;
    END IF;

    IF current_type <> 'character varying' AND current_type <> 'text' THEN
        RAISE NOTICE '008: users.role is already %; no conversion needed.',
                     current_type;
        RETURN;
    END IF;

    -- Refuse to convert if any value would not survive the cast. Reporting
    -- the offending values is more useful than dropping the rows holding them.
    SELECT count(*), min(role)
      INTO stray_count, stray_sample
      FROM users
     WHERE role IS NULL OR role NOT IN ('ADMIN', 'CUSTOMER');

    IF stray_count > 0 THEN
        RAISE EXCEPTION
            '008 aborted: % row(s) in users.role hold a value outside '
            '(ADMIN, CUSTOMER) — first example: %. No data has been changed. '
            'Correct those rows, then re-run this migration.',
            stray_count, coalesce(stray_sample, '<NULL>');
    END IF;

    -- The default is dropped first: a VARCHAR default cannot be cast in
    -- place, and it is restored as an enum default immediately after.
    ALTER TABLE users ALTER COLUMN role DROP DEFAULT;

    ALTER TABLE users
        ALTER COLUMN role TYPE userrole USING role::userrole;

    ALTER TABLE users
        ALTER COLUMN role SET DEFAULT 'CUSTOMER'::userrole;

    ALTER TABLE users ALTER COLUMN role SET NOT NULL;

    RAISE NOTICE '008: users.role converted from % to userrole.', current_type;
END
$$;

-- Rollback (only if an installation must go back to the string column):
--   ALTER TABLE users ALTER COLUMN role DROP DEFAULT;
--   ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(16) USING role::text;
--   ALTER TABLE users ALTER COLUMN role SET DEFAULT 'CUSTOMER';
-- The enum type itself is left in place; DROP TYPE userrole only succeeds
-- once no column references it.
