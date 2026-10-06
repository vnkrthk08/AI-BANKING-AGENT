"""Case domain service: support case creation, taxonomy mapping, SLA calculation, and idempotency."""

from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import CaseRow, OutboxRow, SessionRow
from kural.services.event_bus import event_bus

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
    ) -> dict[str, Any]:
        """Create support case per Spec §9. Idempotent on {call_id}:case:{issue_code}."""
        idem_key = idempotency_key or f"{session_id}:case:{issue_code}"
        now = datetime.now(timezone.utc)

        with self.database.session() as db_session:
            with db_session.begin():
                sess = db_session.get(SessionRow, session_id)
                if sess is None:
                    db_session.add(
                        SessionRow(
                            session_id=session_id,
                            customer_ref=customer_ref,
                            current_state="ISSUE_CAPTURE",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    db_session.flush()

                existing = db_session.scalar(
                    select(CaseRow).where(CaseRow.idempotency_key == idem_key)
                )
                if existing is not None:
                    return self._serialize_case(existing)

                meta = ISSUE_TAXONOMY.get(issue_code, ISSUE_TAXONOMY["UNKNOWN_ISSUE"])
                sla_due_at = now + timedelta(hours=meta["sla_hours"])
                case_id = f"CASE-{uuid4().hex[:8].upper()}"

                row = CaseRow(
                    case_id=case_id,
                    session_id=session_id,
                    customer_ref=customer_ref,
                    case_type=meta["type"],
                    issue_code=issue_code,
                    priority=meta["priority"],
                    summary=summary,
                    key_lines_json=key_lines or [],
                    actions_tried_json=actions_tried or [],
                    callback_id=callback_id,
                    assigned_team=meta["team"],
                    status="NEW",
                    sla_due_at=sla_due_at,
                    idempotency_key=idem_key,
                    category=issue_code,
                    description=summary,
                    callback_requested=callback_id is not None,
                    callback_cancelled=False,
                    created_at=now,
                    updated_at=now,
                )
                db_session.add(row)

                outbox_payload = {
                    "case_id": case_id,
                    "session_id": session_id,
                    "customer_ref": customer_ref,
                    "issue_code": issue_code,
                    "priority": row.priority,
                    "status": "NEW",
                    "assigned_team": row.assigned_team,
                    "callback_id": callback_id,
                }
                outbox_row = OutboxRow(
                    event_topic="case.created",
                    payload_json=outbox_payload,
                    created_at=now,
                )
                db_session.add(outbox_row)
                db_session.flush()

                result = self._serialize_case(row)
                event_bus.publish("case.created", outbox_payload)
                return result

    def update_case(
        self,
        case_id: str,
        patch: dict[str, Any],
        actor: str = "STAFF",
    ) -> dict[str, Any]:
        """Update case status, assigned team, note, or callback link."""
        now = datetime.now(timezone.utc)
        with self.database.session() as db_session:
            with db_session.begin():
                row = db_session.get(CaseRow, case_id)
                if row is None:
                    raise KeyError(f"Case {case_id} not found")

                if "status" in patch:
                    row.status = str(patch["status"])
                if "priority" in patch:
                    row.priority = str(patch["priority"])
                if "assigned_team" in patch:
                    row.assigned_team = str(patch["assigned_team"])
                if "callback_id" in patch:
                    row.callback_id = patch["callback_id"]
                    row.callback_requested = patch["callback_id"] is not None
                if "callback_cancelled" in patch:
                    row.callback_cancelled = bool(patch["callback_cancelled"])
                if "summary" in patch:
                    row.summary = str(patch["summary"])
                    row.description = str(patch["summary"])

                row.updated_at = now

                outbox_payload = {
                    "case_id": case_id,
                    "status": row.status,
                    "priority": row.priority,
                    "assigned_team": row.assigned_team,
                    "callback_id": row.callback_id,
                }
                outbox_row = OutboxRow(
                    event_topic="case.updated",
                    payload_json=outbox_payload,
                    created_at=now,
                )
                db_session.add(outbox_row)
                db_session.flush()

                result = self._serialize_case(row)
                event_bus.publish("case.updated", outbox_payload)
                return result

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        with self.database.session() as db_session:
            row = db_session.get(CaseRow, case_id)
            if row is None:
                return None
            return self._serialize_case(row)

    def list_cases(self, session_id: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as db_session:
            stmt = select(CaseRow).order_by(CaseRow.created_at.desc())
            if session_id:
                stmt = stmt.where(CaseRow.session_id == session_id)
            rows = db_session.scalars(stmt).all()
            return [self._serialize_case(r) for r in rows]

    @staticmethod
    def _serialize_case(row: CaseRow) -> dict[str, Any]:
        return {
            "case_id": row.case_id,
            "id": row.case_id,
            "session_id": row.session_id,
            "call_id": row.session_id,
            "customer_ref": row.customer_ref,
            "customerRef": row.customer_ref,
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
            "status": row.status,
            "sla_due_at": row.sla_due_at.isoformat() if row.sla_due_at else None,
            "slaDueAt": row.sla_due_at.isoformat() if row.sla_due_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
