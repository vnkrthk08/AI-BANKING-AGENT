"""SQLAlchemy tables. Domain services use the repository contracts instead."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
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
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
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


class OperationsAuditEventRow(Base):
    __tablename__ = "operations_audit_events"

    event_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"AUD-{uuid4().hex[:8].upper()}")
    actor: Mapped[str] = mapped_column(String(60), default="SUBBU", nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), default="OPS_MANAGER", nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str] = mapped_column(String(45), default="127.0.0.1", nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class CustomerRow(Base):
    __tablename__ = "customers"

    customer_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(20), default="Hindi", nullable=False)
    app_status: Mapped[str] = mapped_column(String(30), default="NOT_INSTALLED", nullable=False)
    app_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dnd_status: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    account_type: Mapped[str] = mapped_column(String(40), default="SAVINGS", nullable=False)
    branch: Mapped[str] = mapped_column(String(80), default="Mumbai Metro", nullable=False)
    region: Mapped[str] = mapped_column(String(40), default="West", nullable=False)
    assigned_agent_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class CampaignRow(Base):
    __tablename__ = "campaigns"

    campaign_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"CMP-{uuid4().hex[:8].upper()}")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    objective: Mapped[str] = mapped_column(String(80), default="App adoption", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    script_version: Mapped[str] = mapped_column(String(20), default="v1.0", nullable=False)
    segment_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    retry_gap_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    languages_json: Mapped[list[str]] = mapped_column("languages", JSON, default=lambda: ["Hindi", "English"], nullable=False)
    region: Mapped[str] = mapped_column(String(60), default="All India", nullable=False)
    calls_dialed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    answer_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class CampaignContactRow(Base):
    __tablename__ = "campaign_contacts"
    __table_args__ = (
        UniqueConstraint("campaign_id", "customer_ref", name="uq_campaign_customer"),
        Index("ix_campaign_dial_queue", "campaign_id", "status", "next_attempt_at"),
    )

    contact_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"CNT-{uuid4().hex[:8].upper()}")
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.campaign_id", ondelete="CASCADE"), nullable=False, index=True)
    customer_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
    attempts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_disposition: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class CallRecordRow(Base):
    __tablename__ = "call_records"

    call_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"CALL-{uuid4().hex[:8].upper()}")
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id", ondelete="CASCADE"), unique=True, nullable=False)
    customer_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.campaign_id", ondelete="SET NULL"), nullable=True, index=True)
    campaign_name: Mapped[str] = mapped_column(String(128), default="Inbound / Direct", nullable=False)
    masked_phone: Mapped[str] = mapped_column(String(20), default="+91 98XXX XX000", nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="Hindi", nullable=False)
    region: Mapped[str] = mapped_column(String(40), default="West", nullable=False)
    branch: Mapped[str] = mapped_column(String(80), default="Mumbai Metro", nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    duration_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    disposition: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolution_mode: Mapped[str] = mapped_column(String(20), default="AI", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="IN_PROGRESS", nullable=False)
    connected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    consented: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    app_installed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    app_updated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    app_version: Mapped[str] = mapped_column(String(20), default="—", nullable=False)
    sentiment: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    issue_category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    callback_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    escalation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    kural_state: Mapped[str] = mapped_column(String(40), default="READY", nullable=False)
    intent: Mapped[str] = mapped_column(String(40), default="UNKNOWN", nullable=False)
    policy_decision: Mapped[str] = mapped_column(String(20), default="ALLOWED", nullable=False)
    cost_inr: Mapped[float] = mapped_column(Float, default=0.50, nullable=False)
    compliance_flags_json: Mapped[list[str]] = mapped_column("compliance_flags", JSON, default=list, nullable=False)
    feature_interest_json: Mapped[list[str]] = mapped_column("feature_interest", JSON, default=list, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recording_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recording_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class AgentRow(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    team: Mapped[str] = mapped_column(String(80), nullable=False)
    languages_json: Mapped[list[str]] = mapped_column("languages", JSON, default=lambda: ["Hindi", "English"], nullable=False)
    availability: Mapped[str] = mapped_column(String(20), default="AVAILABLE", nullable=False)
    active_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    handled_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_resolution_min: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    sla_hit_percent: Mapped[int] = mapped_column(Integer, default=95, nullable=False)
    skills_json: Mapped[list[str]] = mapped_column("skills", JSON, default=lambda: ["APP_SUPPORT", "GENERAL_SUPPORT"], nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class ReportScheduleRow(Base):
    __tablename__ = "report_schedules"

    schedule_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"SCH-{uuid4().hex[:8].upper()}")
    cadence: Mapped[str] = mapped_column(String(20), default="DAILY", nullable=False)
    time_of_day: Mapped[str] = mapped_column(String(10), default="08:00", nullable=False)
    formats_json: Mapped[list[str]] = mapped_column("formats", JSON, default=lambda: ["PDF", "XLSX"], nullable=False)
    recipient: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    demo_only: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


