"""SQLAlchemy tables. Domain services use the repository contracts instead."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator[datetime]):
    """Keep timestamps UTC-aware on PostgreSQL and SQLite alike."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    current_state: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class ConversationTurnRow(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (UniqueConstraint("session_id", "turn_order", name="uq_turn_session_order"),)

    turn_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    turn_order: Mapped[int] = mapped_column(Integer, nullable=False)
    sanitized_user_text: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class CaseRow(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"CASE-{uuid4().hex[:8].upper()}")
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    customer_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    case_type: Mapped[str] = mapped_column(String(60), default="APP_SUPPORT", nullable=False)
    issue_code: Mapped[str] = mapped_column(String(60), default="UNKNOWN_ISSUE", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="Normal", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    key_lines_json: Mapped[list[str]] = mapped_column("key_lines", JSON, default=list, nullable=False)
    actions_tried_json: Mapped[list[str]] = mapped_column("actions_tried", JSON, default=list, nullable=False)
    callback_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assigned_team: Mapped[str] = mapped_column(String(60), default="APP_SUPPORT", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="NEW", nullable=False)
    sla_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)

    category: Mapped[str] = mapped_column(String(60), default="GENERAL_SUPPORT", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    callback_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    callback_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class CallbackRow(Base):
    __tablename__ = "callbacks"
    __table_args__ = (
        Index(
            "uq_scheduled_case",
            "case_id",
            unique=True,
            sqlite_where=text("status = 'SCHEDULED' AND case_id IS NOT NULL"),
            postgresql_where=text("status = 'SCHEDULED' AND case_id IS NOT NULL"),
        ),
        Index(
            "uq_scheduled_call_no_case",
            "session_id",
            unique=True,
            sqlite_where=text("status = 'SCHEDULED' AND case_id IS NULL"),
            postgresql_where=text("status = 'SCHEDULED' AND case_id IS NULL"),
        ),
    )

    callback_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"CB-{uuid4().hex[:8].upper()}")
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    customer_ref: Mapped[str] = mapped_column(String(64), default="demo-001", nullable=False)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.case_id", ondelete="SET NULL"), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(String(60), default="CUSTOMER_BUSY", nullable=False)
    raw_expression: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_text_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scheduled_at_utc: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    scheduled_at_local: Mapped[str | None] = mapped_column(String(60), nullable=True)
    timezone: Mapped[str] = mapped_column(String(40), default="Asia/Kolkata", nullable=False)
    resolution_rule: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confirmed_by_customer: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="SCHEDULED", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    assigned_agent_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    language: Mapped[str] = mapped_column(String(20), default="en-IN", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    rescheduled_from_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Legacy compatibility column
    requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class CallbackEventRow(Base):
    __tablename__ = "callback_events"

    event_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"CBE-{uuid4().hex[:12].upper()}")
    callback_id: Mapped[str] = mapped_column(ForeignKey("callbacks.callback_id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(60), default="SUBBU", nullable=False)
    call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class OutboxRow(Base):
    __tablename__ = "outbox"

    outbox_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"OUT-{uuid4().hex[:12].upper()}")
    event_topic: Mapped[str] = mapped_column(String(60), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column("payload", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

