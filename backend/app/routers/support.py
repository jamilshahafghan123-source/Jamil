"""Customer support chat and tickets (sections 86, 89).

AUTHORISATION, which is the part that matters:
ticket ownership is checked in the query, not after the fetch. A customer's
list is filtered by user_id at the database, and fetching one by id filters
by user_id too, so a customer asking for someone else's ticket gets 404 —
there is no code path that loads another customer's row and then decides.
Admins are routed through separate endpoints behind require_admin.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..deps import current_user, require_admin
from ..models import (
    AuditLog,
    RiskSettings,
    SupportAuthor,
    SupportMessage,
    SupportTicket,
    TicketCategory,
    TicketPriority,
    TicketStatus,
    User,
)
from ..services import safe_mode as safe_mode_svc
from ..services import support as support_svc
from ..services.mt5_client import mt5
from ..services.workers import (
    WorkerRole,
    project_account_profile,
    project_broker_connectivity,
    project_trading_status,
)

router = APIRouter(prefix="/api/support", tags=["support"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AskOut(BaseModel):
    answer: str
    escalated: bool
    ticket_id: int | None
    category: str
    facts: list[dict]


class MessageOut(BaseModel):
    id: int
    author: str
    body: str
    created_at: datetime


class TicketOut(BaseModel):
    id: int
    category: str
    subject: str
    description: str
    ai_summary: str
    safe_diagnostics: dict
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    messages: list[MessageOut] = []


def _to_out(ticket: SupportTicket, *, with_messages: bool = True) -> TicketOut:
    return TicketOut(
        id=ticket.id,
        category=ticket.category.value,
        subject=ticket.subject,
        description=ticket.description,
        ai_summary=ticket.ai_summary,
        safe_diagnostics=ticket.safe_diagnostics or {},
        priority=ticket.priority.value,
        status=ticket.status.value,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        resolved_at=ticket.resolved_at,
        messages=[
            MessageOut(
                id=m.id, author=m.author.value, body=m.body, created_at=m.created_at
            )
            for m in (ticket.messages if with_messages else [])
        ],
    )


@router.post("/ask", response_model=AskOut)
async def ask(
    body: AskIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> AskOut:
    """Answer from real permitted state, escalating when it cannot.

    The worker runs as WorkerRole.SUPPORT throughout; every projection below
    is obtained through that role, so a scope it does not hold would raise
    rather than quietly widen what support can see.
    """
    role = WorkerRole.SUPPORT

    settings_row = (
        await db.execute(select(RiskSettings).where(RiskSettings.user_id == user.id))
    ).scalar_one_or_none()

    profile = project_account_profile(role, user)

    trading = None
    if settings_row is not None:
        trading = project_trading_status(
            role,
            settings_row,
            halted_today=bool(settings_row.halted_until_date),
        )

    connected = False
    try:
        connected = await mt5.connected()
    except Exception:  # noqa: BLE001 - unreachable broker is a fact, not a 500
        connected = False
    broker = project_broker_connectivity(
        role,
        connected=connected,
        account_type=None,
        currency=None,
        server_allows_real=False,
    )

    safe = safe_mode_svc.evaluate(
        bridge_connected=connected, last_tick_at=None if not connected else None
    )

    result = support_svc.answer(
        body.question,
        trading=trading,
        profile=profile,
        broker=broker,
        safe_mode_active=safe.active,
        safe_mode_messages=safe.customer_messages,
    )

    ticket_id: int | None = None
    if result.should_escalate:
        ticket = SupportTicket(
            user_id=user.id,
            category=_category(result.category),
            subject=body.question[:120],
            # Stored as data. Nothing downstream interprets it.
            description=body.question,
            ai_summary=(
                "Support could not answer automatically and escalated for "
                "human review."
            ),
            safe_diagnostics=result.diagnostics,
            priority=TicketPriority.NORMAL,
            status=TicketStatus.NEEDS_ADMIN,
        )
        db.add(ticket)
        await db.flush()
        db.add(
            SupportMessage(
                ticket_id=ticket.id, author=SupportAuthor.CUSTOMER, body=body.question
            )
        )
        db.add(
            SupportMessage(
                ticket_id=ticket.id, author=SupportAuthor.SUPPORT_AI, body=result.text
            )
        )
        db.add(
            AuditLog(
                user_id=user.id,
                event="support_ticket_escalated",
                detail={"category": result.category, "ticket_subject": ticket.subject},
            )
        )
        await db.commit()
        ticket_id = ticket.id

    facts = []
    intent_facts = getattr(result.intent, "facts", ())
    for key, value in intent_facts:
        facts.append({"label": key, "value": value})

    return AskOut(
        answer=result.text,
        escalated=result.should_escalate,
        ticket_id=ticket_id,
        category=result.category,
        facts=facts,
    )


@router.get("/tickets", response_model=list[TicketOut])
async def my_tickets(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TicketOut]:
    """Only ever this customer's own tickets. Filtered in the query."""
    rows = (
        (
            await db.execute(
                select(SupportTicket)
                .where(SupportTicket.user_id == user.id)
                .order_by(SupportTicket.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_to_out(t, with_messages=False) for t in rows]


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
async def my_ticket(
    ticket_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    ticket = (
        await db.execute(
            select(SupportTicket)
            .options(selectinload(SupportTicket.messages))
            .where(
                SupportTicket.id == ticket_id,
                # Ownership is part of the lookup, not a check afterwards.
                SupportTicket.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return _to_out(ticket)


# ------------------------------------------------------------------- admin

admin_router = APIRouter(prefix="/api/admin/support", tags=["admin"])


class AdminReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@admin_router.get("/tickets", response_model=list[TicketOut])
async def all_tickets(
    status_filter: str | None = None,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[TicketOut]:
    stmt = select(SupportTicket).order_by(SupportTicket.id.desc())
    if status_filter:
        try:
            stmt = stmt.where(SupportTicket.status == TicketStatus(status_filter))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown status") from None
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_out(t, with_messages=False) for t in rows]


@admin_router.post("/tickets/{ticket_id}/reply", response_model=TicketOut)
async def admin_reply(
    ticket_id: int,
    body: AdminReplyIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    ticket = await db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    db.add(
        SupportMessage(ticket_id=ticket.id, author=SupportAuthor.ADMIN, body=body.body)
    )
    # An answered ticket goes back to OPEN: it no longer needs an admin,
    # but it is not resolved until someone says so.
    if ticket.status is TicketStatus.NEEDS_ADMIN:
        ticket.status = TicketStatus.OPEN
    db.add(
        AuditLog(
            user_id=admin.id,
            event="support_ticket_admin_reply",
            detail={"ticket_id": ticket.id},
        )
    )
    await db.commit()
    return _to_out(await _reload(db, ticket.id))


@admin_router.post("/tickets/{ticket_id}/resolve", response_model=TicketOut)
async def admin_resolve(
    ticket_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    ticket = await db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    ticket.status = TicketStatus.RESOLVED
    ticket.resolved_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            user_id=admin.id,
            event="support_ticket_resolved",
            detail={"ticket_id": ticket.id},
        )
    )
    await db.commit()
    return _to_out(await _reload(db, ticket.id))


async def _reload(db: AsyncSession, ticket_id: int) -> SupportTicket:
    """Re-read with messages eager-loaded, for serialising a response."""
    return (
        await db.execute(
            select(SupportTicket)
            .options(selectinload(SupportTicket.messages))
            .where(SupportTicket.id == ticket_id)
        )
    ).scalar_one()


def _category(value: str) -> TicketCategory:
    try:
        return TicketCategory(value)
    except ValueError:
        return TicketCategory.OTHER
