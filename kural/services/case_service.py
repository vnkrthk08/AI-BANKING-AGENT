"""Case domain service: creation with taxonomy/SLA, idempotency, eligibility-based assignment,
lifecycle transitions, notes, resolution and an append-only history.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import AgentRow, CallbackRow, CaseEventRow, CaseRow, CustomerRow, SessionRow
from kural.privacy.masking import mask_phone
from kural.privacy.transcript import safe_transcript
from kural.services.domain_events import emit_event

ISSUE_TAXONOMY: dict[str, dict[str, Any]] = {
    "UPDATE_FAILED_STORAGE": {"priority": "Normal", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 24},
    "UPDATE_FAILED_ERROR": {"priority": "Normal", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 24},
    "UPDATE_FAILED_STORE": {"priority": "Normal", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 24},
    "UPDATE_HOW_TO": {"priority": "Normal", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 24},
    "INSTALL_FAILED": {"priority": "Normal", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 24},
    "APP_NOT_OPENING": {"priority": "High", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 8},
    "APP_CRASH": {"priority": "Normal", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 24},
    "LOGIN_ISSUE": {"priority": "High", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 8},
    "REGISTRATION_ISSUE": {"priority": "High", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 8},
    "APP_SLOW": {"priority": "Low", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 72},
    "NOTIFICATION_ISSUE": {"priority": "Low", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 72},
    "FEATURE_NOT_WORKING": {"priority": "Normal", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 24},
    "GENERAL_SUPPORT": {"priority": "Normal", "team": "CUSTOMER_CARE", "type": "HUMAN_REQUEST", "sla_hours": 24},
    "COMPLAINT": {"priority": "High", "team": "CUSTOMER_CARE", "type": "COMPLAINT", "sla_hours": 8},
    "SECURITY_CONCERN": {"priority": "Urgent", "team": "SECURITY_DESK", "type": "SECURITY", "sla_hours": 1},
    "UNKNOWN_ISSUE": {"priority": "Normal", "team": "APP_SUPPORT", "type": "APP_SUPPORT", "sla_hours": 24},
}

# Conversation-level issue categories (KURAL NLU) mapped onto the operational taxonomy.
CONVERSATION_CATEGORY_MAP: dict[str, str] = {
    "APP_UPDATE_FAILURE": "UPDATE_FAILED_ERROR",
    "UPDATE_CRASH": "APP_CRASH",
    "LOGIN": "LOGIN_ISSUE",
    "PAYMENT": "FEATURE_NOT_WORKING",
    "BIOMETRIC": "LOGIN_ISSUE",
    "NETWORK": "APP_NOT_OPENING",
    "GENERAL": "UPDATE_FAILED_ERROR",
    "HUMAN_REQUEST": "GENERAL_SUPPORT",
}

FIRST_RESPONSE_MINUTES = {"Urgent": 15, "High": 60, "Normal": 240, "Low": 480}
OPEN_STATUSES = ("NEW", "ASSIGNED", "IN_PROGRESS", "PENDING_CUSTOMER")
CASE_STATUSES = set(OPEN_STATUSES) | {"RESOLVED", "CLOSED", "CANCELLED", "OPEN"}
_PRIORITY_CANON = {"urgent": "Urgent", "high": "High", "normal": "Normal", "low": "Low"}


class CaseError(ValueError):
    """A case operation was rejected by a lifecycle rule."""


def normalize_issue_code(category: str | None) -> str:
    if not category:
        return "UNKNOWN_ISSUE"
    code = category.upper()
    if code in ISSUE_TAXONOMY:
        return code
    return CONVERSATION_CATEGORY_MAP.get(code, "UNKNOWN_ISSUE")


def _priority(value: Any) -> str:
    return _PRIORITY_CANON.get(str(value).strip().lower(), "Normal")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _record_event(session: Session, case_id: str, event_type: str, *, actor: str, actor_role: str | None = None,
                  from_value: str | None = None, to_value: str | None = None, note: str | None = None,
                  at: datetime | None = None) -> None:
    session.add(CaseEventRow(
        event_id=f"CSE-{uuid4().hex[:12].upper()}", case_id=case_id, event_type=event_type,
        from_value=from_value, to_value=to_value, note=note, actor=actor[:64], actor_role=actor_role,
        created_at=at or datetime.now(timezone.utc),
    ))


def build_case_row(session: Session, *, session_id: str, customer_ref: str, issue_code: str, summary: str,
                   key_lines: list[str] | None, actions_tried: list[str] | None, callback_id: str | None,
                   idempotency_key: str, actor: str, source: str, now: datetime) -> tuple[CaseRow, bool]:
    """Create (or return the existing idempotent) case inside the caller's transaction.

    Returns ``(row, created)``. Shared by the API service and the KURAL conversation
    repository so every case — staff- or AI-created — follows one taxonomy and SLA policy.
    """
    existing = session.scalar(select(CaseRow).where(CaseRow.idempotency_key == idempotency_key))
    if existing is not None:
        return existing, False

    meta = ISSUE_TAXONOMY.get(issue_code, ISSUE_TAXONOMY["UNKNOWN_ISSUE"])
    priority = meta["priority"]
    row = CaseRow(
        case_id=f"CASE-{uuid4().hex[:8].upper()}",
        session_id=session_id,
        customer_ref=customer_ref,
        case_type=meta["type"],
        issue_code=issue_code,
        priority=priority,
        summary=safe_transcript(summary),
        key_lines_json=[safe_transcript(line) for line in (key_lines or [])],
        actions_tried_json=list(actions_tried or []),
        callback_id=callback_id,
        assigned_team=meta["team"],
        status="NEW",
        sla_due_at=now + timedelta(hours=meta["sla_hours"]),
        first_response_due_at=now + timedelta(minutes=FIRST_RESPONSE_MINUTES[priority]),
        idempotency_key=idempotency_key,
        category=issue_code,
        description=safe_transcript(summary),
        callback_requested=callback_id is not None,
        callback_cancelled=False,
        source=source,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    _record_event(session, row.case_id, "CREATED", actor=actor, to_value=f"{issue_code}/{priority}", at=now)
    emit_event(session, "case.created", "CASE", row.case_id, {
        "case_id": row.case_id, "session_id": session_id, "customer_ref": customer_ref,
        "issue_code": issue_code, "priority": priority, "status": "NEW",
        "assigned_team": row.assigned_team, "callback_id": callback_id,
        "sla_due_at": _iso(row.sla_due_at),
    }, idempotency_key=f"case.created:{row.case_id}")
    auto_assign(session, row, actor="SYSTEM", now=now)
    return row, True


def _open_case_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(CaseRow.assigned_agent_id, func.count(CaseRow.case_id))
        .where(CaseRow.assigned_agent_id.is_not(None), CaseRow.status.in_(OPEN_STATUSES))
        .group_by(CaseRow.assigned_agent_id)
    ).all()
    return {agent_id: count for agent_id, count in rows}


def find_eligible_agent(session: Session, case: CaseRow) -> AgentRow | None:
    """Least-loaded AVAILABLE agent whose skills cover the case and who has spare capacity."""
    customer = session.get(CustomerRow, case.customer_ref)
    language = customer.preferred_language if customer else None
    counts = _open_case_counts(session)
    candidates: list[tuple[int, int, str, AgentRow]] = []
    for agent in session.scalars(select(AgentRow).where(AgentRow.availability == "AVAILABLE")).all():
        skills = set(agent.skills_json or [])
        if not ({case.issue_code, case.assigned_team, "GENERAL_SUPPORT"} & skills):
            continue
        if case.assigned_team == "SECURITY_DESK" and not ({"SECURITY_CONCERN", "SECURITY_DESK"} & skills):
            continue
        load = counts.get(agent.agent_id, 0)
        if load >= (agent.max_open_cases or 12):
            continue
        language_rank = 0 if language and language in (agent.languages_json or []) else 1
        candidates.append((load, language_rank, agent.agent_id, agent))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[:3])
    return candidates[0][3]


def auto_assign(session: Session, case: CaseRow, *, actor: str, now: datetime) -> AgentRow | None:
    agent = find_eligible_agent(session, case)
    if agent is None:
        _record_event(session, case.case_id, "QUEUED_UNASSIGNED", actor=actor,
                      note="No available agent with matching skills and capacity", at=now)
        return None
    _assign(session, case, agent, actor=actor, actor_role=None, now=now, reason="AUTO")
    return agent


def _assign(session: Session, case: CaseRow, agent: AgentRow, *, actor: str, actor_role: str | None,
            now: datetime, reason: str) -> None:
    previous = case.assigned_agent_id
    case.assigned_agent_id = agent.agent_id
    case.assigned_at = now
    if case.status == "NEW":
        case.status = "ASSIGNED"
    case.updated_at = now
    event_type = "REASSIGNED" if previous else "ASSIGNED"
    _record_event(session, case.case_id, event_type, actor=actor, actor_role=actor_role,
                  from_value=previous, to_value=agent.agent_id, note=reason, at=now)
    emit_event(session, f"case.{event_type.lower()}", "CASE", case.case_id, {
        "case_id": case.case_id, "assigned_agent_id": agent.agent_id, "previous_agent_id": previous,
        "priority": case.priority, "issue_code": case.issue_code, "status": case.status,
        "assigned_team": case.assigned_team,
    }, idempotency_key=f"case.{event_type.lower()}:{case.case_id}:{agent.agent_id}:{now.timestamp()}")
    # A linked callback follows the case owner unless staff already assigned it explicitly.
    if case.callback_id:
        callback = session.get(CallbackRow, case.callback_id)
        if callback is not None and callback.assigned_agent_id in (None, previous):
            callback.assigned_agent_id = agent.agent_id


class CaseService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_case(
        self,
        session_id: str,
        customer_ref: str,
        issue_code: str,
        summary: str = "",
        key_lines: list[str] | None = None,
        actions_tried: list[str] | None = None,
        callback_id: str | None = None,
        idempotency_key: str | None = None,
        actor: str = "SUBBU",
        source: str = "STAFF",
    ) -> dict[str, Any]:
        """Create support case per Spec §9. Idempotent on {call_id}:case:{issue_code}."""
        issue_code = normalize_issue_code(issue_code)
        idem_key = idempotency_key or f"{session_id}:case:{issue_code}"
        now = datetime.now(timezone.utc)
        with self.database.session() as db_session:
            with db_session.begin():
                if db_session.get(SessionRow, session_id) is None:
                    db_session.add(SessionRow(session_id=session_id, customer_ref=customer_ref,
                                              current_state="ISSUE_CAPTURE", created_at=now, updated_at=now))
                    db_session.flush()
                row, _created = build_case_row(
                    db_session, session_id=session_id, customer_ref=customer_ref, issue_code=issue_code,
                    summary=summary, key_lines=key_lines, actions_tried=actions_tried, callback_id=callback_id,
                    idempotency_key=idem_key, actor=actor, source=source, now=now,
                )
                return self._serialize_case(row, db_session)

    def assign_case(self, case_id: str, agent_id: str | None, *, actor: str, actor_role: str | None = None) -> dict[str, Any]:
        """Assign to a named agent, or auto-assign when ``agent_id`` is None."""
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            with s.begin():
                case = self._get_for_update(s, case_id)
                if case.status in ("RESOLVED", "CLOSED", "CANCELLED"):
                    raise CaseError("Closed cases cannot be reassigned")
                if agent_id is None:
                    agent = find_eligible_agent(s, case)
                    if agent is None:
                        raise CaseError("No available agent with matching skills and capacity")
                else:
                    agent = s.get(AgentRow, agent_id)
                    if agent is None:
                        raise KeyError(f"Agent {agent_id} not found")
                    if agent.availability == "OFFLINE":
                        raise CaseError("Cannot assign to an offline agent")
                if case.assigned_agent_id == agent.agent_id:
                    return self._serialize_case(case, s)
                _assign(s, case, agent, actor=actor, actor_role=actor_role, now=now,
                        reason="AUTO" if agent_id is None else "MANUAL")
                return self._serialize_case(case, s)

    def unassign_case(self, case_id: str, *, actor: str, actor_role: str | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            with s.begin():
                case = self._get_for_update(s, case_id)
                if case.assigned_agent_id:
                    _record_event(s, case_id, "UNASSIGNED", actor=actor, actor_role=actor_role,
                                  from_value=case.assigned_agent_id, at=now)
                    case.assigned_agent_id = None
                    case.assigned_at = None
                    if case.status == "ASSIGNED":
                        case.status = "NEW"
                    case.updated_at = now
                return self._serialize_case(case, s)

    def set_status(self, case_id: str, status: str, *, actor: str, actor_role: str | None = None,
                   note: str | None = None) -> dict[str, Any]:
        status = status.upper()
        if status == "OPEN":
            status = "IN_PROGRESS"
        if status not in CASE_STATUSES:
            raise CaseError(f"Unknown case status {status}")
        if status == "RESOLVED" and not (note and note.strip()):
            raise CaseError("Resolution notes are required to resolve a case")
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            with s.begin():
                case = self._get_for_update(s, case_id)
                previous = case.status
                if previous == status:
                    return self._serialize_case(case, s)
                if previous in ("CLOSED", "CANCELLED"):
                    raise CaseError(f"Case is {previous.lower()} and cannot change status")
                case.status = status
                case.updated_at = now
                if status == "RESOLVED":
                    case.resolved_at = now
                    case.resolution_notes = safe_transcript(note or "")
                elif previous == "RESOLVED":
                    case.resolved_at = None
                _record_event(s, case_id, "STATUS_CHANGED", actor=actor, actor_role=actor_role,
                              from_value=previous, to_value=status, note=safe_transcript(note) if note else None, at=now)
                emit_event(s, "case.resolved" if status == "RESOLVED" else "case.status_changed", "CASE", case_id, {
                    "case_id": case_id, "status": status, "previous_status": previous,
                    "assigned_agent_id": case.assigned_agent_id, "priority": case.priority,
                }, idempotency_key=f"case.status:{case_id}:{status}:{now.timestamp()}")
                return self._serialize_case(case, s)

    def add_note(self, case_id: str, note: str, *, actor: str, actor_role: str | None = None) -> dict[str, Any]:
        if not note or not note.strip():
            raise CaseError("Note text is required")
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            with s.begin():
                case = self._get_for_update(s, case_id)
                _record_event(s, case_id, "NOTE_ADDED", actor=actor, actor_role=actor_role,
                              note=safe_transcript(note.strip()[:4000]), at=now)
                case.updated_at = now
                if case.status == "ASSIGNED":
                    case.status = "IN_PROGRESS"
                return self._serialize_case(case, s)

    def update_case(self, case_id: str, patch: dict[str, Any], actor: str = "STAFF",
                    actor_role: str | None = None) -> dict[str, Any]:
        """Compatibility patch endpoint; routes each field through the governed lifecycle methods."""
        result: dict[str, Any] | None = None
        if "assigned_agent_id" in patch or "assignedAgentId" in patch:
            agent_id = patch.get("assigned_agent_id", patch.get("assignedAgentId"))
            result = (self.assign_case(case_id, agent_id, actor=actor, actor_role=actor_role)
                      if agent_id else self.unassign_case(case_id, actor=actor, actor_role=actor_role))
        if "status" in patch:
            result = self.set_status(case_id, str(patch["status"]), actor=actor, actor_role=actor_role,
                                     note=patch.get("resolution_notes") or patch.get("resolutionNotes") or patch.get("note"))
        elif patch.get("note"):
            result = self.add_note(case_id, str(patch["note"]), actor=actor, actor_role=actor_role)
        simple = {k: patch[k] for k in ("priority", "assigned_team", "callback_id", "callback_cancelled", "summary") if k in patch}
        if simple:
            now = datetime.now(timezone.utc)
            with self.database.session() as s:
                with s.begin():
                    case = self._get_for_update(s, case_id)
                    if "priority" in simple:
                        new_priority = _priority(simple["priority"])
                        if new_priority != case.priority:
                            _record_event(s, case_id, "PRIORITY_CHANGED", actor=actor, actor_role=actor_role,
                                          from_value=case.priority, to_value=new_priority, at=now)
                            case.priority = new_priority
                    if "assigned_team" in simple:
                        case.assigned_team = str(simple["assigned_team"])
                    if "callback_id" in simple:
                        case.callback_id = simple["callback_id"]
                        case.callback_requested = simple["callback_id"] is not None
                    if "callback_cancelled" in simple:
                        case.callback_cancelled = bool(simple["callback_cancelled"])
                    if "summary" in simple:
                        case.summary = safe_transcript(str(simple["summary"]))
                        case.description = case.summary
                    case.updated_at = now
                    result = self._serialize_case(case, s)
        if result is None:
            found = self.get_case(case_id)
            if found is None:
                raise KeyError(f"Case {case_id} not found")
            return found
        return result

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        with self.database.session() as db_session:
            row = db_session.get(CaseRow, case_id)
            if row is None:
                return None
            return self._serialize_case(row, db_session, include_history=True)

    def list_cases(self, session_id: str | None = None, *, status: str | None = None,
                   assigned_agent_id: str | None = None, unassigned: bool = False,
                   limit: int = 500) -> list[dict[str, Any]]:
        with self.database.session() as db_session:
            stmt = select(CaseRow).order_by(CaseRow.created_at.desc()).limit(limit)
            if session_id:
                stmt = stmt.where(CaseRow.session_id == session_id)
            if status == "OPEN":
                stmt = stmt.where(CaseRow.status.in_(OPEN_STATUSES))
            elif status:
                stmt = stmt.where(CaseRow.status == status.upper())
            if assigned_agent_id:
                stmt = stmt.where(CaseRow.assigned_agent_id == assigned_agent_id)
            if unassigned:
                stmt = stmt.where(CaseRow.assigned_agent_id.is_(None))
            rows = db_session.scalars(stmt).all()
            return [self._serialize_case(r, db_session) for r in rows]

    @staticmethod
    def _get_for_update(session: Session, case_id: str) -> CaseRow:
        row = session.scalar(select(CaseRow).where(CaseRow.case_id == case_id).with_for_update())
        if row is None:
            raise KeyError(f"Case {case_id} not found")
        return row

    @staticmethod
    def _serialize_case(row: CaseRow, db_session: Session | None = None, include_history: bool = False) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        is_open = row.status in OPEN_STATUSES
        sla_breached = bool(is_open and row.sla_due_at and row.sla_due_at < now)
        agent_name = None
        masked_phone = ""
        customer_name = None
        history: list[dict[str, Any]] = []
        if db_session is not None:
            if row.assigned_agent_id:
                agent = db_session.get(AgentRow, row.assigned_agent_id)
                agent_name = agent.name if agent else None
            customer = db_session.get(CustomerRow, row.customer_ref)
            if customer is not None:
                masked_phone = mask_phone(customer.phone)
                customer_name = customer.full_name
            if include_history:
                events = db_session.scalars(
                    select(CaseEventRow).where(CaseEventRow.case_id == row.case_id).order_by(CaseEventRow.created_at.asc())
                ).all()
                history = [{
                    "event_id": e.event_id, "event_type": e.event_type, "from_value": e.from_value,
                    "to_value": e.to_value, "note": e.note, "actor": e.actor, "actor_role": e.actor_role,
                    "created_at": _iso(e.created_at),
                } for e in events]
        data = {
            "case_id": row.case_id,
            "id": row.case_id,
            "session_id": row.session_id,
            "call_id": row.session_id,
            "customer_ref": row.customer_ref,
            "customerRef": row.customer_ref,
            "customer_name": customer_name,
            "masked_phone": masked_phone,
            "case_type": row.case_type,
            "issue_code": row.issue_code,
            "category": row.issue_code,
            "priority": row.priority,
            "summary": row.summary,
            "description": row.summary or row.description,
            "key_lines": row.key_lines_json,
            "actions_tried": row.actions_tried_json,
            "callback_id": row.callback_id,
            "callback_requested": row.callback_requested,
            "callback_cancelled": row.callback_cancelled,
            "assigned_team": row.assigned_team,
            "assigned_agent_id": row.assigned_agent_id,
            "assignedAgentId": row.assigned_agent_id,
            "assigned_agent_name": agent_name,
            "assigned_at": _iso(row.assigned_at),
            "status": row.status,
            "source": row.source,
            "sla_due_at": _iso(row.sla_due_at),
            "slaDueAt": _iso(row.sla_due_at),
            "first_response_due_at": _iso(row.first_response_due_at),
            "sla_breached": sla_breached,
            "resolved_at": _iso(row.resolved_at),
            "resolution_notes": row.resolution_notes,
            "created_at": _iso(row.created_at),
            "createdAt": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }
        if include_history:
            data["history"] = history
        return data
