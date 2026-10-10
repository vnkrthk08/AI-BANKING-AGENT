"""Operational lifecycles: case assignment/history, durable callback execution,
notification delivery log, telephony webhook receipts, campaign approval and
operator system settings.

Revision ID: 0005_operational_lifecycles
Revises: 0004_notifications_schema
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_operational_lifecycles"
down_revision = "0004_notifications_schema"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    bool_false = sa.text("0") if is_sqlite else sa.text("false")

    # Identifier widths: earlier revisions created 36-char keys while the ORM uses 40.
    if not is_sqlite:
        op.alter_column("cases", "case_id", type_=sa.String(40), existing_type=sa.String(36))
        op.alter_column("callbacks", "callback_id", type_=sa.String(40), existing_type=sa.String(36))
        op.alter_column("callbacks", "case_id", type_=sa.String(40), existing_type=sa.String(36))
        op.alter_column("call_records", "masked_phone", type_=sa.String(24), existing_type=sa.String(20))

    with op.batch_alter_table("cases") as batch:
        batch.add_column(sa.Column("assigned_agent_id", sa.String(40), nullable=True))
        batch.add_column(_ts("assigned_at"))
        batch.add_column(_ts("first_response_due_at"))
        batch.add_column(_ts("resolved_at"))
        batch.add_column(sa.Column("resolution_notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source", sa.String(20), nullable=False, server_default="VOICE_AI"))
        batch.add_column(_ts("sla_warning_sent_at"))
        batch.add_column(_ts("sla_breached_at"))
        batch.create_index("ix_cases_assigned_agent_id", ["assigned_agent_id"])

    op.create_table(
        "case_events",
        sa.Column("event_id", sa.String(40), primary_key=True),
        sa.Column("case_id", sa.String(40), sa.ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("from_value", sa.String(128), nullable=True),
        sa.Column("to_value", sa.String(128), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(64), nullable=False, server_default="SYSTEM"),
        sa.Column("actor_role", sa.String(32), nullable=True),
        _ts("created_at", nullable=False),
    )
    op.create_index("ix_case_events_case_id", "case_events", ["case_id"])

    with op.batch_alter_table("callbacks") as batch:
        batch.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
        batch.add_column(_ts("last_attempt_at"))
        batch.add_column(sa.Column("last_outcome", sa.String(40), nullable=True))
        batch.add_column(sa.Column("outcome_notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("provider_call_sid", sa.String(64), nullable=True))
        batch.add_column(sa.Column("call_record_id", sa.String(40), nullable=True))
        batch.add_column(_ts("dispatch_locked_until"))
        batch.add_column(sa.Column("dispatched_version", sa.Integer(), nullable=True))
        batch.add_column(_ts("completed_at"))
        batch.create_index("ix_callbacks_provider_call_sid", ["provider_call_sid"])
    op.create_index("ix_callbacks_due", "callbacks", ["status", "scheduled_at_utc"])

    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(sa.Column("category", sa.String(20), nullable=False, server_default="SERVICE"))
        batch.add_column(sa.Column("max_concurrent", sa.Integer(), nullable=False, server_default="2"))
        batch.add_column(sa.Column("approved_by", sa.String(64), nullable=True))
        batch.add_column(_ts("approved_at"))
        batch.add_column(sa.Column("created_by", sa.String(64), nullable=True))

    with op.batch_alter_table("campaign_contacts") as batch:
        batch.add_column(sa.Column("provider_call_sid", sa.String(64), nullable=True))
        batch.add_column(sa.Column("call_record_id", sa.String(40), nullable=True))
        batch.create_index("ix_campaign_contacts_provider_call_sid", ["provider_call_sid"])

    with op.batch_alter_table("call_records") as batch:
        batch.add_column(sa.Column("channel", sa.String(20), nullable=False, server_default="BROWSER"))
        batch.add_column(sa.Column("provider_call_sid", sa.String(64), nullable=True))
        batch.add_column(_ts("ended_at"))
        batch.create_index("ix_call_records_provider_call_sid", ["provider_call_sid"])

    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("phone", sa.String(20), nullable=True))
        batch.add_column(sa.Column("email", sa.String(255), nullable=True))
        batch.add_column(sa.Column("max_open_cases", sa.Integer(), nullable=False, server_default="12"))
        batch.create_unique_constraint("uq_agents_user_id", ["user_id"])

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("phone", sa.String(20), nullable=True))

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("notification_id", sa.String(36), nullable=True),
        sa.Column("source_event_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("recipient_label", sa.String(128), nullable=False),
        sa.Column("recipient_address", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        _ts("next_attempt_at"),
        _ts("locked_until"),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("provider_message_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        _ts("created_at", nullable=False),
        _ts("updated_at", nullable=False),
        _ts("delivered_at"),
    )
    op.create_index("ix_notification_deliveries_notification_id", "notification_deliveries", ["notification_id"])
    op.create_index("ix_notification_deliveries_source_event_id", "notification_deliveries", ["source_event_id"])
    op.create_index("ix_notification_deliveries_due", "notification_deliveries", ["status", "next_attempt_at"])

    op.create_table(
        "telephony_events",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False, unique=True),
        sa.Column("provider_call_sid", sa.String(64), nullable=True),
        sa.Column("call_id", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=bool_false),
        sa.Column("note", sa.String(200), nullable=True),
        _ts("received_at", nullable=False),
    )
    op.create_index("ix_telephony_events_provider_call_sid", "telephony_events", ["provider_call_sid"])
    op.create_index("ix_telephony_events_call_id", "telephony_events", ["call_id"])

    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=True),
        _ts("updated_at", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_index("ix_telephony_events_call_id", table_name="telephony_events")
    op.drop_index("ix_telephony_events_provider_call_sid", table_name="telephony_events")
    op.drop_table("telephony_events")
    op.drop_index("ix_notification_deliveries_due", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_source_event_id", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_notification_id", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("phone")
    with op.batch_alter_table("agents") as batch:
        batch.drop_constraint("uq_agents_user_id", type_="unique")
        for col in ("max_open_cases", "email", "phone", "user_id"):
            batch.drop_column(col)
    with op.batch_alter_table("call_records") as batch:
        batch.drop_index("ix_call_records_provider_call_sid")
        for col in ("ended_at", "provider_call_sid", "channel"):
            batch.drop_column(col)
    with op.batch_alter_table("campaign_contacts") as batch:
        batch.drop_index("ix_campaign_contacts_provider_call_sid")
        for col in ("call_record_id", "provider_call_sid"):
            batch.drop_column(col)
    with op.batch_alter_table("campaigns") as batch:
        for col in ("created_by", "approved_at", "approved_by", "max_concurrent", "category"):
            batch.drop_column(col)
    op.drop_index("ix_callbacks_due", table_name="callbacks")
    with op.batch_alter_table("callbacks") as batch:
        batch.drop_index("ix_callbacks_provider_call_sid")
        for col in ("completed_at", "dispatched_version", "dispatch_locked_until", "call_record_id",
                    "provider_call_sid", "outcome_notes", "last_outcome", "last_attempt_at",
                    "max_attempts", "attempt_count"):
            batch.drop_column(col)
    op.drop_index("ix_case_events_case_id", table_name="case_events")
    op.drop_table("case_events")
    with op.batch_alter_table("cases") as batch:
        batch.drop_index("ix_cases_assigned_agent_id")
        for col in ("sla_breached_at", "sla_warning_sent_at", "source", "resolution_notes",
                    "resolved_at", "first_response_due_at", "assigned_at", "assigned_agent_id"):
            batch.drop_column(col)
