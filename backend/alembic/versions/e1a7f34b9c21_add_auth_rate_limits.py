"""add_auth_rate_limits

Revision ID: e1a7f34b9c21
Revises: d5f9b23c1a40
Create Date: 2026-11-19 22:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "e1a7f34b9c21"
down_revision: Union[str, Sequence[str], None] = "d5f9b23c1a40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "auth_rate_limits"):
        op.create_table(
            "auth_rate_limits",
            sa.Column("bucket_key", sa.String(length=255), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("window_started_at", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("expires_at", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.PrimaryKeyConstraint("bucket_key"),
        )
        op.create_index("ix_auth_rate_limits_expires_at", "auth_rate_limits", ["expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "auth_rate_limits"):
        op.drop_index("ix_auth_rate_limits_expires_at", table_name="auth_rate_limits")
        op.drop_table("auth_rate_limits")
