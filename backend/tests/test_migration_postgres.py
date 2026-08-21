"""Migration 014 against a real PostgreSQL server.

WHY THIS EXISTS SEPARATELY
--------------------------
`test_migrations.py` reads the SQL and checks what it says. That catches
a migration that forgot IF NOT EXISTS, and nothing else. It cannot catch
a statement PostgreSQL rejects, a NOT NULL column that fails on a table
with rows in it, or a second run that is not actually a no-op — and those
are the failures that matter, because this SQL is run by hand against a
live installation with a customer's history in it.

SKIPPED unless JGOLD_TEST_PG_DSN names a server. There is deliberately no
fallback to SQLite: a migration proved on a database that does not
support ALTER TABLE ... ADD COLUMN IF NOT EXISTS has not been proved.

    JGOLD_TEST_PG_DSN=postgresql://user@/postgres?host=/tmp/sock \
        pytest tests/test_migration_postgres.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio

asyncpg = pytest.importorskip("asyncpg")

DSN = os.environ.get("JGOLD_TEST_PG_DSN")
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

pytestmark = pytest.mark.skipif(
    not DSN, reason="JGOLD_TEST_PG_DSN is not set; no PostgreSQL to test on"
)

SCHEMA = "jgold_migration_test"


@pytest_asyncio.fixture
async def pg():
    """A scratch schema holding a pre-014 installation with one row in it.

    Its own schema, dropped afterwards, so this can be pointed at a
    developer's ordinary database without touching anything in it.
    """
    conn = await asyncpg.connect(DSN)
    await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    await conn.execute(f"CREATE SCHEMA {SCHEMA}")
    await conn.execute(f"SET search_path TO {SCHEMA}")
    await conn.execute(
        "CREATE TABLE users (id SERIAL PRIMARY KEY, email VARCHAR(255))"
    )
    await conn.execute(
        (MIGRATIONS / "010_opportunity_logs.sql").read_text(encoding="utf-8")
    )
    await conn.execute("INSERT INTO users (email) VALUES ('legacy@test')")
    await conn.execute(
        "INSERT INTO opportunity_logs (user_id, symbol, direction, "
        "confidence, ai_decision) VALUES (1, 'XAUUSD', 'BUY', 72, 'BUY')"
    )
    try:
        yield conn
    finally:
        await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await conn.close()


async def _columns(conn) -> dict[str, tuple[str, str, str | None]]:
    rows = await conn.fetch(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = $1 AND table_name = 'opportunity_logs'",
        SCHEMA,
    )
    return {r["column_name"]: (r["data_type"], r["is_nullable"],
                               r["column_default"]) for r in rows}


async def _apply(conn) -> None:
    """Exactly how a person runs it: one file, one transaction."""
    sql = (MIGRATIONS / "014_opportunity_fingerprint.sql").read_text(
        encoding="utf-8")
    async with conn.transaction():
        await conn.execute(sql)


@pytest.mark.asyncio
async def test_014_applies_and_adds_only(pg):
    before = await _columns(pg)
    assert "structure_state" not in before, "the fixture is not pre-014"

    await _apply(pg)

    after = await _columns(pg)
    # Every column that existed still exists, unchanged.
    for name, spec in before.items():
        assert after[name] == spec, f"{name} was altered"
    assert set(after) - set(before) == {
        "structure_state", "entry_price", "suppressed_as_duplicate"
    }


@pytest.mark.asyncio
async def test_014_is_idempotent_in_practice(pg):
    await _apply(pg)
    once = await _columns(pg)
    await _apply(pg)
    await _apply(pg)
    assert await _columns(pg) == once


@pytest.mark.asyncio
async def test_014_leaves_existing_history_intact(pg):
    await _apply(pg)
    row = await pg.fetchrow(
        "SELECT symbol, direction, confidence, structure_state, "
        "entry_price, suppressed_as_duplicate FROM opportunity_logs"
    )
    assert row["symbol"] == "XAUUSD"
    assert row["confidence"] == 72
    # No structure and no entry: a fingerprint cannot be rebuilt from this
    # row, so an old detection can never suppress a live setup.
    assert row["structure_state"] is None
    assert row["entry_price"] is None
    # Nothing was suppressed before the column existed.
    assert row["suppressed_as_duplicate"] is False


@pytest.mark.asyncio
async def test_014_creates_the_cooldown_index(pg):
    await _apply(pg)
    found = await pg.fetchval(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = $1 "
        "AND indexname = 'ix_opportunity_logs_fingerprint_lookup'",
        SCHEMA,
    )
    assert found, "the cooldown lookup has no index"
    assert "user_id" in found and "symbol" in found and "detected_at" in found


@pytest.mark.asyncio
async def test_a_new_row_stores_what_a_fingerprint_needs(pg):
    """The columns are the right TYPES, not merely present."""
    await _apply(pg)
    await pg.execute(
        "INSERT INTO opportunity_logs (user_id, symbol, direction, "
        "confidence, ai_decision, structure_state, entry_price, "
        "suppressed_as_duplicate) VALUES "
        "(1, 'XAUUSD', 'SELL', 66, 'SELL', 'BOS_DOWN', 3000.25, TRUE)"
    )
    row = await pg.fetchrow(
        "SELECT structure_state, entry_price, suppressed_as_duplicate "
        "FROM opportunity_logs WHERE direction = 'SELL'"
    )
    assert row["structure_state"] == "BOS_DOWN"
    assert row["entry_price"] == pytest.approx(3000.25)
    assert row["suppressed_as_duplicate"] is True
