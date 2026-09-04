"""Writes to the general-purpose `audit_logs` table (spec section 10).
Distinct from `app.models.ai_investigation`, which audits Phase 3
investigation runs specifically -- this one is for the campaign/approval
workflow's events (campaign_created, campaign_approved, campaign_rejected,
policy_checked, recovery_action_authorized, recovery_action_executed).

Never pass secrets/credentials in `details` -- nothing in this workflow
handles any, so there's nothing to accidentally leak here.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session

from app.models.audit_log import AuditLog
from app.models.enums import AuditEventType


def write_audit_log(
    session: Session, event_type: AuditEventType, *, actor: str, entity_type: str, entity_id: uuid.UUID, details: dict,
) -> AuditLog:
    entry = AuditLog(
        event_type=event_type, actor=actor, entity_type=entity_type, entity_id=entity_id, details=details,
    )
    session.add(entry)
    return entry
