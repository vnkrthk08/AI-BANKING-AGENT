"""Initial KURAL persistence schema.

Revision ID: 0001_initial
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("customer_ref", sa.String(64), nullable=False),
        sa.Column("current_state", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "conversation_turns",
        sa.Column("turn_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_order", sa.Integer(), nullable=False),
        sa.Column("sanitized_user_text", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(40), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "turn_order", name="uq_turn_session_order"),
    )
    op.create_index("ix_conversation_turns_session_id", "conversation_turns", ["session_id"])
    op.create_table(
        "cases",
        sa.Column("case_id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_ref", sa.String(64), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("callback_requested", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cases_session_id", "cases", ["session_id"])
    op.create_table(
        "callbacks",
        sa.Column("callback_id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.case_id", ondelete="SET NULL"), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_callbacks_session_id", "callbacks", ["session_id"])
    op.create_index("ix_callbacks_case_id", "callbacks", ["case_id"])
    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("state", sa.String(40), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_session_id", "audit_events", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_session_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_callbacks_case_id", table_name="callbacks")
    op.drop_index("ix_callbacks_session_id", table_name="callbacks")
    op.drop_table("callbacks")
    op.drop_index("ix_cases_session_id", table_name="cases")
    op.drop_table("cases")
    op.drop_index("ix_conversation_turns_session_id", table_name="conversation_turns")
    op.drop_table("conversation_turns")
    op.drop_table("sessions")
