"""Phase 4 notifications schema.

Revision ID: 0004_notifications_schema
Revises: 0003_phase4_security_outbox_audit
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_notifications_schema"
down_revision = "0003_phase4_security_outbox_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    bool_false = sa.text("0") if is_sqlite else sa.text("false")

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipient_role", sa.String(32), nullable=True),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("level", sa.String(20), nullable=False, server_default="INFO"),
        sa.Column("category", sa.String(40), nullable=False, server_default="SYSTEM"),
        sa.Column("link_url", sa.String(256), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=bool_false),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("notifications")
