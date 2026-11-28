"""add_digest_delivery_logs

Revision ID: e7f4a21c9b83
Revises: a3c9d14e7b52
Create Date: 2026-11-28 11:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "e7f4a21c9b83"
down_revision: Union[str, Sequence[str], None] = "a3c9d14e7b52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "digest_delivery_logs"):
        op.create_table(
            "digest_delivery_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id"), nullable=True),
            sa.Column("digest_date", sa.String(length=16), nullable=False),
            sa.Column("channels", sa.String(length=64), nullable=False, server_default="email,telegram"),
            sa.Column("sent_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_digest_delivery_user_job", "digest_delivery_logs", ["user_id", "job_posting_id"])
        op.create_index("ix_digest_delivery_user_date", "digest_delivery_logs", ["user_id", "digest_date"])
        op.create_index("ix_digest_delivery_logs_sent_at", "digest_delivery_logs", ["sent_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "digest_delivery_logs"):
        op.drop_table("digest_delivery_logs")
