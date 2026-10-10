"""Phase 4 security, identity, durable outbox, and immutable audit schema.

Revision ID: 0003_phase4_security_outbox_audit
Revises: 0002_phase2_phase3_operations
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_phase4_security_outbox_audit"
down_revision = "0002_phase2_phase3_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    bool_false = sa.text("0") if is_sqlite else sa.text("false")
    bool_true = sa.text("1") if is_sqlite else sa.text("true")

    # 1. Users table
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="AGENT"),
        sa.Column("branch", sa.String(80), nullable=False, server_default="Mumbai Metro"),
        sa.Column("mfa_secret", sa.String(128), nullable=True),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=bool_false),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    # 2. Refresh Tokens table
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("response_envelope_enc", sa.Text(), nullable=True),
        sa.Column("envelope_nonce", sa.String(64), nullable=True),
        sa.Column("envelope_tag", sa.String(64), nullable=True),
        sa.Column("envelope_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_hash", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_hash"),
    )
    op.create_index("ix_refresh_tokens_family", "refresh_tokens", ["family_id"])
    op.create_index("ix_refresh_tokens_user", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])

    # 3. WebSocket Tickets table
    op.create_table(
        "websocket_tickets",
        sa.Column("ticket_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_websocket_tickets_user_id", "websocket_tickets", ["user_id"])

    # 4. Outbox Events table
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency_key"),
    )
    op.create_index("ix_outbox_events_status_locked", "outbox_events", ["status", "locked_until"])

    # 5. Audit Ledger table
    op.create_table(
        "audit_ledger",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=True),
        sa.Column("role", sa.String(40), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("sequence_number", name="uq_audit_ledger_sequence_number"),
    )
    op.create_index("ix_audit_ledger_seq", "audit_ledger", ["sequence_number"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_audit_ledger_seq", table_name="audit_ledger")
    op.drop_table("audit_ledger")

    op.drop_index("ix_outbox_events_status_locked", table_name="outbox_events")
    op.drop_table("outbox_events")

    op.drop_index("ix_websocket_tickets_user_id", table_name="websocket_tickets")
    op.drop_table("websocket_tickets")

    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
