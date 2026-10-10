"""SQLAlchemy implementation of KURAL's domain-level repository contract."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from kural.cases.models import CallbackRequest, SupportCase
from kural.conversation.session import Conversation
from kural.models import State
from kural.persistence.database import Database
from kural.persistence.models import AuditEventRow, CallbackRow, CaseRow, ConversationTurnRow, SessionRow
from kural.privacy.transcript import safe_transcript
from kural.repositories import KuralRepository, RepositoryTransaction


class SqlAlchemyKuralRepository(KuralRepository):
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def transaction(self) -> Iterator["SqlAlchemyUnitOfWork"]:
        with self.database.session() as session:
            with session.begin():
                yield SqlAlchemyUnitOfWork(session)

    def get_session(self, session_id: str) -> Conversation | None:
        with self.database.session() as session:
            row = session.get(SessionRow, session_id)
            return self._conversation(row, session) if row else None

    def health_check(self) -> None:
        with self.database.session() as session:
            session.execute(text("SELECT 1"))

    def get_session_detail(self, session_id: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            row = session.get(SessionRow, session_id)
            if row is None:
                return None
            turns = session.scalars(select(ConversationTurnRow).where(
                ConversationTurnRow.session_id == session_id).order_by(ConversationTurnRow.turn_order)).all()
            return {
                "session_id": row.session_id,
                "customer_ref": row.customer_ref,
                "current_state": row.current_state,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "turns": [{
                    "turn_order": turn.turn_order,
                    "text": turn.sanitized_user_text,
                    "intent": turn.intent,
                    "state": turn.state,
                    "response": turn.response,
                    "outcome": turn.outcome,
                    "timestamp": turn.timestamp,
                } for turn in turns],
            }

    def list_cases(self) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = session.scalars(select(CaseRow).order_by(CaseRow.created_at.desc())).all()
            return [{key: getattr(row, key) for key in (
                "case_id", "session_id", "customer_ref", "category", "description", "status",
                "callback_requested", "created_at", "updated_at",
            )} for row in rows]

    def list_callbacks(self, session_id: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as session:
            statement = select(CallbackRow).order_by(CallbackRow.created_at.desc())
            if session_id is not None:
                statement = statement.where(CallbackRow.session_id == session_id)
            rows = session.scalars(statement).all()
            return [{key: getattr(row, key) for key in (
                "callback_id", "session_id", "case_id", "requested_at", "status", "created_at", "updated_at",
            )} for row in rows]

    def list_audit_events(self, session_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = session.scalars(select(AuditEventRow).where(
                AuditEventRow.session_id == session_id).order_by(AuditEventRow.timestamp, AuditEventRow.event_id)).all()
            return [{
                "event_id": row.event_id, "session_id": row.session_id,
                "event_type": row.event_type, "state": row.state,
                "metadata": row.metadata_json, "timestamp": row.timestamp,
            } for row in rows]

    @staticmethod
    def _conversation(row: SessionRow, session: Session) -> Conversation:
        turn_count = session.scalar(select(func.count()).select_from(ConversationTurnRow).where(
            ConversationTurnRow.session_id == row.session_id)) or 0
        case_id = session.scalar(select(CaseRow.case_id).where(
            CaseRow.session_id == row.session_id).order_by(CaseRow.created_at.desc()).limit(1))
        callback_id = session.scalar(select(CallbackRow.callback_id).where(
            CallbackRow.session_id == row.session_id).order_by(CallbackRow.created_at.desc()).limit(1))
        conv = Conversation(row.session_id, row.customer_ref, State(row.current_state),
                            row.created_at, row.updated_at, turn_count, case_id, callback_id)
        ctx = getattr(row, "context_json", None) or {}
        conv.detour_depth = ctx.get("detour_depth", 0)
        conv.return_state = State(ctx["return_state"]) if ctx.get("return_state") else None
        conv.known_customer_facts = dict(ctx.get("known_customer_facts", {}))
        conv.unknown_required_fields = list(ctx.get("unknown_required_fields", []))
        conv.active_question = ctx.get("active_question")
        conv.active_issue = ctx.get("active_issue")
        conv.conversation_summary = ctx.get("conversation_summary", "")
        conv.recent_relevant_turns = list(ctx.get("recent_relevant_turns", []))
        return conv


class SqlAlchemyUnitOfWork(RepositoryTransaction):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_session(self, session_id: str, customer_ref: str, state: State) -> Conversation:
        now = datetime.now(timezone.utc)
        row = SessionRow(session_id=session_id, customer_ref=customer_ref,
                         current_state=state.value, context_json={}, created_at=now, updated_at=now)
        self.session.add(row)
        self.session.flush()
        return Conversation(session_id, customer_ref, state, now, now, 0)

    def get_session(self, session_id: str) -> Conversation | None:
        row = self.session.scalar(select(SessionRow).where(
            SessionRow.session_id == session_id).with_for_update())
        return SqlAlchemyKuralRepository._conversation(row, self.session) if row else None

    def update_state(self, session_id: str, state: State) -> None:
        row = self.session.get(SessionRow, session_id)
        if row is None:
            raise KeyError("Session not found")
        row.current_state = state.value
        row.updated_at = datetime.now(timezone.utc)

    def update_session(self, conversation: Conversation) -> None:
        row = self.session.get(SessionRow, conversation.session_id)
        if row is None:
            raise KeyError("Session not found")
        row.current_state = conversation.state.value
        row.context_json = {
            "detour_depth": conversation.detour_depth,
            "return_state": conversation.return_state.value if conversation.return_state else None,
            "known_customer_facts": conversation.known_customer_facts,
            "unknown_required_fields": conversation.unknown_required_fields,
            "active_question": conversation.active_question,
            "active_issue": conversation.active_issue,
            "conversation_summary": conversation.conversation_summary,
            "recent_relevant_turns": conversation.recent_relevant_turns,
        }
        row.updated_at = datetime.now(timezone.utc)

    def add_turn(self, session_id: str, turn_order: int, text: str, intent: str,
                 state: State, response: str, outcome: str) -> None:
        session_row = self.session.get(SessionRow, session_id)
        if session_row is None:
            raise KeyError("Session not found")
        session_row.updated_at = datetime.now(timezone.utc)
        self.session.add(ConversationTurnRow(
            session_id=session_id, turn_order=turn_order, sanitized_user_text=safe_transcript(text),
            intent=intent, state=state.value, response=response, outcome=outcome,
        ))

    def add_audit_event(self, session_id: str, event_type: str, state: State | None,
                        metadata: dict[str, Any]) -> None:
        self.session.add(AuditEventRow(
            event_id=str(uuid4()), session_id=session_id, event_type=event_type,
            state=state.value if state is not None else None,
            metadata_json=_sanitize_metadata(metadata), timestamp=datetime.now(timezone.utc),
        ))

    def create_case(self, session_id: str, customer_ref: str, category: str,
                    description: str, status: str) -> SupportCase:
        """AI-raised cases share the operational taxonomy, SLA, idempotency and auto-assignment."""
        from kural.services.case_service import build_case_row, normalize_issue_code

        now = datetime.now(timezone.utc)
        issue_code = normalize_issue_code(category)
        row, _ = build_case_row(
            self.session, session_id=session_id, customer_ref=customer_ref, issue_code=issue_code,
            summary=description, key_lines=None, actions_tried=None, callback_id=None,
            idempotency_key=f"{session_id}:case:{issue_code}", actor="SUBBU", source="VOICE_AI", now=now,
        )
        row.category = category
        return SupportCase(row.case_id, session_id, customer_ref, category, row.description,
                           row.status, False, now, now)

    def request_callback(self, session_id: str, case_id: str | None,
                         requested_at: datetime | None = None, *, customer_ref: str | None = None,
                         readback: str | None = None, rule: str | None = None,
                         raw_expression: str | None = None) -> CallbackRequest:
        """Persist the customer's callback request. With an agreed time it is SCHEDULED (and the
        customer is told the time); without one it is REQUESTED for a human to agree a time."""
        now = datetime.now(timezone.utc)
        if customer_ref is None:
            sess = self.session.get(SessionRow, session_id)
            customer_ref = sess.customer_ref if sess else "unknown"
        if requested_at is not None and readback is not None:
            from kural.services.callback_service import CallbackDraft, format_local, schedule_callback_in_session
            draft = CallbackDraft(scheduled_at_utc=requested_at, scheduled_at_local=format_local(requested_at),
                                  raw_expression=raw_expression, reason="CUSTOMER_BUSY" if case_id is None else "SUPPORT_FOLLOW_UP",
                                  case_id=case_id, rule=rule)
            row, _ = schedule_callback_in_session(self.session, session_id=session_id, customer_ref=customer_ref,
                                                  draft=draft, idempotency_key=None, actor="SUBBU", now=now)
            return CallbackRequest(row.callback_id, session_id, case_id, requested_at, row.status, now, now)
        if case_id is not None:
            case = self.session.get(CaseRow, case_id)
            if case is None:
                raise KeyError("Case not found")
            case.callback_requested = True
            case.updated_at = now
        row = CallbackRow(callback_id=f"CB-{uuid4().hex[:8].upper()}", session_id=session_id, case_id=case_id, customer_ref=customer_ref,
                          requested_at=requested_at, scheduled_at_utc=requested_at,
                          reason="CUSTOMER_BUSY" if case_id is None else "SUPPORT_FOLLOW_UP",
                          status="REQUESTED", created_at=now, updated_at=now,
                          idempotency_key=f"{session_id}:callback-request:{case_id or 'none'}")
        if case_id is not None:
            case = self.session.get(CaseRow, case_id)
            if case is not None:
                case.callback_id = row.callback_id
                row.assigned_agent_id = case.assigned_agent_id
        self.session.add(row)
        self.session.flush()
        from kural.services.callback_service import _event, _payload
        from kural.services.domain_events import emit_event
        _event(self.session, row.callback_id, "REQUESTED", actor="SUBBU", call_id=session_id, at=now)
        emit_event(self.session, "callback.requested", "CALLBACK", row.callback_id, _payload(row),
                   idempotency_key=f"callback.requested:{row.callback_id}")
        return CallbackRequest(row.callback_id, session_id, case_id, requested_at, row.status, now, now)


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe_fields = {"session_id", "case_id", "callback_id", "intent", "old", "new", "category", "status"}

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            return safe_transcript(value)
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value
    return {key: value if key in safe_fields else clean(value) for key, value in metadata.items()}

