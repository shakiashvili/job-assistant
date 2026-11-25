"""add_job_published_at_and_indexes

Revision ID: a3c9d14e7b52
Revises: f2b8c45d0e32
Create Date: 2026-11-25 14:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "a3c9d14e7b52"
down_revision: Union[str, Sequence[str], None] = "f2b8c45d0e32"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "job_postings"):
        if not _has_column(inspector, "job_postings", "posting_date"):
            op.add_column("job_postings", sa.Column("posting_date", sa.String(), nullable=True))
        if not _has_column(inspector, "job_postings", "published_at"):
            op.add_column("job_postings", sa.Column("published_at", sa.DateTime(), nullable=True))
        if not _has_index(inspector, "job_postings", "ix_job_postings_published_at"):
            op.create_index("ix_job_postings_published_at", "job_postings", ["published_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "job_postings"):
        if _has_index(inspector, "job_postings", "ix_job_postings_published_at"):
            op.drop_index("ix_job_postings_published_at", table_name="job_postings")
        if _has_column(inspector, "job_postings", "published_at"):
            with op.batch_alter_table("job_postings", schema=None) as batch_op:
                batch_op.drop_column("published_at")
