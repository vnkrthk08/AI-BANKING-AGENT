"""Callback domain service: durable scheduling, policy validation, idempotent upsert, atomic
versioned rescheduling, cancellation, assignment, leased dispatch claims, outcome recording
and full history.

Lifecycle::

    REQUESTED (no time yet) -> SCHEDULED -> DIALING -> COMPLETED
                                   |           |-> SCHEDULED (retry after BUSY/NO_ANSWER)
                                   |           '-> FAILED (attempts exhausted / provider error)
                                   |-> DUE (time reached, automated dialing unavailable; human must call)
                                   '-> CANCELLED

Every reschedule increments ``version``; a dispatch claim records the version it dialled,
so an execution started for an old time can never be confused with the current schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import (
    AgentRow, CallbackEventRow, CallbackRow, CallRecordRow, CaseRow, CustomerRow, SessionRow,
)
from kural.policy.calling_policy import evaluate_contact_time
from kural.privacy.masking import mask_phone
from kural.services.domain_events import emit_event

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")
ACTIVE_STATUSES = ("REQUESTED", "SCHEDULED", "DIALING", "DUE")
TERMINAL_STATUSES = ("COMPLETED", "CANCELLED", "FAILED")
RETRYABLE_OUTCOMES = {"BUSY", "NO_ANSWER"}
DISPATCH_LEASE = timedelta(minutes=10)


class CallbackPolicyError(ValueError):
    """The requested callback time or transition is not permitted."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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


def format_local(dt_utc: datetime) -> str:
    return dt_utc.astimezone(KOLKATA_TZ).strftime("%a %d %b, %I:%M %p IST")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _event(session: Session, callback_id: str, event_type: str, *, actor: str, old: str | None = None,
           new: str | None = None, call_id: str | None = None, at: datetime | None = None) -> None:
    session.add(CallbackEventRow(
        event_id=f"CBE-{uuid4().hex[:12].upper()}", callback_id=callback_id, event_type=event_type,
        old_value=old, new_value=new, actor=actor[:60], call_id=call_id,
        created_at=at or datetime.now(timezone.utc),
    ))


def _payload(row: CallbackRow, **extra: Any) -> dict[str, Any]:
    return {
        "callback_id": row.callback_id, "status": row.status, "version": row.version,
        "customer_ref": row.customer_ref, "case_id": row.case_id, "reason": row.reason,
        "scheduled_at_utc": _iso(row.scheduled_at_utc), "scheduled_at_local": row.scheduled_at_local,
        "assigned_agent_id": row.assigned_agent_id, **extra,
    }


