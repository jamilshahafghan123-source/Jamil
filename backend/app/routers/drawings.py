"""Customer chart drawings (sections 5, 6, 40).

OWNERSHIP IS PART OF EVERY QUERY, never a check after the fetch. A read,
an update and a delete all filter by `user_id` at the database, so another
customer's drawing is a 404 and there is no code path that loads the row
first and then decides. The user id comes from the token; there is no
endpoint that accepts one.

Geometry is opaque here. The backend stores what the client sends and
enforces who may see it — it does not interpret shapes, which keeps a new
drawing tool a frontend change rather than a schema migration.

These are the customer's own annotations. AI overlays are derived from
analysis, are not persisted, and never touch this table.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import rate_limiter, require_demo_access
from ..models import ChartDrawing, User

router = APIRouter(
    prefix="/api/drawings",
    tags=["drawings"],
    dependencies=[Depends(rate_limiter(120))],
)

#: The shapes the client may create. An unknown kind is refused rather than
#: stored, so the table cannot fill with values nothing can render.
#: Every drawing type the platform will store. A kind outside this set is
#: refused, so a client cannot invent one — the allowlist is the boundary,
#: not the UI's tool list.
KINDS = frozenset(
    {
        "TREND_LINE", "HORIZONTAL", "VERTICAL", "RECTANGLE", "ARROW",
        "TEXT", "RULER", "LONG_POSITION", "SHORT_POSITION", "FIB",
        # Lines that continue past their second point.
        "RAY", "EXTENDED_LINE", "HORIZONTAL_RAY", "CHANNEL",
        # Fibonacci family.
        "FIB_EXTENSION", "FIB_FAN", "FIB_ARCS",
        # Freehand and shapes.
        "BRUSH", "CIRCLE", "TRIANGLE",
        # Annotation.
        "NOTE", "PRICE_LABEL", "CALLOUT",
        # Measurement.
        "PRICE_RANGE", "DATE_RANGE",
    }
)

#: A drawing is a handful of coordinates and maybe a label. This cap stops
#: the column being used as general-purpose storage.
MAX_PAYLOAD_KEYS = 32

#: Drawing colours, as a CLOSED set of names rather than free strings.
#:
#: The stored value ends up in an SVG stroke attribute, so accepting
#: arbitrary text would let a client put anything it liked there. Storing
#: a name the frontend maps to a hex value means the worst a tampered
#: payload can do is name a colour that does not exist, which renders as
#: the default.
STYLE_COLOURS = frozenset({
    "default", "gold", "blue", "green", "red", "purple", "teal", "grey",
})
STYLE_WIDTHS = frozenset({1, 2, 3})
MIN_OPACITY = 0.1
MAX_OPACITY = 1.0
MAX_TEXT_LENGTH = 500


class DrawingIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    timeframe: str = Field(min_length=1, max_length=8)
    kind: str = Field(min_length=1, max_length=24)
    payload: dict = Field(default_factory=dict)
    locked: bool = False
    hidden: bool = False


class DrawingPatch(BaseModel):
    payload: dict | None = None
    locked: bool | None = None
    hidden: bool | None = None


class DrawingOut(BaseModel):
    id: int
    symbol: str
    timeframe: str
    kind: str
    payload: dict
    locked: bool
    hidden: bool
    created_at: datetime
    updated_at: datetime


def _validate(kind: str, payload: dict) -> None:
    if kind not in KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown drawing type")
    if len(payload) > MAX_PAYLOAD_KEYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Drawing payload too large")
    for value in payload.values():
        if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Drawing text is too long"
            )

    style = payload.get("style")
    if style is None:
        return
    if not isinstance(style, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Style must be an object")

    colour = style.get("colour", "default")
    if colour not in STYLE_COLOURS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown colour {colour!r}",
        )

    width = style.get("width", 1)
    # A bool is an int in Python, and True would sail through a range
    # check while meaning nothing as a stroke width.
    if isinstance(width, bool) or width not in STYLE_WIDTHS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Line width must be 1, 2 or 3"
        )

    opacity = style.get("opacity", 1.0)
    if isinstance(opacity, bool) or not isinstance(opacity, (int, float)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Opacity must be a number"
        )
    if not MIN_OPACITY <= float(opacity) <= MAX_OPACITY:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Opacity must be between {MIN_OPACITY} and {MAX_OPACITY}",
        )


def _out(row: ChartDrawing) -> DrawingOut:
    return DrawingOut(
        id=row.id, symbol=row.symbol, timeframe=row.timeframe, kind=row.kind,
        payload=row.payload or {}, locked=row.locked, hidden=row.hidden,
        created_at=row.created_at, updated_at=row.updated_at,
    )


@router.get("", response_model=list[DrawingOut])
async def list_drawings(
    symbol: str = Query(max_length=24),
    timeframe: str = Query(max_length=8),
    user: User = Depends(require_demo_access),
    db: AsyncSession = Depends(get_db),
) -> list[DrawingOut]:
    """This customer's drawings for one symbol and timeframe."""
    rows = (
        (
            await db.execute(
                select(ChartDrawing)
                .where(
                    ChartDrawing.user_id == user.id,
                    ChartDrawing.symbol == symbol.upper(),
                    ChartDrawing.timeframe == timeframe.upper(),
                )
                .order_by(ChartDrawing.id)
            )
        )
        .scalars()
        .all()
    )
    return [_out(r) for r in rows]


@router.post("", response_model=DrawingOut)
async def create_drawing(
    body: DrawingIn,
    user: User = Depends(require_demo_access),
    db: AsyncSession = Depends(get_db),
) -> DrawingOut:
    _validate(body.kind, body.payload)
    row = ChartDrawing(
        # From the token. The body has no user field to supply.
        user_id=user.id,
        symbol=body.symbol.upper(),
        timeframe=body.timeframe.upper(),
        kind=body.kind,
        payload=body.payload,
        locked=body.locked,
        hidden=body.hidden,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.patch("/{drawing_id}", response_model=DrawingOut)
async def update_drawing(
    drawing_id: int,
    body: DrawingPatch,
    user: User = Depends(require_demo_access),
    db: AsyncSession = Depends(get_db),
) -> DrawingOut:
    row = (
        await db.execute(
            select(ChartDrawing).where(
                ChartDrawing.id == drawing_id,
                # Ownership is part of the lookup.
                ChartDrawing.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing not found")

    if body.payload is not None:
        _validate(row.kind, body.payload)
        # A locked drawing does not move. Lock state itself stays editable,
        # otherwise locking would be irreversible.
        if row.locked:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This drawing is locked. Unlock it before editing.",
            )
        row.payload = body.payload
    if body.locked is not None:
        row.locked = body.locked
    if body.hidden is not None:
        row.hidden = body.hidden

    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.delete("/{drawing_id}")
async def delete_drawing(
    drawing_id: int,
    user: User = Depends(require_demo_access),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(ChartDrawing).where(
                ChartDrawing.id == drawing_id,
                ChartDrawing.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": drawing_id}


@router.delete("")
async def clear_drawings(
    symbol: str = Query(max_length=24),
    timeframe: str = Query(max_length=8),
    user: User = Depends(require_demo_access),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Clear this customer's drawings for one symbol and timeframe.

    Scoped to the caller and to one chart, so "clear" can never reach
    another customer's work or another timeframe's.
    """
    result = await db.execute(
        sql_delete(ChartDrawing).where(
            ChartDrawing.user_id == user.id,
            ChartDrawing.symbol == symbol.upper(),
            ChartDrawing.timeframe == timeframe.upper(),
        )
    )
    await db.commit()
    return {"deleted": result.rowcount or 0}
