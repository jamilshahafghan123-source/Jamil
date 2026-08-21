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
