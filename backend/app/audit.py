"""Append-only audit logging.

Every decision that could lead to money moving writes a row here first.
Call sites deliberately never delete or update audit rows.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditLog

log = logging.getLogger("audit")

# Event names used across the app; keep them greppable.
ANALYSIS_REQUESTED = "analysis.requested"
ANALYSIS_COMPLETED = "analysis.completed"
ANALYSIS_FAILED = "analysis.failed"
AI_OUTPUT_REJECTED = "ai.output_rejected"
SIGNAL_CREATED = "signal.created"
RISK_EVALUATED = "risk.evaluated"
RISK_BLOCKED = "risk.blocked"
ORDER_REQUESTED = "order.requested"
ORDER_RESULT = "order.result"
POSITION_CLOSED = "position.closed"
MODE_CHANGED = "mode.changed"
BOT_TOGGLED = "bot.toggled"
EMERGENCY_STOP = "bot.emergency_stop"
SETTINGS_UPDATED = "settings.updated"
LOGIN_SUCCESS = "auth.login_success"
LOGIN_FAILED = "auth.login_failed"
DAILY_LIMIT_HIT = "risk.daily_limit_hit"
SAFE_MODE_PAUSED = "safe_mode.bot_paused"
ADMIN_LOGIN = "auth.admin_login"
ADMIN_LOGIN_FAILED = "auth.admin_login_failed"
PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"
PASSWORD_RESET_USED = "auth.password_reset_used"
BACKUP_CREATED = "backup.created"
BACKUP_FAILED = "backup.failed"
BACKUP_VERIFIED = "backup.verified"
RESTORE_REQUESTED = "backup.restore_requested"
RESTORE_RESULT = "backup.restore_result"


async def record(
    db: AsyncSession,
    event: str,
    detail: dict[str, Any] | None = None,
    user_id: int | None = None,
    *,
    commit: bool = True,
) -> None:
    row = AuditLog(user_id=user_id, event=event, detail=detail or {})
    db.add(row)
    if commit:
        await db.commit()
    log.info("audit event=%s user=%s detail=%s", event, user_id, detail)
