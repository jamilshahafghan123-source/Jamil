"""Chart drawing ownership and scoping (sections 6, 40).

The property that matters: one customer's drawings are unreachable from
another's session — for reading, editing, deleting and clearing alike.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, get_db
from app.main import app
from app.models import (
    ChartDrawing,
    RiskSettings,
    Subscription,
    SubscriptionStatus,
    User,
    UserRole,
)
from app.security import create_access_token


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        alice = User(email="alice@example.com", password_hash="x",
                     role=UserRole.CUSTOMER, is_active=True)
        bob = User(email="bob@example.com", password_hash="x",
                   role=UserRole.CUSTOMER, is_active=True)
        db.add_all([alice, bob])
        await db.commit()
        for u in (alice, bob):
            await db.refresh(u)
            db.add(RiskSettings(user_id=u.id))
            db.add(Subscription(user_id=u.id, status=SubscriptionStatus.ACTIVE,
                                plan="monthly", current_period_end=None))
        await db.commit()
        bobs = ChartDrawing(user_id=bob.id, symbol="XAUUSD", timeframe="M15",
                            kind="TREND_LINE",
                            payload={"x1": 1, "y1": 3000, "x2": 2, "y2": 3010})
        db.add(bobs)
        await db.commit()
        await db.refresh(bobs)
        tokens = {"alice": create_access_token(str(alice.id)),
                  "bob": create_access_token(str(bob.id))}

    async def override_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield {"client": client, "tokens": tokens, "Session": Session,
               "bob_drawing": bobs.id}
    app.dependency_overrides.clear()
    await engine.dispose()


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _create(client, token, **over):
    body = {"symbol": "XAUUSD", "timeframe": "M15", "kind": "TREND_LINE",
            "payload": {"x1": 1, "y1": 2990, "x2": 5, "y2": 3020}}
    body.update(over)
    return await client.post("/api/drawings", headers=_h(token), json=body)


# ------------------------------------------------------------ ownership


@pytest.mark.asyncio
async def test_a_customer_sees_only_their_own_drawings(env):
    await _create(env["client"], env["tokens"]["alice"])
    r = await env["client"].get("/api/drawings?symbol=XAUUSD&timeframe=M15",
                                headers=_h(env["tokens"]["alice"]))
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["id"] != env["bob_drawing"]


@pytest.mark.asyncio
async def test_one_customer_cannot_edit_anothers_drawing(env):
    r = await env["client"].patch(
        f"/api/drawings/{env['bob_drawing']}",
        headers=_h(env["tokens"]["alice"]),
        json={"payload": {"x1": 0, "y1": 0, "x2": 1, "y2": 1}},
    )
    assert r.status_code == 404
    async with env["Session"]() as db:
        row = await db.get(ChartDrawing, env["bob_drawing"])
    assert row.payload["y1"] == 3000  # untouched


@pytest.mark.asyncio
async def test_one_customer_cannot_delete_anothers_drawing(env):
    r = await env["client"].delete(f"/api/drawings/{env['bob_drawing']}",
                                   headers=_h(env["tokens"]["alice"]))
    assert r.status_code == 404
    async with env["Session"]() as db:
        assert await db.get(ChartDrawing, env["bob_drawing"]) is not None


@pytest.mark.asyncio
async def test_clear_cannot_reach_another_customers_work(env):
    """"Clear all" is scoped to the caller and to one chart."""
    await _create(env["client"], env["tokens"]["alice"])
    r = await env["client"].delete("/api/drawings?symbol=XAUUSD&timeframe=M15",
                                   headers=_h(env["tokens"]["alice"]))
    assert r.status_code == 200
    async with env["Session"]() as db:
        remaining = (await db.execute(select(ChartDrawing))).scalars().all()
    # Bob's survives.
    assert [d.id for d in remaining] == [env["bob_drawing"]]


@pytest.mark.asyncio
async def test_a_supplied_user_id_is_ignored(env):
    """The body has no user field; supplying one changes nothing."""
    r = await env["client"].post(
        "/api/drawings", headers=_h(env["tokens"]["alice"]),
        json={"symbol": "XAUUSD", "timeframe": "M15", "kind": "HORIZONTAL",
              "payload": {"y": 3000}, "user_id": 99999},
    )
    assert r.status_code == 200
    async with env["Session"]() as db:
        row = await db.get(ChartDrawing, r.json()["id"])
    assert row.user_id != 99999


@pytest.mark.asyncio
async def test_unauthenticated_cannot_read_or_write(env):
    assert (await env["client"].get(
        "/api/drawings?symbol=XAUUSD&timeframe=M15")).status_code == 401
    assert (await env["client"].post(
        "/api/drawings", json={"symbol": "X", "timeframe": "M15",
                               "kind": "HORIZONTAL"})).status_code == 401


# -------------------------------------------------------------- scoping


@pytest.mark.asyncio
async def test_drawings_are_isolated_by_timeframe(env):
    client, token = env["client"], env["tokens"]["alice"]
    await _create(client, token, timeframe="M15")
    await _create(client, token, timeframe="H1")

    m15 = await client.get("/api/drawings?symbol=XAUUSD&timeframe=M15",
                           headers=_h(token))
    h1 = await client.get("/api/drawings?symbol=XAUUSD&timeframe=H1",
                          headers=_h(token))
    assert len(m15.json()) == 1
    assert len(h1.json()) == 1
    assert m15.json()[0]["id"] != h1.json()[0]["id"]


@pytest.mark.asyncio
async def test_drawings_are_isolated_by_symbol(env):
    client, token = env["client"], env["tokens"]["alice"]
    await _create(client, token, symbol="XAUUSD")
    await _create(client, token, symbol="EURUSD")
    gold = await client.get("/api/drawings?symbol=XAUUSD&timeframe=M15",
                            headers=_h(token))
    assert len(gold.json()) == 1
    assert gold.json()[0]["symbol"] == "XAUUSD"


@pytest.mark.asyncio
async def test_clearing_one_timeframe_leaves_the_other(env):
    client, token = env["client"], env["tokens"]["alice"]
    await _create(client, token, timeframe="M15")
    await _create(client, token, timeframe="H1")
    await client.delete("/api/drawings?symbol=XAUUSD&timeframe=M15",
                        headers=_h(token))
    h1 = await client.get("/api/drawings?symbol=XAUUSD&timeframe=H1",
                          headers=_h(token))
    assert len(h1.json()) == 1


# ------------------------------------------------------------ validation


@pytest.mark.asyncio
async def test_an_unknown_drawing_kind_is_refused(env):
    r = await _create(env["client"], env["tokens"]["alice"], kind="SOMETHING_ELSE")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_an_oversized_payload_is_refused(env):
    r = await _create(env["client"], env["tokens"]["alice"],
                      payload={f"k{i}": i for i in range(100)})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_oversized_text_is_refused(env):
    r = await _create(env["client"], env["tokens"]["alice"], kind="TEXT",
                      payload={"text": "x" * 5000})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_a_locked_drawing_cannot_be_moved_but_can_be_unlocked(env):
    client, token = env["client"], env["tokens"]["alice"]
    created = await _create(client, token)
    did = created.json()["id"]

    await client.patch(f"/api/drawings/{did}", headers=_h(token),
                       json={"locked": True})
    moved = await client.patch(f"/api/drawings/{did}", headers=_h(token),
                               json={"payload": {"x1": 9, "y1": 9, "x2": 9, "y2": 9}})
    assert moved.status_code == 400

    # Locking must be reversible, or it is a trap rather than a feature.
    unlocked = await client.patch(f"/api/drawings/{did}", headers=_h(token),
                                  json={"locked": False})
    assert unlocked.status_code == 200
    again = await client.patch(f"/api/drawings/{did}", headers=_h(token),
                               json={"payload": {"x1": 9, "y1": 9, "x2": 9, "y2": 9}})
    assert again.status_code == 200


@pytest.mark.asyncio
async def test_hiding_is_not_deleting(env):
    client, token = env["client"], env["tokens"]["alice"]
    created = await _create(client, token)
    did = created.json()["id"]
    await client.patch(f"/api/drawings/{did}", headers=_h(token),
                       json={"hidden": True})
    listed = await client.get("/api/drawings?symbol=XAUUSD&timeframe=M15",
                              headers=_h(token))
    # Still returned, flagged hidden: the client decides not to draw it.
    assert len(listed.json()) == 1
    assert listed.json()[0]["hidden"] is True


def test_ai_overlays_are_never_persisted_to_this_table():
    """Section 22: clearing AI overlays must not touch customer drawings."""
    from pathlib import Path

    for module in ("app/routers/analysis.py", "app/services/analyst.py"):
        source = Path(module).read_text(encoding="utf-8")
        assert "ChartDrawing" not in source


def test_every_allowed_kind_is_upper_snake_case():
    """The allowlist is the boundary, so its shape must stay predictable."""
    from app.routers.drawings import KINDS

    for kind in KINDS:
        assert kind == kind.upper()
        assert kind.replace("_", "").isalpha()


def test_the_allowlist_covers_the_whole_drawing_taxonomy():
    """A tool the UI offers but the backend refuses fails only on save.

    Pinning the set rather than counting it means adding a tool to the
    interface without adding it here fails loudly here first.
    """
    from app.routers.drawings import KINDS

    assert KINDS == {
        "TREND_LINE", "HORIZONTAL", "VERTICAL", "RECTANGLE", "ARROW",
        "TEXT", "RULER", "LONG_POSITION", "SHORT_POSITION", "FIB",
        "RAY", "EXTENDED_LINE", "HORIZONTAL_RAY", "CHANNEL",
        "FIB_EXTENSION", "FIB_FAN", "FIB_ARCS",
        "BRUSH", "CIRCLE", "TRIANGLE",
        "NOTE", "PRICE_LABEL", "CALLOUT",
        "PRICE_RANGE", "DATE_RANGE",
    }


# ---------------------------------------------------------------- styles

@pytest.mark.asyncio
async def test_a_valid_style_is_accepted(env):
    r = await _create(env["client"], env["tokens"]["alice"], payload={
        "x1": 1, "y1": 2990, "x2": 5, "y2": 3020,
        "style": {"colour": "gold", "width": 2, "opacity": 0.6},
    })
    assert r.status_code == 200
    assert r.json()["payload"]["style"]["colour"] == "gold"


@pytest.mark.asyncio
async def test_an_arbitrary_colour_string_is_refused(env):
    """The value reaches an SVG stroke attribute, so it must be a name
    from a closed set rather than anything a client cares to send."""
    for attempt in ("url(javascript:alert(1))", "#fff", "red; x", "expression(1)"):
        r = await _create(env["client"], env["tokens"]["alice"], payload={
            "x1": 1, "y1": 2990, "x2": 5, "y2": 3020,
            "style": {"colour": attempt},
        })
        assert r.status_code == 400, attempt


@pytest.mark.asyncio
async def test_out_of_range_width_and_opacity_are_refused(env):
    for style in ({"width": 40}, {"width": 0}, {"width": True},
                  {"opacity": 5}, {"opacity": -1}, {"opacity": "thick"},
                  {"opacity": True}):
        r = await _create(env["client"], env["tokens"]["alice"], payload={
            "x1": 1, "y1": 2990, "x2": 5, "y2": 3020, "style": style,
        })
        assert r.status_code == 400, style


@pytest.mark.asyncio
async def test_a_style_that_is_not_an_object_is_refused(env):
    r = await _create(env["client"], env["tokens"]["alice"], payload={
        "x1": 1, "y1": 2990, "x2": 5, "y2": 3020, "style": "gold",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_drawings_without_a_style_still_work(env):
    """Style is optional; existing drawings predate it entirely."""
    r = await _create(env["client"], env["tokens"]["alice"])
    assert r.status_code == 200
