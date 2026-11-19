"""add_immutable_jd_snapshots

Revision ID: d5f9b23c1a40
Revises: c4e8a12f9b30
Create Date: 2026-11-19 14:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "d5f9b23c1a40"
down_revision: Union[str, Sequence[str], None] = "c4e8a12f9b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "saved_jobs") and not _column_exists(inspector, "saved_jobs", "jd_snapshot"):
        op.add_column("saved_jobs", sa.Column("jd_snapshot", sa.JSON(), nullable=True))

    if _has_table(inspector, "application_tracker") and not _column_exists(inspector, "application_tracker", "jd_snapshot"):
        op.add_column("application_tracker", sa.Column("jd_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _column_exists(inspector, "application_tracker", "jd_snapshot"):
        with op.batch_alter_table("application_tracker", schema=None) as batch_op:
            batch_op.drop_column("jd_snapshot")

    if _column_exists(inspector, "saved_jobs", "jd_snapshot"):
        with op.batch_alter_table("saved_jobs", schema=None) as batch_op:
            batch_op.drop_column("jd_snapshot")
