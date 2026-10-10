"""Transactional domain-event emission.

State changes write an ``OutboxEventRow`` inside the same database transaction that
mutates the aggregate, so an event can never be lost or reported for a change that
rolled back. Real-time dashboard pushes go through ``publish_after_commit`` so the
in-process event bus only announces committed facts.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from kural.persistence.models import OutboxEventRow, utcnow
from kural.services.event_bus import event_bus


def emit_event(
    session: Session,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> OutboxEventRow:
    row = OutboxEventRow(
        id=str(uuid4()),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload_json=payload,
        idempotency_key=idempotency_key or f"{event_type}:{aggregate_id}:{uuid4().hex}",
        status="PENDING",
        retry_count=0,
        created_at=utcnow(),
    )
    session.add(row)
    publish_after_commit(session, event_type, {"aggregate_id": aggregate_id, **_public(payload)})
    return row


def publish_after_commit(session: Session, topic: str, payload: dict[str, Any]) -> None:
    """Queue an in-process dashboard notification that fires only if the transaction commits."""
    pending = session.info.setdefault("kural_after_commit", [])
    pending.append((topic, payload))
    if not session.info.get("kural_after_commit_hooked"):
        session.info["kural_after_commit_hooked"] = True

        @sa_event.listens_for(session, "after_commit")
        def _flush(sess: Session) -> None:
            items = sess.info.pop("kural_after_commit", [])
            for t, p in items:
                event_bus.publish(t, p)

        @sa_event.listens_for(session, "after_rollback")
        def _discard(sess: Session) -> None:
            sess.info.pop("kural_after_commit", None)


_PUBLIC_KEYS = {
    "case_id", "callback_id", "status", "priority", "assigned_team", "assigned_agent_id",
    "campaign_id", "call_id", "version", "issue_code", "outcome", "scheduled_at_utc",
}


def _public(payload: dict[str, Any]) -> dict[str, Any]:
    """Only non-sensitive identifiers are pushed to browsers over the event stream."""
    return {k: v for k, v in payload.items() if k in _PUBLIC_KEYS}