def schedule_callback_in_session(
    session: Session, *, session_id: str, customer_ref: str, draft: CallbackDraft,
    idempotency_key: str | None, actor: str, now: datetime, assigned_agent_id: str | None = None,
) -> tuple[CallbackRow, str]:
    """Create or update (in place) the active callback for a call/case inside the caller's transaction.

    Returns ``(row, action)`` where action is ``created``, ``rescheduled`` or ``unchanged``.
    """
    if idempotency_key:
        existing = session.scalar(select(CallbackRow).where(CallbackRow.idempotency_key == idempotency_key))
        if existing is not None:
            return existing, "unchanged"
    else:
        same = session.scalar(select(CallbackRow).where(
            CallbackRow.session_id == session_id, CallbackRow.status == "SCHEDULED",
            CallbackRow.scheduled_at_utc == draft.scheduled_at_utc,
        ))
        if same is not None:
            return same, "unchanged"

    active_stmt = select(CallbackRow).where(CallbackRow.status.in_(("SCHEDULED", "REQUESTED")))
    if draft.case_id:
        active_stmt = active_stmt.where(CallbackRow.case_id == draft.case_id)
    else:
        active_stmt = active_stmt.where(CallbackRow.session_id == session_id, CallbackRow.case_id.is_(None))
    active = session.scalar(active_stmt.with_for_update())

    if active is not None:
        old_value = active.scheduled_at_local
        active.scheduled_at_utc = draft.scheduled_at_utc
        active.scheduled_at_local = draft.scheduled_at_local
        active.requested_at = draft.scheduled_at_utc
        active.raw_expression = draft.raw_expression or active.raw_expression
        active.requested_text_normalized = draft.requested_text_normalized or active.requested_text_normalized
        active.resolution_rule = draft.rule or active.resolution_rule
        active.reason = draft.reason or active.reason
        active.status = "SCHEDULED"
        active.version += 1
        active.dispatch_locked_until = None
        active.updated_at = now
        event_type = "RESCHEDULED_BY_CUSTOMER" if actor == "SUBBU" else "RESCHEDULED_BY_STAFF"
        _event(session, active.callback_id, event_type, actor=actor, old=old_value,
               new=draft.scheduled_at_local, call_id=session_id, at=now)
        emit_event(session, "callback.rescheduled", "CALLBACK", active.callback_id, _payload(active, previous=old_value),
                   idempotency_key=f"callback.rescheduled:{active.callback_id}:v{active.version}")
        return active, "rescheduled"

    row = CallbackRow(
        callback_id=f"CB-{uuid4().hex[:8].upper()}",
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
        confirmed_by_customer=actor == "SUBBU",
        status="SCHEDULED",
        version=1,
        language=draft.language,
        idempotency_key=idempotency_key or f"{session_id}:callback:{draft.case_id or 'none'}",
        assigned_agent_id=assigned_agent_id,
        created_at=now,
        updated_at=now,
    )
    if draft.case_id:
        case = session.get(CaseRow, draft.case_id)
        if case is not None:
            case.callback_id = row.callback_id
            case.callback_requested = True
            case.callback_cancelled = False
            case.updated_at = now
            row.assigned_agent_id = row.assigned_agent_id or case.assigned_agent_id
    session.add(row)
    session.flush()
    _event(session, row.callback_id, "CREATED", actor=actor, new=draft.scheduled_at_local, call_id=session_id, at=now)
    emit_event(session, "callback.scheduled", "CALLBACK", row.callback_id, _payload(row),
               idempotency_key=f"callback.scheduled:{row.callback_id}")
    return row, "created"


