"""Migrations must not drift away from the models they exist to serve.

There is no migration tool here and no database in the test environment, so
these tests check the two things that can be checked without one: that the
SQL still describes the same enum the application declares, and that every
file is accounted for in the README. Both catch a real, silent failure mode
— a model changing while the hand-run SQL that reconciles an older
installation is left behind.
"""

import re
from pathlib import Path

from app.models import UserRole

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _sql(name: str) -> str:
    return (MIGRATIONS / name).read_text(encoding="utf-8")


def test_user_role_enum_migration_matches_the_model():
    """The labels 008 creates are exactly the roles the application has.

    Adding a third role to `UserRole` without extending this migration would
    leave an upgraded installation unable to store it. Parsing the label list
    out of the CREATE TYPE keeps the check on the statement itself rather
    than on the file's prose.
    """
    sql = _sql("008_user_role_enum.sql")
    match = re.search(
        r"CREATE TYPE userrole AS ENUM \(([^)]*)\)", sql, re.IGNORECASE
    )
    assert match, "008 no longer creates the userrole type"

    declared = {label.strip().strip("'") for label in match.group(1).split(",")}
    assert declared == {role.value for role in UserRole}


def test_user_role_migration_adds_every_label_defensively():
    """Each role is also covered by an idempotent ADD VALUE.

    A database whose type predates a role needs the label added, not just
    created. This asserts the belt-and-braces step covers the same set.
    """
    sql = _sql("008_user_role_enum.sql")
    added = set(
        re.findall(
            r"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '([A-Z_]+)'",
            sql,
        )
    )
    assert added == {role.value for role in UserRole}


def test_role_conversion_refuses_rather_than_discards():
    """The type change must abort on an unmappable value, not drop it.

    A conversion that silently deleted rows it could not cast would be a
    data-loss bug wearing a migration's clothes. The guard is a RAISE
    EXCEPTION, which aborts the enclosing block and leaves the column alone.
    """
    sql = _sql("008_user_role_enum.sql")
    guard = re.search(r"IF stray_count > 0 THEN(.*?)END IF;", sql, re.DOTALL)
    assert guard, "the unmappable-value guard is gone"
    assert "RAISE EXCEPTION" in guard.group(1)
    # An abort is the only permitted response: no statement inside the guard
    # may delete or rewrite a row.
    body = guard.group(1).upper()
    for destructive in ("DELETE", "UPDATE", "TRUNCATE"):
        assert destructive not in body


#: Non-migration SQL that lives in this directory. Each must be named
#: here deliberately, so an unnumbered file cannot quietly avoid the
#: documentation rule by not looking like a migration.
TOOLS = {"verify_schema.sql"}


def test_every_migration_file_is_documented():
    """A file nobody knows to run is the same as a missing migration."""
    readme = _sql("README.md")
    files = sorted(p.name for p in MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
    assert files, "no migrations found"
    undocumented = [name for name in files if f"`{name}`" not in readme]
    assert undocumented == []


def test_every_sql_file_is_either_a_migration_or_a_named_tool():
    """Nothing gets to sit here unaccounted for.

    The documentation rule above matches numbered files. Without this, a
    file called `fix.sql` would satisfy it by not being a migration.
    """
    stray = [
        p.name for p in MIGRATIONS.glob("*.sql")
        if p.name not in TOOLS and not re.match(r"^\d{3}_.+\.sql$", p.name)
    ]
    assert stray == []


def test_the_verification_tool_only_reads():
    """It is pointed at production databases, so it may not write.

    Comments are stripped before scanning. A file that documents "no
    INSERT, no DELETE" would otherwise fail its own promise, and a check
    that trips over prose teaches people to stop writing prose.
    """
    statements = "\n".join(
        line.split("--", 1)[0]
        for line in _sql("verify_schema.sql").splitlines()
    ).upper()
    for destructive in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP",
                        "ALTER", "CREATE"):
        assert destructive not in statements, destructive


def test_014_only_adds():
    """Additive means additive: nothing dropped, renamed or rewritten.

    This is the whole safety claim of a hand-run migration against a
    live installation, so it is asserted on the statements rather than
    trusted to the file's own comments.
    """
    statements = "\n".join(
        line.split("--", 1)[0]
        for line in _sql("014_opportunity_fingerprint.sql").splitlines()
    ).upper()
    for destructive in ("DROP", "DELETE", "TRUNCATE", "UPDATE", "RENAME",
                        "ALTER COLUMN", "SET NOT NULL"):
        assert destructive not in statements, destructive


def test_014_is_idempotent():
    """Every statement must survive being run twice.

    There is no migration runner here, so "did this already run?" is a
    question a person answers from memory. The file has to be safe when
    they answer it wrong.
    """
    sql = _sql("014_opportunity_fingerprint.sql")
    adds = re.findall(r"ADD COLUMN(\s+IF NOT EXISTS)?", sql, re.IGNORECASE)
    assert adds, "014 no longer adds any column"
    assert all(guard.strip() for guard in adds), (
        "every ADD COLUMN needs IF NOT EXISTS"
    )
    creates = re.findall(r"CREATE INDEX(\s+IF NOT EXISTS)?", sql,
                         re.IGNORECASE)
    assert all(guard.strip() for guard in creates), (
        "every CREATE INDEX needs IF NOT EXISTS"
    )


def test_014_does_not_break_existing_rows():
    """The one NOT NULL column carries a default.

    Adding a NOT NULL column without one fails outright on any table
    that already has rows — which is every table this migration is for.
    """
    sql = _sql("014_opportunity_fingerprint.sql")
    not_null = re.search(
        r"ADD COLUMN IF NOT EXISTS\s+(\w+)\s+BOOLEAN NOT NULL\s+DEFAULT\s+(\w+)",
        sql, re.IGNORECASE,
    )
    assert not_null, "the boolean column must be NOT NULL with a default"
    assert not_null.group(2).upper() == "FALSE", (
        "nothing was suppressed before this column existed"
    )
    # The other two must stay nullable: an existing row has no structure
    # state and no entry price, and inventing one would let it collide
    # with a live setup.
    for column in ("structure_state", "entry_price"):
        added = re.search(
            rf"ADD COLUMN IF NOT EXISTS\s+{column}\s+([^;]+);", sql,
            re.IGNORECASE,
        )
        assert added, column
        assert "NOT NULL" not in added.group(1).upper()


def test_014_matches_the_model_it_serves():
    """A column the migration adds and the model does not use is dead."""
    from app.models import OpportunityLog

    columns = OpportunityLog.__table__.c
    sql = _sql("014_opportunity_fingerprint.sql")
    for name in ("structure_state", "entry_price", "suppressed_as_duplicate"):
        assert name in columns, f"the model dropped {name}"
        assert name in sql, f"the migration dropped {name}"
    assert columns["structure_state"].nullable is True
    assert columns["entry_price"].nullable is True
    assert columns["suppressed_as_duplicate"].nullable is False
