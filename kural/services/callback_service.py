"""Callback domain service: scheduling, idempotent upsert, rescheduling, cancellation, and history tracking."""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import CallbackEventRow, CallbackRow, CaseRow, OutboxRow, SessionRow
from kural.services.event_bus import event_bus

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


@dataclass
class CallbackDraft:
    scheduled_at_utc: datetime
    scheduled_at_local: str
    raw_expression: str | None = None
    requested_text_normalized: str | None = None
    reason: str = "CUSTOMER_BUSY"
    case_id: str | None = None
    rule: str | None = None
    timezone: str = "Asia/Kolkata"
    language: str = "en-IN"


class CallbackService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_callback(
        self,
        session_id: str,
        customer_ref: str,
        draft: CallbackDraft,
        idempotency_key: str | None = None,
        actor: str = "SUBBU",
    ) -> dict[str, Any]:
        """Draft -> confirm -> idempotent upsert. If active callback exists, update same record."""
        idem_key = idempotency_key or f"{session_id}:callback:{draft.case_id or 'none'}"
        now = datetime.now(timezone.utc)

        with self.database.session() as db_session:
            with db_session.begin():
                sess = db_session.get(SessionRow, session_id)
                if sess is None:
                    db_session.add(
                        SessionRow(
                            session_id=session_id,
                            customer_ref=customer_ref,
                            current_state="CALLBACK_CONFIRMATION",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    db_session.flush()

                # 1. Check idempotency: exact retry
                if idempotency_key:
                    existing_idem = db_session.scalar(
                        select(CallbackRow).where(CallbackRow.idempotency_key == idempotency_key)
                    )
                    if existing_idem is not None:
                        return self._serialize_callback(existing_idem, db_session)
                else:
                    existing_same = db_session.scalar(
                        select(CallbackRow).where(
                            CallbackRow.session_id == session_id,
                            CallbackRow.status == "SCHEDULED",
                            CallbackRow.scheduled_at_utc == draft.scheduled_at_utc,
                        )
                    )
                    if existing_same is not None:
                        return self._serialize_callback(existing_same, db_session)

                # 2. Check for active SCHEDULED callback for this case (or call without case)
                active_stmt = select(CallbackRow).where(CallbackRow.status == "SCHEDULED")
                if draft.case_id:
                    active_stmt = active_stmt.where(CallbackRow.case_id == draft.case_id)
                else:
                    active_stmt = active_stmt.where(
                        CallbackRow.session_id == session_id,
                        CallbackRow.case_id.is_(None),
                    )

                existing_active = db_session.scalar(active_stmt)

                if existing_active is not None:
                    # In-place reschedule (AT-CB-2)
                    old_value = existing_active.scheduled_at_local
                    existing_active.scheduled_at_utc = draft.scheduled_at_utc
                    existing_active.scheduled_at_local = draft.scheduled_at_local
                    existing_active.requested_at = draft.scheduled_at_utc
                    existing_active.raw_expression = draft.raw_expression or existing_active.raw_expression
                    existing_active.requested_text_normalized = (
                        draft.requested_text_normalized or existing_active.requested_text_normalized
                    )
                    existing_active.resolution_rule = draft.rule or existing_active.resolution_rule
                    existing_active.reason = draft.reason or existing_active.reason
                    existing_active.version += 1
                    existing_active.updated_at = now

                    event_type = "RESCHEDULED_BY_CUSTOMER" if actor == "SUBBU" else "RESCHEDULED_BY_STAFF"
                    event_row = CallbackEventRow(
                        callback_id=existing_active.callback_id,
                        event_type=event_type,
                        old_value=old_value,
                        new_value=draft.scheduled_at_local,
                        actor=actor,
                        call_id=session_id,
                        created_at=now,
                    )
                    db_session.add(event_row)

                    outbox_payload = {
                        "callback_id": existing_active.callback_id,
                        "status": existing_active.status,
                        "scheduled_at_local": existing_active.scheduled_at_local,
                        "scheduled_at_utc": existing_active.scheduled_at_utc.isoformat() if existing_active.scheduled_at_utc else None,
                        "version": existing_active.version,
                        "customer_ref": existing_active.customer_ref,
                        "reason": existing_active.reason,
                    }
                    outbox_row = OutboxRow(
                        event_topic="callback.updated",
                        payload_json=outbox_payload,
                        created_at=now,
                    )
                    db_session.add(outbox_row)
                    db_session.flush()

                    result = self._serialize_callback(existing_active, db_session)
                    event_bus.publish("callback.updated", outbox_payload)
                    return result

                # 3. Create new callback (AT-CB-1, AT-CB-7)
                callback_id = f"CB-{uuid4().hex[:8].upper()}"
                row = CallbackRow(
                    callback_id=callback_id,
                    session_id=session_id,
                    customer_ref=customer_ref,
                    case_id=draft.case_id,
                    reason=draft.reason,
                    raw_expression=draft.raw_expression,
                    requested_text_normalized=draft.requested_text_normalized,
                    scheduled_at_utc=draft.scheduled_at_utc,
                    scheduled_at_local=draft.scheduled_at_local,
                    requested_at=draft.scheduled_at_utc,
                    timezone=draft.timezone,
                    resolution_rule=draft.rule,
                    confirmed_by_customer=True,
                    status="SCHEDULED",
                    version=1,
                    language=draft.language,
                    idempotency_key=idem_key,
                    created_at=now,
                    updated_at=now,
                )
                db_session.add(row)
                db_session.flush()

                event_row = CallbackEventRow(
                    callback_id=callback_id,
                    event_type="CREATED",
                    old_value=None,
                    new_value=draft.scheduled_at_local,
                    actor=actor,
                    call_id=session_id,
                    created_at=now,
                )
                db_session.add(event_row)

                outbox_payload = {
                    "callback_id": callback_id,
                    "status": "SCHEDULED",
                    "scheduled_at_local": draft.scheduled_at_local,
                    "scheduled_at_utc": draft.scheduled_at_utc.isoformat() if draft.scheduled_at_utc else None,
                    "version": 1,
                    "customer_ref": customer_ref,
                    "reason": draft.reason,
                }
                outbox_row = OutboxRow(
                    event_topic="callback.created",
                    payload_json=outbox_payload,
                    created_at=now,
                )
                db_session.add(outbox_row)
                db_session.flush()

                result = self._serialize_callback(row, db_session)
                event_bus.publish("callback.created", outbox_payload)
                return result

    def reschedule_callback(
        self,
        callback_id: str,
        scheduled_at_utc: datetime,
        scheduled_at_local: str,
        actor: str = "STAFF",
        call_id: str | None = None,
    ) -> dict[str, Any]:
        """Reschedule existing callback (AT-CB-5: staff or customer). Increments version."""
        now = datetime.now(timezone.utc)
        with self.database.session() as db_session:
            with db_session.begin():
                row = db_session.get(CallbackRow, callback_id)
                if row is None:
                    raise KeyError(f"Callback {callback_id} not found")

                old_value = row.scheduled_at_local
                row.scheduled_at_utc = scheduled_at_utc
                row.scheduled_at_local = scheduled_at_local
                row.requested_at = scheduled_at_utc
                row.version += 1
                row.status = "SCHEDULED"
                row.updated_at = now

                event_type = "RESCHEDULED_BY_CUSTOMER" if actor == "SUBBU" else "RESCHEDULED_BY_STAFF"
                event_row = CallbackEventRow(
                    callback_id=callback_id,
                    event_type=event_type,
                    old_value=old_value,
                    new_value=scheduled_at_local,
                    actor=actor,
                    call_id=call_id or row.session_id,
                    created_at=now,
                )
                db_session.add(event_row)

                outbox_payload = {
                    "callback_id": callback_id,
                    "status": "SCHEDULED",
                    "scheduled_at_local": scheduled_at_local,
                    "scheduled_at_utc": scheduled_at_utc.isoformat(),
                    "version": row.version,
                    "customer_ref": row.customer_ref,
                    "reason": row.reason,
                }
                outbox_row = OutboxRow(
                    event_topic="callback.updated",
                    payload_json=outbox_payload,
                    created_at=now,
                )
                db_session.add(outbox_row)
                db_session.flush()

                result = self._serialize_callback(row, db_session)
                event_bus.publish("callback.updated", outbox_payload)
                return result

    def cancel_callback(
        self,
        callback_id: str,
        actor: str = "SUBBU",
        call_id: str | None = None,
    ) -> dict[str, Any]:
        """Cancel callback (AT-CB-3)."""
        now = datetime.now(timezone.utc)
        with self.database.session() as db_session:
            with db_session.begin():
                row = db_session.get(CallbackRow, callback_id)
                if row is None:
                    raise KeyError(f"Callback {callback_id} not found")

                old_value = row.scheduled_at_local
                row.status = "CANCELLED"
                row.updated_at = now

                if row.case_id:
                    case = db_session.get(CaseRow, row.case_id)
                    if case:
                        case.callback_cancelled = True
                        case.updated_at = now

                event_type = "CANCELLED_BY_CUSTOMER" if actor == "SUBBU" else "CANCELLED_BY_STAFF"
                event_row = CallbackEventRow(
                    callback_id=callback_id,
                    event_type=event_type,
                    old_value=old_value,
                    new_value=None,
                    actor=actor,
                    call_id=call_id or row.session_id,
                    created_at=now,
                )
                db_session.add(event_row)

                outbox_payload = {
                    "callback_id": callback_id,
                    "status": "CANCELLED",
                    "scheduled_at_local": row.scheduled_at_local,
                    "version": row.version,
                    "customer_ref": row.customer_ref,
                    "reason": row.reason,
                }
                outbox_row = OutboxRow(
                    event_topic="callback.cancelled",
                    payload_json=outbox_payload,
                    created_at=now,
                )
                db_session.add(outbox_row)
                db_session.flush()

                result = self._serialize_callback(row, db_session)
                event_bus.publish("callback.cancelled", outbox_payload)
                return result

    def get_callback(self, callback_id: str) -> dict[str, Any] | None:
        with self.database.session() as db_session:
            row = db_session.get(CallbackRow, callback_id)
            if row is None:
                return None
            return self._serialize_callback(row, db_session)

    def list_callbacks(self, session_id: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as db_session:
            stmt = select(CallbackRow).order_by(CallbackRow.created_at.desc())
            if session_id:
                stmt = stmt.where(CallbackRow.session_id == session_id)
            rows = db_session.scalars(stmt).all()
            return [self._serialize_callback(r, db_session) for r in rows]

    def _serialize_callback(self, row: CallbackRow, db_session: Session) -> dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        events = db_session.scalars(
            select(CallbackEventRow)
            .where(CallbackEventRow.callback_id == row.callback_id)
            .order_by(CallbackEventRow.created_at.asc())
        ).all()

        is_overdue = (
            row.status == "SCHEDULED"
            and row.scheduled_at_utc is not None
            and now_utc > (row.scheduled_at_utc + timedelta(minutes=15))
        )
        effective_status = "OVERDUE" if is_overdue else row.status

        # Find latest reschedule event for "Moved from X -> Y" label
        reschedule_events = [e for e in events if "RESCHEDULED" in e.event_type]
        moved_label = None
        if reschedule_events:
            last_resched = reschedule_events[-1]
            if last_resched.old_value and last_resched.new_value:
                actor_label = " (staff)" if "STAFF" in last_resched.event_type else ""
                moved_label = f"Moved from {last_resched.old_value} → {last_resched.new_value}{actor_label}"
            elif last_resched.old_value:
                actor_label = " (staff)" if "STAFF" in last_resched.event_type else ""
                moved_label = f"Moved from {last_resched.old_value}{actor_label}"

        # Generate relative label
        relative_label = self._format_relative_label(row.scheduled_at_utc, row.scheduled_at_local)

        return {
            "callback_id": row.callback_id,
            "id": row.callback_id,
            "session_id": row.session_id,
            "call_id": row.session_id,
            "customer_ref": row.customer_ref,
            "customerRef": row.customer_ref,
            "case_id": row.case_id,
            "reason": row.reason,
            "raw_expression": row.raw_expression,
            "requested_text_normalized": row.requested_text_normalized,
            "scheduled_at_utc": row.scheduled_at_utc.isoformat() if row.scheduled_at_utc else None,
            "scheduled_at_local": row.scheduled_at_local,
            "preferredAt": row.scheduled_at_utc.isoformat() if row.scheduled_at_utc else None,
            "slaDueAt": row.scheduled_at_utc.isoformat() if row.scheduled_at_utc else None,
            "timezone": row.timezone,
            "resolution_rule": row.resolution_rule,
            "confirmed_by_customer": row.confirmed_by_customer,
            "status": effective_status,
            "raw_status": row.status,
            "is_overdue": is_overdue,
            "version": row.version,
            "assigned_agent_id": row.assigned_agent_id,
            "assignedAgentId": row.assigned_agent_id,
            "language": row.language,
            "preferredLanguage": row.language,
            "relative_label": relative_label,
            "moved_label": moved_label,
            "rescheduled_from_id": row.rescheduled_from_id,
            "superseded_by_id": row.superseded_by_id,
            "rescheduledCount": len(reschedule_events),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "history": [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "old_value": e.old_value,
                    "new_value": e.new_value,
                    "actor": e.actor,
                    "call_id": e.call_id,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
        }

    @staticmethod
    def _format_relative_label(dt_utc: datetime | None, local_str: str | None) -> str:
        if local_str:
            return local_str
        if dt_utc is None:
            return "As soon as available"
        dt_local = dt_utc.astimezone(KOLKATA_TZ)
        return dt_local.strftime("%a %d %b, %I:%M %p IST")