class CallbackService:
    def __init__(self, database: Database) -> None:
        self.database = database

    # ------------------------------------------------------------------ scheduling
    def validate_time(self, scheduled_at_utc: datetime, now: datetime | None = None) -> None:
        decision = evaluate_contact_time(scheduled_at_utc, now)
        if not decision:
            raise CallbackPolicyError(decision.code, decision.message)

    def upsert_callback(
        self,
        session_id: str,
        customer_ref: str,
        draft: CallbackDraft,
        idempotency_key: str | None = None,
        actor: str = "SUBBU",
        enforce_policy: bool = False,
        assigned_agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Draft -> confirm -> idempotent upsert. If an active callback exists, update the same record."""
        now = datetime.now(timezone.utc)
        if draft.scheduled_at_utc.tzinfo is None:
            draft.scheduled_at_utc = draft.scheduled_at_utc.replace(tzinfo=timezone.utc)
        if enforce_policy:
            self.validate_time(draft.scheduled_at_utc, now)
        with self.database.session() as db_session:
            with db_session.begin():
                if db_session.get(SessionRow, session_id) is None:
                    db_session.add(SessionRow(session_id=session_id, customer_ref=customer_ref,
                                              current_state="CALLBACK_CONFIRMATION", created_at=now, updated_at=now))
                    db_session.flush()
                row, _ = schedule_callback_in_session(
                    db_session, session_id=session_id, customer_ref=customer_ref, draft=draft,
                    idempotency_key=idempotency_key, actor=actor, now=now, assigned_agent_id=assigned_agent_id,
                )
                return self._serialize_callback(row, db_session)

    def reschedule_callback(
        self,
        callback_id: str,
        scheduled_at_utc: datetime,
        scheduled_at_local: str | None = None,
        actor: str = "STAFF",
        call_id: str | None = None,
        enforce_policy: bool = False,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Atomically move a callback to a new time; increments version and invalidates any older dispatch."""
        now = datetime.now(timezone.utc)
        if scheduled_at_utc.tzinfo is None:
            scheduled_at_utc = scheduled_at_utc.replace(tzinfo=timezone.utc)
        if enforce_policy:
            self.validate_time(scheduled_at_utc, now)
        scheduled_at_local = scheduled_at_local or format_local(scheduled_at_utc)
        with self.database.session() as db_session:
            with db_session.begin():
                row = self._get_for_update(db_session, callback_id)
                if row.status in ("COMPLETED", "CANCELLED"):
                    raise CallbackPolicyError("TERMINAL", f"A {row.status.lower()} callback cannot be rescheduled")
                if row.status == "DIALING" and row.dispatch_locked_until and row.dispatch_locked_until > now:
                    raise CallbackPolicyError("IN_PROGRESS", "This callback is being dialled right now; try again after the attempt finishes")
                if expected_version is not None and row.version != expected_version:
                    raise CallbackPolicyError("VERSION_CONFLICT", "The callback was changed by someone else; refresh and retry")
                old_value = row.scheduled_at_local
                row.scheduled_at_utc = scheduled_at_utc
                row.scheduled_at_local = scheduled_at_local
                row.requested_at = scheduled_at_utc
                row.version += 1
                row.status = "SCHEDULED"
                row.dispatch_locked_until = None
                row.updated_at = now
                event_type = "RESCHEDULED_BY_CUSTOMER" if actor == "SUBBU" else "RESCHEDULED_BY_STAFF"
                _event(db_session, callback_id, event_type, actor=actor, old=old_value, new=scheduled_at_local,
                       call_id=call_id or row.session_id, at=now)
                emit_event(db_session, "callback.rescheduled", "CALLBACK", callback_id, _payload(row, previous=old_value),
                           idempotency_key=f"callback.rescheduled:{callback_id}:v{row.version}")
                return self._serialize_callback(row, db_session)

    def cancel_callback(self, callback_id: str, actor: str = "SUBBU", call_id: str | None = None,
                        reason: str | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.database.session() as db_session:
            with db_session.begin():
                row = self._get_for_update(db_session, callback_id)
                if row.status == "CANCELLED":
                    return self._serialize_callback(row, db_session)
                if row.status == "COMPLETED":
                    raise CallbackPolicyError("TERMINAL", "A completed callback cannot be cancelled")
                old_value = row.scheduled_at_local
                row.status = "CANCELLED"
                row.version += 1
                row.dispatch_locked_until = None
                row.updated_at = now
                if reason:
                    row.outcome_notes = reason[:500]
                if row.case_id:
                    case = db_session.get(CaseRow, row.case_id)
                    if case:
                        case.callback_cancelled = True
                        case.updated_at = now
                event_type = "CANCELLED_BY_CUSTOMER" if actor == "SUBBU" else "CANCELLED_BY_STAFF"
                _event(db_session, callback_id, event_type, actor=actor, old=old_value,
                       call_id=call_id or row.session_id, at=now)
                emit_event(db_session, "callback.cancelled", "CALLBACK", callback_id, _payload(row),
                           idempotency_key=f"callback.cancelled:{callback_id}")
                return self._serialize_callback(row, db_session)

    def assign_callback(self, callback_id: str, agent_id: str | None, *, actor: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            with s.begin():
                row = self._get_for_update(s, callback_id)
                if agent_id is not None and s.get(AgentRow, agent_id) is None:
                    raise KeyError(f"Agent {agent_id} not found")
                previous = row.assigned_agent_id
                if previous == agent_id:
                    return self._serialize_callback(row, s)
                row.assigned_agent_id = agent_id
                row.updated_at = now
                _event(s, callback_id, "REASSIGNED" if previous else "ASSIGNED", actor=actor, old=previous, new=agent_id, at=now)
                emit_event(s, "callback.assigned", "CALLBACK", callback_id, _payload(row, previous_agent_id=previous),
                           idempotency_key=f"callback.assigned:{callback_id}:{agent_id}:{now.timestamp()}")
                return self._serialize_callback(row, s)

    def complete_callback(self, callback_id: str, *, outcome: str, notes: str | None, actor: str) -> dict[str, Any]:
        """Record a human-handled callback outcome (e.g. agent dialled manually)."""
        outcome = outcome.upper()
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            with s.begin():
                row = self._get_for_update(s, callback_id)
                if row.status in TERMINAL_STATUSES:
                    raise CallbackPolicyError("TERMINAL", f"Callback is already {row.status.lower()}")
                row.attempt_count += 1
                row.last_attempt_at = now
                row.last_outcome = outcome
                row.outcome_notes = (notes or "")[:2000] or row.outcome_notes
                if outcome in RETRYABLE_OUTCOMES and row.attempt_count < row.max_attempts:
                    row.status = "DUE"
                else:
                    row.status = "COMPLETED" if outcome in ("COMPLETED", "RESOLVED", "CONNECTED") else "FAILED"
                    row.completed_at = now
                row.version += 1
                row.dispatch_locked_until = None
                row.updated_at = now
                _event(s, callback_id, f"OUTCOME_{outcome}", actor=actor, new=row.status, at=now)
                emit_event(s, "callback.outcome", "CALLBACK", callback_id, _payload(row, outcome=outcome),
                           idempotency_key=f"callback.outcome:{callback_id}:{row.attempt_count}")
                return self._serialize_callback(row, s)

    # ------------------------------------------------------------------ execution
    def claim_due(self, now: datetime | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Atomically lease SCHEDULED callbacks whose time has arrived (or DIALING ones whose lease expired)."""
        now = now or datetime.now(timezone.utc)
        claimed: list[dict[str, Any]] = []
        with self.database.session() as s:
            with s.begin():
                rows = s.scalars(
                    select(CallbackRow).where(
                        or_(
                            (CallbackRow.status == "SCHEDULED") & (CallbackRow.scheduled_at_utc <= now),
                            (CallbackRow.status == "DIALING") & (CallbackRow.dispatch_locked_until <= now),
                        ),
                        or_(CallbackRow.dispatch_locked_until.is_(None), CallbackRow.dispatch_locked_until <= now),
                    ).order_by(CallbackRow.scheduled_at_utc.asc()).limit(limit).with_for_update(skip_locked=True)
                ).all()
                for row in rows:
                    recovered = row.status == "DIALING"
                    row.status = "DIALING"
                    row.dispatch_locked_until = now + DISPATCH_LEASE
                    row.dispatched_version = row.version
                    row.updated_at = now
                    _event(s, row.callback_id, "DISPATCH_RECOVERED" if recovered else "DISPATCH_CLAIMED",
                           actor="SCHEDULER", new=f"v{row.version}", at=now)
                    customer = s.get(CustomerRow, row.customer_ref)
                    claimed.append({
                        "callback_id": row.callback_id, "version": row.version, "customer_ref": row.customer_ref,
                        "case_id": row.case_id, "session_id": row.session_id, "assigned_agent_id": row.assigned_agent_id,
                        "phone": customer.phone if customer else None,
                        "dnd": bool(customer.dnd_status) if customer else True,
                        "customer_exists": customer is not None,
                        "provider_call_sid": row.provider_call_sid if recovered else None,
                        "recovered": recovered,
                        "attempt_count": row.attempt_count,
                    })
        return claimed

    def mark_dispatch_blocked(self, callback_id: str, version: int, *, code: str, message: str) -> dict[str, Any] | None:
        """Automated dialing is not possible/permitted: hand the due callback to a human (status DUE)."""
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            with s.begin():
                row = self._get_for_update(s, callback_id)
                if row.version != version or row.status != "DIALING":
                    return None
                row.status = "DUE"
                row.dispatch_locked_until = None
                row.last_outcome = code
                row.outcome_notes = message[:500]
                row.updated_at = now
                _event(s, callback_id, "DUE_FOR_HUMAN", actor="SCHEDULER", new=code, at=now)
                emit_event(s, "callback.due", "CALLBACK", callback_id, _payload(row, block_code=code, block_reason=message),
                           idempotency_key=f"callback.due:{callback_id}:v{version}")
                return self._serialize_callback(row, s)

    def record_dial_started(self, callback_id: str, version: int, *, provider_call_sid: str, call_record_id: str) -> bool:
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            with s.begin():
                row = self._get_for_update(s, callback_id)
                if row.version != version or row.status != "DIALING":
                    return False
                row.provider_call_sid = provider_call_sid
                row.call_record_id = call_record_id
                row.attempt_count += 1
                row.last_attempt_at = now
                row.updated_at = now
                _event(s, callback_id, "DIAL_STARTED", actor="SCHEDULER", new=provider_call_sid, at=now)
                return True

    def record_outcome(self, callback_id: str, *, outcome: str, provider_call_sid: str | None = None,
                       actor: str = "TELEPHONY", retry_gap: timedelta = timedelta(hours=2)) -> dict[str, Any] | None:
        """Apply a provider-reported dial outcome. Stale outcomes (sid mismatch) are ignored."""
        outcome = outcome.upper()
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            with s.begin():
                row = self._get_for_update(s, callback_id)
                if provider_call_sid and row.provider_call_sid and row.provider_call_sid != provider_call_sid:
                    return None
                if row.status != "DIALING":
                    return None
                row.last_outcome = outcome
                row.dispatch_locked_until = None
                row.updated_at = now
                if outcome == "COMPLETED":
                    row.status = "COMPLETED"
                    row.completed_at = now
                elif outcome in RETRYABLE_OUTCOMES and row.attempt_count < row.max_attempts:
                    from kural.policy.calling_policy import next_permitted_slot
                    retry_at = now + retry_gap
                    if not evaluate_contact_time(retry_at, now):
                        retry_at = next_permitted_slot(retry_at)
                    row.status = "SCHEDULED"
                    row.scheduled_at_utc = retry_at
                    row.scheduled_at_local = format_local(retry_at)
                    row.version += 1
                elif outcome == "CANCELLED":
                    row.status = "DUE"
                else:
                    row.status = "FAILED"
                    row.completed_at = now
                _event(s, callback_id, f"OUTCOME_{outcome}", actor=actor, new=row.status,
                       call_id=provider_call_sid, at=now)
                emit_event(s, "callback.outcome", "CALLBACK", callback_id, _payload(row, outcome=outcome),
                           idempotency_key=f"callback.outcome:{callback_id}:{row.attempt_count}:{outcome}")
                return self._serialize_callback(row, s)

    # ------------------------------------------------------------------ reads
    def get_callback(self, callback_id: str) -> dict[str, Any] | None:
        with self.database.session() as db_session:
            row = db_session.get(CallbackRow, callback_id)
            if row is None:
                return None
            return self._serialize_callback(row, db_session)

    def find_by_provider_sid(self, provider_call_sid: str) -> dict[str, Any] | None:
        with self.database.session() as s:
            row = s.scalar(select(CallbackRow).where(CallbackRow.provider_call_sid == provider_call_sid))
            return self._serialize_callback(row, s) if row else None

    def list_callbacks(self, session_id: str | None = None, *, status: str | None = None,
                       assigned_agent_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self.database.session() as db_session:
            stmt = select(CallbackRow).order_by(CallbackRow.created_at.desc()).limit(limit)
            if session_id:
                stmt = stmt.where(CallbackRow.session_id == session_id)
            if status == "ACTIVE":
                stmt = stmt.where(CallbackRow.status.in_(ACTIVE_STATUSES))
            elif status:
                stmt = stmt.where(CallbackRow.status == status.upper())
            if assigned_agent_id:
                stmt = stmt.where(CallbackRow.assigned_agent_id == assigned_agent_id)
            rows = db_session.scalars(stmt).all()
            return [self._serialize_callback(r, db_session) for r in rows]

    @staticmethod
    def _get_for_update(session: Session, callback_id: str) -> CallbackRow:
        row = session.scalar(select(CallbackRow).where(CallbackRow.callback_id == callback_id).with_for_update())
        if row is None:
            raise KeyError(f"Callback {callback_id} not found")
        return row

    def _serialize_callback(self, row: CallbackRow, db_session: Session) -> dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        events = db_session.scalars(
            select(CallbackEventRow)
            .where(CallbackEventRow.callback_id == row.callback_id)
            .order_by(CallbackEventRow.created_at.asc())
        ).all()

        is_overdue = (
            row.status in ("SCHEDULED", "DUE")
            and row.scheduled_at_utc is not None
            and now_utc > (row.scheduled_at_utc + timedelta(minutes=15))
        )
        effective_status = "OVERDUE" if (is_overdue and row.status == "SCHEDULED") else row.status

        reschedule_events = [e for e in events if "RESCHEDULED" in e.event_type]
        moved_label = None
        if reschedule_events:
            last = reschedule_events[-1]
            actor_label = " (staff)" if "STAFF" in last.event_type else ""
            if last.old_value and last.new_value:
                moved_label = f"Moved from {last.old_value} → {last.new_value}{actor_label}"
            elif last.old_value:
                moved_label = f"Moved from {last.old_value}{actor_label}"

        customer = db_session.get(CustomerRow, row.customer_ref)
        case = db_session.get(CaseRow, row.case_id) if row.case_id else None
        call = db_session.scalar(select(CallRecordRow).where(CallRecordRow.session_id == row.session_id))
        agent = db_session.get(AgentRow, row.assigned_agent_id) if row.assigned_agent_id else None

        return {
            "callback_id": row.callback_id,
            "id": row.callback_id,
            "session_id": row.session_id,
            "call_id": call.call_id if call else row.session_id,
            "customer_ref": row.customer_ref,
            "customerRef": row.customer_ref,
            "customer_name": customer.full_name if customer else None,
            "case_id": row.case_id,
            "reason": row.reason,
            "raw_expression": row.raw_expression,
            "requested_text_normalized": row.requested_text_normalized,
            "scheduled_at_utc": _iso(row.scheduled_at_utc),
            "scheduled_at_local": row.scheduled_at_local,
            "preferredAt": _iso(row.scheduled_at_utc),
            "slaDueAt": _iso(row.scheduled_at_utc),
            "timezone": row.timezone,
            "resolution_rule": row.resolution_rule,
            "confirmed_by_customer": row.confirmed_by_customer,
            "status": effective_status,
            "raw_status": row.status,
            "is_overdue": is_overdue,
            "version": row.version,
            "assigned_agent_id": row.assigned_agent_id,
            "assignedAgentId": row.assigned_agent_id,
            "assigned_agent_name": agent.name if agent else None,
            "language": row.language,
            "preferredLanguage": customer.preferred_language if customer else row.language,
            "relative_label": row.scheduled_at_local or (format_local(row.scheduled_at_utc) if row.scheduled_at_utc else "Time not yet agreed"),
            "moved_label": moved_label,
            "rescheduled_from_id": row.rescheduled_from_id,
            "superseded_by_id": row.superseded_by_id,
            "rescheduledCount": len(reschedule_events),
            "maskedPhone": mask_phone(customer.phone) if customer else "",
            "campaignName": call.campaign_name if call else None,
            "priority": case.priority if case else None,
            "attempt_count": row.attempt_count,
            "max_attempts": row.max_attempts,
            "last_attempt_at": _iso(row.last_attempt_at),
            "last_outcome": row.last_outcome,
            "outcome_notes": row.outcome_notes,
            "provider_call_sid": row.provider_call_sid,
            "completed_at": _iso(row.completed_at),
            "requestedAt": _iso(row.created_at) or "",
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
            "history": [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "old_value": e.old_value,
                    "new_value": e.new_value,
                    "actor": e.actor,
                    "call_id": e.call_id,
                    "created_at": _iso(e.created_at),
                }
                for e in events
            ],
        }
