"""Phase 2 and Phase 3 operations, campaign, call records, customer, and outbox schema.

Revision ID: 0002_phase2_phase3_operations
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_phase2_phase3_operations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    bool_false = sa.text("0") if is_sqlite else sa.text("false")
    bool_true = sa.text("1") if is_sqlite else sa.text("true")

    # 1. Update existing tables with new columns
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("context_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("case_type", sa.String(60), nullable=False, server_default="APP_SUPPORT"))
        batch_op.add_column(sa.Column("issue_code", sa.String(60), nullable=False, server_default="UNKNOWN_ISSUE"))
        batch_op.add_column(sa.Column("priority", sa.String(20), nullable=False, server_default="Normal"))
        batch_op.add_column(sa.Column("summary", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("key_lines", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("actions_tried", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("callback_id", sa.String(40), nullable=True))
        batch_op.add_column(sa.Column("assigned_team", sa.String(60), nullable=False, server_default="APP_SUPPORT"))
        batch_op.add_column(sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("callback_cancelled", sa.Boolean(), nullable=False, server_default=bool_false))
        batch_op.create_unique_constraint("uq_cases_idempotency_key", ["idempotency_key"])

    with op.batch_alter_table("callbacks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("customer_ref", sa.String(64), nullable=False, server_default="demo-001"))
        batch_op.add_column(sa.Column("reason", sa.String(60), nullable=False, server_default="CUSTOMER_BUSY"))
        batch_op.add_column(sa.Column("raw_expression", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("requested_text_normalized", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("scheduled_at_utc", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("scheduled_at_local", sa.String(60), nullable=True))
        batch_op.add_column(sa.Column("timezone", sa.String(40), nullable=False, server_default="Asia/Kolkata"))
        batch_op.add_column(sa.Column("resolution_rule", sa.String(40), nullable=True))
        batch_op.add_column(sa.Column("confirmed_by_customer", sa.Boolean(), nullable=False, server_default=bool_true))
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("assigned_agent_id", sa.String(40), nullable=True))
        batch_op.add_column(sa.Column("language", sa.String(20), nullable=False, server_default="en-IN"))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("rescheduled_from_id", sa.String(40), nullable=True))
        batch_op.add_column(sa.Column("superseded_by_id", sa.String(40), nullable=True))
        batch_op.create_unique_constraint("uq_callbacks_idempotency_key", ["idempotency_key"])

    # Partial indexes for scheduled callbacks
    op.create_index(
        "uq_scheduled_case",
        "callbacks",
        ["case_id"],
        unique=True,
        sqlite_where=sa.text("status = 'SCHEDULED' AND case_id IS NOT NULL"),
        postgresql_where=sa.text("status = 'SCHEDULED' AND case_id IS NOT NULL"),
    )
    op.create_index(
        "uq_scheduled_call_no_case",
        "callbacks",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text("status = 'SCHEDULED' AND case_id IS NULL"),
        postgresql_where=sa.text("status = 'SCHEDULED' AND case_id IS NULL"),
    )

    # 2. Create new tables
    op.create_table(
        "callback_events",
        sa.Column("event_id", sa.String(40), primary_key=True),
        sa.Column("callback_id", sa.String(40), sa.ForeignKey("callbacks.callback_id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(60), nullable=False, server_default="SUBBU"),
        sa.Column("call_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "outbox",
        sa.Column("outbox_id", sa.String(40), primary_key=True),
        sa.Column("event_topic", sa.String(60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "operations_audit_events",
        sa.Column("event_id", sa.String(40), primary_key=True),
        sa.Column("actor", sa.String(60), nullable=False, server_default="SUBBU"),
        sa.Column("actor_role", sa.String(40), nullable=False, server_default="OPS_MANAGER"),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("ip", sa.String(45), nullable=False, server_default="127.0.0.1"),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "customers",
        sa.Column("customer_ref", sa.String(64), primary_key=True),
        sa.Column("full_name", sa.String(128), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("email", sa.String(128), nullable=True),
        sa.Column("preferred_language", sa.String(20), nullable=False, server_default="Hindi"),
        sa.Column("app_status", sa.String(30), nullable=False, server_default="NOT_INSTALLED"),
        sa.Column("app_version", sa.String(20), nullable=True),
        sa.Column("dnd_status", sa.Boolean(), nullable=False, server_default=bool_false),
        sa.Column("account_type", sa.String(40), nullable=False, server_default="SAVINGS"),
        sa.Column("branch", sa.String(80), nullable=False, server_default="Mumbai Metro"),
        sa.Column("region", sa.String(40), nullable=False, server_default="West"),
        sa.Column("assigned_agent_id", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_customers_phone", "customers", ["phone"], unique=True)

    op.create_table(
        "campaigns",
        sa.Column("campaign_id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("objective", sa.String(80), nullable=False, server_default="App adoption"),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("script_version", sa.String(20), nullable=False, server_default="v1.0"),
        sa.Column("segment_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("retry_gap_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("languages", sa.JSON(), nullable=False, server_default=sa.text("'[\"Hindi\", \"English\"]'")),
        sa.Column("region", sa.String(60), nullable=False, server_default="All India"),
        sa.Column("calls_dialed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("answer_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "campaign_contacts",
        sa.Column("contact_id", sa.String(40), primary_key=True),
        sa.Column("campaign_id", sa.String(40), sa.ForeignKey("campaigns.campaign_id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("customer_ref", sa.String(64), nullable=False, index=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("attempts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_disposition", sa.String(40), nullable=True),
        sa.Column("last_session_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "customer_ref", name="uq_campaign_customer"),
    )
    op.create_index("ix_campaign_dial_queue", "campaign_contacts", ["campaign_id", "status", "next_attempt_at"])

    op.create_table(
        "call_records",
        sa.Column("call_id", sa.String(40), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("customer_ref", sa.String(64), nullable=False, index=True),
        sa.Column("campaign_id", sa.String(40), sa.ForeignKey("campaigns.campaign_id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("campaign_name", sa.String(128), nullable=False, server_default="Inbound / Direct"),
        sa.Column("masked_phone", sa.String(20), nullable=False, server_default="+91 98XXX XX000"),
        sa.Column("language", sa.String(20), nullable=False, server_default="Hindi"),
        sa.Column("region", sa.String(40), nullable=False, server_default="West"),
        sa.Column("branch", sa.String(80), nullable=False, server_default="Mumbai Metro"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disposition", sa.String(40), nullable=True),
        sa.Column("resolution_mode", sa.String(20), nullable=False, server_default="AI"),
        sa.Column("status", sa.String(20), nullable=False, server_default="IN_PROGRESS"),
        sa.Column("connected", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column("consented", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column("app_installed", sa.Boolean(), nullable=False, server_default=bool_false),
        sa.Column("app_updated", sa.Boolean(), nullable=False, server_default=bool_false),
        sa.Column("app_version", sa.String(20), nullable=False, server_default="—"),
        sa.Column("sentiment", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("issue_category", sa.String(60), nullable=True),
        sa.Column("callback_id", sa.String(40), nullable=True),
        sa.Column("escalation_id", sa.String(40), nullable=True),
        sa.Column("kural_state", sa.String(40), nullable=False, server_default="READY"),
        sa.Column("intent", sa.String(40), nullable=False, server_default="UNKNOWN"),
        sa.Column("policy_decision", sa.String(20), nullable=False, server_default="ALLOWED"),
        sa.Column("cost_inr", sa.Float(), nullable=False, server_default="0.50"),
        sa.Column("compliance_flags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("feature_interest", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("recording_available", sa.Boolean(), nullable=False, server_default=bool_false),
        sa.Column("recording_path", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "agents",
        sa.Column("agent_id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("team", sa.String(80), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False, server_default=sa.text("'[\"Hindi\", \"English\"]'")),
        sa.Column("availability", sa.String(20), nullable=False, server_default="AVAILABLE"),
        sa.Column("active_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("handled_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_resolution_min", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("sla_hit_percent", sa.Integer(), nullable=False, server_default="95"),
        sa.Column("skills", sa.JSON(), nullable=False, server_default=sa.text("'[\"APP_SUPPORT\", \"GENERAL_SUPPORT\"]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "report_schedules",
        sa.Column("schedule_id", sa.String(40), primary_key=True),
        sa.Column("cadence", sa.String(20), nullable=False, server_default="DAILY"),
        sa.Column("time_of_day", sa.String(10), nullable=False, server_default="08:00"),
        sa.Column("formats", sa.JSON(), nullable=False, server_default=sa.text("'[\"PDF\", \"XLSX\"]'")),
        sa.Column("recipient", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column("demo_only", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("report_schedules")
    op.drop_table("agents")
    op.drop_table("call_records")
    op.drop_index("ix_campaign_dial_queue", table_name="campaign_contacts")
    op.drop_table("campaign_contacts")
    op.drop_table("campaigns")
    op.drop_index("ix_customers_phone", table_name="customers")
    op.drop_table("customers")
    op.drop_table("operations_audit_events")
    op.drop_table("outbox")
    op.drop_table("callback_events")

    op.drop_index("uq_scheduled_call_no_case", table_name="callbacks")
    op.drop_index("uq_scheduled_case", table_name="callbacks")

    with op.batch_alter_table("callbacks", schema=None) as batch_op:
        batch_op.drop_constraint("uq_callbacks_idempotency_key", type_="unique")
        batch_op.drop_column("superseded_by_id")
        batch_op.drop_column("rescheduled_from_id")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("language")
        batch_op.drop_column("assigned_agent_id")
        batch_op.drop_column("version")
        batch_op.drop_column("confirmed_by_customer")
        batch_op.drop_column("resolution_rule")
        batch_op.drop_column("timezone")
        batch_op.drop_column("scheduled_at_local")
        batch_op.drop_column("scheduled_at_utc")
        batch_op.drop_column("requested_text_normalized")
        batch_op.drop_column("raw_expression")
        batch_op.drop_column("reason")
        batch_op.drop_column("customer_ref")

    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.drop_constraint("uq_cases_idempotency_key", type_="unique")
        batch_op.drop_column("callback_cancelled")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("sla_due_at")
        batch_op.drop_column("assigned_team")
        batch_op.drop_column("callback_id")
        batch_op.drop_column("actions_tried")
        batch_op.drop_column("key_lines")
        batch_op.drop_column("summary")
        batch_op.drop_column("priority")
        batch_op.drop_column("issue_code")
        batch_op.drop_column("case_type")

    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_column("context_json")
